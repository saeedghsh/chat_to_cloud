"""Parse WhatsApp "Export chat" text files into messages."""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ENCODING = "utf-8-sig"

# Matches lines that start a new message in an Android export, e.g.:
#   7/4/19, 15:50 - John Doe: Hello
#   7/4/2019, 3:50 PM - Jane: Hi
#   07/04/19, 15:50:01 - System message...
MSG_START_RE = re.compile(
    r"""
    ^
    (?P<timestamp>
        \d{1,2}\/\d{1,2}\/\d{2,4}      # date like 7/4/19 or 07/04/2019
        ,\s
        \d{1,2}:\d{2}                   # time hh:mm
        (?::\d{2})?                     # optional :ss
        (?:\s?[AP]M)?                   # optional AM/PM
    )
    \s(?:-\s|[\u2013\u2014]\s)          # hyphen or en/em dash followed by space
    (?P<rest>.*)                        # the remainder of the line
    $
    """,
    re.VERBOSE,
)

# Splits "Name: message" into participant and message.
NAME_SPLIT_RE = re.compile(r"^(?P<participant>[^:]+):\s(?P<message>.*)$")


@dataclass(frozen=True)
class Message:
    """One chat message; `participant` is None for system messages."""

    timestamp: str
    participant: str | None
    text: str


def parse_lines(lines: Iterable[str]) -> list[Message]:
    """Parse export lines into messages, joining multi-line messages.

    Timestamps keep their original string form. Lines before the first
    message start are skipped.
    """
    messages: list[Message] = []
    timestamp: str | None = None
    participant: str | None = None
    parts: list[str] = []

    def flush() -> None:
        if timestamp is not None:
            messages.append(Message(timestamp, participant, "\n".join(parts).rstrip()))

    for raw in lines:
        line = raw.rstrip("\r\n")
        start = MSG_START_RE.match(line)
        if start:
            flush()
            timestamp = start.group("timestamp")
            rest = start.group("rest")
            named = NAME_SPLIT_RE.match(rest)
            if named:
                participant = named.group("participant")
                parts = [named.group("message")]
            else:
                participant = None
                parts = [rest]
        elif timestamp is not None:
            parts.append(line)
        else:
            logger.debug("Skipping line before the first message: %r", line)
    flush()
    return messages


def read_chat(path: Path, encoding: str = ENCODING) -> list[Message]:
    """Read an exported chat, tolerating BOMs and legacy Latin-1 exports."""
    try:
        text = path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        logger.warning("%s failed; falling back to latin-1 for %s", encoding, path)
        text = path.read_text(encoding="latin-1")
    return parse_lines(text.splitlines())
