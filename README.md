# chat-to-cloud

Generate static and animated word clouds from WhatsApp chat exports,
separately for English words, Farsi words, and emoji.

## Usage

1. Export a chat from WhatsApp on your phone: open the chat, then
   *More > Export chat > Without media*. This produces a file such as
   `WhatsApp Chat with Alice.txt`. Exports from Android, with lines like
   `7/4/19, 15:50 - Alice: Hello`, are supported.
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
   and, from this directory, run:

```sh
uv run chat-to-cloud static "chats/WhatsApp Chat with Alice.txt"
```

The first run creates the virtual environment and downloads the fonts.

### Static images

The `static` command writes one PNG per token set next to the chat file:
`<chat>_en_wc.png` (English words), `<chat>_fa_wc.png` (Farsi words), and
`<chat>_emoji_wc.png` (emoji). A token set with no tokens is skipped.

Common options:

- `--language en|fa|emoji|all`: render only one token set (default `all`).
- `--output-dir DIR`: write outputs elsewhere.
- `--width`, `--height`: image size (default 1600x1200).
- `--seed N`: reproducible layout; by default each run differs.

Several chat files can be given at once. Run `uv run chat-to-cloud --help`
or `uv run chat-to-cloud static --help` for the full reference. The
`chats/` and `output/` directories are git-ignored, so they are convenient
places for exports and results.

### Animations

Two commands render MP4 videos of the cloud building up over the chat's
history, with a footer showing the chat, the current date, and progress:

```sh
uv run chat-to-cloud animate "chats/WhatsApp Chat with Alice.txt"
uv run chat-to-cloud animate-dynamic "chats/WhatsApp Chat with Alice.txt"
```

- `animate` lays out the final cloud once; each word then grows in place
  as it is used. Writes `<chat>_<language>_wc_animation.mp4`.
- `animate-dynamic` makes every keyframe a complete cloud and moves words
  smoothly between keyframes as their relative frequencies change.
  Writes `<chat>_<language>_wc_dynamic_animation.mp4`. It is slower: a
  few minutes per language for a chat of a few thousand messages.

Both accept `--language`, `--output-dir`, and tuning options such as
`--keyframes`, `--frames-per-step`, `--fps`, `--max-words`, and
`--width`/`--height`. See `uv run chat-to-cloud animate --help` and
`uv run chat-to-cloud animate-dynamic --help`. Videos are encoded with
the ffmpeg binary bundled by `imageio-ffmpeg`, so no system ffmpeg is
needed.

## Web app

The same Python code also runs as a static web page. It loads
[Pyodide](https://pyodide.org/) from its CDN and turns a chat export into
an image or animation inside the browser, so the chat is never uploaded.
Videos are encoded by the browser's WebCodecs API through the
[mediabunny](https://mediabunny.dev/) library (MPL-2.0, also from a CDN):
H.264 MP4 where the browser can encode it, otherwise WebM.

```sh
uv run python scripts/build_pages.py                     # writes _site/
uv run python -m http.server 8000 --directory _site      # http://localhost:8000
```

The build copies `web/`, packs `src/chat_to_cloud` into
`python/chat_to_cloud.zip`, adds the checksum-verified fonts with their
licenses, and writes the runtime pins from `[tool.chat-to-cloud.browser]`
in `pyproject.toml` to `runtime-config.json`. Pyodide supplies Python 3.14
and most packages. `arabic-reshaper` and the pure-Python `python-bidi`
0.4.2 come from PyPI. Pyodide's Pillow cannot shape Arabic script, so the
words are pre-shaped as described in `tokens.display_form`.

Rendering runs on a single core in the browser and is slower than the
command line, so the page offers smaller sizes. The animation settings
otherwise use the command-line defaults.

`.github/workflows/pages.yml` runs the checks and tests, builds the site,
and deploys it on pushes to `master` or `main`. To enable it, set the
repository's *Settings > Pages > Build and deployment > Source* to
*GitHub Actions*.

## Fonts and licensing

Fonts are not stored in this repository. Each is pinned to an immutable
upstream URL and a SHA-256 checksum (see `src/chat_to_cloud/fonts.py`),
downloaded on first use, and cached in the user data directory
(`~/.local/share/chat-to-cloud/fonts` on Linux). Run
`uv run chat-to-cloud fetch-fonts` to download them ahead of time. Set
`CHAT_TO_CLOUD_FONT_DIR` to use a different directory, for example on an
offline machine where the files were copied by hand.

| Used for | Font | Source | License |
| --- | --- | --- | --- |
| English, video labels | DejaVu Sans 2.37 | [dejavu-fonts release](https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37) | [Bitstream Vera / DejaVu](https://dejavu-fonts.github.io/License.html), free and permissive |
| Farsi | Noto Naskh Arabic | [notofonts](https://github.com/notofonts/arabic) | [SIL Open Font License 1.1](https://openfontlicense.org/) |
| Emoji | OpenMoji 16.0.0 (black glyf) | [hfg-gmuend/openmoji](https://github.com/hfg-gmuend/openmoji/tree/16.0.0) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |

All three fonts permit free use, including for images you publish, and
redistribution. The web app serves copies of them together with their
license texts from `web/licenses/`. Emoji clouds are drawn with OpenMoji
graphics, so credit them when you share those images, for example:

> Emoji graphics by [OpenMoji](https://openmoji.org/), licensed under
> [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

CC BY-SA is a share-alike license. If a published emoji cloud counts as an
adaptation of the OpenMoji graphics, it should also be released under
CC BY-SA 4.0.

## Development

The project uses [uv](https://docs.astral.sh/uv/) for Python, dependencies,
and running tools:

```sh
uv sync                    # create .venv with runtime and dev dependencies
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type check (strict)
uv run pre-commit install  # optional: run ruff and mypy on every commit
```

The web app has an opt-in test that loads the built site in a real
browser. It needs network access:

```sh
uv sync --group browser
uv run playwright install chromium
RUN_BROWSER_TESTS=1 uv run pytest -m browser
```

Set `BROWSER_EXECUTABLE=/usr/bin/google-chrome` to use an installed Chrome
instead.
