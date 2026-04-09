import pytest
from pathlib import Path

import cowork_pilot.planning as planning
from cowork_pilot.planning.models import (
    ClassificationSnapshot,
    PlanningContext,
    PlanningStage,
    PlanningPipelineResult,
    ProjectConventionProfile,
    ProjectMode,
    SizeClass,
)
from cowork_pilot.planning.storage import bootstrap_run_dir, create_run_id, write_intermediate_doc


def test_planning_stage_enums_include_brownfield_substages():
    assert PlanningStage.CLASSIFICATION.value == "classification"
    assert (
        PlanningStage.BROWNFIELD_CODE_OBSERVATION_EXTRACTION.value
        == "brownfield_code_observation_extraction"
    )
    assert (
        PlanningStage.BROWNFIELD_OBSERVATION_SYNTHESIS.value
        == "brownfield_observation_synthesis"
    )
    assert (
        PlanningStage.BROWNFIELD_GAP_SYNTHESIS.value
        == "brownfield_gap_synthesis"
    )
    assert PlanningStage.CORE_DOCS_CHECK.value == "core_docs_check"
    assert PlanningStage.ADAPTIVE_DOCS_SELECTION.value == "adaptive_docs_selection"


def test_project_modes():
    assert ProjectMode.GREENFIELD.value == "greenfield"
    assert ProjectMode.BROWNFIELD.value == "brownfield"
    assert SizeClass.SMALL.value == "small"
    assert SizeClass.MEDIUM.value == "medium"
    assert SizeClass.LARGE.value == "large"
    assert ProjectConventionProfile.SPECS_CENTERED.value == "specs_centered"
    assert (
        ProjectConventionProfile.PRODUCT_SPECS_CENTERED.value
        == "product_specs_centered"
    )


def test_classification_snapshot_defaults():
    snapshot = ClassificationSnapshot(
        project_mode=ProjectMode.GREENFIELD,
        size_class=SizeClass.SMALL,
        product_type="web-app",
        confidence="high",
        borderline=False,
    )

    assert snapshot.classification_snapshot_kind == "initial"
    assert snapshot.initial_size_class is None
    assert snapshot.confirmed_size_class is None
    assert snapshot.initial_borderline is None
    assert snapshot.confirmed_borderline is None
    assert snapshot.confirmed_change_impact is None
    assert snapshot.requires_observation_reclassification is False


def test_planning_package_exports():
    assert planning.ProjectMode is ProjectMode
    assert planning.SizeClass is SizeClass
    assert planning.PlanningStage is PlanningStage
    assert planning.ClassificationSnapshot is ClassificationSnapshot
    assert planning.PlanningContext is PlanningContext
    assert planning.PlanningPipelineResult is PlanningPipelineResult
    assert planning.create_run_id is create_run_id
    assert planning.bootstrap_run_dir is bootstrap_run_dir
    assert planning.write_intermediate_doc is write_intermediate_doc
    assert callable(planning.render_stage_prompt)
    assert callable(planning.run_planning_pipeline)


def test_write_intermediate_doc_rejects_path_escape(tmp_path):
    run_dir = bootstrap_run_dir(tmp_path, "run-1")

    with pytest.raises(ValueError):
        write_intermediate_doc(run_dir, "../escape.md", "blocked")

    assert not (tmp_path / "escape.md").exists()


def test_write_intermediate_doc_allows_nested_paths(tmp_path):
    run_dir = bootstrap_run_dir(tmp_path, "run-2")
    doc_path = write_intermediate_doc(run_dir, "nested/notes.md", "ok")

    assert doc_path == run_dir / "nested" / "notes.md"
    assert doc_path.read_text(encoding="utf-8") == "ok"


def test_bootstrap_run_dir_rejects_path_escape(tmp_path):
    with pytest.raises(ValueError):
        bootstrap_run_dir(tmp_path, "../escape")


def test_bootstrap_run_dir_rejects_absolute_run_id(tmp_path):
    with pytest.raises(ValueError):
        bootstrap_run_dir(tmp_path, str(Path("/tmp/escape")))


def test_planning_stage_includes_exec_plan_skeleton_feature_outline_and_detail():
    assert PlanningStage.EXEC_PLAN_SKELETON.value == "exec_plan_skeleton"
    assert PlanningStage.EXEC_PLAN_FEATURE_OUTLINE.value == "exec_plan_feature_outline"
    assert PlanningStage.EXEC_PLAN_DETAIL.value == "exec_plan_detail"


def test_outline_plan_dataclass_fields():
    from cowork_pilot.planning.models import OutlinePlan
    plan = OutlinePlan(number="01", name="project-setup", filename="01-project-setup.md", feature_scope=("auth",))
    assert plan.number == "01"
    assert plan.name == "project-setup"
    assert plan.filename == "01-project-setup.md"
    assert plan.feature_scope == ("auth",)
