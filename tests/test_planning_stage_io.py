"""Tests for stage IO contract builder and inventory."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from cowork_pilot.planning.models import (
    PlanningStage,
    StageDispatch,
    ClassificationSnapshot,
    ProjectMode,
    SizeClass,
)
from cowork_pilot.planning.stage_io import (
    StageIOContract,
    build_stage_io_contract,
    STAGE_READ_POLICY,
    STAGE_REQUIRED_DOC_ROLES,
)


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project structure."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "docs").mkdir()
    (project / "docs" / "generated").mkdir()
    (project / "docs" / "generated" / "planning").mkdir()
    (project / "docs" / "exec-plans").mkdir()
    (project / "docs" / "exec-plans" / "planning").mkdir()
    return project


@pytest.fixture
def run_dir(tmp_path):
    """Create a minimal run directory structure."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "inputs").mkdir()
    (run / "stage-handoffs").mkdir()
    return run


@pytest.fixture
def snapshot():
    """Create a classification snapshot."""
    return ClassificationSnapshot(
        project_mode=ProjectMode.GREENFIELD,
        size_class=SizeClass.SMALL,
        product_type="greenfield-app",
        confidence="high",
        borderline=False,
    )


@pytest.fixture
def dispatch():
    """Create a stage dispatch."""
    return StageDispatch(
        stage=PlanningStage.CLASSIFICATION,
        execution_kind="ai",
        order=0,
    )


class TestStageIOContractBasics:
    """Test StageIOContract dataclass."""

    def test_contract_is_frozen(self):
        """Contract should be immutable."""
        contract = StageIOContract(
            stage=PlanningStage.CLASSIFICATION,
            substage="",
            slice_name="",
            required_doc_roles=(),
            resolved_role_paths={},
            selected_context_paths=(),
            read_policy="none",
            read_paths=(),
            primary_inputs=(),
            input_paths={},
            missing_input_paths=(),
            output_paths=(),
            primary_output_path=None,
            upstream_output_paths=(),
            runtime_log_paths=(),
            stage_handoff_path=Path("/tmp/test.md"),
            canonical_generated_root=Path("/tmp"),
            canonical_exec_plan_root=Path("/tmp"),
            canonical_spec_root=None,
            plan_slug=None,
        )
        with pytest.raises(AttributeError):
            contract.stage = PlanningStage.WORK_SIZING

    def test_contract_required_fields(self):
        """Contract should have all required fields."""
        contract = StageIOContract(
            stage=PlanningStage.CLASSIFICATION,
            substage="",
            slice_name="",
            required_doc_roles=(),
            resolved_role_paths={},
            selected_context_paths=(),
            read_policy="none",
            read_paths=(),
            primary_inputs=(),
            input_paths={},
            missing_input_paths=(),
            output_paths=(),
            primary_output_path=None,
            upstream_output_paths=(),
            runtime_log_paths=(),
            stage_handoff_path=Path("/tmp/test.md"),
            canonical_generated_root=Path("/tmp"),
            canonical_exec_plan_root=Path("/tmp"),
            canonical_spec_root=None,
            plan_slug=None,
        )
        assert contract.stage == PlanningStage.CLASSIFICATION
        assert contract.read_policy == "none"
        assert contract.canonical_generated_root == Path("/tmp")


class TestStageReadPolicyMapping:
    """Test STAGE_READ_POLICY constant."""

    def test_all_stages_have_read_policy(self):
        """Every PlanningStage should have a read policy."""
        for stage in PlanningStage:
            assert stage in STAGE_READ_POLICY, f"Missing read policy for {stage}"

    def test_read_policies_are_valid(self):
        """All policies should be valid string values."""
        valid_policies = {
            "none",
            "index_only",
            "spec_documents",
            "all",
        }
        for policy in STAGE_READ_POLICY.values():
            assert policy in valid_policies, f"Invalid policy: {policy}"

    def test_classification_has_no_policy(self):
        """Classification should read no policy."""
        assert STAGE_READ_POLICY[PlanningStage.CLASSIFICATION] == "none"


class TestStageRequiredDocRoles:
    """Test STAGE_REQUIRED_DOC_ROLES constant."""

    def test_all_stages_have_doc_roles(self):
        """Every PlanningStage should have required doc roles."""
        for stage in PlanningStage:
            assert stage in STAGE_REQUIRED_DOC_ROLES, f"Missing doc roles for {stage}"

    def test_doc_roles_are_tuples(self):
        """All doc roles should be tuples of strings."""
        for roles in STAGE_REQUIRED_DOC_ROLES.values():
            assert isinstance(roles, tuple)
            assert all(isinstance(role, str) for role in roles)

    def test_classification_requires_no_roles(self):
        """Classification should require no doc roles."""
        assert STAGE_REQUIRED_DOC_ROLES[PlanningStage.CLASSIFICATION] == ()


class TestBuildStageIOContract:
    """Test build_stage_io_contract function."""

    def test_classification_stage_contract(self, project_dir, run_dir, dispatch, snapshot):
        """Build contract for classification stage."""
        # Create input files
        (run_dir / "inputs" / "request.md").write_text("Request content")
        (run_dir / "inputs" / "normalized-request.md").write_text("Normalized request")

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        assert contract.stage == PlanningStage.CLASSIFICATION
        assert contract.read_policy == "none"
        assert contract.required_doc_roles == ()
        assert contract.canonical_generated_root == project_dir / "docs" / "generated" / "planning"
        assert contract.canonical_exec_plan_root == project_dir / "docs" / "exec-plans" / "planning"

    def test_contract_computes_canonical_roots(self, project_dir, run_dir, dispatch, snapshot):
        """Contract should compute canonical roots correctly."""
        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        assert contract.canonical_generated_root.exists()
        assert contract.canonical_exec_plan_root.exists()

    def test_contract_stage_handoff_path(self, project_dir, run_dir, dispatch, snapshot):
        """Stage handoff path should follow naming convention."""
        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # Should be run_dir/stage-handoffs/{stage}-{substage_or_slice_or_main}.md
        assert "stage-handoffs" in str(contract.stage_handoff_path)
        assert contract.stage_handoff_path.parent == run_dir / "stage-handoffs"

    def test_classification_primary_inputs(self, project_dir, run_dir, dispatch, snapshot):
        """Classification stage should have request and normalized-request as primary inputs."""
        (run_dir / "inputs" / "request.md").write_text("Request content")
        (run_dir / "inputs" / "normalized-request.md").write_text("Normalized request")

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # Primary inputs should include these files
        assert any("request.md" in str(p) for p in contract.primary_inputs)
        assert any("normalized-request.md" in str(p) for p in contract.primary_inputs)

    def test_missing_input_paths(self, project_dir, run_dir, dispatch, snapshot):
        """Should track missing primary input paths."""
        # Don't create any input files
        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # Classification expects request.md and normalized-request.md
        # At least one should be missing
        assert len(contract.missing_input_paths) > 0

    def test_output_paths_classification(self, project_dir, run_dir, dispatch, snapshot):
        """Classification should have correct output path."""
        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        assert contract.primary_output_path is not None
        assert "classification-report.md" in str(contract.primary_output_path)
        assert contract.primary_output_path in contract.output_paths

    def test_read_paths_order_for_classification(self, project_dir, run_dir, dispatch, snapshot):
        """Read paths should follow order: normalized-request first."""
        (run_dir / "inputs" / "normalized-request.md").write_text("Normalized")

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # For classification with "none" policy, should still include request/normalized-request
        assert len(contract.read_paths) > 0

    def test_runtime_log_paths(self, project_dir, run_dir, dispatch, snapshot):
        """Should include runtime log paths."""
        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # Should always include these three (even if they don't exist)
        log_path_names = {p.name for p in contract.runtime_log_paths}
        assert "assumptions.md" in log_path_names
        assert "answer-log.md" in log_path_names
        assert "approval-log.md" in log_path_names

    def test_previous_handoff_in_upstream_outputs(self, project_dir, run_dir, dispatch, snapshot):
        """Previous handoff should be in upstream_output_paths."""
        handoff_path = run_dir / "previous-handoff.md"
        handoff_path.write_text("Previous")

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=handoff_path,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        assert handoff_path in contract.upstream_output_paths

    def test_core_docs_and_adaptive_docs(self, project_dir, run_dir, dispatch, snapshot):
        """Core and adaptive docs should be tracked."""
        core = project_dir / "AGENTS.md"
        core.write_text("Agents")
        adaptive = project_dir / "docs" / "ARCHITECTURE.md"
        adaptive.parent.mkdir(exist_ok=True)
        adaptive.write_text("Architecture")

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(core,),
            adaptive_docs=(adaptive,),
        )

        # These should appear somewhere in read_paths or selected_context_paths
        all_paths = set(contract.read_paths) | set(contract.selected_context_paths)
        # At least one of these files should be included
        assert core in all_paths or adaptive in all_paths

    def test_exec_plan_detail_stage_has_plan_slug(self, project_dir, run_dir, snapshot):
        """exec_plan_detail should resolve plan_slug from dispatch."""
        dispatch = StageDispatch(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            execution_kind="ai",
            order=11,
            substage="search-feature",
            slice_name="",
        )

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # plan_slug should be resolved from substage
        assert contract.plan_slug == "search-feature"
        # Output path should use plan_slug
        assert any("search-feature.md" in str(p) for p in contract.output_paths)

    def test_exec_plan_detail_fallback_plan_slug(self, project_dir, run_dir, snapshot):
        """exec_plan_detail should use 'exec-plan' when substage is empty."""
        dispatch = StageDispatch(
            stage=PlanningStage.EXEC_PLAN_DETAIL,
            execution_kind="ai",
            order=11,
            substage="",
            slice_name="",
        )

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # plan_slug should default to exec-plan
        assert contract.plan_slug == "exec-plan"

    def test_core_docs_check_stage(self, project_dir, run_dir, snapshot):
        """core_docs_check stage should have correct inputs and outputs."""
        dispatch = StageDispatch(
            stage=PlanningStage.CORE_DOCS_CHECK,
            execution_kind="ai",
            order=1,
        )
        # Create classification report (upstream output)
        canonical_gen = project_dir / "docs" / "generated" / "planning"
        canonical_gen.mkdir(parents=True, exist_ok=True)
        (canonical_gen / "classification-report.md").write_text("Classification")

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        assert contract.stage == PlanningStage.CORE_DOCS_CHECK
        # Should require agents and spec_index roles
        assert "agents" in contract.required_doc_roles
        assert "spec_index" in contract.required_doc_roles
        # Should output core-docs-check.md
        assert any("core-docs-check.md" in str(p) for p in contract.output_paths)

    def test_exec_plan_feature_outline_stage(self, project_dir, run_dir, snapshot):
        """exec_plan_feature_outline stage should use slice_name in output."""
        dispatch = StageDispatch(
            stage=PlanningStage.EXEC_PLAN_FEATURE_OUTLINE,
            execution_kind="ai",
            order=10,
            slice_name="auth-flow",
        )

        contract = build_stage_io_contract(
            project_dir=project_dir,
            run_dir=run_dir,
            dispatch=dispatch,
            previous_handoff=None,
            snapshot=snapshot,
            core_docs=(),
            adaptive_docs=(),
        )

        # Output should contain feature-outlines/{slice_name}.md
        assert any("feature-outlines/auth-flow.md" in str(p) for p in contract.output_paths)
