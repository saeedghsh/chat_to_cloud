import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from chat_to_cloud.fonts import (
    FONT_DIR_ENV,
    FontDownloadError,
    FontSource,
    font_dir,
    font_path,
)

FONT_BYTES = b"not really a font"


def _source(resource: Path, **overrides: str) -> FontSource:
    values = {
        "filename": "Test.ttf",
        "url": resource.as_uri(),
        "sha256": hashlib.sha256(resource.read_bytes()).hexdigest(),
        "license": "test",
    }
    values.update(overrides)
    return FontSource(**values)


def test_font_path_downloads_once_and_reuses_cache(tmp_path: Path) -> None:
    resource = tmp_path / "upstream.ttf"
    resource.write_bytes(FONT_BYTES)
    source = _source(resource)
    cache = tmp_path / "cache"

    path = font_path(source, cache)
    resource.unlink()  # a second lookup must not download again

    assert path == cache / "Test.ttf"
    assert font_path(source, cache).read_bytes() == FONT_BYTES


def test_font_path_extracts_member_from_tar_bz2(tmp_path: Path) -> None:
    archive = tmp_path / "fonts.tar.bz2"
    with tarfile.open(archive, "w:bz2") as tar:
        info = tarfile.TarInfo("pkg/ttf/Test.ttf")
        info.size = len(FONT_BYTES)
        tar.addfile(info, io.BytesIO(FONT_BYTES))
    source = _source(archive, archive_member="pkg/ttf/Test.ttf")

    assert font_path(source, tmp_path / "cache").read_bytes() == FONT_BYTES


def test_checksum_mismatch_fails_without_writing(tmp_path: Path) -> None:
    resource = tmp_path / "upstream.ttf"
    resource.write_bytes(FONT_BYTES)
    source = _source(resource, sha256="0" * 64)
    cache = tmp_path / "cache"

    with pytest.raises(FontDownloadError, match="Checksum mismatch"):
        font_path(source, cache)
    assert not (cache / "Test.ttf").exists()


def test_unreachable_url_raises_font_download_error(tmp_path: Path) -> None:
    source = FontSource("Test.ttf", (tmp_path / "missing").as_uri(), "0" * 64, "test")

    with pytest.raises(FontDownloadError, match="Could not download"):
        font_path(source, tmp_path / "cache")


def test_font_dir_honors_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FONT_DIR_ENV, str(tmp_path))

    assert font_dir() == tmp_path
