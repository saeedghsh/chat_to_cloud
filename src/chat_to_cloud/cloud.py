"""Static word clouds built with the `wordcloud` package."""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path

from PIL import Image
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


def static_cloud(
    tokens: Iterable[str],
    font_path: Path,
    *,
    width: int = 1600,
    height: int = 1200,
    random_state: int | None = None,
) -> Image.Image | None:
    """Render tokens as an image; return None when there is nothing to render."""
    frequencies = Counter(token for token in tokens if token)
    if not frequencies:
        return None
    cloud = make_wordcloud(
        frequencies, font_path, width, height, random_state=random_state
    )
    image: Image.Image = cloud.to_image()
    return image


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
    image = static_cloud(
        tokens, font_path, width=width, height=height, random_state=random_state
    )
    if image is None:
        logger.info("No tokens to render for %s", output_path)
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, optimize=True)
    logger.info("Wrote %s", output_path)
    return True
