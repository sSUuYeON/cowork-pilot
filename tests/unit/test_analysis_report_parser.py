import pytest

from cowork_pilot.orchestrator.analysis_report import (
    OverviewDecision,
    parse_overview_decisions,
    MissingDecisionTableError,
    MalformedDecisionTableError,
)


def test_parse_basic_table():
    report = """
# Analysis Report

## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | poll lifecycle shared |
| voter | no | self contained |
"""
    decisions = parse_overview_decisions(report)
    assert decisions == {
        "host": OverviewDecision(domain="host", overview_needed=True, reason="poll lifecycle shared"),
        "voter": OverviewDecision(domain="voter", overview_needed=False, reason="self contained"),
    }


def test_missing_section_raises():
    report = "# Analysis Report\n\nNo table here.\n"
    with pytest.raises(MissingDecisionTableError):
        parse_overview_decisions(report)


def test_bad_column_order_raises():
    report = """
## Domain Overview Decisions

| overview_needed | domain | reason |
|---|---|---|
| yes | host | x |
"""
    with pytest.raises(MalformedDecisionTableError):
        parse_overview_decisions(report)


def test_invalid_value_raises():
    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | maybe | x |
"""
    with pytest.raises(MalformedDecisionTableError):
        parse_overview_decisions(report)


def test_empty_reason_raises():
    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes |   |
"""
    with pytest.raises(MalformedDecisionTableError):
        parse_overview_decisions(report)


def test_load_tolerant_returns_none_when_missing():
    from cowork_pilot.orchestrator.analysis_report import load_overview_decisions_tolerant

    report = "# Analysis Report\n\nNo table.\n"
    assert load_overview_decisions_tolerant(report) is None


def test_load_tolerant_returns_decisions_when_present():
    from cowork_pilot.orchestrator.analysis_report import load_overview_decisions_tolerant

    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | because |
"""
    result = load_overview_decisions_tolerant(report)
    assert result is not None
    assert result["host"].overview_needed is True


def test_section_stops_at_next_heading():
    report = """
## Domain Overview Decisions

| domain | overview_needed | reason |
|---|---|---|
| host | yes | a |

## Appendix

| ignored | ignored | ignored |
|---|---|---|
| foo | no | bar |
"""
    decisions = parse_overview_decisions(report)
    assert set(decisions) == {"host"}
