"""Parse a project brief Markdown file into structured dataclasses.

The brief format is defined in docs/specs/2026-03-25-meta-agent-design.md §3.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class Page:
    name: str
    description: str = ""
    key_elements: list[str] = field(default_factory=list)


@dataclass
class Entity:
    name: str
    fields: list[str] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)


@dataclass
class ArchDecision:
    decision: str
    rationale: str = ""


@dataclass
class Reference:
    name: str
    url: str = ""
    notes: str = ""


@dataclass
class Brief:
    """Structured representation of a project brief."""
    # Overview (required)
    name: str = ""
    description: str = ""
    type: str = ""

    # Tech Stack (required: language, framework)
    language: str = ""
    framework: str = ""
    database: str = ""
    styling: str = ""
    package_manager: str = ""

    # Pages / Features
    pages: list[Page] = field(default_factory=list)

    # Data Model
    entities: list[Entity] = field(default_factory=list)

    # Architecture Decisions
    decisions: list[ArchDecision] = field(default_factory=list)

    # Constraints
    auth: str = ""
    deployment: str = ""
    performance: str = ""
    accessibility: str = ""
    other_constraints: list[str] = field(default_factory=list)

    # Non-Goals
    non_goals: list[str] = field(default_factory=list)

    # References
    references: list[Reference] = field(default_factory=list)

    def domain_doc_names(self) -> list[str]:
        """Return list of domain-specific doc filenames based on constraints."""
        docs: list[str] = []
        if self.auth:
            docs.append("auth.md")
        if self.deployment:
            docs.append("deployment.md")
        return docs


# ── Parsing ──────────────────────────────────────────────────────────

_RE_KV = re.compile(r'^- (\w[\w_]*): (.*)$')
_RE_KV_CHILD = re.compile(r'^(\w[\w_]*): (.*)$')  # For indented child properties
_RE_QUOTED = re.compile(r'^"(.*)"$|^\'(.*)\'$')
_RE_LIST_ITEM = re.compile(r'^- "([^"]*)"$|^- \'([^\']*)\'$|^- (.+)$')


def _unquote(val: str) -> str:
    """Remove surrounding quotes from a value string."""
    val = val.strip()
    m = _RE_QUOTED.match(val)
    if m:
        return m.group(1) if m.group(1) is not None else m.group(2)
    return val


def _parse_list_value(val: str) -> list[str]:
    """Parse a YAML-like inline list: ["a", "b", "c"]."""
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        items = []
        for item in re.split(r',\s*', inner):
            items.append(_unquote(item.strip()))
        return items
    return []


def _find_section(lines: list[str], heading: str) -> list[str]:
    """Extract lines under a specific ## heading until the next ## or EOF."""
    body: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## ") and stripped != heading:
                break
            body.append(line)
    return body


def _parse_overview(lines: list[str]) -> dict[str, str]:
    body = _find_section(lines, "## 1. Overview")
    result: dict[str, str] = {}
    for line in body:
        m = _RE_KV.match(line.strip())
        if m:
            result[m.group(1)] = _unquote(m.group(2))
    return result


def _parse_tech_stack(lines: list[str]) -> dict[str, str]:
    body = _find_section(lines, "## 2. Tech Stack")
    result: dict[str, str] = {}
    for line in body:
        m = _RE_KV.match(line.strip())
        if m:
            result[m.group(1)] = _unquote(m.group(2))
    return result


def _parse_pages(lines: list[str]) -> list[Page]:
    body = _find_section(lines, "## 3. Pages / Features")
    pages: list[Page] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        is_child = (line != stripped) and not stripped.startswith("- ")

        # Try parent pattern first (with dash)
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "page":
                if current is not None:
                    pages.append(Page(**current))
                current = {"name": _unquote(val), "description": "", "key_elements": []}
        # Try child pattern (without dash) if indented
        elif is_child:
            m = _RE_KV_CHILD.match(stripped)
            if m and current is not None:
                key, val = m.group(1), m.group(2)
                if key == "description":
                    current["description"] = _unquote(val)
                elif key == "key_elements":
                    current["key_elements"] = _parse_list_value(val)

    if current is not None:
        pages.append(Page(**current))
    return pages


def _parse_entities(lines: list[str]) -> list[Entity]:
    body = _find_section(lines, "## 4. Data Model")
    entities: list[Entity] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        is_child = (line != stripped) and not stripped.startswith("- ")

        # Try parent pattern first (with dash)
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "entity":
                if current is not None:
                    entities.append(Entity(**current))
                current = {"name": _unquote(val), "fields": [], "relations": []}
        # Try child pattern (without dash) if indented
        elif is_child:
            m = _RE_KV_CHILD.match(stripped)
            if m and current is not None:
                key, val = m.group(1), m.group(2)
                if key == "fields":
                    current["fields"] = _parse_list_value(val)
                elif key == "relations":
                    current["relations"] = _parse_list_value(val)

    if current is not None:
        entities.append(Entity(**current))
    return entities


def _parse_decisions(lines: list[str]) -> list[ArchDecision]:
    body = _find_section(lines, "## 5. Architecture Decisions")
    decisions: list[ArchDecision] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        is_child = (line != stripped) and not stripped.startswith("- ")

        # Try parent pattern first (with dash)
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "decision":
                if current is not None:
                    decisions.append(ArchDecision(**current))
                current = {"decision": _unquote(val), "rationale": ""}
        # Try child pattern (without dash) if indented
        elif is_child:
            m = _RE_KV_CHILD.match(stripped)
            if m and current is not None and m.group(1) == "rationale":
                current["rationale"] = _unquote(m.group(2))

    if current is not None:
        decisions.append(ArchDecision(**current))
    return decisions


def _parse_constraints(lines: list[str]) -> dict[str, str | list[str]]:
    body = _find_section(lines, "## 6. Constraints")
    result: dict[str, str | list[str]] = {}
    for line in body:
        m = _RE_KV.match(line.strip())
        if m:
            key, val = m.group(1), m.group(2)
            if key == "other":
                result[key] = _parse_list_value(val)
            else:
                result[key] = _unquote(val)
    return result


def _parse_non_goals(lines: list[str]) -> list[str]:
    body = _find_section(lines, "## 7. Non-Goals")
    goals: list[str] = []
    for line in body:
        stripped = line.strip()
        # Match: - "text" or - 'text' or - text
        if stripped.startswith("- "):
            val = stripped[2:].strip()
            goals.append(_unquote(val))
    return goals


def _parse_references(lines: list[str]) -> list[Reference]:
    body = _find_section(lines, "## 8. References")
    refs: list[Reference] = []
    current: dict | None = None

    for line in body:
        stripped = line.strip()
        is_child = (line != stripped) and not stripped.startswith("- ")

        # Try parent pattern first (with dash)
        m = _RE_KV.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if key == "ref":
                if current is not None:
                    refs.append(Reference(**current))
                current = {"name": _unquote(val), "url": "", "notes": ""}
        # Try child pattern (without dash) if indented
        elif is_child:
            m = _RE_KV_CHILD.match(stripped)
            if m and current is not None:
                key, val = m.group(1), m.group(2)
                if key == "url":
                    current["url"] = _unquote(val)
                elif key == "notes":
                    current["notes"] = _unquote(val)

    if current is not None:
        refs.append(Reference(**current))
    return refs


# ── Public API ───────────────────────────────────────────────────────

REQUIRED_FIELDS = ["name", "description", "type", "language", "framework"]


def parse_brief(path: Path) -> Brief:
    """Parse a project brief Markdown file into a Brief dataclass.

    Raises ValueError if required fields are missing.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    overview = _parse_overview(lines)
    tech = _parse_tech_stack(lines)
    constraints = _parse_constraints(lines)

    # Validate required fields
    all_fields = {**overview, **tech}
    for req in REQUIRED_FIELDS:
        if not all_fields.get(req):
            raise ValueError(f"Required field missing or empty: {req}")

    return Brief(
        name=overview.get("name", ""),
        description=overview.get("description", ""),
        type=overview.get("type", ""),
        language=tech.get("language", ""),
        framework=tech.get("framework", ""),
        database=tech.get("database", ""),
        styling=tech.get("styling", ""),
        package_manager=tech.get("package_manager", ""),
        pages=_parse_pages(lines),
        entities=_parse_entities(lines),
        decisions=_parse_decisions(lines),
        auth=str(constraints.get("auth", "")),
        deployment=str(constraints.get("deployment", "")),
        performance=str(constraints.get("performance", "")),
        accessibility=str(constraints.get("accessibility", "")),
        other_constraints=list(constraints.get("other", [])),
        non_goals=_parse_non_goals(lines),
        references=_parse_references(lines),
    )
