from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def sample_chat() -> Path:
    return DATA_DIR / "sample_chat.txt"
