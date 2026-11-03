from pathlib import Path

from chat_to_cloud.whatsapp import Message, parse_lines, read_chat


def test_read_chat_parses_participants_system_and_multiline(
    sample_chat: Path,
) -> None:
    messages = read_chat(sample_chat)

    assert len(messages) == 8
    assert messages[0].participant is None
    assert messages[0].text.startswith("Messages and calls are end-to-end")
    assert messages[1] == Message(
        "1/2/24, 09:01", "Alice", "Good morning! Coffee later? ☕"
    )
    assert messages[3].text == (
        "Sure, coffee at the usual place.\nIt has the best coffee in town."
    )
    assert messages[-1].timestamp == "1/4/24, 7:15 PM"


def test_parse_lines_skips_text_before_first_message() -> None:
    messages = parse_lines(["stray header", "12/31/23, 23:59:59 - Bob: Hi"])

    assert messages == [Message("12/31/23, 23:59:59", "Bob", "Hi")]


def test_parse_lines_accepts_en_dash_separator() -> None:
    messages = parse_lines(["7/4/2019, 3:50 PM \u2013 Jane: Hello"])

    assert messages == [Message("7/4/2019, 3:50 PM", "Jane", "Hello")]


def test_read_chat_falls_back_to_latin1(tmp_path: Path) -> None:
    chat = tmp_path / "legacy.txt"
    chat.write_bytes("1/2/24, 09:01 - Zo\xe9: caf\xe9".encode("latin-1"))

    assert read_chat(chat) == [Message("1/2/24, 09:01", "Zoé", "café")]
