# tests/test_planning_recovery.py

from cowork_pilot.planning.recovery import recover_interrupted_stage, RecoveryDecision


def test_recovery_completes_when_outputs_exist_and_valid(tmp_path):
    output = tmp_path / "stage-output.md"
    output.write_text("# Good Output\n" + "content\n" * 20, encoding="utf-8")

    decision = recover_interrupted_stage(
        run_dir=tmp_path,
        stage="scope_structuring",
        expected_outputs=(str(output),),
        min_lines=5,
    )
    assert decision == RecoveryDecision.MARK_COMPLETED


def test_recovery_retries_when_outputs_exist_but_short(tmp_path):
    output = tmp_path / "stage-output.md"
    output.write_text("# Short\n", encoding="utf-8")

    decision = recover_interrupted_stage(
        run_dir=tmp_path,
        stage="scope_structuring",
        expected_outputs=(str(output),),
        min_lines=10,
    )
    assert decision == RecoveryDecision.DELETE_AND_RETRY
    assert not output.exists()


def test_recovery_retries_when_no_outputs(tmp_path):
    decision = recover_interrupted_stage(
        run_dir=tmp_path,
        stage="scope_structuring",
        expected_outputs=("missing.md",),
    )
    assert decision == RecoveryDecision.RETRY
