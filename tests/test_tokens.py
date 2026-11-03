from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont, features

from chat_to_cloud import fonts
from chat_to_cloud.tokens import display_form, tokens_by_message, tokens_for_language
from chat_to_cloud.whatsapp import Message, read_chat

ZWNJ = "\N{ZERO WIDTH NON-JOINER}"


def test_english_tokens_are_lowercased_and_filtered(sample_chat: Path) -> None:
    tokens = tokens_for_language(read_chat(sample_chat), "en")

    assert tokens.count("coffee") == 4
    # Stop words, short words, and WhatsApp/link placeholders are dropped.
    for dropped in ("the", "at", "it", "media", "omitted", "youtube", "www"):
        assert dropped not in tokens


def test_farsi_tokens_are_filtered_and_shaped_for_display() -> None:
    messages = [Message("t", "A", f"می{ZWNJ}خواهم از قهوه، ها کتاب")]

    tokens = tokens_for_language(messages, "fa")

    # The ZWNJ-joined word stays whole; stop words are removed; punctuation is
    # stripped before shaping.
    assert tokens == [
        display_form(f"می{ZWNJ}خواهم"),
        display_form("قهوه"),
        display_form("کتاب"),
    ]


def _render(text: str, layout: ImageFont.Layout | None = None) -> Image.Image:
    font = ImageFont.truetype(fonts.font_path(fonts.ARABIC), 48, layout_engine=layout)
    image = Image.new("L", (400, 100), 255)
    ImageDraw.Draw(image).text((10, 10), text, font=font, fill=0)
    return image


@pytest.mark.fonts
@pytest.mark.skipif(not features.check("raqm"), reason="needs Pillow with raqm")
def test_display_form_renders_like_properly_shaped_text() -> None:
    word = "کاپیتان"
    # Reference: raqm given the logical text performs real bidi and shaping.
    expected = _render(word, ImageFont.Layout.RAQM)

    # WordCloud and the animations use Pillow's default layout engine.
    actual = _render(display_form(word))

    assert ImageChops.difference(actual, expected).getbbox() is None


def test_emoji_tokens_keep_modifier_and_zwj_sequences(sample_chat: Path) -> None:
    tokens = tokens_for_language(read_chat(sample_chat), "emoji")

    assert tokens == ["☕", "😀", "😀", "👍🏽", "👨‍👩‍👧", "❤️"]


def test_tokens_by_message_keeps_one_entry_per_message(sample_chat: Path) -> None:
    messages = read_chat(sample_chat)

    grouped = tokens_by_message(messages, "emoji")

    assert len(grouped) == len(messages)
    assert grouped[2] == ["😀", "😀"]
    assert grouped[0] == []
