from cowork_pilot.planning.marker_protocol import extract_terminal_marker_bundle


def test_parser_ignores_code_block_examples():
    message = """
```text
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
</COWORK_PILOT_EVENT>
```

설명 텍스트

<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-1
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
"""
    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["STAGE_COMPLETE"]


def test_parser_treats_fenced_block_between_markers_as_contiguity_break():
    message = """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-1
reason: continue
assumption: earlier note
confidence: low
impact: low
</COWORK_PILOT_EVENT>
```text
<COWORK_PILOT_EVENT>
type: APPROVAL_REQUIRED
stage: plan_review
event_id: pr-fenced
reason: ignore fenced example
subject: fenced
proposed_decision: ignore
blocking: true
</COWORK_PILOT_EVENT>
```
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-2
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
"""

    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["STAGE_COMPLETE"]


def test_parser_only_accepts_last_contiguous_top_level_bundle():
    message = """
설명 텍스트

<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: product_completeness_review
event_id: pcr-1
reason: continue
assumption: dashboard redirect
confidence: medium
impact: medium
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: ok
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
"""
    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["ASSUMPTION_LOG", "STAGE_COMPLETE"]


def test_parser_ignores_earlier_separated_marker_blocks_and_keeps_final_tail():
    message = """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-1
reason: continue
assumption: earlier note
confidence: low
impact: low
</COWORK_PILOT_EVENT>

중간 설명 텍스트

<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-2
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
"""

    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["STAGE_COMPLETE"]


def test_parser_ignores_text_before_final_single_marker_bundle():
    message = """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-1
reason: continue
assumption: keep chunk split
confidence: low
impact: medium
</COWORK_PILOT_EVENT>
중간 설명
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-2
reason: complete
summary: ok
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
"""

    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["STAGE_COMPLETE"]


def test_parser_rejects_input_required_missing_type_specific_fields():
    message = """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing redirect
question: 로그인 후 기본 이동 경로는?
</COWORK_PILOT_EVENT>
"""

    assert extract_terminal_marker_bundle(message) == ()


def test_parser_rejects_disallowed_bundle_combination():
    message = """
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-1
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-2
reason: continue
assumption: keep split
confidence: low
impact: medium
</COWORK_PILOT_EVENT>
"""

    assert extract_terminal_marker_bundle(message) == ()


def test_parser_rejects_non_whitespace_text_after_final_marker():
    message = """
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: plan_review
event_id: pr-1
reason: complete
summary: done
outputs:
  - plan-review.md
</COWORK_PILOT_EVENT>
추가 설명
"""

    assert extract_terminal_marker_bundle(message) == ()


def test_parser_accepts_allowed_bundle_assumption_then_stage_complete():
    message = """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: product_completeness_review
event_id: pcr-1
reason: continue
assumption: dashboard redirect
confidence: medium
impact: medium
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: ok
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
    """
    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["ASSUMPTION_LOG", "STAGE_COMPLETE"]
    assert bundle[0].payload == {
        "assumption": "dashboard redirect",
        "confidence": "medium",
        "impact": "medium",
    }
    assert bundle[1].payload == {
        "summary": "ok",
        "outputs": ["product-completeness-review.md"],
    }


def test_parser_accepts_allowed_bundle_assumption_then_approval_required():
    message = """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-1
reason: continue
assumption: keep split
confidence: medium
impact: low
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: APPROVAL_REQUIRED
stage: plan_review
event_id: pr-2
reason: needs signoff
subject: plan review scope
proposed_decision: proceed with current split
blocking: true
</COWORK_PILOT_EVENT>
"""

    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["ASSUMPTION_LOG", "APPROVAL_REQUIRED"]


def test_parser_accepts_allowed_bundle_assumption_then_needs_human():
    message = """
<COWORK_PILOT_EVENT>
type: ASSUMPTION_LOG
stage: plan_review
event_id: pr-1
reason: continue
assumption: keep split
confidence: medium
impact: low
</COWORK_PILOT_EVENT>
<COWORK_PILOT_EVENT>
type: NEEDS_HUMAN
stage: plan_review
event_id: pr-2
reason: insufficient context
issue: scope is ambiguous
why_ai_stopped: decision requires human input
suggested_next_action: clarify the scope split
</COWORK_PILOT_EVENT>
"""

    bundle = extract_terminal_marker_bundle(message)

    assert [item.type for item in bundle] == ["ASSUMPTION_LOG", "NEEDS_HUMAN"]


def test_parser_returns_empty_tuple_on_malformed_yaml():
    message = """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: test
event_id: t-1
reason: test
this line has no colon
question: test
options:
  - a
recommended: a
blocking: true
</COWORK_PILOT_EVENT>
"""

    assert extract_terminal_marker_bundle(message) == ()
