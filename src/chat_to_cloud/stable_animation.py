"""Cumulative word-cloud animation with fixed word positions.

The complete chat is packed once, so every word keeps a stable position and
color while its size and opacity grow over time.
"""

import logging
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from chat_to_cloud import video
from chat_to_cloud.cloud import make_wordcloud
from chat_to_cloud.tokens import Language, tokens_by_message
from chat_to_cloud.whatsapp import Message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StableSettings:
    """Rendering parameters for `render_stable_animation`."""

    width: int = 1280
    height: int = 960
    keyframes: int = 48
    frames_per_step: int = 6
    fps: int = 24
    max_words: int = 150
    random_state: int = 42
    # Below 1, small counts render relatively larger, making early growth
    # visible.
    growth_exponent: float = 0.55
    hold_seconds: float = 0.75

    def __post_init__(self) -> None:
        video.check_dimensions(self.width, self.height)
        if not 0 < self.growth_exponent <= 1:
            raise ValueError("growth_exponent must be in (0, 1]")
        if self.hold_seconds < 0:
            raise ValueError("hold_seconds cannot be negative")


@dataclass(frozen=True)
class _Slot:
    """A word's permanent place in the final layout."""

    word: str
    final_count: int
    font_size: int
    x: int
    y: int
    width: int
    height: int
    color: tuple[int, ...]


@dataclass(frozen=True)
class _Canvas:
    font_path: Path
    label_font_path: Path
    width: int
    height: int
    footer_height: int
    growth_exponent: float
    title: str
    total_messages: int


def _build_stable_layout(
    frequencies: Counter[str],
    font_path: Path,
    width: int,
    height: int,
    max_words: int,
    random_state: int,
) -> list[_Slot]:
    """Pack the final cloud once and turn it into permanent slots."""
    cloud = make_wordcloud(
        frequencies,
        font_path,
        width,
        height,
        max_words=max_words,
        random_state=random_state,
    )
    measuring_draw = ImageDraw.Draw(Image.new("RGB", (width, height), "white"))
    layout: list[_Slot] = []
    for (word, _), font_size, (row, column), orientation, color in cloud.layout_:
        # Slots assume horizontal words, which `make_wordcloud` guarantees.
        if orientation is not None:
            raise ValueError("Animated layouts require horizontal words")
        font = ImageFont.truetype(font_path, font_size)
        left, top, right, bottom = measuring_draw.textbbox(
            (0, 0), word, font=font, anchor="lt"
        )
        layout.append(
            _Slot(
                word=word,
                final_count=frequencies[word],
                font_size=font_size,
                x=int(column - left),
                y=int(row - top),
                width=int(right - left),
                height=int(bottom - top),
                color=ImageColor.getrgb(color),
            )
        )
    return layout


def _ease(progress: float) -> float:
    """Smoothstep easing with zero velocity at both ends."""
    return progress * progress * (3.0 - 2.0 * progress)


def _render_frame(
    layout: Sequence[_Slot],
    first: Counter[str],
    second: Counter[str],
    progress: float,
    canvas: _Canvas,
    *,
    timestamp: str,
    messages_seen: float,
) -> np.ndarray:
    """Draw words scaled inside their final slots, then the footer."""
    image = Image.new("RGBA", (canvas.width, canvas.height), "white")
    words_layer = Image.new("RGBA", (canvas.width, canvas.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(words_layer)
    eased = _ease(progress)
    for item in layout:
        start = first.get(item.word, 0)
        count = start + (second.get(item.word, 0) - start) * eased
        if count <= 0:
            continue
        growth = min(1.0, count / item.final_count) ** canvas.growth_exponent
        font_size = max(1, round(item.font_size * growth))
        # Skip unreadable specks; new words fade in over their first occurrence.
        if font_size < 3:
            continue
        alpha = round(255 * min(1.0, count))
        font = ImageFont.truetype(canvas.font_path, font_size)
        left, top, right, bottom = draw.textbbox(
            (0, 0), item.word, font=font, anchor="lt"
        )
        x = item.x + (item.width - (right - left)) / 2 - left
        y = item.y + (item.height - (bottom - top)) / 2 - top
        draw.text(
            (round(x), round(y)),
            item.word,
            font=font,
            fill=(*item.color, alpha),
            anchor="lt",
        )

    image = Image.alpha_composite(image, words_layer)
    video.draw_footer(
        image,
        font_path=canvas.label_font_path,
        footer_height=canvas.footer_height,
        title=canvas.title,
        timestamp=timestamp,
        messages_seen=messages_seen,
        total_messages=canvas.total_messages,
    )
    return np.asarray(image.convert("RGB"))


def _frames(
    layout: Sequence[_Slot],
    timeline: video.Timeline,
    canvas: _Canvas,
    *,
    frames_per_step: int,
    hold_frames: int,
) -> Iterator[np.ndarray]:
    boundaries, snapshots, timestamps = (
        timeline.boundaries,
        timeline.snapshots,
        timeline.timestamps,
    )
    first_frame = _render_frame(
        layout,
        Counter(),
        snapshots[0],
        1.0,
        canvas,
        timestamp=timestamps[0],
        messages_seen=boundaries[0],
    )
    for _ in range(hold_frames):
        yield first_frame

    for index in range(1, len(snapshots)):
        for step in range(1, frames_per_step + 1):
            progress = step / frames_per_step
            messages_seen = boundaries[index - 1] + (
                boundaries[index] - boundaries[index - 1]
            ) * _ease(progress)
            yield _render_frame(
                layout,
                snapshots[index - 1],
                snapshots[index],
                progress,
                canvas,
                timestamp=timestamps[index if progress >= 0.5 else index - 1],
                messages_seen=messages_seen,
            )

    final_frame = _render_frame(
        layout,
        snapshots[-1],
        snapshots[-1],
        1.0,
        canvas,
        timestamp=timestamps[-1],
        messages_seen=canvas.total_messages,
    )
    for _ in range(hold_frames):
        yield final_frame


def render_stable_animation(
    messages: Sequence[Message],
    language: Language,
    output_path: Path,
    *,
    font_path: Path,
    label_font_path: Path,
    title: str,
    settings: StableSettings | None = None,
) -> bool:
    """Write the animation as MP4; return False when there is nothing to show."""
    settings = settings or StableSettings()
    if not messages:
        logger.info("Skipping %s: no messages were parsed", output_path)
        return False
    grouped_tokens = tokens_by_message(messages, language)
    final_frequencies = Counter(token for tokens in grouped_tokens for token in tokens)
    if not final_frequencies:
        logger.info("Skipping %s: no %s tokens", output_path, language)
        return False

    footer_height = video.footer_height_for(settings.height)
    timeline = video.build_timeline(messages, grouped_tokens, settings.keyframes)
    layout = _build_stable_layout(
        final_frequencies,
        font_path,
        settings.width,
        settings.height - footer_height,
        settings.max_words,
        settings.random_state,
    )
    canvas = _Canvas(
        font_path=font_path,
        label_font_path=label_font_path,
        width=settings.width,
        height=settings.height,
        footer_height=footer_height,
        growth_exponent=settings.growth_exponent,
        title=title,
        total_messages=timeline.boundaries[-1],
    )
    frames = _frames(
        layout,
        timeline,
        canvas,
        frames_per_step=settings.frames_per_step,
        hold_frames=max(1, round(settings.hold_seconds * settings.fps)),
    )
    frame_count = video.write_mp4(frames, output_path, settings.fps)
    logger.info(
        "Wrote %s (%d frames, %.1fs, %d words)",
        output_path,
        frame_count,
        frame_count / settings.fps,
        len(layout),
    )
    return True
