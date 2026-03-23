from cowork_pilot.dispatcher import classify_tool_use
from cowork_pilot.models import EventType


def test_classify_ask_user_question():
    tool_use = {"id": "t1", "name": "AskUserQuestion", "input": {}}
    assert classify_tool_use(tool_use) == EventType.QUESTION


def test_classify_bash_permission():
    tool_use = {"id": "t2", "name": "Bash", "input": {"command": "rm -rf /"}}
    assert classify_tool_use(tool_use) == EventType.PERMISSION


def test_classify_read_permission():
    tool_use = {"id": "t3", "name": "Read", "input": {"file_path": "/etc/passwd"}}
    assert classify_tool_use(tool_use) == EventType.PERMISSION


def test_classify_mcp_tool_permission():
    tool_use = {"id": "t4", "name": "mcp__codex__codex", "input": {}}
    assert classify_tool_use(tool_use) == EventType.PERMISSION


# --- Context Extraction Tests ---
import json
from pathlib import Path
from cowork_pilot.dispatcher import extract_context


def test_extract_context_returns_recent_messages(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "웹서버 만들어줘"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Express로 만들겠습니다."}]}},
        {"type": "user", "message": {"role": "user", "content": "좋아"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "포트를 선택해주세요."}, {"type": "tool_use", "id": "t1", "name": "AskUserQuestion", "input": {}}]}},
    ]
    with open(jsonl, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    context = extract_context(jsonl, max_lines=3)
    assert len(context) == 3


def test_extract_context_skips_non_messages(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    lines = [
        {"type": "progress", "data": {}},
        {"type": "user", "message": {"role": "user", "content": "안녕"}},
        {"type": "queue-operation", "data": {}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "반갑습니다"}]}},
    ]
    with open(jsonl, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    context = extract_context(jsonl, max_lines=10)
    assert len(context) == 2  # only user and assistant records


# --- Prompt Builder Tests ---
from cowork_pilot.dispatcher import build_prompt
from cowork_pilot.models import Event


def test_build_prompt_question():
    event = Event(
        event_type=EventType.QUESTION,
        tool_use_id="t1",
        tool_name="AskUserQuestion",
        questions=[{
            "question": "어떤 DB를 쓸까요?",
            "options": [
                {"label": "PostgreSQL", "description": "관계형"},
                {"label": "SQLite", "description": "경량"},
            ],
            "multiSelect": False,
        }],
        context_lines=["[user] DB가 필요한 프로젝트야", "[assistant] 알겠습니다."],
    )
    prompt = build_prompt(event, docs_content="## 기획서\nPostgreSQL 사용\n")
    assert "어떤 DB를 쓸까요?" in prompt
    assert "PostgreSQL" in prompt
    assert "SQLite" in prompt
    assert "기획서" in prompt
    assert "RESPOND WITH ONLY" in prompt


def test_build_prompt_permission():
    event = Event(
        event_type=EventType.PERMISSION,
        tool_use_id="t2",
        tool_name="Bash",
        tool_input={"command": "npm install express"},
        context_lines=["[user] Express 서버 만들어줘"],
    )
    prompt = build_prompt(event, docs_content="## golden-rules\n삭제 명령 거부\n")
    assert "npm install express" in prompt
    assert "allow" in prompt.lower()
    assert "deny" in prompt.lower()
    assert "golden-rules" in prompt


# --- CLI Invocation Tests ---
from unittest.mock import patch, MagicMock
from cowork_pilot.dispatcher import call_cli
from cowork_pilot.config import Config


def test_call_cli_codex(tmp_path):
    config = Config(engine="codex", project_dir=str(tmp_path))
    with patch("cowork_pilot.dispatcher.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="1", stderr="", returncode=0
        )
        result = call_cli("test prompt", config)
        assert result == "1"
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert "codex" in args[0][0][0]


def test_call_cli_claude(tmp_path):
    config = Config(engine="claude", project_dir=str(tmp_path))
    with patch("cowork_pilot.dispatcher.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="allow", stderr="", returncode=0
        )
        result = call_cli("test prompt", config)
        assert result == "allow"
        args = mock_run.call_args
        assert "claude" in args[0][0][0]


def test_call_cli_timeout(tmp_path):
    config = Config(engine="codex", project_dir=str(tmp_path))
    with patch("cowork_pilot.dispatcher.subprocess.run") as mock_run:
        mock_run.side_effect = TimeoutError("CLI timed out")
        result = call_cli("test prompt", config)
        assert result is None


# --- Document Loader Tests ---
from cowork_pilot.dispatcher import load_docs


def test_load_docs_reads_key_files(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "decision-criteria.md").write_text("## 판단 기준\n항상 PostgreSQL 선택\n")
    (docs_dir / "golden-rules.md").write_text("## 규칙\n삭제 금지\n")

    content = load_docs(tmp_path)
    assert "판단 기준" in content
    assert "삭제 금지" in content


def test_load_docs_missing_dir(tmp_path):
    content = load_docs(tmp_path / "nonexistent")
    assert content == ""
