// Runs the chat_to_cloud Python package in Pyodide and encodes its frames
// with WebCodecs. Requests are handled one at a time, in order.
let session;
let mediabunny;
let queue = Promise.resolve();

async function checkedFetch(path) {
  const response = await fetch(new URL(path, self.location.href));
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status}).`);
  return response;
}

function progress(id, text, fraction = null) {
  self.postMessage({ id, progress: { text, fraction } });
}

async function initialize(id) {
  const config = await (await checkedFetch("./runtime-config.json")).json();
  const indexURL = `https://cdn.jsdelivr.net/pyodide/v${config["pyodide-version"]}/full/`;
  progress(id, "Loading Python…");
  const { loadPyodide } = await import(`${indexURL}pyodide.mjs`);
  const pyodide = await loadPyodide({ indexURL });
  if (pyodide.version !== config["pyodide-version"]) throw new Error("Pyodide version mismatch.");
  const pythonVersion = pyodide.runPython("import sys; '.'.join(map(str, sys.version_info[:2]))");
  if (pythonVersion !== config["python-version"]) throw new Error("Python version mismatch.");

  progress(id, "Loading the word-cloud packages…");
  await pyodide.loadPackage(config["pyodide-packages"]);
  const micropip = pyodide.pyimport("micropip");
  await micropip.install(config["pypi-packages"]);

  progress(id, "Loading fonts…");
  const archive = await (await checkedFetch("./python/chat_to_cloud.zip")).arrayBuffer();
  pyodide.unpackArchive(archive, "zip", { extractDir: "/app" });
  pyodide.FS.mkdirTree("/fonts");
  await Promise.all(config.fonts.map(async (name) => {
    const data = await (await checkedFetch(`./fonts/${name}`)).arrayBuffer();
    pyodide.FS.writeFile(`/fonts/${name}`, new Uint8Array(data));
  }));
  mediabunny = await import(
    `https://cdn.jsdelivr.net/npm/mediabunny@${config["mediabunny-version"]}/dist/bundles/mediabunny.min.mjs`
  );
  session = pyodide.runPython(`
import sys
from pathlib import Path
sys.path.insert(0, "/app")
from chat_to_cloud.browser import BrowserSession
BrowserSession(Path("/fonts"))
`);
  return { ready: true };
}

function toJs(proxy) {
  if (proxy === undefined || proxy === null) return null;
  const value = proxy.toJs({ dict_converter: Object.fromEntries });
  proxy.destroy();
  return value;
}

function image({ language, width, height }) {
  const png = toJs(session.static_png(language, width, height));
  if (!png) return null;
  return { data: png.buffer, mime: "image/png", extension: "png" };
}

async function video(id, { kind, language, title, width, height }) {
  progress(id, kind === "dynamic" ? "Planning how the words move…" : "Laying out the words…");
  const info = toJs(session.start_animation(kind, language, title, width, height));
  if (!info) return null;

  const { Output, BufferTarget, Mp4OutputFormat, WebMOutputFormat, VideoSampleSource,
    VideoSample, QUALITY_HIGH, getFirstEncodableVideoCodec } = mediabunny;
  // Prefer H.264 in MP4, which plays almost everywhere; fall back to WebM.
  const codec = await getFirstEncodableVideoCodec(["avc", "vp9", "av1", "vp8"], {
    width: info.width, height: info.height, quality: QUALITY_HIGH,
  });
  if (!codec) throw new Error("This browser cannot encode video. Try a recent Chrome, Edge, Firefox, or Safari.");
  const mp4 = codec === "avc";
  const output = new Output({
    format: mp4 ? new Mp4OutputFormat({ fastStart: "in-memory" }) : new WebMOutputFormat(),
    target: new BufferTarget(),
  });
  const source = new VideoSampleSource({ codec, quality: QUALITY_HIGH });
  output.addVideoTrack(source, { frameRate: info.fps });
  await output.start();

  for (let index = 0; ; index++) {
    const frame = toJs(session.next_frame());
    if (!frame) break;
    const sample = new VideoSample(frame, {
      format: "RGBX",
      codedWidth: info.width,
      codedHeight: info.height,
      timestamp: index / info.fps,
      duration: 1 / info.fps,
    });
    await source.add(sample);
    sample.close();
    if (index % 6 === 0) {
      progress(id, `Rendering frame ${index + 1} of ${info.frame_count}…`, (index + 1) / info.frame_count);
    }
  }
  await output.finalize();
  return {
    data: output.target.buffer,
    mime: mp4 ? "video/mp4" : "video/webm",
    extension: mp4 ? "mp4" : "webm",
  };
}

async function handle(id, action, args) {
  if (action === "init") return initialize(id);
  if (action === "load") return toJs(session.load_chat(args.text));
  if (action === "image") return image(args);
  if (action === "video") return video(id, args);
  throw new Error(`Unknown action ${action}.`);
}

self.onmessage = ({ data }) => {
  queue = queue.then(async () => {
    try {
      const result = await handle(data.id, data.action, data.args);
      self.postMessage({ id: data.id, result }, result?.data ? [result.data] : []);
    } catch (error) {
      // Python errors carry a traceback; its last line is the useful part.
      const message = String(error.message || error).trim().split("\n").at(-1);
      self.postMessage({ id: data.id, error: message });
    }
  });
};
