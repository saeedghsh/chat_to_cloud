# chat-to-cloud

Generate word clouds from WhatsApp chat exports, separately for English
words, Farsi words, and emoji.

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
