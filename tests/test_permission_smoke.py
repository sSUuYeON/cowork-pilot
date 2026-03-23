"""Smoke test: verifies Permission event classification and prompt building."""
from cowork_pilot.dispatcher import classify_tool_use, build_prompt
from cowork_pilot.models import EventType, Event


def test_classify_read_as_permission():
    tool_use = {"name": "Read", "id": "toolu_test1", "input": {"file_path": "/tmp/test.py"}}
    assert classify_tool_use(tool_use) == EventType.PERMISSION


def test_classify_bash_as_permission():
    tool_use = {"name": "Bash", "id": "toolu_test2", "input": {"command": "ls -la"}}
    assert classify_tool_use(tool_use) == EventType.PERMISSION


def test_classify_ask_user_question_as_question():
    tool_use = {"name": "AskUserQuestion", "id": "toolu_test3", "input": {}}
    assert classify_tool_use(tool_use) == EventType.QUESTION


def test_permission_prompt_contains_tool_name():
    event = Event(
        event_type=EventType.PERMISSION,
        tool_use_id="toolu_test4",
        tool_name="Bash",
        tool_input={"command": "npm test"},
    )
    prompt = build_prompt(event)
    assert "Bash" in prompt
    assert "npm test" in prompt
    assert "allow" in prompt.lower()
    assert "deny" in prompt.lower()


def test_permission_prompt_with_docs():
    """Verify docs content is injected into the prompt."""
    event = Event(
        event_type=EventType.PERMISSION,
        tool_use_id="toolu_test5",
        tool_name="Write",
        tool_input={"file_path": "/tmp/output.txt", "content": "hello"},
    )
    docs = "--- golden-rules.md ---\nNever allow rm -rf"
    prompt = build_prompt(event, docs_content=docs)
    assert "golden-rules" in prompt
    assert "rm -rf" in prompt
