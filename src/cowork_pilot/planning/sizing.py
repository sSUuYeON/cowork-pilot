from __future__ import annotations

from collections.abc import Mapping, Sequence


def size_work_items(scope_map: Mapping[str, Sequence[str]] | None = None) -> list[str]:
    if not scope_map:
        return ["baseline-scope"]

    work_items: list[str] = []
    for group_name, items in scope_map.items():
        for item in items:
            work_items.append(f"{group_name}:{item}")
    return work_items


def parse_work_sizing(path: "Path") -> list[dict]:
    """Parse AI-generated work-sizing.md into a list of work item dicts."""
    from pathlib import Path as _Path
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    items = data.get("work_items", [])
    if not isinstance(items, list):
        raise ValueError("work_items must be an array")
    return items
