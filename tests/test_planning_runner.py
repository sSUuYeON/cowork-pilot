from pathlib import Path

import pytest

from cowork_pilot.main import run_planning_mode
from cowork_pilot.planning.authoring import write_exec_plan
from cowork_pilot.planning.models import PlanningContext, PlanningPipelineResult, PlanningStage, ProjectMode
from cowork_pilot.planning.prompts import render_stage_prompt
from cowork_pilot.planning.runner import (
    resume_planning_pipeline_with_user_response,
    resume_planning_waiting_run_with_cli,
    run_planning_pipeline,
    run_planning_stage_with_runtime,
)
from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_orchestrator import RuntimeUpdate
from cowork_pilot.planning.runtime_storage import read_run_state, write_run_state
from cowork_pilot.planning.stage_executor import QueuedQuestion, StageExecutionResult


def test_planning_runner_smoke():
    result = run_planning_pipeline()

    assert isinstance(result, PlanningPipelineResult)
    assert isinstance(result.stage_prompt, str)


def test_planning_pipeline_preserves_context_and_stage_prompt(tmp_path):
    context = PlanningContext(run_dir=tmp_path, target_version="v1")

    result = run_planning_pipeline(context)

    assert result.context == context
    assert result.stage_prompt == render_stage_prompt(PlanningStage.CLASSIFICATION, context)
    assert result.snapshot is not None


def test_write_exec_plan_accepts_source_and_destination(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# plan\n", encoding="utf-8")
    destination_dir = tmp_path / "plans"

    output = write_exec_plan(source, destination_dir, plan_name="exec-plan.md")

    assert output == destination_dir / "exec-plan.md"
    assert output.read_text(encoding="utf-8") == "# plan\n"


def test_write_exec_plan_rejects_path_escape_in_plan_name(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# plan\n", encoding="utf-8")

    with pytest.raises(ValueError):
        write_exec_plan(source, tmp_path / "plans", plan_name="../escape.md")


def test_write_exec_plan_rejects_absolute_plan_name(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# plan\n", encoding="utf-8")

    with pytest.raises(ValueError):
        write_exec_plan(source, tmp_path / "plans", plan_name=str(Path("/tmp/escape.md")))


def test_planning_runner_saves_resume_handle_from_thread_started(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.run_exec_stage",
        lambda **kwargs: type(
            "ExecResult",
            (),
            {
                "event_lines": ['{"type":"thread.started","thread_id":"thread-123"}'],
                "assistant_message": """
<COWORK_PILOT_EVENT>
type: INPUT_REQUIRED
stage: product_completeness_review
event_id: pcr-1
reason: missing redirect
question: 로그인 후 기본 이동 경로는?
options:
  - dashboard
recommended: dashboard
blocking: true
</COWORK_PILOT_EVENT>
""",
                "exit_code": 0,
            },
        )(),
    )

    updated = run_planning_stage_with_runtime(
        run_dir=tmp_path,
        stage="product_completeness_review",
        prompt="continue",
    )

    assert updated == RuntimeUpdate(state=PlanningRuntimeState.WAITING_FOR_INPUT)
    state = read_run_state(tmp_path)
    assert state["state"] == PlanningRuntimeState.WAITING_FOR_INPUT.value
    assert state["resume_handle"] == "thread-123"
    assert state["resume_handle_kind"] == "codex_thread_id"
    assert state["surface"] == "exec"
    assert state["stage"] == "product_completeness_review"
    assert state["event_id"] == "pcr-1"
    assert state["pending_event_id"] == "pcr-1"
    assert state["pending_question"]["question"] == "로그인 후 기본 이동 경로는?"


def test_answer_roundtrip_moves_waiting_for_input_to_running_exec(tmp_path, monkeypatch):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
        metadata={
            "resume_handle": "thread-123",
            "resume_handle_kind": "codex_thread_id",
            "surface": "exec",
            "stage": "product_completeness_review",
            "substage": "",
            "pending_event_id": "pcr-1",
        },
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.run_exec_resume",
        lambda **kwargs: type(
            "ExecResult",
            (),
            {
                "event_lines": [],
                "assistant_message": """
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: product_completeness_review
event_id: pcr-2
reason: complete
summary: done
outputs:
  - product-completeness-review.md
</COWORK_PILOT_EVENT>
""",
                "exit_code": 0,
            },
        )(),
    )

    updated = resume_planning_waiting_run_with_cli(
        run_dir=tmp_path,
        response_text="dashboard",
        response_kind="answer",
    )

    assert updated == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert (tmp_path / "answer-log.md").read_text(encoding="utf-8") == "- [pcr-1] dashboard\n"
    state = read_run_state(tmp_path)
    assert state["state"] == PlanningRuntimeState.RUNNING_EXEC.value
    assert state["event_id"] == "pcr-2"
    assert state["stage"] == "product_completeness_review"
    assert state["resume_handle"] == "thread-123"
    assert state["surface"] == "exec"


def test_approval_roundtrip_moves_waiting_for_approval_to_running_exec(tmp_path, monkeypatch):
    write_run_state(
        tmp_path,
        state=PlanningRuntimeState.WAITING_FOR_APPROVAL.value,
        metadata={
            "resume_handle": "thread-123",
            "resume_handle_kind": "codex_thread_id",
            "surface": "exec",
            "stage": "scope_structuring",
            "substage": "",
            "pending_event_id": "scope-approve-1",
        },
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.run_exec_resume",
        lambda **kwargs: type(
            "ExecResult",
            (),
            {
                "event_lines": [],
                "assistant_message": """
<COWORK_PILOT_EVENT>
type: STAGE_COMPLETE
stage: scope_structuring
event_id: ss-2
reason: complete
summary: done
outputs:
  - scope-map.md
</COWORK_PILOT_EVENT>
""",
                "exit_code": 0,
            },
        )(),
    )

    updated = resume_planning_waiting_run_with_cli(
        run_dir=tmp_path,
        response_text="approved",
        response_kind="approval",
    )

    assert updated == RuntimeUpdate(state=PlanningRuntimeState.RUNNING_EXEC)
    assert (tmp_path / "approval-log.md").read_text(encoding="utf-8") == (
        "- [scope-approve-1] decision=approved\n"
    )
    state = read_run_state(tmp_path)
    assert state["state"] == PlanningRuntimeState.RUNNING_EXEC.value
    assert state["event_id"] == "ss-2"
    assert state["stage"] == "scope_structuring"
    assert state["resume_handle"] == "thread-123"
    assert state["surface"] == "exec"


def test_run_planning_pipeline_greenfield_writes_coverage_gap_and_exec_plan(tmp_path):
    result = run_planning_pipeline(
        PlanningContext(run_dir=tmp_path, target_version="v-greenfield")
    )

    assert (tmp_path / "coverage-gap.md").exists()
    # With the new skeleton→feature-outline→detail flow, exec_plan_path is not set
    # (the old single-file EXEC_PLAN_AUTHORING path is replaced by EXEC_PLAN_SKELETON)
    assert result.runtime_state == "completed"


def test_run_planning_pipeline_brownfield_generates_gap_artifacts(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=tmp_path,
            target_version="v-brownfield",
            change_request_text="로그인 후 기본 이동 경로를 dashboard로 바꾼다",
        )
    )

    assert result.snapshot.project_mode.value == "brownfield"
    assert (tmp_path / "spec-implementation-gap.md").exists()
    assert (tmp_path / "change-impact-gap.md").exists()


def test_planning_pipeline_stops_on_failed_ai_stage(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    def fake_execute_stage_subsession(*, stage, **kwargs):
        if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
            return type(
                "StageExecutionResult",
                (),
                {
                    "runtime_state": PlanningRuntimeState.FAILED.value,
                    "completed_stage": None,
                    "emitted_markers": (),
                    "generated_outputs": (),
                    "resume_handle": "thread-failed",
                    "queued_questions": (),
                    "queued_approvals": (),
                    "assumption_records": (),
                },
            )()
        return type(
            "StageExecutionResult",
            (),
            {
                "runtime_state": PlanningRuntimeState.RUNNING_EXEC.value,
                "completed_stage": stage.value,
                "emitted_markers": (),
                "generated_outputs": (),
                "resume_handle": None,
                "queued_questions": (),
                "queued_approvals": (),
                "assumption_records": (),
            },
        )()

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=tmp_path / "run",
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="build a planning tool",
        )
    )

    assert result.runtime_state == "failed"
    assert result.stopped_stage == "product_completeness_review"


def test_planning_pipeline_resumes_current_stage_before_continuing(tmp_path, monkeypatch):
    import cowork_pilot.planning.pipeline as planning_pipeline

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    run_dir = tmp_path / "run"

    call_counts: dict[str, int] = {}
    side_effect_calls = {
        "extraction": 0,
        "synthesis": 0,
        "gap": 0,
    }

    def fake_execute_stage_subsession(*, stage, **kwargs):
        count = call_counts.get(stage.value, 0) + 1
        call_counts[stage.value] = count
        if stage is PlanningStage.CORE_DOCS_PRESENCE_REVIEW and count == 1:
            return type(
                "StageExecutionResult",
                (),
                {
                    "runtime_state": PlanningRuntimeState.WAITING_FOR_INPUT.value,
                    "completed_stage": None,
                    "emitted_markers": (),
                    "generated_outputs": (),
                    "resume_handle": "thread-completeness",
                    "queued_questions": (),
                    "queued_approvals": (),
                    "assumption_records": (),
                },
            )()
        return type(
            "StageExecutionResult",
            (),
            {
                "runtime_state": PlanningRuntimeState.RUNNING_EXEC.value,
                "completed_stage": stage.value,
                "emitted_markers": (),
                "generated_outputs": (),
                "resume_handle": None,
                "queued_questions": (),
                "queued_approvals": (),
                "assumption_records": (),
            },
        )()

    def fake_resume_stage_subsession(*, run_dir, response_text, response_kind):
        _ = (run_dir, response_text, response_kind)
        return type(
            "StageExecutionResult",
            (),
            {
                "runtime_state": PlanningRuntimeState.RUNNING_EXEC.value,
                "completed_stage": PlanningStage.CORE_DOCS_PRESENCE_REVIEW.value,
                "emitted_markers": (),
                "generated_outputs": (),
                "resume_handle": "thread-completeness",
                "queued_questions": (),
                "queued_approvals": (),
                "assumption_records": (),
            },
        )()

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.resume_stage_subsession",
        fake_resume_stage_subsession,
    )
    original_extraction = planning_pipeline.run_code_observation_extraction
    original_synthesis = planning_pipeline.run_observation_synthesis
    original_gap = planning_pipeline.run_gap_synthesis

    def counting_extraction(*args, **kwargs):
        side_effect_calls["extraction"] += 1
        return original_extraction(*args, **kwargs)

    def counting_synthesis(*args, **kwargs):
        side_effect_calls["synthesis"] += 1
        return original_synthesis(*args, **kwargs)

    def counting_gap(*args, **kwargs):
        side_effect_calls["gap"] += 1
        return original_gap(*args, **kwargs)

    monkeypatch.setattr(planning_pipeline, "run_code_observation_extraction", counting_extraction)
    monkeypatch.setattr(planning_pipeline, "run_observation_synthesis", counting_synthesis)
    monkeypatch.setattr(planning_pipeline, "run_gap_synthesis", counting_gap)

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.BROWNFIELD,
            explicit_mode=True,
            request_text="current flow needs redesign",
            change_request_text="change login landing to dashboard",
        )
    )

    assert result.runtime_state == "waiting_for_input"
    assert result.stopped_stage == "core_docs_presence_review"
    initial_counts = call_counts.copy()
    assert initial_counts["brownfield_code_observation_extraction"] >= 1
    assert initial_counts["brownfield_observation_synthesis"] == 1
    assert initial_counts["brownfield_gap_synthesis"] == 1
    assert initial_counts["core_docs_presence_review"] == 1
    initial_side_effect_calls = side_effect_calls.copy()

    resumed = resume_planning_pipeline_with_user_response(
        run_dir=run_dir,
        response_text="dashboard",
        response_kind="answer",
    )

    assert resumed.runtime_state == "completed"
    assert call_counts["brownfield_code_observation_extraction"] == initial_counts["brownfield_code_observation_extraction"]
    assert call_counts["brownfield_observation_synthesis"] == initial_counts["brownfield_observation_synthesis"]
    assert call_counts["brownfield_gap_synthesis"] == initial_counts["brownfield_gap_synthesis"]
    assert call_counts["core_docs_presence_review"] == initial_counts["core_docs_presence_review"]
    assert call_counts["scope_structuring"] > initial_counts.get("scope_structuring", 0)
    assert call_counts["plan_review"] > initial_counts.get("plan_review", 0)
    assert call_counts["exec_plan_skeleton"] > initial_counts.get("exec_plan_skeleton", 0)
    assert side_effect_calls == initial_side_effect_calls


def test_brownfield_missing_change_request_stops_before_ai_subpipeline(tmp_path, monkeypatch):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("print('hi')\n", encoding="utf-8")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def fail_if_called(*args, **kwargs):  # pragma: no cover - defensive guard
        raise AssertionError("brownfield AI subpipeline should not run without a change request")

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=tmp_path / "run",
            project_dir=project_dir,
            mode=ProjectMode.BROWNFIELD,
            explicit_mode=True,
            request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
            change_request_text="",
        )
    )

    assert result.runtime_state == "waiting_for_input"
    assert result.stopped_stage == "request_normalization"
    assert (tmp_path / "run" / "inputs" / "change-request.md").exists()
    assert (project_dir / "docs" / "planning" / "change-request.md").exists()
    assert "## 승인 기준" in (tmp_path / "run" / "inputs" / "change-request.md").read_text(
        encoding="utf-8"
    )


def test_brownfield_run_dir_only_uses_project_root_for_change_request(tmp_path):
    project_dir = tmp_path / "project"
    run_dir = project_dir / "docs" / "generated" / "planning-runs" / "run-001"
    run_dir.mkdir(parents=True)
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            mode=ProjectMode.BROWNFIELD,
            explicit_mode=True,
            request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
            change_request_text="",
        )
    )

    assert result.runtime_state == "waiting_for_input"
    assert (project_dir / "docs" / "planning" / "change-request.md").exists()
    assert not (run_dir / "docs" / "planning" / "change-request.md").exists()


def test_run_dir_only_standard_layout_classifies_from_inferred_project_root(tmp_path):
    project_dir = tmp_path / "project"
    run_dir = project_dir / "docs" / "generated" / "planning-runs" / "run-001"
    run_dir.mkdir(parents=True)
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
            change_request_text="",
        )
    )

    assert result.snapshot.project_mode.value == "brownfield"
    assert result.runtime_state == "waiting_for_input"
    assert (project_dir / "docs" / "planning" / "change-request.md").exists()


def test_brownfield_pipeline_reuses_existing_canonical_change_request(tmp_path):
    project_dir = tmp_path / "project"
    run_dir = tmp_path / "run"
    project_dir.mkdir()
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    canonical_change_request = project_dir / "docs" / "planning" / "change-request.md"
    canonical_change_request.parent.mkdir(parents=True)
    canonical_change_request.write_text(
        """# Brownfield Change Request

## 변경 목표

로그인 후 기본 이동 경로를 dashboard로 바꾼다
""",
        encoding="utf-8",
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.BROWNFIELD,
            explicit_mode=True,
            request_text="현재 멤버 관리 흐름을 재설계하고 싶다",
            change_request_text="",
        )
    )

    assert result.runtime_state == "completed"
    assert canonical_change_request.read_text(encoding="utf-8") == (
        "# Brownfield Change Request\n\n## 변경 목표\n\n로그인 후 기본 이동 경로를 dashboard로 바꾼다\n"
    )


def test_run_planning_mode_creates_runtime_aware_run_artifacts(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        (
            f"[project]\n"
            f'dir = "{project_dir}"\n\n'
            "[planning]\n"
            'run_root = "docs/generated/planning-runs"\n'
            'default_project_mode = "greenfield"\n'
        ),
        encoding="utf-8",
    )

    run_planning_mode(config_path)

    run_dirs = sorted((project_dir / "docs" / "generated" / "planning-runs").glob("*"))
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "coverage-gap.md").exists()
    # With the new skeleton→feature-outline→detail flow, the single exec-plan.md
    # is no longer produced via EXEC_PLAN_AUTHORING; the run completes through EXEC_PLAN_SKELETON
    assert (run_dirs[0] / "run-state.json").exists()


def test_blocking_question_resumes_same_stage_then_moves_to_next_stage(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    events: list[tuple[str, str]] = []

    def fake_execute_stage_subsession(
        *,
        run_dir: Path,
        stage: PlanningStage,
        prompt: str,
        assumption_scope: str = "broad_product_design",
        project_dir: Path | None = None,
    ):
        _ = (prompt, assumption_scope, project_dir)
        events.append(("exec", stage.value))
        if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
            write_run_state(
                run_dir,
                state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                metadata={
                    "resume_handle": "thread-completeness",
                    "resume_handle_kind": "codex_thread_id",
                    "surface": "exec",
                    "stage": stage.value,
                    "substage": "",
                    "event_id": "pcr-1",
                    "pending_event_id": "pcr-1",
                },
            )
            return StageExecutionResult(
                runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                completed_stage=None,
                emitted_markers=(),
                generated_outputs=(),
                resume_handle="thread-completeness",
                queued_questions=(
                    QueuedQuestion(
                        event_id="pcr-1",
                        question="로그인 후 기본 이동 경로는?",
                        blocking=True,
                    ),
                ),
                queued_approvals=(),
                assumption_records=(),
            )

        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=stage.value,
            emitted_markers=(),
            generated_outputs=(f"{stage.value}.md",),
            resume_handle=f"thread-{stage.value}",
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    def fake_resume_stage_subsession(*, run_dir: Path, response_text: str, response_kind: str):
        _ = (run_dir, response_text, response_kind)
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value,
            emitted_markers=(),
            generated_outputs=("product-completeness-review.md",),
            resume_handle="thread-completeness",
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.resume_stage_subsession",
        fake_resume_stage_subsession,
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="로그인 플로우와 대시보드 이동을 정리하고 싶다",
        )
    )

    assert result.runtime_state == "waiting_for_input"
    assert result.stopped_stage == PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value

    resumed = resume_planning_pipeline_with_user_response(
        run_dir=run_dir,
        response_text="dashboard",
        response_kind="answer",
    )

    assert resumed.runtime_state == "completed"
    assert events[:2] == [
        ("exec", "product_completeness_review"),
        ("exec", "scope_structuring"),
    ]


def test_resume_stays_inside_current_stage_when_question_remains_blocking(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    events: list[tuple[str, str]] = []

    def fake_execute_stage_subsession(
        *,
        run_dir: Path,
        stage: PlanningStage,
        prompt: str,
        assumption_scope: str = "broad_product_design",
        project_dir: Path | None = None,
    ):
        _ = (prompt, assumption_scope, project_dir)
        events.append(("exec", stage.value))
        write_run_state(
            run_dir,
            state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
            metadata={
                "resume_handle": "thread-completeness",
                "resume_handle_kind": "codex_thread_id",
                "surface": "exec",
                "stage": stage.value,
                "substage": "",
                "event_id": "pcr-1",
                "pending_event_id": "pcr-1",
            },
        )
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
            completed_stage=None,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle="thread-completeness",
            queued_questions=(
                QueuedQuestion(
                    event_id="pcr-1",
                    question="로그인 후 기본 이동 경로는?",
                    blocking=True,
                ),
            ),
            queued_approvals=(),
            assumption_records=(),
        )

    def fake_resume_stage_subsession(*, run_dir: Path, response_text: str, response_kind: str):
        _ = (response_text, response_kind)
        write_run_state(
            run_dir,
            state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
            metadata={
                "resume_handle": "thread-completeness",
                "resume_handle_kind": "codex_thread_id",
                "surface": "exec",
                "stage": PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value,
                "substage": "",
                "event_id": "pcr-2",
                "pending_event_id": "pcr-2",
            },
        )
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
            completed_stage=None,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle="thread-completeness",
            queued_questions=(
                QueuedQuestion(
                    event_id="pcr-2",
                    question="대시보드 이전에 온보딩을 거쳐야 하나요?",
                    blocking=True,
                ),
            ),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.resume_stage_subsession",
        fake_resume_stage_subsession,
    )

    first = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="로그인 플로우와 대시보드 이동을 정리하고 싶다",
        )
    )

    assert first.runtime_state == "waiting_for_input"

    resumed = resume_planning_pipeline_with_user_response(
        run_dir=run_dir,
        response_text="dashboard",
        response_kind="answer",
    )

    assert resumed.runtime_state == "waiting_for_input"
    assert resumed.stopped_stage == PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value
    assert events == [("exec", "product_completeness_review")]


def test_write_numbered_exec_plan_creates_file_with_number_prefix(tmp_path):
    from cowork_pilot.planning.authoring import write_numbered_exec_plan

    source = tmp_path / "detail.md"
    source.write_text("# Auth Flow\n\n## Chunk 1\n...", encoding="utf-8")
    dest_dir = tmp_path / "docs" / "exec-plans" / "planning"

    result = write_numbered_exec_plan(source, dest_dir, plan_name="02-auth-flow")
    assert result is not None
    assert result.name == "02-auth-flow.md"
    assert result.read_text(encoding="utf-8").startswith("# Auth Flow")


def test_write_numbered_exec_plan_rejects_path_escape(tmp_path):
    from cowork_pilot.planning.authoring import write_numbered_exec_plan

    source = tmp_path / "detail.md"
    source.write_text("content", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe"):
        write_numbered_exec_plan(source, tmp_path, plan_name="../escape")


def test_resume_planning_pipeline_restores_from_run_dir(tmp_path, monkeypatch):
    from cowork_pilot.planning.runner import resume_planning_pipeline
    from cowork_pilot.planning.runtime_storage import write_pipeline_state
    from cowork_pilot.planning.pipeline import load_planning_pipeline_result_from_run_dir

    run_dir = tmp_path / "docs" / "generated" / "planning-runs" / "run-001"
    run_dir.mkdir(parents=True)
    project_dir = tmp_path

    write_run_state(run_dir, state="waiting_for_input", metadata={
        "stage": "scope_structuring",
        "resume_handle": "thread-abc",
        "resume_handle_kind": "codex_thread_id",
        "surface": "exec",
        "event_id": "evt-1",
    })
    write_pipeline_state(run_dir, context=PlanningContext(
        run_dir=run_dir, project_dir=project_dir, mode=ProjectMode.GREENFIELD, explicit_mode=True,
    ), next_dispatch_index=5)

    # Mock resume to just return
    monkeypatch.setattr(
        "cowork_pilot.planning.runner.resume_planning_pipeline_with_user_response",
        lambda **kwargs: load_planning_pipeline_result_from_run_dir(run_dir),
    )

    result = resume_planning_pipeline(run_dir=run_dir, response_text="approved", response_kind="approval")
    assert result is not None


def test_pipeline_skips_already_completed_stages(tmp_path, monkeypatch):
    from cowork_pilot.planning.runtime_storage import write_completed_stage

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    run_dir = tmp_path / "run"

    # Pre-populate completed stages:
    # indices 0-2 are local (classification, core_docs_check, adaptive_docs_selection)
    # index 3 is AI (product_completeness_review) — mark it completed to test skip
    write_completed_stage(run_dir, stage="classification", dispatch_index=0)
    write_completed_stage(run_dir, stage="core_docs_check", dispatch_index=1)
    write_completed_stage(run_dir, stage="adaptive_docs_selection", dispatch_index=2)
    write_completed_stage(run_dir, stage="product_completeness_review", dispatch_index=3)

    executed_ai_stages: list[str] = []

    def fake_execute_stage_subsession(*, run_dir, stage, prompt, assumption_scope="broad_product_design", project_dir=None):
        executed_ai_stages.append(stage.value)
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=stage.value,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle=None,
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="build a planning tool",
        )
    )

    assert result.runtime_state == "completed"
    # product_completeness_review (AI, index 3) should NOT have been executed
    assert "product_completeness_review" not in executed_ai_stages
    # scope_structuring (AI, index 4) SHOULD have been executed
    assert "scope_structuring" in executed_ai_stages


def test_interactive_run_resolves_blocking_question_in_same_process(tmp_path, monkeypatch):
    """Interactive mode: first stage returns waiting, user answers in terminal, pipeline completes."""
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    call_count = {"resume": 0}

    def fake_execute_stage_subsession(
        *,
        run_dir: Path,
        stage: PlanningStage,
        prompt: str,
        assumption_scope: str = "broad_product_design",
        project_dir: Path | None = None,
    ):
        if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
            write_run_state(
                run_dir,
                state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                metadata={
                    "resume_handle": "thread-interactive",
                    "resume_handle_kind": "codex_thread_id",
                    "surface": "exec",
                    "stage": stage.value,
                    "substage": "",
                    "event_id": "pcr-1",
                    "pending_event_id": "pcr-1",
                    "pending_question": {
                        "event_id": "pcr-1",
                        "question": "기본 경로는?",
                        "options": ["dashboard"],
                        "recommended": "dashboard",
                        "blocking": True,
                    },
                },
            )
            from cowork_pilot.planning.stage_executor import PendingQuestion
            return StageExecutionResult(
                runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                completed_stage=None,
                emitted_markers=(),
                generated_outputs=(),
                resume_handle="thread-interactive",
                queued_questions=(
                    QueuedQuestion(event_id="pcr-1", question="기본 경로는?", blocking=True),
                ),
                queued_approvals=(),
                assumption_records=(),
                pending_question=PendingQuestion(
                    event_id="pcr-1",
                    question="기본 경로는?",
                    options=("dashboard",),
                    recommended="dashboard",
                    blocking=True,
                ),
            )
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=stage.value,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle=None,
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    def fake_resume_stage_subsession(*, run_dir, response_text, response_kind):
        call_count["resume"] += 1
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value,
            emitted_markers=(),
            generated_outputs=("product-completeness-review.md",),
            resume_handle="thread-interactive",
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.resume_stage_subsession",
        fake_resume_stage_subsession,
    )
    # Mock terminal input
    monkeypatch.setattr(
        "cowork_pilot.planning.terminal_ui._default_input_fn",
        lambda _: "",  # Enter = accept recommended
    )
    # Bypass completion verifier for local stages (pre-existing issue: no real artifacts)
    from cowork_pilot.planning.completion_verifier import CompletionVerdict
    monkeypatch.setattr(
        "cowork_pilot.planning.pipeline.verify_stage_completion",
        lambda *a, **kw: CompletionVerdict(passed=True),
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="build a planning tool",
        ),
        interactive=True,
    )

    assert result.runtime_state == "completed"
    assert call_count["resume"] == 1


def test_non_interactive_run_stops_on_blocking_question(tmp_path, monkeypatch):
    """Non-interactive mode: blocking question halts the pipeline as before."""
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    def fake_execute_stage_subsession(
        *,
        run_dir: Path,
        stage: PlanningStage,
        prompt: str,
        assumption_scope: str = "broad_product_design",
        project_dir: Path | None = None,
    ):
        if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
            write_run_state(
                run_dir,
                state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                metadata={
                    "resume_handle": "thread-1",
                    "resume_handle_kind": "codex_thread_id",
                    "surface": "exec",
                    "stage": stage.value,
                    "substage": "",
                    "event_id": "pcr-1",
                    "pending_event_id": "pcr-1",
                },
            )
            return StageExecutionResult(
                runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                completed_stage=None,
                emitted_markers=(),
                generated_outputs=(),
                resume_handle="thread-1",
                queued_questions=(
                    QueuedQuestion(event_id="pcr-1", question="경로?", blocking=True),
                ),
                queued_approvals=(),
                assumption_records=(),
            )
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=stage.value,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle=None,
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )
    # Bypass completion verifier for local stages (pre-existing issue: no real artifacts)
    from cowork_pilot.planning.completion_verifier import CompletionVerdict
    monkeypatch.setattr(
        "cowork_pilot.planning.pipeline.verify_stage_completion",
        lambda *a, **kw: CompletionVerdict(passed=True),
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="build a planning tool",
        ),
        interactive=False,
    )

    assert result.runtime_state == "waiting_for_input"


def test_interactive_consecutive_questions_resolved_before_stage_advance(tmp_path, monkeypatch):
    """Two blocking questions in the same stage are both resolved interactively."""
    run_dir = tmp_path / "run"
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    resume_calls: list[str] = []

    def fake_execute_stage_subsession(
        *,
        run_dir: Path,
        stage: PlanningStage,
        prompt: str,
        assumption_scope: str = "broad_product_design",
        project_dir: Path | None = None,
    ):
        if stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW:
            write_run_state(
                run_dir,
                state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                metadata={
                    "resume_handle": "thread-multi",
                    "resume_handle_kind": "codex_thread_id",
                    "surface": "exec",
                    "stage": stage.value,
                    "substage": "",
                    "event_id": "q1",
                    "pending_event_id": "q1",
                },
            )
            from cowork_pilot.planning.stage_executor import PendingQuestion
            return StageExecutionResult(
                runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                completed_stage=None,
                emitted_markers=(),
                generated_outputs=(),
                resume_handle="thread-multi",
                queued_questions=(
                    QueuedQuestion(event_id="q1", question="질문 1?", blocking=True),
                ),
                queued_approvals=(),
                assumption_records=(),
                pending_question=PendingQuestion(
                    event_id="q1", question="질문 1?", options=(), recommended="A", blocking=True,
                ),
            )
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=stage.value,
            emitted_markers=(),
            generated_outputs=(),
            resume_handle=None,
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    def fake_resume_stage_subsession(*, run_dir, response_text, response_kind):
        resume_calls.append(response_text)
        if len(resume_calls) == 1:
            # First resume => another blocking question
            from cowork_pilot.planning.stage_executor import PendingQuestion
            write_run_state(
                run_dir,
                state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                metadata={
                    "resume_handle": "thread-multi",
                    "resume_handle_kind": "codex_thread_id",
                    "surface": "exec",
                    "stage": "product_completeness_review",
                    "substage": "",
                    "event_id": "q2",
                    "pending_event_id": "q2",
                },
            )
            return StageExecutionResult(
                runtime_state=PlanningRuntimeState.WAITING_FOR_INPUT.value,
                completed_stage=None,
                emitted_markers=(),
                generated_outputs=(),
                resume_handle="thread-multi",
                queued_questions=(
                    QueuedQuestion(event_id="q2", question="질문 2?", blocking=True),
                ),
                queued_approvals=(),
                assumption_records=(),
                pending_question=PendingQuestion(
                    event_id="q2", question="질문 2?", options=("X", "Y"), recommended="X", blocking=True,
                ),
            )
        # Second resume => stage complete
        return StageExecutionResult(
            runtime_state=PlanningRuntimeState.RUNNING_EXEC.value,
            completed_stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW.value,
            emitted_markers=(),
            generated_outputs=("product-completeness-review.md",),
            resume_handle="thread-multi",
            queued_questions=(),
            queued_approvals=(),
            assumption_records=(),
        )

    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.execute_stage_subsession",
        fake_execute_stage_subsession,
    )
    monkeypatch.setattr(
        "cowork_pilot.planning.stage_executor.resume_stage_subsession",
        fake_resume_stage_subsession,
    )
    # Simulate two answers
    answer_queue = iter(["A", ""])  # first answer text, second Enter=recommended
    monkeypatch.setattr(
        "cowork_pilot.planning.terminal_ui._default_input_fn",
        lambda _: next(answer_queue),
    )
    # Bypass completion verifier for local stages (pre-existing issue: no real artifacts)
    from cowork_pilot.planning.completion_verifier import CompletionVerdict
    monkeypatch.setattr(
        "cowork_pilot.planning.pipeline.verify_stage_completion",
        lambda *a, **kw: CompletionVerdict(passed=True),
    )

    result = run_planning_pipeline(
        PlanningContext(
            run_dir=run_dir,
            project_dir=project_dir,
            mode=ProjectMode.GREENFIELD,
            explicit_mode=True,
            request_text="build a planning tool",
        ),
        interactive=True,
    )

    assert result.runtime_state == "completed"
    assert len(resume_calls) == 2
