from pathlib import Path

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


def test_emoji_tokens_keep_modifier_and_zwj_sequences(sample_chat: Path) -> None:
    tokens = tokens_for_language(read_chat(sample_chat), "emoji")

    assert tokens == ["☕", "😀", "😀", "👍🏽", "👨‍👩‍👧", "❤️"]


def test_tokens_by_message_keeps_one_entry_per_message(sample_chat: Path) -> None:
    messages = read_chat(sample_chat)

    grouped = tokens_by_message(messages, "emoji")

    assert len(grouped) == len(messages)
    assert grouped[2] == ["😀", "😀"]
    assert grouped[0] == []
