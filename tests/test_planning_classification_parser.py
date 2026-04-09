# tests/test_planning_classification_parser.py
import pytest
from pathlib import Path

from cowork_pilot.planning.classification import parse_classification_report
from cowork_pilot.planning.models import ClassificationSnapshot, ProjectMode, SizeClass


def test_parse_classification_report(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '# Classification\n\n```json\n'
        '{"project_mode":"greenfield","product_type":"spec-driven-product",'
        '"size_class":"medium","core_user_flows":["onboarding","checkout"],'
        '"primary_entities":["user","order"],"risks":["scope creep"]}\n'
        '```\n\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    snapshot = parse_classification_report(tmp_path / "classification-report.md")
    assert snapshot.project_mode is ProjectMode.GREENFIELD
    assert snapshot.size_class is SizeClass.MEDIUM
    assert snapshot.product_type == "spec-driven-product"


def test_parse_classification_report_missing_json_raises(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        "No json here\n<!-- ORCHESTRATOR:DONE -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="JSON"):
        parse_classification_report(tmp_path / "classification-report.md")


def test_parse_classification_report_missing_key_raises(tmp_path: Path):
    (tmp_path / "classification-report.md").write_text(
        '```json\n{"project_mode":"greenfield"}\n```\n<!-- ORCHESTRATOR:DONE -->\n',
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        parse_classification_report(tmp_path / "classification-report.md")
