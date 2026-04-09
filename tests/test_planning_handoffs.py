from pathlib import Path

import pytest

from cowork_pilot.planning import handoffs
from cowork_pilot.planning.models import PlanningStage


def test_write_stage_handoff_creates_numbered_markdown(tmp_path: Path):
    handoff_path = handoffs.write_stage_handoff(
        run_dir=tmp_path,
        order=2,
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        decisions=("redirect는 dashboard로 둔다",),
        unresolved_questions=(),
        assumptions=("기본 권한 모델은 관리자/멤버 2종",),
        outputs=("product-completeness-review.md", "coverage-gap.md"),
        next_read_set=("inputs/normalized-request.md", "coverage-gap.md"),
    )

    assert handoff_path == tmp_path / "stage-handoffs" / "02-product_completeness_review.md"
    assert "redirect는 dashboard로 둔다" in handoff_path.read_text(encoding="utf-8")
    assert "coverage-gap.md" in handoff_path.read_text(encoding="utf-8")


def test_write_stage_handoff_includes_stage_purpose_and_round_trips(
    tmp_path: Path,
):
    handoff_path = handoffs.write_stage_handoff(
        run_dir=tmp_path,
        order=2,
        stage=PlanningStage.PRODUCT_COMPLETENESS_REVIEW,
        decisions=("redirect는 dashboard로 둔다",),
        unresolved_questions=("어드민 권한 범위는?",),
        assumptions=("기본 권한 모델은 관리자/멤버 2종",),
        outputs=("product-completeness-review.md", "coverage-gap.md"),
        next_read_set=("inputs/normalized-request.md", "coverage-gap.md"),
    )

    text = handoff_path.read_text(encoding="utf-8")
    assert "## Stage Purpose" in text

    loaded = handoffs.load_stage_handoff(handoff_path)

    assert loaded.order == 2
    assert loaded.stage is PlanningStage.PRODUCT_COMPLETENESS_REVIEW
    assert loaded.stage_purpose
    assert loaded.decisions == ("redirect는 dashboard로 둔다",)
    assert loaded.unresolved_questions == ("어드민 권한 범위는?",)
    assert loaded.assumptions == ("기본 권한 모델은 관리자/멤버 2종",)
    assert loaded.outputs == ("product-completeness-review.md", "coverage-gap.md")
    assert loaded.next_read_set == ("inputs/normalized-request.md", "coverage-gap.md")


def test_load_stage_handoff_rejects_missing_required_sections(tmp_path: Path):
    handoff_path = tmp_path / "stage-handoffs" / "02-product_completeness_review.md"
    handoff_path.parent.mkdir(parents=True)
    handoff_path.write_text(
        "\n".join(
            [
                "# Stage Handoff",
                "",
                "- order: 02",
                "- stage: product_completeness_review",
                "",
                "## Stage Purpose",
                "- product completeness review",
                "",
                "## Decisions",
                "- redirect는 dashboard로 둔다",
                "",
                "## Unresolved Questions",
                "- 어드민 권한 범위는?",
                "",
                "## Assumptions",
                "- 기본 권한 모델은 관리자/멤버 2종",
                "",
                "## Next Read Set",
                "- inputs/normalized-request.md",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required handoff section: Outputs"):
        handoffs.load_stage_handoff(handoff_path)


def test_build_stage_read_set_derives_inputs_from_run_dir_and_skips_missing_runtime_logs(
    tmp_path: Path,
):
    normalized_request = tmp_path / "inputs" / "normalized-request.md"
    normalized_request.parent.mkdir(parents=True)
    normalized_request.write_text("normalized", encoding="utf-8")

    change_request = tmp_path / "inputs" / "change-request.md"
    change_request.write_text("change request", encoding="utf-8")

    previous_handoff = tmp_path / "stage-handoffs" / "02-product_completeness_review.md"
    previous_handoff.parent.mkdir(parents=True)
    previous_handoff.write_text("handoff", encoding="utf-8")

    canonical_doc = tmp_path / "docs" / "specs" / "index.md"
    canonical_doc.parent.mkdir(parents=True)
    canonical_doc.write_text("canonical", encoding="utf-8")

    runtime_log = tmp_path / "assumptions.md"
    runtime_log.write_text("log", encoding="utf-8")

    read_set = handoffs.build_stage_read_set(
        run_dir=tmp_path,
        canonical_docs=(canonical_doc,),
        previous_handoff=previous_handoff,
        runtime_logs=("assumptions.md", "missing-log.md", tmp_path / "answer-log.md"),
    )

    assert read_set == (
        normalized_request,
        change_request,
        previous_handoff,
        canonical_doc,
        runtime_log,
    )
