"""Locate, download, and verify the fonts used for rendering.

Fonts are not committed. Each one is pinned to an immutable upstream URL and a
SHA-256 checksum, downloaded on first use, and cached in `font_dir()`.
"""

import hashlib
import io
import logging
import os
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import platformdirs

from chat_to_cloud.tokens import Language

logger = logging.getLogger(__name__)

FONT_DIR_ENV = "CHAT_TO_CLOUD_FONT_DIR"


@dataclass(frozen=True)
class FontSource:
    """A pinned font download.

    `sha256` is the checksum of the downloaded resource. When it is a
    `.tar.bz2` archive, `archive_member` names the font file inside it.
    """

    filename: str
    url: str
    sha256: str
    license: str
    archive_member: str | None = None


class FontDownloadError(RuntimeError):
    """Raised when a font cannot be downloaded or fails verification."""


LATIN = FontSource(
    filename="DejaVuSans.ttf",
    url=(
        "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
        "version_2_37/dejavu-fonts-ttf-2.37.tar.bz2"
    ),
    sha256="fa9ca4d13871dd122f61258a80d01751d603b4d3ee14095d65453b4e846e17d7",
    license="Bitstream Vera / DejaVu license (free, permissive)",
    archive_member="dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf",
)
ARABIC = FontSource(
    filename="NotoNaskhArabic-Regular.ttf",
    url=(
        "https://raw.githubusercontent.com/notofonts/notofonts.github.io/"
        "cb61ee5541f7c90cd00720f3eadf898f1ebf9c3c/"
        "fonts/NotoNaskhArabic/hinted/ttf/NotoNaskhArabic-Regular.ttf"
    ),
    sha256="6f0a92031367b2f5a2078fe9d24f3433122b61a0bad57c423aad8f3c39aa2e6e",
    license="SIL Open Font License 1.1",
)
EMOJI = FontSource(
    filename="OpenMoji-black-glyf.ttf",
    url=(
        "https://raw.githubusercontent.com/hfg-gmuend/openmoji/16.0.0/"
        "font/OpenMoji-black-glyf/OpenMoji-black-glyf.ttf"
    ),
    sha256="047a7739677878842288bc76ada6c9007eac78def63f8029d1db891ad3f537b9",
    license="CC BY-SA 4.0 (attribution required)",
)

ALL_FONTS = (LATIN, ARABIC, EMOJI)
LANGUAGE_FONTS: dict[Language, FontSource] = {"en": LATIN, "fa": ARABIC, "emoji": EMOJI}
# Footer labels (titles, timestamps) in animations.
LABEL_FONT = LATIN


def font_dir() -> Path:
    """Return the font cache directory, honoring `CHAT_TO_CLOUD_FONT_DIR`."""
    override = os.environ.get(FONT_DIR_ENV)
    if override:
        return Path(override)
    return platformdirs.user_data_path("chat-to-cloud") / "fonts"


def font_path(source: FontSource, directory: Path | None = None) -> Path:
    """Return the local path of a font, downloading it on first use."""
    path = (directory or font_dir()) / source.filename
    if not path.is_file():
        download_font(source, path)
    return path


def download_font(source: FontSource, path: Path) -> None:
    """Download, verify, and atomically write a font to `path`."""
    logger.info("Downloading %s from %s", source.filename, source.url)
    try:
        with urllib.request.urlopen(source.url, timeout=60) as response:
            data: bytes = response.read()
    except OSError as error:
        raise FontDownloadError(f"Could not download {source.url}: {error}") from error

    digest = hashlib.sha256(data).hexdigest()
    if digest != source.sha256:
        raise FontDownloadError(
            f"Checksum mismatch for {source.url}: "
            f"expected {source.sha256}, got {digest}"
        )
    if source.archive_member is not None:
        data = _read_archive_member(data, source.archive_member)

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(data)
    Path(temporary.name).replace(path)


def _read_archive_member(archive: bytes, member: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:bz2") as tar:
        try:
            extracted = tar.extractfile(member)
        except KeyError:
            extracted = None
        if extracted is None:
            raise FontDownloadError(f"{member} is not a regular file in the archive")
        return extracted.read()
