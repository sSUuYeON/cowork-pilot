import json
from cowork_pilot.watcher import parse_jsonl_line


def test_parse_assistant_with_tool_use():
    line = json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "선택해주세요."},
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "AskUserQuestion",
                    "input": {"questions": [{"question": "DB?", "options": []}]},
                },
            ],
        },
        "timestamp": "2026-03-21T10:00:00Z",
    })
    result = parse_jsonl_line(line)
    assert result is not None
    assert result["type"] == "assistant"
    assert len(result["tool_uses"]) == 1
    assert result["tool_uses"][0]["name"] == "AskUserQuestion"


def test_parse_user_with_tool_result():
    line = json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_123", "content": "ok"},
            ],
        },
    })
    result = parse_jsonl_line(line)
    assert result is not None
    assert result["type"] == "user"
    assert result["tool_results"] == ["toolu_123"]


def test_parse_non_message_record():
    line = json.dumps({"type": "progress", "data": {}})
    result = parse_jsonl_line(line)
    assert result is None


def test_parse_invalid_json():
    result = parse_jsonl_line("not valid json {{{")
    assert result is None


# --- State Machine Tests ---
import time
from cowork_pilot.watcher import WatcherStateMachine
from cowork_pilot.models import WatcherState, EventType


def test_state_machine_idle_to_detected():
    sm = WatcherStateMachine(debounce_seconds=0.1)
    assert sm.state == WatcherState.IDLE

    tool_use = {"id": "toolu_001", "name": "AskUserQuestion", "input": {"questions": []}}
    sm.on_tool_use(tool_use)
    assert sm.state == WatcherState.TOOL_USE_DETECTED


def test_state_machine_debounce_then_pending():
    sm = WatcherStateMachine(debounce_seconds=0.05)
    tool_use = {"id": "toolu_001", "name": "AskUserQuestion", "input": {"questions": []}}
    sm.on_tool_use(tool_use)

    # Simulate debounce tick
    sm.tick()  # not yet
    assert sm.state == WatcherState.DEBOUNCE_WAIT

    time.sleep(0.06)
    sm.tick()
    assert sm.state == WatcherState.PENDING_RESPONSE


def test_state_machine_tool_result_resets():
    sm = WatcherStateMachine(debounce_seconds=0.01)
    tool_use = {"id": "toolu_001", "name": "AskUserQuestion", "input": {}}
    sm.on_tool_use(tool_use)
    sm.tick()  # DETECTED → DEBOUNCE_WAIT
    time.sleep(0.02)
    sm.tick()  # DEBOUNCE_WAIT → PENDING_RESPONSE
    assert sm.state == WatcherState.PENDING_RESPONSE

    sm.on_tool_result("toolu_001")
    assert sm.state == WatcherState.RESPONDED

    sm.tick()
    assert sm.state == WatcherState.IDLE


def test_state_machine_consecutive_tool_use_keeps_latest():
    sm = WatcherStateMachine(debounce_seconds=0.1)
    sm.on_tool_use({"id": "toolu_001", "name": "Bash", "input": {}})
    sm.on_tool_use({"id": "toolu_002", "name": "AskUserQuestion", "input": {}})
    assert sm.pending_tool_use["id"] == "toolu_002"


def test_state_machine_get_pending_event():
    sm = WatcherStateMachine(debounce_seconds=0.01)
    sm.on_tool_use({
        "id": "toolu_001",
        "name": "AskUserQuestion",
        "input": {"questions": [{"question": "DB?", "options": []}]},
    })
    sm.tick()  # DETECTED → DEBOUNCE_WAIT
    time.sleep(0.02)
    sm.tick()  # DEBOUNCE_WAIT → PENDING_RESPONSE

    event = sm.get_pending_event()
    assert event is not None
    assert event.event_type == EventType.QUESTION
    assert event.tool_use_id == "toolu_001"


# --- JSONLTail Tests ---
from pathlib import Path
from cowork_pilot.watcher import JSONLTail
from tests.conftest import write_jsonl_line


def test_jsonl_tail_reads_new_lines(tmp_path):
    path = tmp_path / "test.jsonl"
    path.write_text('{"type":"progress"}\n')

    tail = JSONLTail(path)
    # First call skips existing content
    lines = tail.read_new_lines()
    assert lines == []

    # Append new line
    write_jsonl_line(path, {
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_t1", "name": "Bash", "input": {}}
        ]},
    })

    lines = tail.read_new_lines()
    assert len(lines) == 1


def test_jsonl_tail_handles_missing_file(tmp_path):
    path = tmp_path / "nonexistent.jsonl"
    tail = JSONLTail(path)
    lines = tail.read_new_lines()
    assert lines == []


def test_jsonl_tail_switch_file(tmp_path):
    path1 = tmp_path / "session1.jsonl"
    path1.write_text('{"type":"progress"}\n')
    tail = JSONLTail(path1)
    tail.read_new_lines()

    path2 = tmp_path / "session2.jsonl"
    path2.write_text('{"type":"progress"}\n')
    tail.switch_file(path2)
    lines = tail.read_new_lines()
    assert lines == []  # skips existing
