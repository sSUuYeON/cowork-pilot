# src/cowork_pilot/planning/completion_verifier.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from cowork_pilot.planning.models import PlanningStage
from cowork_pilot.planning.session_profiles import ARTIFACT_OWNERSHIP_TABLE

_DONE_MARKER = "<!-- ORCHESTRATOR:DONE -->"

_FORBIDDEN_SCOPE_DOMAINS = frozenset({
    "agents", "spec_index", "design_guide", "architecture",
    "security", "core_beliefs", "data_model", "spec_documents",
})

from cowork_pilot.planning.prompts import _STAGE_CONTRACTS


def _get_required_keys(stage: PlanningStage) -> tuple[str, ...] | None:
    """Derive required JSON keys from _STAGE_CONTRACTS (single source of truth).

    Returns None if the stage has no required JSON keys (empty json_keys tuple).
    """
    contract = _STAGE_CONTRACTS.get(stage)
    if contract is None or not contract.json_keys:
        return None
    return contract.json_keys


@dataclass(frozen=True)
class CompletionVerdict:
    passed: bool
    missing_artifacts: tuple[str, ...] = ()
    reason: str = ""


def extract_json_block(content: str) -> dict | list | None:
    """Extract the first fenced JSON block from markdown content."""
    pattern = r"```json\s*\n(.*?)\n```"
    match = re.search(pattern, content, re.DOTALL)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def verify_stage_completion(
    stage: PlanningStage,
    *,
    run_dir: Path,
) -> CompletionVerdict:
    ownership = ARTIFACT_OWNERSHIP_TABLE.get(stage)
    if ownership is None:
        return CompletionVerdict(passed=True)

    # 1. File existence
    missing: list[str] = []
    for artifact_rel in ownership.completion_artifacts:
        artifact_path = run_dir / artifact_rel
        if not artifact_path.exists():
            missing.append(artifact_rel)
    if missing:
        return CompletionVerdict(passed=False, missing_artifacts=tuple(missing))

    primary_path = run_dir / ownership.completion_artifacts[0]
    content = primary_path.read_text(encoding="utf-8")

    # 2. Done marker
    if _DONE_MARKER not in content:
        return CompletionVerdict(
            passed=False,
            reason=f"{ownership.completion_artifacts[0]} missing <!-- ORCHESTRATOR:DONE --> marker",
        )

    # 3. JSON block parse
    required_keys = _get_required_keys(stage)
    if required_keys is not None:
        data = extract_json_block(content)
        if data is None:
            return CompletionVerdict(
                passed=False,
                reason=f"{ownership.completion_artifacts[0]} has no parseable JSON block",
            )
        if not isinstance(data, dict):
            return CompletionVerdict(
                passed=False,
                reason=f"{ownership.completion_artifacts[0]} JSON root must be an object",
            )
        missing_keys = [k for k in required_keys if k not in data]
        if missing_keys:
            return CompletionVerdict(
                passed=False,
                reason=f"Missing required JSON keys: {', '.join(missing_keys)}",
            )

        # 4. Stage-specific validation
        if stage is PlanningStage.SCOPE_STRUCTURING:
            return _validate_scope_map(data)

    return CompletionVerdict(passed=True)


def _validate_scope_map(data: dict) -> CompletionVerdict:
    """Reject scope maps that use doc-role names as domains."""
    domains = data.get("domains", [])
    if isinstance(domains, list):
        violations = [d for d in domains if isinstance(d, str) and d.lower() in _FORBIDDEN_SCOPE_DOMAINS]
        if violations:
            return CompletionVerdict(
                passed=False,
                reason=f"scope-map.md uses doc role names as domains: {violations}",
            )
    return CompletionVerdict(passed=True)
