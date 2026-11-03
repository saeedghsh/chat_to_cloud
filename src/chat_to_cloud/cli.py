"""Command-line interface: `chat-to-cloud <command> ...`."""

import argparse
import dataclasses
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from chat_to_cloud import fonts
from chat_to_cloud.cloud import write_static_cloud
from chat_to_cloud.dynamic_animation import DynamicSettings, render_dynamic_animation
from chat_to_cloud.stable_animation import StableSettings, render_stable_animation
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


# Help for animation settings; the defaults come from the settings classes.
_SETTING_HELP = {
    "width": "video width in pixels (even)",
    "height": "video height in pixels (even), including the footer",
    "keyframes": "number of points in the chat at which frequencies are sampled",
    "frames_per_step": "interpolated frames between keyframes",
    "fps": "frames per second",
    "max_words": "maximum number of words in the cloud",
    "random_state": "layout seed",
    "growth_exponent": "below 1 makes early word growth more visible; in (0, 1]",
    "hold_seconds": "pause on the first and last frame",
    "relative_scaling": "frequency-to-size scaling, 0 (rank only) to 1 (linear)",
    "fill_ratio": "fraction of the canvas that word boxes may cover",
    "packing_margin": "minimum gap between words in pixels",
    "max_movement": (
        "words moving faster than this many px/frame fade instead of sliding; "
        "0 is automatic"
    ),
    "workers": "parallel render processes; 0 selects up to four",
    "verify_layout": "check every planned frame for overlapping words",
}


def _add_settings_arguments(
    parser: argparse.ArgumentParser, settings_class: type[Any]
) -> None:
    """Expose every field of a settings dataclass as a command-line option."""
    defaults = settings_class()
    for field in dataclasses.fields(settings_class):
        default = getattr(defaults, field.name)
        name = "seed" if field.name == "random_state" else field.name
        flag = "--" + name.replace("_", "-")
        help_text = _SETTING_HELP[field.name]
        if isinstance(default, bool):
            parser.add_argument(
                flag, dest=field.name, action="store_true", help=help_text
            )
        else:
            parser.add_argument(
                flag,
                dest=field.name,
                type=type(default),
                default=default,
                metavar=name.upper(),
                help=f"{help_text} (default: %(default)s)",
            )
    parser.set_defaults(settings_class=settings_class)


def _settings_from_args(args: argparse.Namespace) -> Any:
    settings_class = args.settings_class
    names = (field.name for field in dataclasses.fields(settings_class))
    return settings_class(**{name: getattr(args, name) for name in names})


def _run_animate(args: argparse.Namespace) -> None:
    for chat_path in args.chats:
        messages = read_chat(chat_path)
        for language in _selected_languages(args.language):
            render_stable_animation(
                messages,
                language,
                _output_dir(args, chat_path)
                / f"{chat_path.stem}_{language}_wc_animation.mp4",
                font_path=fonts.font_path(fonts.LANGUAGE_FONTS[language]),
                label_font_path=fonts.font_path(fonts.LABEL_FONT),
                title=f"{chat_path.stem} — {language}",
                settings=args.settings,
            )


def _run_animate_dynamic(args: argparse.Namespace) -> None:
    for chat_path in args.chats:
        messages = read_chat(chat_path)
        for language in _selected_languages(args.language):
            render_dynamic_animation(
                messages,
                language,
                _output_dir(args, chat_path)
                / f"{chat_path.stem}_{language}_wc_dynamic_animation.mp4",
                font_path=fonts.font_path(fonts.LANGUAGE_FONTS[language]),
                label_font_path=fonts.font_path(fonts.LABEL_FONT),
                title=f"{chat_path.stem} — {language} dynamic",
                settings=args.settings,
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

    animate = commands.add_parser(
        "animate",
        help="render an MP4 in which words grow in fixed positions",
        description=(
            "Animate the cumulative word cloud over the chat's history. The "
            "final cloud is laid out once and each word grows in place."
        ),
    )
    _add_chat_arguments(animate)
    _add_settings_arguments(animate, StableSettings)
    animate.set_defaults(run=_run_animate)

    dynamic = commands.add_parser(
        "animate-dynamic",
        help="render an MP4 in which the layout reflows as words grow",
        description=(
            "Animate the cumulative word cloud over the chat's history. Each "
            "keyframe is a full cloud and words move smoothly between them."
        ),
    )
    _add_chat_arguments(dynamic)
    _add_settings_arguments(dynamic, DynamicSettings)
    dynamic.set_defaults(run=_run_animate_dynamic)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the command-line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if "settings_class" in args:
        try:
            args.settings = _settings_from_args(args)
        except ValueError as error:
            parser.error(str(error))
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    args.run(args)
