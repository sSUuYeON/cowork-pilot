from __future__ import annotations

from collections.abc import Sequence


def pack_plans(work_items: Sequence[str] | None = None) -> list[str]:
    if not work_items:
        return []
    return [f"chunk:{item}" for item in work_items]


def parse_plan_packing(path: "Path") -> list[dict]:
    """Parse AI-generated plan-packing.md into a list of plan dicts."""
    from pathlib import Path as _Path
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    plans = data.get("plans", [])
    if not isinstance(plans, list):
        raise ValueError("plans must be an array")
    return plans
