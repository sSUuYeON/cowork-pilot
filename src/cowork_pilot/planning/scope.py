from __future__ import annotations

from cowork_pilot.planning.models import ClassificationSnapshot


def build_scope_map(
    core_docs: list[str] | None = None,
    adaptive_docs: list[str] | None = None,
    snapshot: ClassificationSnapshot | None = None,
) -> dict[str, list[str]]:
    base_scope = list(core_docs or []) + list(adaptive_docs or [])
    if snapshot is not None and snapshot.project_mode.value == "brownfield":
        base_scope.append("brownfield-gap-analysis")
    return {
        "planning-scope": base_scope or ["baseline-scope"],
    }


def parse_scope_map(path: "Path") -> dict[str, list[str]]:
    """Parse AI-generated scope-map.md into domain -> feature list mapping."""
    from pathlib import Path as _Path
    from cowork_pilot.planning.completion_verifier import extract_json_block

    content = path.read_text(encoding="utf-8")
    data = extract_json_block(content)
    if data is None or not isinstance(data, dict):
        raise ValueError(f"No valid JSON block in {path}")
    scope: dict[str, list[str]] = {}
    for feature in data.get("features", []):
        if isinstance(feature, dict):
            domain = str(feature.get("domain", "unknown"))
            name = str(feature.get("name", ""))
            scope.setdefault(domain, []).append(name)
        elif isinstance(feature, str):
            scope.setdefault("default", []).append(feature)
    # Ensure all domains from the domains list exist even if no features
    for domain in data.get("domains", []):
        scope.setdefault(str(domain), [])
    return scope
