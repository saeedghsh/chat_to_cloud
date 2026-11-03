from pathlib import Path

import imageio.v3 as iio
import pytest

from chat_to_cloud.cli import main

SMALL = ["--width", "320", "--height", "240", "--keyframes", "3", "--fps", "4"]


@pytest.mark.fonts
@pytest.mark.parametrize(
    ("command", "suffix", "extra"),
    [
        ("animate", "wc_animation", ["--frames-per-step", "2"]),
        ("animate-dynamic", "wc_dynamic_animation", ["--frames-per-step", "2"]),
    ],
)
def test_animation_commands_write_mp4_per_language(
    sample_chat: Path, tmp_path: Path, command: str, suffix: str, extra: list[str]
) -> None:
    main(
        [command, str(sample_chat), "--output-dir", str(tmp_path), *SMALL, *extra]
        + (
            ["--workers", "1", "--verify-layout"]
            if command == "animate-dynamic"
            else []
        )
    )

    for language in ("en", "fa", "emoji"):
        frames = iio.imread(
            tmp_path / f"sample_chat_{language}_{suffix}.mp4", plugin="FFMPEG"
        )
        assert frames.shape[0] > 0
        assert frames.shape[1:] == (240, 320, 3)


@pytest.mark.parametrize("command", ["animate", "animate-dynamic"])
def test_animation_commands_reject_odd_dimensions(
    sample_chat: Path, command: str
) -> None:
    with pytest.raises(SystemExit):
        main([command, str(sample_chat), "--width", "321"])


def test_animate_rejects_invalid_growth_exponent(sample_chat: Path) -> None:
    with pytest.raises(SystemExit):
        main(["animate", str(sample_chat), "--growth-exponent", "1.5"])
