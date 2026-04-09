from cowork_pilot.planning.outline import parse_outline_plans


_SAMPLE_OUTLINE = """\
## exec-plan 개요

| # | 파일명 | 범위 | Chunk 수 | 의존성 |
|---|--------|------|---------|--------|
| 1 | 01-project-setup.md | 초기화 | 3 | 없음 |
| 2 | 02-auth-flow.md | 인증 | 5 | 01 |
| 3 | 03-data-layer.md | DB | 4 | 01 |

## 01-project-setup.md 상세

### Chunk 1: 환경설정
...

## 02-auth-flow.md 상세

### Chunk 1: 로그인
...

## 03-data-layer.md 상세

### Chunk 1: 스키마
...
"""


def test_parse_outline_plans_extracts_all_plans():
    plans = parse_outline_plans(_SAMPLE_OUTLINE)
    assert len(plans) == 3
    assert plans[0].number == "01"
    assert plans[0].name == "project-setup"
    assert plans[0].filename == "01-project-setup.md"
    assert plans[1].number == "02"
    assert plans[1].name == "auth-flow"
    assert plans[2].number == "03"


def test_parse_outline_plans_deduplicates_table_and_header_matches():
    plans = parse_outline_plans(_SAMPLE_OUTLINE)
    names = [p.filename for p in plans]
    assert len(names) == len(set(names))


def test_parse_outline_plans_returns_empty_on_empty_input():
    assert parse_outline_plans("") == ()


def test_parse_outline_plans_sorted_by_number():
    reversed_outline = """\
| 1 | 03-z.md | z | 1 | - |
| 2 | 01-a.md | a | 1 | - |

## 01-a.md 상세
## 03-z.md 상세
"""
    plans = parse_outline_plans(reversed_outline)
    assert plans[0].number == "01"
    assert plans[1].number == "03"


def test_build_detail_dispatches_creates_one_per_plan():
    from cowork_pilot.planning.outline import build_detail_dispatches
    from cowork_pilot.planning.models import OutlinePlan, PlanningStage

    plans = (
        OutlinePlan(number="01", name="project-setup", filename="01-project-setup.md"),
        OutlinePlan(number="02", name="auth-flow", filename="02-auth-flow.md"),
    )
    dispatches = build_detail_dispatches(plans, start_order=20)
    assert len(dispatches) == 2
    assert all(d.stage is PlanningStage.EXEC_PLAN_DETAIL for d in dispatches)
    assert dispatches[0].substage == "01-project-setup"
    assert dispatches[0].order == 20
    assert dispatches[1].substage == "02-auth-flow"
    assert dispatches[1].order == 21


def test_parse_skeleton_features_extracts_ordered_features():
    from cowork_pilot.planning.outline import parse_skeleton_features

    skeleton = """\
# Exec-Plan Skeleton

## 실행 순서

| # | Feature | 의존성 |
|---|---------|--------|
| 1 | auth | 없음 |
| 2 | user-profile | auth |
| 3 | notifications | auth, user-profile |

## 의존관계 요약
auth → user-profile → notifications
"""
    features = parse_skeleton_features(skeleton)
    assert len(features) == 3
    assert features[0] == "auth"
    assert features[1] == "user-profile"
    assert features[2] == "notifications"


def test_parse_skeleton_features_returns_empty_on_no_table():
    from cowork_pilot.planning.outline import parse_skeleton_features
    assert parse_skeleton_features("no table here") == ()


def test_build_feature_outline_dispatches_creates_one_per_feature():
    from cowork_pilot.planning.outline import build_feature_outline_dispatches
    from cowork_pilot.planning.models import PlanningStage

    features = ("auth", "user-profile", "notifications")
    dispatches = build_feature_outline_dispatches(features, start_order=15)
    assert len(dispatches) == 3
    assert all(d.stage is PlanningStage.EXEC_PLAN_FEATURE_OUTLINE for d in dispatches)
    assert dispatches[0].substage == "auth"
    assert dispatches[0].order == 15
    assert dispatches[1].substage == "user-profile"
    assert dispatches[2].substage == "notifications"


def test_merge_feature_outlines_produces_numbered_outline(tmp_path):
    from cowork_pilot.planning.outline import merge_feature_outlines

    skeleton = """\
| # | Feature | 의존성 |
|---|---------|--------|
| 1 | auth | 없음 |
| 2 | data-layer | auth |
"""
    (tmp_path / "exec-plan-skeleton.md").write_text(skeleton, encoding="utf-8")

    outlines_dir = tmp_path / "feature-outlines"
    outlines_dir.mkdir()
    (outlines_dir / "auth.md").write_text(
        "## auth\n\n### Chunk 1: Login\n- Completion Criteria:\n  - [ ] Login works\n- Tasks:\n  - Task 1: Build form\n",
        encoding="utf-8",
    )
    (outlines_dir / "data-layer.md").write_text(
        "## data-layer\n\n### Chunk 1: Schema\n- Completion Criteria:\n  - [ ] Tables created\n- Tasks:\n  - Task 1: Define schema\n",
        encoding="utf-8",
    )

    result = merge_feature_outlines(run_dir=tmp_path)
    assert result is not None
    content = result.read_text(encoding="utf-8")

    # Check numbering
    assert "01-auth.md" in content
    assert "02-data-layer.md" in content
    # Check feature content is included
    assert "Login" in content
    assert "Schema" in content


def test_merge_feature_outlines_skips_missing_features(tmp_path):
    from cowork_pilot.planning.outline import merge_feature_outlines

    skeleton = "| 1 | auth | - |\n| 2 | missing-feature | - |"
    (tmp_path / "exec-plan-skeleton.md").write_text(skeleton, encoding="utf-8")

    outlines_dir = tmp_path / "feature-outlines"
    outlines_dir.mkdir()
    (outlines_dir / "auth.md").write_text("## auth\n### Chunk 1: Login\n...\n", encoding="utf-8")
    # missing-feature.md intentionally not created

    result = merge_feature_outlines(run_dir=tmp_path)
    content = result.read_text(encoding="utf-8")
    assert "01-auth.md" in content
    # missing feature gets a placeholder warning
    assert "02-missing-feature.md" in content
    assert "WARNING" in content or "missing" in content.lower()
