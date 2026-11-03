# chat-to-cloud

Generate word clouds from WhatsApp chat exports, separately for English
words, Farsi words, and emoji.

## Fonts and licensing

Fonts are not stored in this repository. Each is pinned to an immutable
upstream URL and a SHA-256 checksum (see `src/chat_to_cloud/fonts.py`),
downloaded on first use, and cached in the user data directory
(`~/.local/share/chat-to-cloud/fonts` on Linux). Set
`CHAT_TO_CLOUD_FONT_DIR` to use a different directory, for example on an
offline machine where the files were copied by hand.

| Used for | Font | Source | License |
| --- | --- | --- | --- |
| English, video labels | DejaVu Sans 2.37 | [dejavu-fonts release](https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37) | [Bitstream Vera / DejaVu](https://dejavu-fonts.github.io/License.html), free and permissive |
| Farsi | Noto Naskh Arabic | [notofonts](https://github.com/notofonts/arabic) | [SIL Open Font License 1.1](https://openfontlicense.org/) |
| Emoji | OpenMoji 16.0.0 (black glyf) | [hfg-gmuend/openmoji](https://github.com/hfg-gmuend/openmoji/tree/16.0.0) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |

All three fonts permit free use, including for images you publish. Emoji
clouds are drawn with OpenMoji graphics, so credit them when you share
those images, for example:

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
