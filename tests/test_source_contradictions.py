from __future__ import annotations

import json
from pathlib import Path

from cowork_pilot.source_contradictions import (
    contradiction_index_path,
    contradiction_item_json_path,
    contradiction_item_md_path,
    detect_source_contradictions,
    load_contradiction_report,
    write_contradiction_report,
)


def _seed_extracts(tmp_path: Path) -> Path:
    generated = tmp_path / "docs" / "generated"
    extracts = generated / "domain-extracts"
    host_dir = extracts / "host"
    host_dir.mkdir(parents=True, exist_ok=True)
    (extracts / "shared.md").write_text(
        "\n".join(
            [
                "<!-- SOURCE: shared.md#6.2 기능 목록 -->",
                "- 잠금 전까지 질문/보기 텍스트 편집",
                "<!-- SOURCE: shared.md#8.6 인터랙션 -->",
                "- draft는 생성 직후 1회 편집 허용",
            ]
        ),
        encoding="utf-8",
    )
    (host_dir / "edit-poll.md").write_text(
        "\n".join(
            [
                "<!-- SOURCE: edit-poll.md#9.4 보안 규칙 -->",
                "- onlyAllowedFieldsChanged(['status', 'closedAt'])",
                "<!-- SOURCE: edit-poll.md#6.2 기능 목록 -->",
                "- 질문/보기 텍스트 편집",
            ]
        ),
        encoding="utf-8",
    )
    return generated


def test_detect_source_contradictions_finds_edit_poll_conflicts(tmp_path: Path) -> None:
    generated = _seed_extracts(tmp_path)

    report = detect_source_contradictions(generated)

    ids = {item.contradiction_id for item in report.blocking}
    assert "host--edit-poll--edit_window" in ids
    assert "host--edit-poll--editable_fields" in ids


def test_write_and_load_contradiction_report_uses_index_json(tmp_path: Path) -> None:
    generated = _seed_extracts(tmp_path)
    report = detect_source_contradictions(generated)

    write_contradiction_report(generated, report)

    index_data = json.loads(contradiction_index_path(generated).read_text(encoding="utf-8"))
    assert len(index_data["blocking"]) == len(report.blocking)

    item_id = report.blocking[0].contradiction_id
    assert contradiction_item_json_path(generated, item_id).exists()
    assert contradiction_item_md_path(generated, item_id).exists()

    reloaded = load_contradiction_report(generated)
    assert [item.contradiction_id for item in reloaded.blocking] == [
        item.contradiction_id for item in report.blocking
    ]
