import json
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

from cowork_pilot.main import process_one_event
from cowork_pilot.config import Config
from cowork_pilot.models import Event, EventType, Response
from cowork_pilot.logger import StructuredLogger


def test_process_one_event_question(tmp_path):
    """Full pipeline: Event → Dispatcher → Validator → Responder (mocked)."""
    # Setup project docs
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "golden-rules.md").write_text("## Rules\nNo dangerous ops\n")
    (docs_dir / "decision-criteria.md").write_text("## Criteria\nAlways pick option 1\n")

    # Setup JSONL
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("")

    config = Config(engine="codex", project_dir=str(tmp_path))
    logger = StructuredLogger(tmp_path / "logs" / "test.jsonl")

    event = Event(
        event_type=EventType.QUESTION,
        tool_use_id="toolu_int001",
        tool_name="AskUserQuestion",
        questions=[{
            "question": "DB를 골라주세요",
            "options": [
                {"label": "PostgreSQL", "description": "관계형"},
                {"label": "SQLite", "description": "경량"},
            ],
            "multiSelect": False,
        }],
        context_lines=["[user] DB 프로젝트 시작"],
    )

    with patch("cowork_pilot.main.call_cli") as mock_cli, \
         patch("cowork_pilot.main.execute_applescript") as mock_apple, \
         patch("cowork_pilot.main.post_verify_response") as mock_verify:

        mock_cli.return_value = "1"
        mock_apple.return_value = True
        mock_verify.return_value = True

        success = process_one_event(event, jsonl, config, logger)

        assert success is True
        mock_cli.assert_called_once()
        mock_apple.assert_called_once()
        mock_verify.assert_called_once()


def test_process_one_event_validation_failure_retries(tmp_path):
    """If CLI returns bad format, retry up to max_retries."""
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "golden-rules.md").write_text("")

    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("")

    config = Config(engine="codex", project_dir=str(tmp_path), max_retries=2)
    logger = StructuredLogger(tmp_path / "logs" / "test.jsonl")

    event = Event(
        event_type=EventType.QUESTION,
        tool_use_id="toolu_int002",
        tool_name="AskUserQuestion",
        questions=[{"question": "?", "options": [{"label": "A", "description": ""}], "multiSelect": False}],
        context_lines=[],
    )

    with patch("cowork_pilot.main.call_cli") as mock_cli:
        # First two calls return garbage, never valid
        mock_cli.side_effect = ["I think A is best", "Probably option A"]

        success = process_one_event(event, jsonl, config, logger)
        assert success is False
        assert mock_cli.call_count == 2
