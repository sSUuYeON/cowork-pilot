"""Phase 1 quality gate — split into shared / features / overviews.

This module provides :func:`evaluate_phase1`, the new Phase 1 validator
introduced by the `_overview.md` optional refactor plan. Unlike the legacy
:mod:`cowork_pilot.quality_gate` this validator:

* treats ``shared.md`` and feature files as *hard required*;
* treats ``_overview.md`` as *warning only*;
* consults the Domain Overview Decisions table (parsed by
  :mod:`cowork_pilot.orchestrator.analysis_report`) as the single source
  of truth for "is an overview expected for this domain?";
* falls back to a tolerant legacy mode when the decision table is
  missing, so that projects produced before the contract do not
  hard-fail on re-runs.

Assumed layout (resolved relative to ``project_root``)::

    project_root/
      analysis-report.md
      domain-extracts/
        shared.md
        <domain>/<feature>.md
        <domain>/_overview.md   # optional

Call sites that operate on the traditional ``docs/generated`` layout
must pass ``project_root = project_dir / "docs" / "generated"`` (see
:mod:`cowork_pilot.docs_orchestrator`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cowork_pilot.orchestrator.analysis_report import (
    OverviewDecision,
    load_overview_decisions_tolerant,
)
from cowork_pilot.orchestrator.feature_detector import detect_features


OVERVIEW_MIN_LINES = 10
"""An ``_overview.md`` shorter than this is considered ceremonial (warning)."""


@dataclass
class Phase1Result:
    """Result of :func:`evaluate_phase1`.

    * ``ok`` — ``True`` iff there were no hard failures.
    * ``hard_failures`` — halting problems (missing report, missing shared,
      missing feature files). The caller must stop the pipeline on any
      non-empty value.
    * ``warnings`` — non-halting advisories (missing or ceremonial
      ``_overview.md`` for a domain that declared ``overview_needed=yes``,
      stray short overviews for domains that declared ``no``, etc.).
    """

    ok: bool
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _overview_line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _evaluate_overview_decisions(
    decisions: dict[str, OverviewDecision],
    extracts: Path,
    project_root: Path,
) -> list[str]:
    """Return the warning list produced by walking the decision table.

    ``decisions`` is the parsed Domain Overview Decisions table. The
    function only produces *warnings* — missing or ceremonial overview
    files must never hard-fail the gate (invariant 3 of the plan).
    """
    warnings: list[str] = []
    for domain, decision in decisions.items():
        overview_path = extracts / domain / "_overview.md"
        if decision.overview_needed:
            if not overview_path.exists():
                warnings.append(
                    f"domain {domain!r} has overview_needed=yes but "
                    f"{overview_path.relative_to(project_root)} does not exist"
                )
                continue
            line_count = _overview_line_count(overview_path)
            if line_count < OVERVIEW_MIN_LINES:
                warnings.append(
                    f"domain {domain!r} _overview.md has only {line_count} lines "
                    f"(< {OVERVIEW_MIN_LINES}); looks ceremonial"
                )
        else:
            # overview_needed=no: silent unless a short file exists anyway.
            if not overview_path.exists():
                continue
            line_count = _overview_line_count(overview_path)
            if line_count < OVERVIEW_MIN_LINES:
                warnings.append(
                    f"domain {domain!r} has overview_needed=no but a short "
                    f"_overview.md exists ({line_count} lines); consider removing"
                )
    return warnings


def evaluate_phase1(project_root: Path) -> Phase1Result:
    """Evaluate Phase 1 artifacts under *project_root*.

    Hard-fail conditions (set ``ok=False``):
      * ``analysis-report.md`` missing.
      * ``domain-extracts/shared.md`` missing.
      * ``domain-extracts/`` has no feature files at all.

    Warning conditions (``ok`` stays ``True``):
      * Decision table exists, a domain declares ``overview_needed=yes``,
        but the overview file does not exist.
      * An overview file exists but has fewer than
        :data:`OVERVIEW_MIN_LINES` lines (ceremonial).

    Legacy mode: if the Domain Overview Decisions table cannot be parsed
    (missing or malformed), the function silently skips *all* overview
    checks. This is the migration branch — legacy projects produced
    before the contract must not hard-fail and must not be spammed with
    overview warnings.
    """
    result = Phase1Result(ok=True)

    report_path = project_root / "analysis-report.md"
    extracts = project_root / "domain-extracts"

    if not report_path.exists():
        result.hard_failures.append("analysis-report.md is missing")

    shared = extracts / "shared.md"
    if not shared.exists():
        result.hard_failures.append(
            "domain-extracts/shared.md is missing (hard fail)"
        )

    features = detect_features(extracts) if extracts.exists() else []
    if not features:
        result.hard_failures.append(
            "no feature files were produced under domain-extracts/"
        )

    report_text = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    decisions = load_overview_decisions_tolerant(report_text)

    if decisions is not None:
        result.warnings.extend(
            _evaluate_overview_decisions(decisions, extracts, project_root)
        )
    # else: legacy / migration mode — no overview warnings.

    result.ok = not result.hard_failures
    return result
