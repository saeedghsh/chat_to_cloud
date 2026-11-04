"""Build the static web app in `_site/` from `web/` and the Python package."""

import argparse
import json
import shutil
import tomllib
import zipfile
from pathlib import Path

from chat_to_cloud import fonts

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "chat_to_cloud"


def runtime_config() -> dict[str, object]:
    """Return the browser runtime pins declared in `pyproject.toml`."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    config: dict[str, object] = project["tool"]["chat-to-cloud"]["browser"]
    return config


def build_pages(output: Path = ROOT / "_site") -> None:
    """Replace `output`, which must be a dedicated `_site` directory."""
    output = output.absolute()
    if output.name != "_site" or output.is_symlink():
        raise ValueError("Output must be a dedicated directory named _site")
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree(ROOT / "web", output)

    (output / "python").mkdir()
    with zipfile.ZipFile(
        output / "python" / "chat_to_cloud.zip", "w", zipfile.ZIP_DEFLATED
    ) as archive:
        for module in sorted(PACKAGE.glob("*.py")):
            archive.write(module, module.relative_to(PACKAGE.parent))

    # Fonts are downloaded and checksum-verified as for the command line,
    # then served with the page; their licenses ship in `licenses/`.
    (output / "fonts").mkdir()
    for source in fonts.ALL_FONTS:
        shutil.copy2(fonts.font_path(source), output / "fonts" / source.filename)

    config = runtime_config() | {
        "fonts": [source.filename for source in fonts.ALL_FONTS]
    }
    (output / "runtime-config.json").write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )
    (output / ".nojekyll").touch()


def main() -> None:
    """Build the site at the path given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    build_pages(parser.parse_args().output)


if __name__ == "__main__":
    main()
