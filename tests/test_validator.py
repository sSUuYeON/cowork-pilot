from cowork_pilot.validator import validate_response
from cowork_pilot.models import EventType, Response


# --- QUESTION validation ---

def test_validate_question_option_number():
    resp = validate_response("1", EventType.QUESTION, num_options=3)
    assert resp is not None
    assert resp.action == "select"
    assert resp.value == 1


def test_validate_question_option_number_boundary():
    resp = validate_response("3", EventType.QUESTION, num_options=3)
    assert resp is not None
    assert resp.value == 3


def test_validate_question_out_of_range():
    resp = validate_response("5", EventType.QUESTION, num_options=3)
    assert resp is None


def test_validate_question_zero():
    resp = validate_response("0", EventType.QUESTION, num_options=3)
    assert resp is None


def test_validate_question_other():
    resp = validate_response("Other: 커스텀 답변", EventType.QUESTION, num_options=3)
    assert resp is not None
    assert resp.action == "other"
    assert resp.value == "커스텀 답변"


def test_validate_question_garbage():
    resp = validate_response("I think option 1 is best because...", EventType.QUESTION, num_options=3)
    assert resp is None


def test_validate_escalate_question():
    resp = validate_response("ESCALATE", EventType.QUESTION, num_options=3)
    assert resp is not None
    assert resp.action == "escalate"


def test_validate_escalate_permission():
    resp = validate_response("ESCALATE", EventType.PERMISSION)
    assert resp is not None
    assert resp.action == "escalate"


# --- PERMISSION validation ---

def test_validate_permission_allow():
    resp = validate_response("allow", EventType.PERMISSION)
    assert resp is not None
    assert resp.action == "allow"


def test_validate_permission_deny():
    resp = validate_response("deny", EventType.PERMISSION)
    assert resp is not None
    assert resp.action == "deny"


def test_validate_permission_case_insensitive():
    resp = validate_response("Allow", EventType.PERMISSION)
    assert resp is not None
    assert resp.action == "allow"


def test_validate_permission_garbage():
    resp = validate_response("I think we should allow this", EventType.PERMISSION)
    assert resp is None


# --- FREE_TEXT validation ---

def test_validate_free_text():
    resp = validate_response("다음 단계 진행", EventType.FREE_TEXT)
    assert resp is not None
    assert resp.action == "text"
    assert resp.value == "다음 단계 진행"


def test_validate_free_text_empty():
    resp = validate_response("", EventType.FREE_TEXT)
    assert resp is None


def test_validate_free_text_whitespace():
    resp = validate_response("   ", EventType.FREE_TEXT)
    assert resp is None
