from __future__ import annotations

import re
from pathlib import Path

from cowork_pilot.auto_answer_context import resolve_phase2_step_inputs
from cowork_pilot.orchestrator_prompts import (
    build_session_prompt,
    compute_available_extracts,
)


def _parse_read_files(prompt: str) -> list[Path]:
    match = re.search(r"읽어야 할 파일:\s*\n((?:\s*-\s*.+\n?)+)", prompt)
    if not match:
        return []
    block = match.group(1)
    paths: list[Path] = []
    for line in block.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            paths.append(Path(stripped[2:].strip()))
    return paths


def _seed_phase2_project(tmp_path: Path) -> Path:
    generated = tmp_path / "docs" / "generated"
    (generated / "references").mkdir(parents=True, exist_ok=True)
    (generated / "domain-extracts" / "entry").mkdir(parents=True, exist_ok=True)
    (generated / "domain-extracts" / "host").mkdir(parents=True, exist_ok=True)
    (generated / "gap-reports").mkdir(parents=True, exist_ok=True)

    (generated / "references" / "checklists.md").write_text("checklist\n", encoding="utf-8")
    (generated / "analysis-report.md").write_text("report\n", encoding="utf-8")
    (generated / "domain-extracts" / "shared.md").write_text("shared\n", encoding="utf-8")
    (generated / "domain-extracts" / "entry" / "join-code.md").write_text("join\n", encoding="utf-8")
    (generated / "domain-extracts" / "entry" / "share-link-qr.md").write_text("qr\n", encoding="utf-8")
    (generated / "domain-extracts" / "host" / "_overview.md").write_text("overview\n", encoding="utf-8")
    return generated


def test_resolve_phase2_step_inputs_read_set_matches_template(tmp_path: Path) -> None:
    _seed_phase2_project(tmp_path)
    extracts = compute_available_extracts(
        tmp_path / "docs" / "generated" / "domain-extracts",
    )
    inputs = resolve_phase2_step_inputs(
        project_dir=tmp_path,
        step_name="phase_2:entry:join-code",
        phase_template="phase2_manual",
        bundle=[("entry", "join-code")],
        extracts=extracts,
        overview_reasons={"host": "shared lifecycle"},
    )

    prompt = build_session_prompt(inputs.phase_template, **inputs.render_kwargs)
    read_files = _parse_read_files(prompt)
    prompt_expected = list(inputs.required_inputs) + [
        path for path in inputs.optional_inputs if path.name == "_overview.md"
    ]

    assert set(read_files) == set(prompt_expected)


def test_resolve_phase2_step_inputs_optional_gap_report(tmp_path: Path) -> None:
    generated = _seed_phase2_project(tmp_path)
    gap_report = generated / "gap-reports" / "entry--join-code.md"
    gap_report.write_text("existing gap\n", encoding="utf-8")

    extracts = compute_available_extracts(
        tmp_path / "docs" / "generated" / "domain-extracts",
    )
    inputs = resolve_phase2_step_inputs(
        project_dir=tmp_path,
        step_name="phase_2:entry:join-code",
        phase_template="phase2_manual",
        bundle=[("entry", "join-code")],
        extracts=extracts,
        overview_reasons={},
    )

    assert gap_report in inputs.optional_inputs


def test_resolve_phase2_step_inputs_bundle_multiple_features(tmp_path: Path) -> None:
    _seed_phase2_project(tmp_path)
    extracts = compute_available_extracts(
        tmp_path / "docs" / "generated" / "domain-extracts",
    )
    inputs = resolve_phase2_step_inputs(
        project_dir=tmp_path,
        step_name="phase_2:entry:join-code+entry:share-link-qr",
        phase_template="phase2_manual",
        bundle=[("entry", "join-code"), ("entry", "share-link-qr")],
        extracts=extracts,
        overview_reasons={},
    )

    assert (
        tmp_path / "docs" / "generated" / "domain-extracts" / "entry" / "join-code.md"
    ) in inputs.required_inputs
    assert (
        tmp_path / "docs" / "generated" / "domain-extracts" / "entry" / "share-link-qr.md"
    ) in inputs.required_inputs
