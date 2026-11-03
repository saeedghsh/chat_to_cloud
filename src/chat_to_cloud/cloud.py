"""Static word clouds built with the `wordcloud` package."""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from wordcloud import WordCloud

logger = logging.getLogger(__name__)


def make_wordcloud(
    frequencies: Mapping[str, int],
    font_path: Path,
    width: int = 1600,
    height: int = 1200,
    *,
    max_words: int = 200,
    random_state: int | None = None,
    relative_scaling: float | str = "auto",
) -> WordCloud:
    """Lay out a word cloud from non-empty frequencies.

    Words are always horizontal; the animations depend on that.
    """
    cleaned = {word: count for word, count in frequencies.items() if word and count > 0}
    if not cleaned:
        raise ValueError("No tokens to render")
    return WordCloud(
        width=width,
        height=height,
        background_color="white",
        font_path=str(font_path),
        collocations=True,
        normalize_plurals=True,
        prefer_horizontal=1.0,
        max_words=max_words,
        random_state=random_state,
        relative_scaling=relative_scaling,
    ).generate_from_frequencies(cleaned)


def write_static_cloud(
    tokens: Iterable[str],
    font_path: Path,
    output_path: Path,
    *,
    width: int = 1600,
    height: int = 1200,
    random_state: int | None = None,
) -> bool:
    """Render tokens to a PNG; return False when there is nothing to render."""
    frequencies = Counter(token for token in tokens if token)
    if not frequencies:
        logger.info("No tokens to render for %s", output_path)
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cloud = make_wordcloud(
        frequencies, font_path, width, height, random_state=random_state
    )
    cloud.to_file(str(output_path))
    logger.info("Wrote %s (%d distinct tokens)", output_path, len(frequencies))
    return True
