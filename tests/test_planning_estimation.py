# tests/test_planning_estimation.py

from cowork_pilot.planning.estimation import estimate_sessions, SessionEstimate


def test_estimate_small_greenfield():
    est = estimate_sessions(
        mode="greenfield",
        size_class="small",
        feature_count=5,
        domain_count=2,
    )
    assert est.total_sessions > 0
    assert est.time_range_minutes[0] < est.time_range_minutes[1]


def test_estimate_large_brownfield_more_sessions_than_small():
    small = estimate_sessions(mode="greenfield", size_class="small", feature_count=3, domain_count=1)
    large = estimate_sessions(mode="brownfield", size_class="large", feature_count=15, domain_count=4)
    assert large.total_sessions > small.total_sessions


def test_estimate_includes_skeleton_feature_outline_and_detail_sessions():
    est = estimate_sessions(mode="greenfield", size_class="medium", feature_count=6, domain_count=2)
    assert est.skeleton_sessions == 1
    assert est.feature_outline_sessions == 6  # 1 per feature
    assert est.detail_sessions == 6  # 1 per feature
