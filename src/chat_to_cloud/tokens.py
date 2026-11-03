"""Extract English words, Farsi words, and emoji from chat messages."""

import functools
import re
from collections.abc import Callable, Sequence
from typing import Literal

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import features

from chat_to_cloud.whatsapp import Message

type Language = Literal["en", "fa", "emoji"]
LANGUAGES: tuple[Language, ...] = ("en", "fa", "emoji")

# --- English ---------------------------------------------------------------

EN_EXCLUDE = frozenset(
    {
        # WhatsApp placeholders and link fragments
        "media",
        "omitted",
        "link",
        "https",
        "youtube",
        "soundcloud",
        "spotify",
        "instagram",
        "www",
        "com",
        # stop words
        "and",
        "the",
        "is",
        "in",
        "a",
        "of",
        "at",
        "as",
        "if",
    }
)
_EN_WORD_RE = re.compile(r"[A-Za-z]+")

# --- Farsi -----------------------------------------------------------------

# Arabic-script blocks (including Persian letters and presentation forms);
# a word may contain internal zero-width non-joiners (U+200C).
_FA_CHARS = r"\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"
_FA_WORD_RE = re.compile(rf"[{_FA_CHARS}]+(?:\u200C[{_FA_CHARS}]+)*")
# Leading/trailing Latin and Arabic punctuation.
_FA_PUNCT_RE = re.compile(
    r"^[\s\.\,\!\?\-\u060C\u061B\u061F]+|[\s\.\,\!\?\-\u060C\u061B\u061F]+$"
)
FA_EXCLUDE = frozenset({"از", "یا", "با", "می", "ها", "تا"})

# --- Emoji -----------------------------------------------------------------

_ZWJ = r"\u200D"
_MODIFIERS = r"\uFE0E\uFE0F\U0001F3FB-\U0001F3FF"  # variation selectors, skin tones
# A broad, practical class of emoji "core" code points. It deliberately
# over-includes some non-emoji symbols in these blocks, which is acceptable for
# frequency counting.
_EMOJI_CORE = (
    r"\u231A-\u231B"  # watch, hourglass
    r"\u23E9-\u23F3\u23F8-\u23FA"  # media controls
    r"\u24C2"  # circled M
    r"\u25AA-\u25AB\u25B6\u25C0\u25FB-\u25FE"
    r"\u2600-\u27BF"  # misc symbols, dingbats
    r"\u2934-\u2935"
    r"\u2B05-\u2B07\u2B1B-\u2B1C\u2B50\u2B55"
    r"\u3030\u303D\u3297\u3299"
    r"\U0001F170-\U0001F1FF"  # enclosed letters, regional indicators
    r"\U0001F300-\U0001F5FF"  # misc symbols and pictographs
    r"\U0001F600-\U0001F64F"  # emoticons
    r"\U0001F680-\U0001F6FF"  # transport and map
    r"\U0001F700-\U0001F8FF"  # alchemical, geometric ext., arrows supplement
    r"\U0001F900-\U0001F9FF"  # supplemental symbols and pictographs
    r"\U0001FA00-\U0001FAFF"  # chess, legacy computing, extended-A
    r"\U0001FB00-\U0001FBFF"
)
# A core emoji with an optional modifier, followed by any ZWJ-joined parts
# (families, professions, etc.).
_EMOJI_UNIT = rf"[{_EMOJI_CORE}][{_MODIFIERS}]?"
_EMOJI_RE = re.compile(rf"{_EMOJI_UNIT}(?:{_ZWJ}{_EMOJI_UNIT})*")


def extract_english(text: str) -> list[str]:
    """Return ASCII alphabetic word tokens."""
    return _EN_WORD_RE.findall(text)


def extract_farsi(text: str) -> list[str]:
    """Return Arabic-script word tokens, keeping internal ZWNJs."""
    return _FA_WORD_RE.findall(text)


def extract_emojis(text: str) -> list[str]:
    """Return emoji sequences, including modifier and ZWJ sequences."""
    return _EMOJI_RE.findall(text)


def _clean_english(tokens: Sequence[str]) -> list[str]:
    lowered = (token.lower().strip() for token in tokens)
    return [t for t in lowered if len(t) > 2 and t not in EN_EXCLUDE]


@functools.cache
def _pillow_shapes_text() -> bool:
    """Return whether Pillow lays out complex scripts itself (via libraqm).

    Pip wheels of Pillow use raqm when the system provides FriBiDi; other
    builds (e.g. conda's) draw characters one by one, left to right.
    """
    return bool(features.check("raqm"))


def display_form(word: str) -> str:
    """Return the string to hand to Pillow so that `word` renders correctly.

    With raqm, Pillow reorders and shapes Arabic script itself, so the
    logical text is passed through; pre-shaping it would be reversed again.
    Without raqm, the word is converted to joined letter forms in visual order.
    """
    if _pillow_shapes_text():
        return word
    return str(get_display(arabic_reshaper.reshape(word)))


def _clean_farsi(tokens: Sequence[str]) -> list[str]:
    kept = (token.strip() for token in tokens)
    result = []
    for token in kept:
        if len(token) <= 1 or token in FA_EXCLUDE:
            continue
        clean = _FA_PUNCT_RE.sub("", token).strip()
        if clean:
            result.append(display_form(clean))
    return result


def _clean_emojis(tokens: Sequence[str]) -> list[str]:
    return [token for token in tokens if token]


_PIPELINES: dict[
    Language, tuple[Callable[[str], list[str]], Callable[[Sequence[str]], list[str]]]
] = {
    "en": (extract_english, _clean_english),
    "fa": (extract_farsi, _clean_farsi),
    "emoji": (extract_emojis, _clean_emojis),
}


def tokens_by_message(
    messages: Sequence[Message], language: Language
) -> list[list[str]]:
    """Return render-ready tokens for each message, in chronological order."""
    extract, clean = _PIPELINES[language]
    return [clean(extract(message.text)) for message in messages]


def tokens_for_language(messages: Sequence[Message], language: Language) -> list[str]:
    """Return all render-ready tokens for a language."""
    return [
        token for tokens in tokens_by_message(messages, language) for token in tokens
    ]
