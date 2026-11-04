import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from chat_to_cloud import fonts
from scripts.build_pages import PACKAGE, build_pages


@pytest.mark.fonts
def test_build_ships_package_fonts_licenses_and_pins(
    tmp_path: Path, sample_chat: Path
) -> None:
    output = tmp_path / "_site"
    build_pages(output)

    for name in ("index.html", "app.js", "worker.js", "styles.css", ".nojekyll"):
        assert (output / name).is_file()
    for license_file in ("DejaVu", "NotoNaskhArabic", "OpenMoji"):
        assert list((output / "licenses").glob(f"{license_file}-*.txt"))
    config = json.loads((output / "runtime-config.json").read_text(encoding="utf-8"))
    assert config["pyodide-version"]
    assert config["fonts"] == [source.filename for source in fonts.ALL_FONTS]
    for source in fonts.ALL_FONTS:
        shipped = (output / "fonts" / source.filename).read_bytes()
        assert shipped == fonts.font_path(source).read_bytes()

    with zipfile.ZipFile(output / "python" / "chat_to_cloud.zip") as archive:
        for source_file in PACKAGE.glob("*.py"):
            name = f"chat_to_cloud/{source_file.name}"
            assert archive.read(name) == source_file.read_bytes()
        archive.extractall(tmp_path / "extracted")
    # Use only the archive and the shipped fonts, as the browser does.
    script = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(tmp_path / 'extracted')!r}); "
        "from chat_to_cloud.browser import BrowserSession; "
        f"s = BrowserSession(Path({str(output / 'fonts')!r})); "
        f"s.load_chat(Path({str(sample_chat)!r}).read_text(encoding='utf-8')); "
        "assert s.static_png('fa', 200, 160)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.fonts
def test_rebuild_removes_stale_files(tmp_path: Path) -> None:
    output = tmp_path / "_site"
    build_pages(output)
    (output / "stale.txt").touch()

    build_pages(output)

    assert not (output / "stale.txt").exists()


def test_build_refuses_other_directories(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="_site"):
        build_pages(tmp_path / "web")
