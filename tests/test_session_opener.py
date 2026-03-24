# tests/test_session_opener.py
from unittest.mock import patch

from cowork_pilot.session_opener import (
    build_open_session_script,
    build_type_prompt_script,
    open_new_session,
)


def test_build_open_session_script_contains_shift_cmd_o():
    script = build_open_session_script()
    assert "key code 31 using {shift down, command down}" in script


def test_build_open_session_script_activates_claude():
    script = build_open_session_script()
    assert 'tell application "Claude" to activate' in script


def test_build_open_session_script_has_session_load_delay():
    script = build_open_session_script(session_load_delay=5.0)
    assert "delay 5.0" in script


def test_build_type_prompt_script_pastes_and_enters():
    script = build_type_prompt_script()
    assert "key code 9 using command down" in script  # Cmd+V
    assert "keystroke return" in script


def test_open_new_session_without_prompt():
    """Opens session only, no prompt typed."""
    with patch("cowork_pilot.session_opener.execute_applescript") as mock_exec:
        mock_exec.return_value = True

        result = open_new_session()

        assert result is True
        assert mock_exec.call_count == 1
        # Verify the script contains Shift+Cmd+O
        script_arg = mock_exec.call_args[0][0]
        assert "key code 31 using {shift down, command down}" in script_arg


def test_open_new_session_with_prompt():
    """Opens session and types an initial prompt."""
    with patch("cowork_pilot.session_opener.execute_applescript") as mock_exec, \
         patch("cowork_pilot.session_opener.set_clipboard") as mock_clip:
        mock_exec.return_value = True
        mock_clip.return_value = True

        result = open_new_session(initial_prompt="다음 태스크를 진행해주세요")

        assert result is True
        assert mock_exec.call_count == 2  # open + type
        mock_clip.assert_called_once_with("다음 태스크를 진행해주세요")


def test_open_new_session_fails_on_open():
    """If opening fails, return False immediately."""
    with patch("cowork_pilot.session_opener.execute_applescript") as mock_exec:
        mock_exec.return_value = False

        result = open_new_session(initial_prompt="hello")

        assert result is False
        assert mock_exec.call_count == 1  # didn't try to type


def test_open_new_session_fails_on_clipboard():
    """If clipboard fails, return False."""
    with patch("cowork_pilot.session_opener.execute_applescript") as mock_exec, \
         patch("cowork_pilot.session_opener.set_clipboard") as mock_clip:
        mock_exec.return_value = True
        mock_clip.return_value = False

        result = open_new_session(initial_prompt="hello")

        assert result is False
