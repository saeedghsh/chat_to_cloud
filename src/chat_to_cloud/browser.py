"""Session object that the static web page drives through Pyodide.

The page passes the chat text in and receives PNG bytes or raw video frames
back, so the chat never leaves the browser. Video encoding happens in
JavaScript because ffmpeg is not available there.
"""

import io
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np

from chat_to_cloud import fonts
from chat_to_cloud.cloud import static_cloud
from chat_to_cloud.dynamic_animation import DynamicSettings, dynamic_animation
from chat_to_cloud.stable_animation import StableSettings, stable_animation
from chat_to_cloud.tokens import LANGUAGES, Language, tokens_for_language
from chat_to_cloud.video import Animation
from chat_to_cloud.whatsapp import Message, parse_lines

type AnimationKind = Literal["stable", "dynamic"]


class ChatSummary(TypedDict):
    """Facts about a loaded chat; `tokens` counts distinct tokens per language."""

    messages: int
    participants: list[str]
    first: str | None
    last: str | None
    tokens: dict[str, int]


class VideoInfo(TypedDict):
    """Encoding parameters for the frames that `next_frame` will return."""

    frame_count: int
    fps: int
    width: int
    height: int


def _language(value: str) -> Language:
    for language in LANGUAGES:
        if language == value:
            return language
    raise ValueError(f"Unknown language: {value!r}")


class BrowserSession:
    """Hold one chat and at most one animation that is being rendered."""

    def __init__(self, font_directory: Path) -> None:
        self._font_directory = font_directory
        self._messages: list[Message] = []
        self._animation: Animation | None = None

    def _font(self, source: fonts.FontSource) -> Path:
        return fonts.font_path(source, self._font_directory)

    def load_chat(self, text: str) -> ChatSummary:
        """Parse an exported chat, replacing any previous one."""
        self._messages = parse_lines(text.removeprefix("﻿").splitlines())
        self._animation = None
        participants = {m.participant for m in self._messages if m.participant}
        return ChatSummary(
            messages=len(self._messages),
            participants=sorted(participants),
            first=self._messages[0].timestamp if self._messages else None,
            last=self._messages[-1].timestamp if self._messages else None,
            tokens={
                language: len(set(tokens_for_language(self._messages, language)))
                for language in LANGUAGES
            },
        )

    def static_png(self, language: str, width: int, height: int) -> bytes | None:
        """Render a word cloud with a fresh layout; None when there are no tokens."""
        chosen = _language(language)
        image = static_cloud(
            tokens_for_language(self._messages, chosen),
            self._font(fonts.LANGUAGE_FONTS[chosen]),
            width=width,
            height=height,
        )
        if image is None:
            return None
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def start_animation(
        self,
        kind: AnimationKind,
        language: str,
        title: str,
        width: int,
        height: int,
    ) -> VideoInfo | None:
        """Lay out an animation; None when there are no tokens.

        Frames are then pulled one at a time with `next_frame`.
        """
        chosen = _language(language)
        font_path = self._font(fonts.LANGUAGE_FONTS[chosen])
        label_font_path = self._font(fonts.LABEL_FONT)
        full_title = f"{title} — {chosen}"
        if kind == "stable":
            animation = stable_animation(
                self._messages,
                chosen,
                font_path=font_path,
                label_font_path=label_font_path,
                title=full_title,
                settings=StableSettings(width=width, height=height),
            )
        elif kind == "dynamic":
            # Pyodide cannot start processes, so render in this one.
            animation = dynamic_animation(
                self._messages,
                chosen,
                font_path=font_path,
                label_font_path=label_font_path,
                title=f"{full_title} dynamic",
                settings=DynamicSettings(width=width, height=height, workers=1),
            )
        else:
            raise ValueError(f"Unknown animation kind: {kind!r}")
        self._animation = animation
        if animation is None:
            return None
        return VideoInfo(
            frame_count=animation.frame_count,
            fps=animation.fps,
            width=animation.width,
            height=animation.height,
        )

    def next_frame(self) -> bytes | None:
        """Return the next frame as RGBX bytes, or None after the last one.

        WebCodecs accepts four bytes per pixel, so a constant fourth byte is
        appended to every RGB pixel.
        """
        if self._animation is None:
            return None
        frame = next(self._animation.frames, None)
        if frame is None:
            self._animation = None
            return None
        height, width, _ = frame.shape
        padded = np.full((height, width, 4), 255, dtype=np.uint8)
        padded[..., :3] = frame
        return padded.tobytes()
