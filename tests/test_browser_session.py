import io
from pathlib import Path

import pytest
from PIL import Image

from chat_to_cloud import fonts
from chat_to_cloud.browser import BrowserSession

pytestmark = pytest.mark.fonts


@pytest.fixture
def session(sample_chat: Path) -> BrowserSession:
    browser_session = BrowserSession(fonts.font_dir())
    browser_session.load_chat(sample_chat.read_text(encoding="utf-8-sig"))
    return browser_session


def test_load_chat_summarizes_messages_and_tokens(sample_chat: Path) -> None:
    session = BrowserSession(fonts.font_dir())

    summary = session.load_chat("﻿" + sample_chat.read_text(encoding="utf-8"))

    assert summary["messages"] == 8
    assert summary["participants"] == ["Alice", "Bob"]
    assert summary["first"] is not None
    assert all(summary["tokens"][language] > 0 for language in ("en", "fa", "emoji"))


def test_static_png_is_a_png_of_the_requested_size(session: BrowserSession) -> None:
    data = session.static_png("fa", 320, 200)

    assert data is not None
    assert Image.open(io.BytesIO(data)).size == (320, 200)


def test_static_png_is_none_without_tokens() -> None:
    session = BrowserSession(fonts.font_dir())
    session.load_chat("1/1/20, 10:00 - A: only english words\n")

    assert session.static_png("emoji", 320, 200) is None


@pytest.mark.parametrize("kind", ["stable", "dynamic"])
def test_animation_yields_announced_rgbx_frames(
    session: BrowserSession, kind: str
) -> None:
    info = session.start_animation(kind, "emoji", "chat", 160, 160)  # type: ignore[arg-type]

    assert info is not None
    frames = []
    while (frame := session.next_frame()) is not None:
        frames.append(frame)
    assert len(frames) == info["frame_count"]
    assert {len(frame) for frame in frames} == {160 * 160 * 4}
    assert frames[0][3::4] == b"\xff" * (160 * 160)


def test_unknown_language_is_rejected(session: BrowserSession) -> None:
    with pytest.raises(ValueError, match="language"):
        session.static_png("de", 320, 200)
