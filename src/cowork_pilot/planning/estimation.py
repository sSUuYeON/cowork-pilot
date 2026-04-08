from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SessionEstimate:
    total_sessions: int
    skeleton_sessions: int
    feature_outline_sessions: int
    detail_sessions: int
    stage_sessions: int
    time_range_minutes: tuple[int, int]
    breakdown: dict[str, int]


def estimate_sessions(
    *,
    mode: str,
    size_class: str,
    feature_count: int,
    domain_count: int,
    minutes_per_session: tuple[int, int] = (3, 8),
) -> SessionEstimate:
    """Estimate total sessions and time for planning pipeline."""
    # Base stage sessions (classification through plan review)
    base = _base_stage_count(mode, size_class, domain_count)

    # Skeleton: always 1 session (feature list + ordering only)
    skeleton_sessions = 1

    # Feature outline: 1 session per feature (chunk decomposition per feature)
    feature_outline_sessions = max(1, feature_count)

    # Detail: 1 session per feature (session prompt filling)
    detail_sessions = max(1, feature_count)

    total = base + skeleton_sessions + feature_outline_sessions + detail_sessions

    return SessionEstimate(
        total_sessions=total,
        skeleton_sessions=skeleton_sessions,
        feature_outline_sessions=feature_outline_sessions,
        detail_sessions=detail_sessions,
        stage_sessions=base,
        time_range_minutes=(total * minutes_per_session[0], total * minutes_per_session[1]),
        breakdown={
            "base_stages": base,
            "skeleton": skeleton_sessions,
            "feature_outline": feature_outline_sessions,
            "detail": detail_sessions,
        },
    )


def _base_stage_count(mode: str, size_class: str, domain_count: int) -> int:
    """Count non-exec-plan AI stages based on mode and size."""
    count = 0
    # Classification substages
    if size_class in ("medium", "large"):
        count += 2  # input-audit + synthesis
    else:
        count += 1

    if mode == "brownfield":
        # Extraction slices + synthesis + gap
        slices = {"small": 1, "medium": 2, "large": 3}.get(size_class, 1)
        count += slices + 2  # slices + observation_synthesis + gap_synthesis
        count += 1  # core_docs_presence_review

    # Completeness review substages
    if size_class == "large":
        count += 3
    elif size_class == "medium":
        count += 2
    else:
        count += 1

    # Scope structuring
    if size_class == "medium":
        count += 2
    else:
        count += 1

    # Plan review (always 2 substages)
    count += 2

    return count
