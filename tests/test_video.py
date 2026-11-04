from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import imageio.v3 as iio
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from chat_to_cloud import fonts
from chat_to_cloud.tokens import Language, display_form
from chat_to_cloud.video import (
    build_timeline,
    check_dimensions,
    draw_word,
    word_sprite,
    write_mp4,
)
from chat_to_cloud.whatsapp import Message


def _messages(count: int) -> list[Message]:
    return [Message(f"t{index}", "A", "") for index in range(count)]


def test_timeline_samples_cumulative_counts_and_ends_at_last_message() -> None:
    grouped = [["a"], [], ["a", "b"], ["c"], ["b"]]

    timeline = build_timeline(_messages(5), grouped, keyframe_count=2)

    assert timeline.boundaries == [2, 5]  # rounded halves of five messages
    assert timeline.snapshots == [Counter(a=1), Counter(a=2, b=2, c=1)]
    assert timeline.timestamps == ["t1", "t4"]


def test_timeline_never_has_more_keyframes_than_messages() -> None:
    timeline = build_timeline(_messages(3), [["a"]] * 3, keyframe_count=10)

    assert timeline.boundaries == [1, 2, 3]


def test_timeline_can_drop_leading_empty_keyframes() -> None:
    grouped: list[list[str]] = [[], [], ["a"], ["b"]]

    timeline = build_timeline(_messages(4), grouped, 4).without_leading_empty()

    assert timeline.boundaries == [3, 4]
    assert timeline.timestamps == ["t2", "t3"]


@pytest.mark.parametrize(("width", "height"), [(161, 200), (200, 158)])
def test_check_dimensions_rejects_odd_or_small_sizes(width: int, height: int) -> None:
    with pytest.raises(ValueError, match="even and at least"):
        check_dimensions(width, height)


def test_write_mp4_encodes_all_frames(tmp_path: Path) -> None:
    frames = [np.full((160, 160, 3), shade, dtype=np.uint8) for shade in (0, 255)]
    output = tmp_path / "out.mp4"

    assert write_mp4(frames, output, fps=4) == 2
    assert iio.imread(output, plugin="FFMPEG").shape == (2, 160, 160, 3)
    assert list(tmp_path.iterdir()) == [output]


def test_write_mp4_leaves_nothing_behind_on_failure(tmp_path: Path) -> None:
    def failing_frames() -> Iterator[np.ndarray]:
        yield np.zeros((160, 160, 3), dtype=np.uint8)
        raise RuntimeError("render failed")

    with pytest.raises(RuntimeError, match="render failed"):
        write_mp4(failing_frames(), tmp_path / "out.mp4", fps=4)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.fonts
@pytest.mark.parametrize("language", ["en", "fa", "emoji"])
def test_cached_word_drawing_matches_draw_text(language: Language) -> None:
    font_path = fonts.font_path(fonts.LANGUAGE_FONTS[language])
    word = {
        "en": "Coffee",
        "fa": display_form("قهوه\N{ZERO WIDTH NON-JOINER}ها"),
        "emoji": "😀",
    }[language]
    # Overlapping, translucent words exercise blending order as well.
    placements = [
        ((10, 12), 40, (200, 30, 30, 255)),
        ((25, 20), 33, (30, 90, 200, 140)),
    ]
    expected = Image.new("RGBA", (160, 100), (0, 0, 0, 0))
    actual = expected.copy()
    expected_draw, actual_draw = ImageDraw.Draw(expected), ImageDraw.Draw(actual)
    for position, size, fill in placements:
        expected_draw.text(
            position,
            word,
            font=ImageFont.truetype(font_path, size),
            fill=fill,
            anchor="lt",
        )
        draw_word(actual_draw, position, word_sprite(word, font_path, size), fill)

    assert actual.tobytes() == expected.tobytes()
