import json
import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_jsonl(tmp_path):
    """Create a temporary JSONL file for testing."""
    path = tmp_path / "test_session.jsonl"
    path.touch()
    return path


def write_jsonl_line(path: Path, record: dict):
    """Helper: append a JSON line to a file."""
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
