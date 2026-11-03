"""Cumulative word-cloud animation in which the layout reflows continuously.

Every frame is derived from the one before it. Font sizes interpolate between
cumulative keyframes while a collision resolver moves words only as far as
necessary, so words grow, shrink, enter, leave, and reflow without jumping
between unrelated layouts.
"""

import colorsys
import hashlib
import logging
import math
import os
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from chat_to_cloud import video
from chat_to_cloud.cloud import make_wordcloud
from chat_to_cloud.tokens import Language, tokens_by_message
from chat_to_cloud.whatsapp import Message

logger = logging.getLogger(__name__)

type Rectangle = tuple[float, float, float, float]


@dataclass(frozen=True)
class DynamicSettings:
    """Rendering parameters for `render_dynamic_animation`."""

    width: int = 1280
    height: int = 960
    keyframes: int = 24
    # Interpolated frames between consecutive frequency keyframes.
    frames_per_step: int = 36
    fps: int = 24
    max_words: int = 100
    # WordCloud's frequency-to-size scaling, 0 (rank only) to 1 (linear).
    relative_scaling: float = 0.5
    # Fraction of the canvas area that word boxes may cover.
    fill_ratio: float = 0.46
    random_state: int = 42
    packing_margin: float = 2.0
    # Words whose target moves more than this many px per frame fade out and
    # back in rather than sliding; 0 selects a size-based threshold.
    max_movement: float = 0.0
    hold_seconds: float = 0.75
    # Parallel raster workers; 0 selects up to four automatically.
    workers: int = 0
    # Check every planned frame for overlapping word boxes before encoding.
    verify_layout: bool = False

    def __post_init__(self) -> None:
        video.check_dimensions(self.width, self.height)
        if not 0 <= self.relative_scaling <= 1:
            raise ValueError("relative_scaling must be between 0 and 1")
        if not 0 < self.fill_ratio < 0.8:
            raise ValueError("fill_ratio must be greater than 0 and below 0.8")
        for name in ("packing_margin", "max_movement", "hold_seconds", "workers"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class _WordStyle:
    """Frequency-derived visual properties at one moment."""

    font_size: float
    alpha: float


@dataclass(frozen=True)
class _LayoutWord:
    """One word's geometry in one frame.

    `box_font_size` sizes the collision box, which can differ from the drawn
    `font_size` while a word fades.
    """

    word: str
    font_size: float
    box_font_size: float
    center_x: float
    center_y: float
    color: tuple[int, int, int]
    alpha: float = 1.0


@dataclass(frozen=True)
class _FrameSpec:
    words: tuple[_LayoutWord, ...]
    timestamp: str
    messages_seen: float


@dataclass(frozen=True)
class _RenderTask:
    """Picklable input for rendering one frame, possibly in a worker process."""

    frame: _FrameSpec
    font_path: Path
    label_font_path: Path
    width: int
    height: int
    footer_height: int
    title: str
    total_messages: int


def _stable_color(word: str) -> tuple[int, int, int]:
    digest = hashlib.blake2b(word.encode("utf-8"), digest_size=4).digest()
    hue = int.from_bytes(digest, "big") / (2**32 - 1)
    red, green, blue = colorsys.hsv_to_rgb(hue, 0.68, 0.62)
    return round(red * 255), round(green * 255), round(blue * 255)


@lru_cache(maxsize=32768)
def _text_box(word: str, font_path: Path, font_size: int) -> tuple[float, ...]:
    font = ImageFont.truetype(font_path, font_size)
    image = Image.new("L", (1, 1))
    return ImageDraw.Draw(image).textbbox((0, 0), word, font=font, anchor="lt")


def _text_dimensions(
    word: str, font_path: Path, font_size: float
) -> tuple[float, float]:
    left, top, right, bottom = _text_box(word, font_path, max(1, round(font_size)))
    return right - left, bottom - top


def _keyframe_styles(
    frequencies: Counter[str],
    *,
    font_path: Path,
    width: int,
    height: int,
    max_words: int,
    relative_scaling: float,
    fill_ratio: float,
    random_state: int,
) -> dict[str, _WordStyle]:
    """Use static WordCloud sizes, uniformly scaled for rectangle packing."""
    if not frequencies:
        return {}
    cloud = make_wordcloud(
        frequencies,
        font_path,
        width,
        height,
        max_words=max_words,
        random_state=random_state,
        relative_scaling=relative_scaling,
    )
    static_sizes = {
        word: float(font_size) for (word, _), font_size, _, _, _ in cloud.layout_
    }
    total_area = 0.0
    for word, font_size in static_sizes.items():
        word_width, word_height = _text_dimensions(word, font_path, font_size)
        total_area += (word_width + 4) * (word_height + 4)
    area_scale = math.sqrt(width * height * fill_ratio / max(1.0, total_area))
    scale = min(1.0, area_scale)
    return {
        word: _WordStyle(font_size=max(1.0, size * scale), alpha=1.0)
        for word, size in static_sizes.items()
    }


def _ease(progress: float) -> float:
    """Smootherstep easing with continuous acceleration at both endpoints."""
    return progress**3 * (progress * (progress * 6 - 15) + 10)


def _interpolate_styles(
    first: dict[str, _WordStyle],
    second: dict[str, _WordStyle],
    progress: float,
    relocated_words: set[str],
) -> dict[str, _WordStyle]:
    """Blend two keyframes; relocated words fade out, then in at the new size."""
    eased = _ease(progress)
    result: dict[str, _WordStyle] = {}
    for word in first.keys() | second.keys():
        old = first.get(word)
        new = second.get(word)
        if word in relocated_words and old is not None and new is not None:
            if progress < 0.45:
                result[word] = _WordStyle(old.font_size, 1.0 - _ease(progress / 0.45))
            elif progress > 0.55:
                result[word] = _WordStyle(
                    new.font_size, _ease((progress - 0.55) / 0.45)
                )
            continue
        if old is not None and new is not None:
            result[word] = _WordStyle(
                old.font_size + (new.font_size - old.font_size) * eased, 1.0
            )
        elif new is not None:
            result[word] = _WordStyle(new.font_size * (0.18 + 0.82 * eased), eased)
        elif old is not None and eased < 1.0:
            result[word] = _WordStyle(old.font_size * (1.0 - 0.82 * eased), 1.0 - eased)
    return result


def _rectangle(
    word: str,
    font_size: float,
    center_x: float,
    center_y: float,
    font_path: Path,
    margin: float,
) -> Rectangle:
    word_width, word_height = _text_dimensions(word, font_path, font_size)
    half_width = word_width / 2 + margin
    half_height = word_height / 2 + margin
    return (
        center_x - half_width,
        center_y - half_height,
        center_x + half_width,
        center_y + half_height,
    )


def _rectangles_overlap(first: Rectangle, second: Rectangle) -> bool:
    return not (
        first[2] <= second[0]
        or second[2] <= first[0]
        or first[3] <= second[1]
        or second[3] <= first[1]
    )


def _position_is_free(
    rectangle: Rectangle, placed: Iterable[Rectangle], width: int, height: int
) -> bool:
    if (
        rectangle[0] < 0
        or rectangle[1] < 0
        or rectangle[2] > width
        or rectangle[3] > height
    ):
        return False
    return all(not _rectangles_overlap(rectangle, other) for other in placed)


def _spiral_positions(
    origin_x: float,
    origin_y: float,
    width: int,
    height: int,
    *,
    step: float = 0.42,
    radial_step: float = 1.4,
) -> Iterator[tuple[float, float]]:
    """Yield the origin followed by increasingly distant candidates."""
    yield origin_x, origin_y
    maximum_radius = math.hypot(width, height)
    index = 1
    while True:
        angle = index * step
        radius = index * radial_step * step
        if radius > maximum_radius:
            break
        yield origin_x + math.cos(angle) * radius, origin_y + math.sin(angle) * radius
        index += 1


def _nearest_free_position(
    word: str,
    font_size: float,
    origin_x: float,
    origin_y: float,
    placed: Sequence[Rectangle],
    *,
    font_path: Path,
    width: int,
    height: int,
    margin: float,
) -> tuple[float, float] | None:
    for center_x, center_y in _spiral_positions(origin_x, origin_y, width, height):
        rectangle = _rectangle(word, font_size, center_x, center_y, font_path, margin)
        if _position_is_free(rectangle, placed, width, height):
            return center_x, center_y
    return None


def _pack_initial_layout(
    styles: dict[str, _WordStyle],
    *,
    font_path: Path,
    width: int,
    height: int,
    margin: float,
) -> dict[str, _LayoutWord]:
    """Pack a complete cloud, shrinking all words uniformly until it fits."""
    current_styles = styles
    for _ in range(12):
        layout: dict[str, _LayoutWord] = {}
        rectangles: list[Rectangle] = []
        ordered = sorted(
            current_styles.items(), key=lambda item: (-item[1].font_size, item[0])
        )
        for word, style in ordered:
            position = _nearest_free_position(
                word,
                style.font_size,
                width / 2,
                height / 2,
                rectangles,
                font_path=font_path,
                width=width,
                height=height,
                margin=margin,
            )
            if position is None:
                break
            center_x, center_y = position
            layout[word] = _LayoutWord(
                word=word,
                font_size=style.font_size,
                box_font_size=style.font_size,
                center_x=center_x,
                center_y=center_y,
                color=_stable_color(word),
            )
            rectangles.append(
                _rectangle(word, style.font_size, center_x, center_y, font_path, margin)
            )
        if len(layout) == len(current_styles):
            return layout
        current_styles = {
            word: replace(style, font_size=style.font_size * 0.92)
            for word, style in current_styles.items()
        }
    raise ValueError("Unable to fit the initial dynamic word cloud")


def _clamp(center: float, half_extent: float, limit: int) -> float:
    """Keep a box of the given half extent inside [0, limit]."""
    return min(limit - half_extent, max(half_extent, center))


def _reflow_from_previous(
    previous: dict[str, _LayoutWord],
    styles: dict[str, _WordStyle],
    desired_centers: dict[str, tuple[float, float]],
    *,
    font_path: Path,
    width: int,
    height: int,
    margin: float,
    max_iterations: int = 60,
) -> dict[str, _LayoutWord]:
    """Place all words at their desired centers and push overlaps apart.

    Overlapping pairs separate along the axis of least overlap, each moving in
    inverse proportion to its area, so large words stay put. If collisions
    remain after `max_iterations`, all words shrink uniformly and the
    resolution restarts.
    """
    words = sorted(styles)
    for scale_index in range(100, 3, -2):
        scale = scale_index / 100
        centers_x: list[float] = []
        centers_y: list[float] = []
        half_widths: list[float] = []
        half_heights: list[float] = []
        active: list[int] = []
        for index, word in enumerate(words):
            style = styles[word]
            center_x, center_y = desired_centers.get(word, (width / 2, height / 2))
            font_size = style.font_size * scale
            word_width, word_height = _text_dimensions(word, font_path, font_size)
            centers_x.append(center_x)
            centers_y.append(center_y)
            half_widths.append(word_width / 2 + margin)
            half_heights.append(word_height / 2 + margin)
            if style.alpha > 0.02 and font_size >= 3:
                active.append(index)

        for index in active:
            centers_x[index] = _clamp(centers_x[index], half_widths[index], width)
            centers_y[index] = _clamp(centers_y[index], half_heights[index], height)

        for _ in range(max_iterations):
            shifts_x = [0.0] * len(words)
            shifts_y = [0.0] * len(words)
            collision_found = False
            # Sweep along x: once a later box starts right of the current box's
            # right edge, no further box in this order can overlap it.
            order = sorted(
                active, key=lambda index: centers_x[index] - half_widths[index]
            )
            for order_index, first in enumerate(order):
                first_right = centers_x[first] + half_widths[first]
                for second in order[order_index + 1 :]:
                    if centers_x[second] - half_widths[second] >= first_right:
                        break
                    delta_x = centers_x[second] - centers_x[first]
                    delta_y = centers_y[second] - centers_y[first]
                    overlap_x = half_widths[first] + half_widths[second] - abs(delta_x)
                    overlap_y = (
                        half_heights[first] + half_heights[second] - abs(delta_y)
                    )
                    if overlap_x <= 0 or overlap_y <= 0:
                        continue
                    collision_found = True
                    first_mass = max(1.0, styles[words[first]].font_size ** 2)
                    second_mass = max(1.0, styles[words[second]].font_size ** 2)
                    total_mass = first_mass + second_mass
                    first_share = second_mass / total_mass
                    second_share = first_mass / total_mass
                    if overlap_x < overlap_y:
                        if delta_x == 0:
                            direction = 1.0 if first < second else -1.0
                        else:
                            direction = 1.0 if delta_x > 0 else -1.0
                        separation = overlap_x + 0.2
                        shifts_x[first] -= direction * separation * first_share
                        shifts_x[second] += direction * separation * second_share
                    else:
                        if delta_y == 0:
                            direction = 1.0 if first < second else -1.0
                        else:
                            direction = 1.0 if delta_y > 0 else -1.0
                        separation = overlap_y + 0.2
                        shifts_y[first] -= direction * separation * first_share
                        shifts_y[second] += direction * separation * second_share
            if not collision_found:
                break
            for index in active:
                centers_x[index] = _clamp(
                    centers_x[index] + shifts_x[index], half_widths[index], width
                )
                centers_y[index] = _clamp(
                    centers_y[index] + shifts_y[index], half_heights[index], height
                )

        rectangles: list[Rectangle] = []
        valid = True
        for index in active:
            rectangle = (
                centers_x[index] - half_widths[index],
                centers_y[index] - half_heights[index],
                centers_x[index] + half_widths[index],
                centers_y[index] + half_heights[index],
            )
            if not _position_is_free(rectangle, rectangles, width, height):
                valid = False
                break
            rectangles.append(rectangle)
        if not valid:
            continue

        result: dict[str, _LayoutWord] = {}
        for index, word in enumerate(words):
            style = styles[word]
            old = previous.get(word)
            result[word] = _LayoutWord(
                word=word,
                font_size=style.font_size * scale,
                box_font_size=style.font_size * scale,
                center_x=centers_x[index],
                center_y=centers_y[index],
                color=old.color if old is not None else _stable_color(word),
                alpha=style.alpha,
            )
        return result
    raise AssertionError("Unable to resolve a collision-free frame")


def _desired_center(
    word: str,
    old_target: _LayoutWord | None,
    new_target: _LayoutWord | None,
    progress: float,
    relocated: bool,
) -> tuple[float, float] | None:
    if old_target is not None and new_target is not None:
        if relocated:
            chosen = old_target if progress < 0.5 else new_target
            return chosen.center_x, chosen.center_y
        eased = _ease(progress)
        return (
            old_target.center_x + (new_target.center_x - old_target.center_x) * eased,
            old_target.center_y + (new_target.center_y - old_target.center_y) * eased,
        )
    target = new_target or old_target
    return None if target is None else (target.center_x, target.center_y)


def _build_continuous_frames(
    keyframe_styles: Sequence[dict[str, _WordStyle]],
    boundaries: Sequence[int],
    timestamps: Sequence[str],
    *,
    font_path: Path,
    width: int,
    height: int,
    margin: float,
    max_movement: float,
    frames_per_step: int,
    hold_frames: int,
) -> list[_FrameSpec]:
    """Plan every frame sequentially so geometry never resets at a keyframe."""
    target_layouts = [
        _pack_initial_layout(
            styles, font_path=font_path, width=width, height=height, margin=margin
        )
        for styles in keyframe_styles
    ]
    effective_styles = [
        {word: _WordStyle(item.font_size, 1.0) for word, item in layout.items()}
        for layout in target_layouts
    ]
    previous = target_layouts[0]
    frames = [
        _FrameSpec(tuple(previous.values()), timestamps[0], boundaries[0])
        for _ in range(hold_frames)
    ]

    relocation_threshold = math.hypot(width, height) * 0.55
    if max_movement > 0:
        # 1.875 is the peak speed of smootherstep, so this bounds the fastest
        # per-frame movement of a sliding word.
        relocation_threshold = min(
            relocation_threshold, max_movement * frames_per_step / 1.875
        )
    for keyframe_index in range(1, len(effective_styles)):
        old_layout = target_layouts[keyframe_index - 1]
        new_layout = target_layouts[keyframe_index]
        relocated_words = {
            word
            for word in old_layout.keys() & new_layout.keys()
            if math.hypot(
                new_layout[word].center_x - old_layout[word].center_x,
                new_layout[word].center_y - old_layout[word].center_y,
            )
            > relocation_threshold
        }
        for step_index in range(1, frames_per_step + 1):
            progress = step_index / frames_per_step
            styles = _interpolate_styles(
                effective_styles[keyframe_index - 1],
                effective_styles[keyframe_index],
                progress,
                relocated_words,
            )
            desired_centers = {}
            for word in styles:
                center = _desired_center(
                    word,
                    old_layout.get(word),
                    new_layout.get(word),
                    progress,
                    word in relocated_words,
                )
                if center is not None:
                    desired_centers[word] = center
            previous = _reflow_from_previous(
                previous,
                styles,
                desired_centers,
                font_path=font_path,
                width=width,
                height=height,
                margin=margin,
            )
            messages_seen = boundaries[keyframe_index - 1] + (
                boundaries[keyframe_index] - boundaries[keyframe_index - 1]
            ) * _ease(progress)
            timestamp = timestamps[
                keyframe_index if progress >= 0.5 else keyframe_index - 1
            ]
            frames.append(
                _FrameSpec(tuple(previous.values()), timestamp, messages_seen)
            )
        logger.debug(
            "Planned keyframe %d/%d", keyframe_index + 1, len(effective_styles)
        )

    frames.extend(frames[-1] for _ in range(hold_frames))
    return frames


def _render_frame(task: _RenderTask) -> np.ndarray:
    image = Image.new("RGBA", (task.width, task.height), "white")
    words_layer = Image.new("RGBA", (task.width, task.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(words_layer)
    for item in sorted(task.frame.words, key=lambda value: value.font_size):
        if item.alpha <= 0.02 or item.font_size < 3:
            continue
        font_size = max(1, round(item.font_size))
        font = ImageFont.truetype(task.font_path, font_size)
        left, top, right, bottom = _text_box(item.word, task.font_path, font_size)
        x = item.center_x - (left + right) / 2
        y = item.center_y - (top + bottom) / 2
        draw.text(
            (round(x), round(y)),
            item.word,
            font=font,
            fill=(*item.color, round(255 * item.alpha)),
            anchor="lt",
        )

    image = Image.alpha_composite(image, words_layer)
    video.draw_footer(
        image,
        font_path=task.label_font_path,
        footer_height=task.footer_height,
        title=task.title,
        timestamp=task.frame.timestamp,
        messages_seen=task.frame.messages_seen,
        total_messages=task.total_messages,
    )
    return np.asarray(image.convert("RGB"))


def _render_tasks(tasks: Sequence[_RenderTask], workers: int) -> Iterator[np.ndarray]:
    if workers == 1:
        for task in tasks:
            yield _render_frame(task)
        return
    with ProcessPoolExecutor(max_workers=workers) as executor:
        yield from executor.map(_render_frame, tasks, chunksize=1)


def _assert_no_overlaps(
    frames: Sequence[_FrameSpec],
    *,
    font_path: Path,
    width: int,
    height: int,
    margin: float,
) -> None:
    """Verify that every planned frame follows the bounding-box rule."""
    for frame_index, frame in enumerate(frames):
        rectangles: list[Rectangle] = []
        for item in frame.words:
            if item.alpha <= 0.02 or item.font_size < 3:
                continue
            rectangle = _rectangle(
                item.word,
                item.box_font_size,
                item.center_x,
                item.center_y,
                font_path,
                margin,
            )
            if not _position_is_free(rectangle, rectangles, width, height):
                raise AssertionError(
                    f"Overlapping word rectangles in planned frame {frame_index}"
                )
            rectangles.append(rectangle)


def render_dynamic_animation(
    messages: Sequence[Message],
    language: Language,
    output_path: Path,
    *,
    font_path: Path,
    label_font_path: Path,
    title: str,
    settings: DynamicSettings | None = None,
) -> bool:
    """Write the animation as MP4; return False when there is nothing to show."""
    settings = settings or DynamicSettings()
    if not messages:
        logger.info("Skipping %s: no messages were parsed", output_path)
        return False
    grouped_tokens = tokens_by_message(messages, language)
    if not any(grouped_tokens):
        logger.info("Skipping %s: no %s tokens", output_path, language)
        return False

    timeline = video.build_timeline(
        messages, grouped_tokens, settings.keyframes
    ).without_leading_empty()
    footer_height = video.footer_height_for(settings.height)
    cloud_height = settings.height - footer_height
    styles = [
        _keyframe_styles(
            frequencies,
            font_path=font_path,
            width=settings.width,
            height=cloud_height,
            max_words=settings.max_words,
            relative_scaling=settings.relative_scaling,
            fill_ratio=settings.fill_ratio,
            random_state=settings.random_state,
        )
        for frequencies in timeline.snapshots
    ]
    frames = _build_continuous_frames(
        styles,
        timeline.boundaries,
        timeline.timestamps,
        font_path=font_path,
        width=settings.width,
        height=cloud_height,
        margin=settings.packing_margin,
        max_movement=settings.max_movement,
        frames_per_step=settings.frames_per_step,
        hold_frames=max(1, round(settings.hold_seconds * settings.fps)),
    )
    if settings.verify_layout:
        _assert_no_overlaps(
            frames,
            font_path=font_path,
            width=settings.width,
            height=cloud_height,
            margin=settings.packing_margin,
        )

    workers = max(1, settings.workers or min(4, os.cpu_count() or 1))
    tasks = [
        _RenderTask(
            frame=frame,
            font_path=font_path,
            label_font_path=label_font_path,
            width=settings.width,
            height=settings.height,
            footer_height=footer_height,
            title=title,
            total_messages=len(messages),
        )
        for frame in frames
    ]
    frame_count = video.write_mp4(
        _render_tasks(tasks, workers), output_path, settings.fps
    )
    logger.info(
        "Wrote %s (%d frames, %.1fs, %d keyframes, %d render workers)",
        output_path,
        frame_count,
        frame_count / settings.fps,
        len(styles),
        workers,
    )
    return True
