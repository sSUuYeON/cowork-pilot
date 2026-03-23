from cowork_pilot.responder import build_applescript
from cowork_pilot.models import Response, EventType


def test_build_applescript_select_first_option():
    resp = Response(action="select", value=1)
    script = build_applescript(resp, EventType.QUESTION, num_options=3)
    assert 'activate' in script
    assert 'keystroke return' in script
    # First option is already selected, just press enter
    assert 'key code 125' not in script  # no arrow down


def test_build_applescript_select_third_option():
    resp = Response(action="select", value=3)
    script = build_applescript(resp, EventType.QUESTION, num_options=3)
    assert 'activate' in script
    # Need to press down arrow 2 times to get to option 3
    assert script.count('key code 125') == 2
    assert 'keystroke return' in script


def test_build_applescript_other_text():
    resp = Response(action="other", value="커스텀 답변")
    script = build_applescript(resp, EventType.QUESTION, num_options=3)
    assert 'activate' in script
    assert 'keystroke return' in script
    assert '커스텀 답변' in script


def test_build_applescript_allow():
    resp = Response(action="allow")
    script = build_applescript(resp, EventType.PERMISSION)
    assert 'activate' in script
    assert 'keystroke return' in script  # Enter = allow


def test_build_applescript_deny():
    resp = Response(action="deny")
    script = build_applescript(resp, EventType.PERMISSION)
    assert 'activate' in script
    assert 'key code 53' in script  # Esc = deny


def test_build_applescript_free_text():
    resp = Response(action="text", value="진행해주세요")
    script = build_applescript(resp, EventType.FREE_TEXT)
    assert 'activate' in script
    assert '진행해주세요' in script
    assert 'keystroke return' in script


# --- Execute + Post-Verify Tests ---
import time
import json
import threading
from unittest.mock import patch, MagicMock
from pathlib import Path
from cowork_pilot.responder import execute_applescript, post_verify_response


def test_execute_applescript_success():
    with patch("cowork_pilot.responder.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = execute_applescript('tell application "Claude" to activate')
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0][0] == "osascript"


def test_execute_applescript_failure():
    with patch("cowork_pilot.responder.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        result = execute_applescript('invalid script')
        assert result is False


def test_post_verify_finds_tool_result(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("")

    def append_result():
        time.sleep(0.1)
        with open(jsonl, "a") as f:
            record = {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_verify1", "content": "ok"}],
                },
            }
            f.write(json.dumps(record) + "\n")

    t = threading.Thread(target=append_result)
    t.start()

    result = post_verify_response(jsonl, "toolu_verify1", timeout_seconds=2.0, poll_interval=0.05)
    t.join()
    assert result is True


def test_post_verify_timeout(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("")

    result = post_verify_response(jsonl, "toolu_never", timeout_seconds=0.2, poll_interval=0.05)
    assert result is False
