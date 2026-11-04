"""Timeline, footer, and MP4 helpers shared by the animations."""

import logging
import math
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from chat_to_cloud.whatsapp import Message

logger = logging.getLogger(__name__)

MIN_DIMENSION = 160


@dataclass(frozen=True)
class Timeline:
    """Cumulative token frequencies at evenly spaced points of a chat.

    `boundaries[i]` is the number of messages included in `snapshots[i]`, and
    `timestamps[i]` is the timestamp of the last of those messages.
    """

    boundaries: list[int]
    snapshots: list[Counter[str]]
    timestamps: list[str]

    def __post_init__(self) -> None:
        if not (len(self.boundaries) == len(self.snapshots) == len(self.timestamps)):
            raise ValueError("Timeline sequences must have equal lengths")

    def without_leading_empty(self) -> "Timeline":
        """Drop keyframes before the first one containing any token."""
        first = next(index for index, counts in enumerate(self.snapshots) if counts)
        return Timeline(
            self.boundaries[first:], self.snapshots[first:], self.timestamps[first:]
        )


@dataclass(frozen=True)
class Animation:
    """Lazily rendered RGB frames and the facts needed to encode them."""

    frames: Iterator[np.ndarray]
    frame_count: int
    fps: int
    width: int
    height: int


def build_timeline(
    messages: Sequence[Message],
    grouped_tokens: Sequence[Sequence[str]],
    keyframe_count: int,
) -> Timeline:
    """Sample cumulative frequencies at up to `keyframe_count` message counts."""
    message_count = len(messages)
    count = min(message_count, keyframe_count)
    boundaries = sorted(
        {max(1, round(index * message_count / count)) for index in range(1, count + 1)}
    )
    snapshots: list[Counter[str]] = []
    frequencies: Counter[str] = Counter()
    previous = 0
    for boundary in boundaries:
        for message_tokens in grouped_tokens[previous:boundary]:
            frequencies.update(message_tokens)
        snapshots.append(frequencies.copy())
        previous = boundary
    timestamps = [messages[boundary - 1].timestamp for boundary in boundaries]
    return Timeline(boundaries, snapshots, timestamps)


def check_dimensions(width: int, height: int) -> None:
    """Reject frame sizes that the H.264 encoder cannot handle."""
    for value in (width, height):
        if value < MIN_DIMENSION or value % 2:
            raise ValueError(
                f"MP4 dimensions must be even and at least {MIN_DIMENSION} pixels"
            )


@dataclass(frozen=True)
class WordSprite:
    """A word rasterized once at one size.

    `box` is the text bounding box for a left-top anchor at the origin, and
    `offset` is where the mask's corner lies relative to that anchor.
    """

    mask: Image.Image
    box: tuple[float, float, float, float]
    offset: tuple[int, int]


@lru_cache(maxsize=512)
def word_sprite(word: str, font_path: Path, size: int) -> WordSprite:
    """Rasterize `word` as a grayscale coverage mask, cached per size.

    Animations redraw the same words at the same sizes in many frames, and
    rasterizing glyphs is the bulk of the rendering time.
    """
    font = ImageFont.truetype(font_path, size)
    measuring_draw = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = measuring_draw.textbbox(
        (0, 0), word, font=font, anchor="lt"
    )
    # A margin guards against antialiasing just outside the bounding box.
    margin = 2
    corner_x, corner_y = math.floor(left) - margin, math.floor(top) - margin
    mask = Image.new(
        "L",
        (math.ceil(right) + margin - corner_x, math.ceil(bottom) + margin - corner_y),
        0,
    )
    ImageDraw.Draw(mask).text(
        (-corner_x, -corner_y), word, font=font, fill=255, anchor="lt"
    )
    return WordSprite(mask, (left, top, right, bottom), (corner_x, corner_y))


def draw_word(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    sprite: WordSprite,
    fill: tuple[int, ...],
) -> None:
    """Draw a sprite as `draw.text` would draw its word at `position`.

    Both blend the fill color through the same coverage mask, so the pixels
    are identical.
    """
    x, y = position
    draw.bitmap((x + sprite.offset[0], y + sprite.offset[1]), sprite.mask, fill=fill)


def footer_height_for(height: int) -> int:
    """Return the height of the footer band at the bottom of each frame."""
    return max(72, round(height * 0.1))


def _truncate_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
    """Shorten text with an ellipsis so it fits within `max_width`."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if draw.textlength(text[:middle] + ellipsis, font=font) <= max_width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + ellipsis


def draw_footer(
    image: Image.Image,
    *,
    font_path: Path,
    footer_height: int,
    title: str,
    timestamp: str,
    messages_seen: float,
    total_messages: int,
) -> None:
    """Draw the title, timestamp, message count, and progress bar in place."""
    width, height = image.size
    draw = ImageDraw.Draw(image)
    footer_top = height - footer_height
    draw.rectangle((0, footer_top, width, height), fill=(255, 255, 255, 255))
    label_size = max(10, min(20, round(footer_height * 0.2)))
    label_font = ImageFont.truetype(font_path, label_size)
    detail = f"{timestamp}    {round(messages_seen):,} / {total_messages:,} messages"
    available_width = width - 48
    title = _truncate_text(draw, title, label_font, available_width)
    detail = _truncate_text(draw, detail, label_font, available_width)
    first_line_y = footer_top + 7
    draw.text((24, first_line_y), title, font=label_font, fill=(35, 35, 35, 255))
    draw.text(
        (24, first_line_y + label_size + 3),
        detail,
        font=label_font,
        fill=(90, 90, 90, 255),
    )

    progress_left, progress_right = 24, width - 24
    progress_y = height - 11
    draw.rounded_rectangle(
        (progress_left, progress_y - 4, progress_right, progress_y + 4),
        radius=4,
        fill=(225, 225, 225, 255),
    )
    fraction = min(1.0, messages_seen / total_messages)
    if fraction > 0:
        draw.rounded_rectangle(
            (
                progress_left,
                progress_y - 4,
                progress_left + (progress_right - progress_left) * fraction,
                progress_y + 4,
            ),
            radius=4,
            fill=(70, 105, 170, 255),
        )


def write_mp4(frames: Iterable[np.ndarray], output_path: Path, fps: int) -> int:
    """Encode RGB frames as H.264 MP4 and return the number of frames.

    The video is written to a temporary file next to `output_path` and moved
    into place only once complete, so a failed run never leaves a truncated
    video behind.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_path.stem}.",
        suffix=output_path.suffix,
        dir=output_path.parent,
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
    writer = imageio.get_writer(
        temporary_path,
        fps=fps,
        codec="libx264",
        macro_block_size=None,
        output_params=["-movflags", "+faststart"],
    )
    frame_count = 0
    try:
        for frame in frames:
            writer.append_data(frame)
            frame_count += 1
        writer.close()
    except BaseException:
        writer.close()
        temporary_path.unlink(missing_ok=True)
        raise
    temporary_path.replace(output_path)
    return frame_count
