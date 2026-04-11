from __future__ import annotations

import re
from dataclasses import dataclass


class MissingDecisionTableError(ValueError):
    """Raised when analysis-report.md has no Domain Overview Decisions section."""


class MalformedDecisionTableError(ValueError):
    """Raised when the table exists but does not match the required format."""


@dataclass(frozen=True)
class OverviewDecision:
    domain: str
    overview_needed: bool
    reason: str


_HEADING_RE = re.compile(r"^##\s+Domain Overview Decisions\s*$", re.MULTILINE)


def parse_overview_decisions(report_text: str) -> dict[str, OverviewDecision]:
    match = _HEADING_RE.search(report_text)
    if not match:
        raise MissingDecisionTableError(
            "analysis-report.md is missing the '## Domain Overview Decisions' section"
        )

    # Grab everything after the heading until the next '## ' or end of file.
    tail = report_text[match.end():]
    next_section = re.search(r"^##\s+", tail, re.MULTILINE)
    body = tail[: next_section.start()] if next_section else tail

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # Expect: header row, separator row, then data rows.
    table_rows = [ln for ln in lines if ln.startswith("|")]
    if len(table_rows) < 3:
        raise MalformedDecisionTableError(
            "Domain Overview Decisions table must have a header, separator, and at least one data row"
        )

    header_cells = [c.strip() for c in table_rows[0].strip("|").split("|")]
    if header_cells != ["domain", "overview_needed", "reason"]:
        raise MalformedDecisionTableError(
            f"unexpected column order: {header_cells!r}, must be ['domain', 'overview_needed', 'reason']"
        )

    decisions: dict[str, OverviewDecision] = {}
    for row in table_rows[2:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) != 3:
            raise MalformedDecisionTableError(f"row does not have 3 cells: {row!r}")
        domain, needed, reason = cells
        if needed not in ("yes", "no"):
            raise MalformedDecisionTableError(
                f"overview_needed must be 'yes' or 'no', got {needed!r} for domain {domain!r}"
            )
        if not reason:
            raise MalformedDecisionTableError(f"reason is empty for domain {domain!r}")
        decisions[domain] = OverviewDecision(
            domain=domain,
            overview_needed=(needed == "yes"),
            reason=reason,
        )
    return decisions


def load_overview_decisions_tolerant(
    report_text: str,
) -> dict[str, OverviewDecision] | None:
    """Return decisions if the table exists and is valid; return None otherwise.

    Used by the quality gate in migration mode: legacy projects that predate
    the decision-table contract should not hard-fail.
    """
    try:
        return parse_overview_decisions(report_text)
    except (MissingDecisionTableError, MalformedDecisionTableError):
        return None
