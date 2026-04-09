from pathlib import Path

import pytest

from cowork_pilot.planning.quality_gate import evaluate_stage_gate, GateResult


@pytest.mark.parametrize("stage,min_expected", [
    ("classification", 5),
    ("core_docs_check", 5),
    ("adaptive_docs_selection", 5),
    ("scope_structuring", 5),
    ("work_sizing", 5),
    ("plan_packing", 5),
    ("plan_review", 10),
])
def test_converted_stage_quality_gate_threshold(stage: str, min_expected: int, tmp_path: Path):
    output_file = tmp_path / f"{stage}-output.md"
    output_file.write_text("x\n" * (min_expected - 1), encoding="utf-8")
    result = evaluate_stage_gate(
        stage=stage,
        run_dir=tmp_path,
        expected_outputs=(str(output_file),),
    )
    assert not result.passed, f"{stage} should fail with {min_expected - 1} lines"


def test_gate_passes_when_all_outputs_exist(tmp_path):
    output = tmp_path / "coverage-gap.md"
    output.write_text("# Coverage Gap\n\nLine 1\nLine 2\nLine 3\nLine 4\nLine 5\n" * 3, encoding="utf-8")
    result = evaluate_stage_gate(
        stage="product_completeness_review",
        run_dir=tmp_path,
        expected_outputs=(str(output),),
    )
    assert result.passed is True
    assert result.reason == ""


def test_gate_fails_when_output_missing(tmp_path):
    result = evaluate_stage_gate(
        stage="product_completeness_review",
        run_dir=tmp_path,
        expected_outputs=("nonexistent.md",),
    )
    assert result.passed is False
    assert "missing" in result.reason.lower()


def test_gate_fails_when_output_too_short(tmp_path):
    output = tmp_path / "coverage-gap.md"
    output.write_text("# Title\n", encoding="utf-8")
    result = evaluate_stage_gate(
        stage="product_completeness_review",
        run_dir=tmp_path,
        expected_outputs=(str(output),),
        min_lines=10,
    )
    assert result.passed is False
    assert "short" in result.reason.lower() or "lines" in result.reason.lower()


def test_gate_fails_skeleton_with_zero_parsed_features(tmp_path):
    """Skeleton file exists and is long enough, but contains no parseable feature entries."""
    output = tmp_path / "exec-plan-skeleton.md"
    output.write_text("# Skeleton\n\nSome discussion text.\n" * 10, encoding="utf-8")
    result = evaluate_stage_gate(
        stage="exec_plan_skeleton",
        run_dir=tmp_path,
        expected_outputs=(str(output),),
    )
    assert result.passed is False
    assert "0 features" in result.reason.lower()


def test_rollback_stage_removes_outputs_and_returns_new_index(tmp_path):
    from cowork_pilot.planning.quality_gate import rollback_stage

    artifact = tmp_path / "coverage-gap.md"
    artifact.write_text("bad content", encoding="utf-8")

    result = rollback_stage(
        run_dir=tmp_path,
        dispatch_index=5,
        outputs_to_remove=(str(artifact),),
    )
    assert result.rolled_back is True
    assert result.retry_dispatch_index == 5
    assert not artifact.exists()


def test_rollback_stage_caps_at_max_retries(tmp_path):
    import json
    from cowork_pilot.planning.quality_gate import rollback_stage

    # Pre-set retry count to 3 (at max)
    (tmp_path / "retry-counts.json").write_text(json.dumps({"5": 3}), encoding="utf-8")

    result = rollback_stage(
        run_dir=tmp_path,
        dispatch_index=5,
        outputs_to_remove=(),
        max_retries=3,
    )
    assert result.rolled_back is False
    assert result.escalated is True
