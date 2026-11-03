"""Command-line interface: `chat-to-cloud <command> ...`."""

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from chat_to_cloud import fonts
from chat_to_cloud.cloud import write_static_cloud
from chat_to_cloud.tokens import LANGUAGES, Language, tokens_for_language
from chat_to_cloud.whatsapp import read_chat

logger = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _selected_languages(choice: str) -> tuple[Language, ...]:
    if choice == "all":
        return LANGUAGES
    return tuple(language for language in LANGUAGES if language == choice)


def _output_dir(args: argparse.Namespace, chat_path: Path) -> Path:
    output_dir: Path | None = args.output_dir
    return output_dir or chat_path.parent


def _add_chat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "chats", type=Path, nargs="+", help="exported WhatsApp chat .txt files"
    )
    parser.add_argument(
        "--language",
        choices=(*LANGUAGES, "all"),
        default="all",
        help="token set to render (default: all, as separate files)",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="default: next to each chat file"
    )


def _run_fetch_fonts(args: argparse.Namespace) -> None:
    for source in fonts.ALL_FONTS:
        path = fonts.font_path(source)
        logger.info("%s: %s (%s)", source.filename, path, source.license)


def _run_static(args: argparse.Namespace) -> None:
    for chat_path in args.chats:
        messages = read_chat(chat_path)
        for language in _selected_languages(args.language):
            write_static_cloud(
                tokens_for_language(messages, language),
                fonts.font_path(fonts.LANGUAGE_FONTS[language]),
                _output_dir(args, chat_path) / f"{chat_path.stem}_{language}_wc.png",
                width=args.width,
                height=args.height,
                random_state=args.seed,
            )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for all subcommands."""
    parser = argparse.ArgumentParser(
        prog="chat-to-cloud",
        description="Generate word clouds from WhatsApp chat exports.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug messages"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser(
        "fetch-fonts", help="download and verify all fonts ahead of time"
    )
    fetch.set_defaults(run=_run_fetch_fonts)

    static = commands.add_parser("static", help="render static PNG word clouds")
    _add_chat_arguments(static)
    static.add_argument("--width", type=_positive_int, default=1600)
    static.add_argument("--height", type=_positive_int, default=1200)
    static.add_argument(
        "--seed", type=int, help="fix the layout for reproducible output"
    )
    static.set_defaults(run=_run_static)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the command-line interface."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    args.run(args)
