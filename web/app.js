// UI only: the worker owns Python and video encoding.
const $ = (id) => document.getElementById(id);
const pending = new Map();
let worker;
let nextId = 0;
let chat = null; // { name, text, summary }
let resultURL = null;
let cancelling = false;

function fatal(error) {
  worker?.terminate();
  pending.clear();
  $("loading").hidden = true;
  $("app").hidden = true;
  $("error").hidden = false;
  $("error-text").textContent = `The app could not load. Check your connection and try again. ${error.message}`;
}

function request(action, args = {}, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const id = ++nextId;
    pending.set(id, { resolve, reject, onProgress });
    worker.postMessage({ id, action, args });
  });
}

function startWorker() {
  worker = new Worker(new URL("./worker.js", import.meta.url), { type: "module" });
  worker.onmessage = ({ data }) => {
    const call = pending.get(data.id);
    if (!call) return;
    if (data.progress) return call.onProgress(data.progress);
    pending.delete(data.id);
    if (data.error) call.reject(new Error(data.error));
    else call.resolve(data.result);
  };
  worker.onerror = (event) => fatal(new Error(event.message || "The worker stopped."));
  return request("init", {}, ({ text }) => { $("loading").textContent = text; });
}

function showProgress(text, fraction = null) {
  $("empty-state").hidden = true;
  $("progress").hidden = false;
  $("progress-text").textContent = text;
  $("progress-bar").style.width = fraction === null ? "0" : `${Math.round(fraction * 100)}%`;
}

function setBusy(busy) {
  for (const id of ["chat-file", "language", "kind", "size"]) $(id).disabled = busy;
  $("generate").disabled = busy || !chat;
  $("app").setAttribute("aria-busy", String(busy));
  if (!busy) $("progress").hidden = true;
}

function showFeedback(message) {
  $("feedback").textContent = message;
  $("feedback").hidden = !message;
}

function clearResult() {
  if (resultURL) URL.revokeObjectURL(resultURL);
  resultURL = null;
  $("result").hidden = true;
  $("result-image").hidden = true;
  $("result-video").hidden = true;
  $("result-video").removeAttribute("src");
  $("empty-state").hidden = false;
}

const languageNames = { en: "English words", fa: "Farsi words", emoji: "emoji" };

function describeChat({ messages, participants, first, last, tokens }) {
  if (!messages) return "No messages found. Is this an Android WhatsApp export?";
  const people = participants.length ? ` between ${participants.join(", ")}` : "";
  const counts = Object.entries(tokens)
    .map(([language, count]) => `${count.toLocaleString()} distinct ${languageNames[language]}`)
    .join(" · ");
  return `${messages.toLocaleString()} messages${people}, ${first} to ${last}. ${counts}.`;
}

async function loadChat(file) {
  clearResult();
  showFeedback("");
  setBusy(true);
  try {
    showProgress("Reading the chat…");
    const text = await file.text();
    const summary = await request("load", { text });
    chat = summary.messages ? { name: file.name.replace(/\.txt$/i, ""), text, summary } : null;
    $("board-title").textContent = file.name.replace(/\.txt$/i, "");
    $("chat-summary").textContent = describeChat(summary);
  } catch (error) {
    chat = null;
    showFeedback(error.message);
  } finally {
    setBusy(false);
  }
}

async function generate() {
  const language = $("language").value;
  const kind = $("kind").value;
  const [width, height] = $("size").value.split("x").map(Number);
  if (!chat.summary.tokens[language]) {
    showFeedback(`This chat has no ${languageNames[language]}.`);
    return;
  }
  clearResult();
  showFeedback("");
  setBusy(true);
  $("cancel").hidden = kind === "image";
  try {
    showProgress(kind === "image" ? "Arranging the words…" : "Starting…");
    const output = kind === "image"
      ? await request("image", { language, width, height })
      : await request(
        "video", { kind, language, title: chat.name, width, height },
        ({ text, fraction }) => showProgress(text, fraction),
      );
    if (!output) {
      showFeedback(`This chat has no ${languageNames[language]}.`);
      return;
    }
    resultURL = URL.createObjectURL(new Blob([output.data], { type: output.mime }));
    const media = $(kind === "image" ? "result-image" : "result-video");
    media.src = resultURL;
    media.hidden = false;
    const suffix = kind === "image" ? "wc" : kind === "stable" ? "wc_animation" : "wc_dynamic_animation";
    $("download").href = resultURL;
    $("download").download = `${chat.name}_${language}_${suffix}.${output.extension}`;
    $("emoji-credit").hidden = language !== "emoji";
    $("result").hidden = false;
    $("empty-state").hidden = true;
  } catch (error) {
    if (error.message !== "Cancelled.") showFeedback(error.message);
  } finally {
    if (!cancelling) setBusy(false);
  }
}

// Python cannot be interrupted mid-render, so cancelling restarts the worker
// and reloads the chat into the fresh one.
async function cancel() {
  cancelling = true;
  worker.terminate();
  for (const call of pending.values()) call.reject(new Error("Cancelled."));
  pending.clear();
  showProgress("Cancelling…");
  $("cancel").hidden = true;
  try {
    await startWorker();
    if (chat) await request("load", { text: chat.text });
  } catch (error) {
    fatal(error);
  } finally {
    cancelling = false;
    setBusy(false);
  }
}

function updateNote() {
  const notes = {
    image: "Images get a fresh layout every time.",
    stable: "Takes about a minute for a few thousand messages.",
    dynamic: "Can take many minutes; try Small first.",
  };
  $("settings-note").textContent = notes[$("kind").value];
}

$("chat-file").addEventListener("change", (event) => {
  const [file] = event.target.files;
  if (file) loadChat(file);
});
$("generate").addEventListener("click", generate);
$("cancel").addEventListener("click", cancel);
$("kind").addEventListener("change", updateNote);
$("retry").addEventListener("click", () => location.reload());

startWorker()
  .then(() => {
    $("loading").hidden = true;
    $("app").hidden = false;
    setBusy(false);
  })
  .catch(fatal);
