from pathlib import Path

import pytest
from PIL import Image

from chat_to_cloud.cli import main


@pytest.mark.fonts
def test_static_writes_one_png_per_language(sample_chat: Path, tmp_path: Path) -> None:
    main(["static", str(sample_chat), "--output-dir", str(tmp_path), "--seed", "1"])

    for language in ("en", "fa", "emoji"):
        with Image.open(tmp_path / f"sample_chat_{language}_wc.png") as image:
            assert image.size == (1600, 1200)


@pytest.mark.fonts
def test_static_skips_language_without_tokens(tmp_path: Path) -> None:
    chat = tmp_path / "english_only.txt"
    chat.write_text("1/2/24, 09:01 - Alice: hello there friend\n", encoding="utf-8")

    main(
        ["static", str(chat), "--language", "all", "--width", "320", "--height", "240"]
    )

    assert (tmp_path / "english_only_en_wc.png").is_file()
    assert not (tmp_path / "english_only_fa_wc.png").exists()
    assert not (tmp_path / "english_only_emoji_wc.png").exists()


def test_rejects_unknown_language(sample_chat: Path) -> None:
    with pytest.raises(SystemExit):
        main(["static", str(sample_chat), "--language", "de"])
