from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from collections.abc import Mapping


@dataclass(frozen=True)
class ReviewIssue:
    category: str
    severity: str
    description: str
    evidence: str


@dataclass(frozen=True)
class ReviewVerdict:
    coverage_pass: bool
    sizing_pass: bool
    executionability_pass: bool
    overdesign_pass: bool
    issues: tuple[ReviewIssue, ...]
    gap_artifacts_consumed: tuple[str, ...]


def run_plan_review(
    packed_plans: Sequence[str] | None = None,
    *,
    gap_artifacts: Mapping[str, Sequence[str]] | None = None,
) -> ReviewVerdict:
    plans = tuple(packed_plans or ())
    artifacts = gap_artifacts or {}
    issues: list[ReviewIssue] = []

    coverage_pass = True
    for artifact_name, gap_items in artifacts.items():
        for gap_item in gap_items:
            if not any(gap_item in plan for plan in plans):
                coverage_pass = False
                issues.append(
                    ReviewIssue(
                        category="coverage",
                        severity="blocking",
                        description=f"missing plan coverage for {gap_item}",
                        evidence=artifact_name,
                    )
                )

    sizing_pass = len(plans) <= 8
    if not sizing_pass:
        issues.append(
            ReviewIssue(
                category="sizing",
                severity="warning",
                description="plan decomposition is too wide for the current scope",
                evidence=str(len(plans)),
            )
        )

    executionability_pass = all(plan.strip() for plan in plans)
    if not executionability_pass:
        issues.append(
            ReviewIssue(
                category="executionability",
                severity="blocking",
                description="one or more plan items are empty",
                evidence="packed_plans",
            )
        )

    overdesign_pass = True
    for plan in plans:
        if "undocumented-screen" in plan or "undocumented screen" in plan:
            overdesign_pass = False
            issues.append(
                ReviewIssue(
                    category="overdesign",
                    severity="warning",
                    description="plan introduces an undocumented surface",
                    evidence=plan,
                )
            )

    return ReviewVerdict(
        coverage_pass=coverage_pass,
        sizing_pass=sizing_pass,
        executionability_pass=executionability_pass,
        overdesign_pass=overdesign_pass,
        issues=tuple(issues),
        gap_artifacts_consumed=tuple(artifacts.keys()),
    )


def should_rollback(verdict: ReviewVerdict) -> bool:
    """Return True if verdict contains blocking issues that warrant rollback."""
    return any(issue.severity == "blocking" for issue in verdict.issues)


def parse_plan_review(path: "Path") -> ReviewVerdict:
    """Parse AI-generated plan-review.md into a ReviewVerdict.

    Rollback is determined deterministically from parsed issues.
    """
    from pathlib import Path as _Path
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")

    raw_issues = data.get("issues", [])
    issues: list[ReviewIssue] = []
    for raw in raw_issues:
        if isinstance(raw, dict):
            issues.append(ReviewIssue(
                category=str(raw.get("category", "unknown")),
                severity=str(raw.get("severity", "warning")),
                description=str(raw.get("description", "")),
                evidence="plan-review.md",
            ))

    has_blocking = any(i.severity == "blocking" for i in issues)
    coverage_status = str(data.get("coverage_status", "unknown"))

    return ReviewVerdict(
        coverage_pass=(coverage_status in ("full", "complete") and not has_blocking),
        sizing_pass=not any(i.category == "sizing" and i.severity == "blocking" for i in issues),
        executionability_pass=not any(i.category == "executionability" and i.severity == "blocking" for i in issues),
        overdesign_pass=not any(i.category == "overdesign" and i.severity == "blocking" for i in issues),
        issues=tuple(issues),
        gap_artifacts_consumed=(),
    )
