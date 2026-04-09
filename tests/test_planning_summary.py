# tests/test_planning_summary.py

from cowork_pilot.planning.summary import build_pipeline_summary, PipelineSummary


def test_build_summary_counts_stages_and_plans(tmp_path):
    # Create some completed-stages.json and exec-plan files
    import json
    (tmp_path / "completed-stages.json").write_text(json.dumps([
        {"stage": "classification", "dispatch_index": 0},
        {"stage": "core_docs_check", "dispatch_index": 1},
        {"stage": "exec_plan_outline", "dispatch_index": 10},
        {"stage": "exec_plan_detail", "dispatch_index": 11},
        {"stage": "exec_plan_detail", "dispatch_index": 12},
    ]), encoding="utf-8")

    plans_dir = tmp_path / "docs" / "exec-plans" / "planning"
    plans_dir.mkdir(parents=True)
    (plans_dir / "01-setup.md").write_text("plan 1", encoding="utf-8")
    (plans_dir / "02-auth.md").write_text("plan 2", encoding="utf-8")

    summary = build_pipeline_summary(run_dir=tmp_path, project_dir=tmp_path)
    assert summary.total_stages_completed == 5
    assert summary.exec_plan_count == 2
    assert summary.errors == 0


def test_build_summary_returns_none_on_empty_run(tmp_path):
    summary = build_pipeline_summary(run_dir=tmp_path, project_dir=tmp_path)
    assert summary.total_stages_completed == 0
