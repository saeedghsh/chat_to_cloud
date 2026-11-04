from pathlib import Path

import pytest

from chat_to_cloud import fonts
from chat_to_cloud.dynamic_animation import DynamicSettings, dynamic_animation
from chat_to_cloud.stable_animation import StableSettings, stable_animation
from chat_to_cloud.tokens import Language
from chat_to_cloud.whatsapp import Message, read_chat

pytestmark = pytest.mark.fonts


@pytest.mark.parametrize("language", ["en", "fa", "emoji"])
def test_announced_frame_count_matches_rendered_frames(
    sample_chat: Path, language: Language
) -> None:
    messages = read_chat(sample_chat)
    font = fonts.font_path(fonts.LANGUAGE_FONTS[language])
    label_font = fonts.font_path(fonts.LABEL_FONT)
    animations = [
        stable_animation(
            messages,
            language,
            font_path=font,
            label_font_path=label_font,
            title="t",
            settings=StableSettings(320, 240, keyframes=3, frames_per_step=2, fps=4),
        ),
        dynamic_animation(
            messages,
            language,
            font_path=font,
            label_font_path=label_font,
            title="t",
            settings=DynamicSettings(
                320, 240, keyframes=3, frames_per_step=2, fps=4, workers=1
            ),
        ),
    ]

    for animation in animations:
        assert animation is not None
        frames = list(animation.frames)
        assert len(frames) == animation.frame_count
        assert {frame.shape for frame in frames} == {(240, 320, 3)}


def test_animations_are_none_without_tokens() -> None:
    messages = [Message("1/1/20, 10:00", "A", "only english words")]
    font = fonts.font_path(fonts.ARABIC)
    label_font = fonts.font_path(fonts.LABEL_FONT)

    assert (
        stable_animation(
            messages, "fa", font_path=font, label_font_path=label_font, title="t"
        )
        is None
    )
    assert (
        dynamic_animation(
            messages, "fa", font_path=font, label_font_path=label_font, title="t"
        )
        is None
    )
