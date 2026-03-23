from cowork_pilot.models import EventType, WatcherState, Event, Response


def test_event_type_values():
    assert EventType.QUESTION.value == "question"
    assert EventType.PERMISSION.value == "permission"
    assert EventType.FREE_TEXT.value == "free_text"


def test_watcher_state_values():
    assert WatcherState.IDLE.value == "idle"
    assert WatcherState.TOOL_USE_DETECTED.value == "tool_use_detected"
    assert WatcherState.DEBOUNCE_WAIT.value == "debounce_wait"
    assert WatcherState.PENDING_RESPONSE.value == "pending_response"
    assert WatcherState.RESPONDED.value == "responded"


def test_event_creation_question():
    event = Event(
        event_type=EventType.QUESTION,
        tool_use_id="toolu_abc123",
        tool_name="AskUserQuestion",
        questions=[{
            "question": "어떤 DB를 쓸까요?",
            "options": [
                {"label": "PostgreSQL", "description": "관계형 DB"},
                {"label": "SQLite", "description": "경량 DB"},
            ],
            "multiSelect": False,
        }],
        context_lines=["이전 대화 내용 1", "이전 대화 내용 2"],
    )
    assert event.event_type == EventType.QUESTION
    assert event.tool_use_id == "toolu_abc123"
    assert len(event.questions) == 1
    assert event.questions[0]["options"][0]["label"] == "PostgreSQL"


def test_event_creation_permission():
    event = Event(
        event_type=EventType.PERMISSION,
        tool_use_id="toolu_xyz789",
        tool_name="Bash",
        tool_input={"command": "ls -la"},
        context_lines=[],
    )
    assert event.event_type == EventType.PERMISSION
    assert event.tool_name == "Bash"
    assert event.tool_input["command"] == "ls -la"


def test_response_option_selection():
    resp = Response(action="select", value=2)
    assert resp.action == "select"
    assert resp.value == 2


def test_response_other_text():
    resp = Response(action="other", value="커스텀 답변입니다")
    assert resp.action == "other"
    assert resp.value == "커스텀 답변입니다"


def test_response_permission():
    resp = Response(action="allow", value=None)
    assert resp.action == "allow"


def test_response_free_text():
    resp = Response(action="text", value="다음 단계 진행해주세요")
    assert resp.action == "text"
