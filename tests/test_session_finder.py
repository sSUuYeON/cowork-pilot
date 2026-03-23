import json
import time
from pathlib import Path

from cowork_pilot.session_finder import find_active_jsonl


def test_find_active_jsonl_returns_most_recent(tmp_path):
    """Given multiple .jsonl files, return the most recently modified one."""
    session_dir = tmp_path / "org" / "user" / "local_vm1" / ".claude" / "projects" / "-sessions-foo"
    session_dir.mkdir(parents=True)

    old_file = session_dir / "old-session.jsonl"
    old_file.write_text('{"type":"assistant"}\n')

    time.sleep(0.1)  # ensure different mtime

    new_file = session_dir / "new-session.jsonl"
    new_file.write_text('{"type":"assistant"}\n')

    result = find_active_jsonl(tmp_path)
    assert result == new_file


def test_find_active_jsonl_no_files(tmp_path):
    """Given no .jsonl files, return None."""
    result = find_active_jsonl(tmp_path)
    assert result is None


def test_find_active_jsonl_ignores_empty(tmp_path):
    """Ignore empty JSONL files (0 bytes)."""
    session_dir = tmp_path / "org" / "user" / "local_vm1" / ".claude" / "projects" / "-sessions-bar"
    session_dir.mkdir(parents=True)

    empty_file = session_dir / "empty.jsonl"
    empty_file.touch()

    valid_file = session_dir / "valid.jsonl"
    valid_file.write_text('{"type":"assistant"}\n')

    result = find_active_jsonl(tmp_path)
    assert result == valid_file
