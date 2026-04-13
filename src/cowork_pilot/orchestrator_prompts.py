"""Jinja2 template loader and prompt builder for docs-orchestrator sessions.

Loads .j2 templates from orchestrator_templates/ and renders them with
the provided variables.  Follows the same Jinja2 environment pattern as
scaffolder.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cowork_pilot.orchestrator.analysis_report import (
    load_overview_decisions_tolerant,
)


# ── Phase → template mapping ────────────────────────────────────────

_PHASE_TEMPLATE_MAP: dict[str, str] = {
    "phase1_single": "phase1_single.j2",
    "phase1_domain": "phase1_domain.j2",
    "phase2_auto": "phase2_auto.j2",
    "phase2_manual": "phase2_manual.j2",
    "phase2_conflict_auto": "phase2_conflict_auto.j2",
    "phase2_conflict_manual": "phase2_conflict_manual.j2",
    "phase3_design_docs": "phase3_design_docs.j2",
    "phase3_product_spec": "phase3_product_spec.j2",
    "phase3_architecture": "phase3_architecture.j2",
    "phase3_agents": "phase3_agents.j2",
    "phase4_consistency": "phase4_consistency.j2",
    "phase4_rescore": "phase4_rescore.j2",
    "phase4_quality": "phase4_quality.j2",
    "phase5_outline": "phase5_outline.j2",
    "phase5_detail": "phase5_detail.j2",
}


# ── Available extracts (Chunk 4 · Task 4.1) ─────────────────────────


@dataclass
class AvailableExtracts:
    """Presence map for `domain-extracts/` content used by downstream phases.

    Attributes
    ----------
    shared:
        ``True`` iff ``<extracts_root>/shared.md`` exists.
    overviews:
        Mapping ``domain -> bool`` telling whether
        ``<extracts_root>/<domain>/_overview.md`` exists. Every directory
        under ``<extracts_root>`` (except the reserved ``references`` dir)
        appears as a key, even if the overview file is missing.
    features:
        Mapping ``domain -> [feature_file_name, ...]`` listing every
        ``*.md`` feature file under ``<extracts_root>/<domain>/`` other
        than ``_overview.md``.
    """

    shared: bool = False
    overviews: dict[str, bool] = field(default_factory=dict)
    features: dict[str, list[str]] = field(default_factory=dict)


def compute_available_extracts(extracts_root: Path) -> AvailableExtracts:
    """Scan *extracts_root* and return a presence map of its contents.

    Parameters
    ----------
    extracts_root:
        Absolute path to the ``domain-extracts`` directory of a project.
        May point at a directory that does not exist — in that case an
        empty :class:`AvailableExtracts` is returned.
    """
    info = AvailableExtracts()
    info.shared = (extracts_root / "shared.md").exists()
    if not extracts_root.exists():
        return info
    for domain_dir in sorted(p for p in extracts_root.iterdir() if p.is_dir()):
        if domain_dir.name == "references":
            continue
        info.overviews[domain_dir.name] = (domain_dir / "_overview.md").exists()
        info.features[domain_dir.name] = sorted(
            f.name
            for f in domain_dir.iterdir()
            if f.is_file() and f.suffix == ".md" and f.name != "_overview.md"
        )
    return info


def load_overview_reasons(project_dir: Path) -> dict[str, str]:
    """Return ``{domain: reason}`` from ``analysis-report.md``, tolerant.

    Used as optional context for phase 2 / phase 3 prompts. If the report
    is missing or malformed, an empty mapping is returned — the presence
    data from :func:`compute_available_extracts` remains the single source
    of truth for "does an overview exist?".

    This is the single public helper used by phase2/phase3 render call
    sites to populate the ``overview_reasons`` kwarg explicitly
    (plan 2026-04-12-overview-optional, Chunk 4, Step 5 strict alignment).
    """
    report_path = project_dir / "docs" / "generated" / "analysis-report.md"
    if not report_path.exists():
        return {}
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    decisions = load_overview_decisions_tolerant(text)
    if decisions is None:
        return {}
    return {d.domain: d.reason for d in decisions.values()}


# ── Jinja2 environment ──────────────────────────────────────────────

def _get_jinja_env(template_dir: Path | None = None) -> Environment:
    """Create Jinja2 environment with the orchestrator_templates directory."""
    if template_dir is None:
        template_dir = Path(__file__).parent / "orchestrator_templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        keep_trailing_newline=True,
    )
    return env


# ── Public API ───────────────────────────────────────────────────────

def build_session_prompt(
    phase: str,
    *,
    template_dir: Path | None = None,
    **kwargs: object,
) -> str:
    """Build a session prompt for the given *phase*.

    Parameters
    ----------
    phase:
        One of the keys in ``_PHASE_TEMPLATE_MAP``, e.g. ``"phase1_single"``,
        ``"phase2_auto"``, ``"phase4_consistency"``.
    template_dir:
        Override the template directory (useful for testing).
    **kwargs:
        Template variables — passed directly to ``template.render()``.

    Returns
    -------
    str
        The rendered prompt string.

    Raises
    ------
    ValueError
        If *phase* is not recognised.
    """
    template_name = _PHASE_TEMPLATE_MAP.get(phase)
    if template_name is None:
        raise ValueError(
            f"Unknown phase {phase!r}. "
            f"Valid phases: {sorted(_PHASE_TEMPLATE_MAP)}"
        )

    # No central auto-inject hook. Callers of overview-aware phases
    # (phase2_auto, phase2_manual, phase3_architecture) must pass
    # ``extracts`` and ``overview_reasons`` explicitly — see
    # plan 2026-04-12-overview-optional.md Chunk 4 Step 5.
    env = _get_jinja_env(template_dir)
    template = env.get_template(template_name)
    return template.render(**kwargs)


def get_phase_template_name(phase: str) -> str:
    """Return the .j2 filename for *phase*.

    Raises ValueError if *phase* is not in the map.
    """
    template_name = _PHASE_TEMPLATE_MAP.get(phase)
    if template_name is None:
        raise ValueError(
            f"Unknown phase {phase!r}. "
            f"Valid phases: {sorted(_PHASE_TEMPLATE_MAP)}"
        )
    return template_name


def build_codex_session_prompt(
    phase: str,
    *,
    template_dir: Path | None = None,
    **kwargs: object,
) -> str:
    """Build a Codex-backend session prompt for *phase*.

    Renders ``codex_wrapper.j2`` which includes the canonical base template
    for *phase* followed by ``_includes/codex_runtime_contract.j2``.

    The base template is never modified. The Codex runtime contract is
    appended only through the wrapper.

    Parameters
    ----------
    phase:
        One of the keys in ``_PHASE_TEMPLATE_MAP``.
    template_dir:
        Override the template directory (useful for testing).
    **kwargs:
        Template variables passed to the base template via the wrapper.

    Raises
    ------
    ValueError
        If *phase* is not recognised.
    """
    base_template_name = get_phase_template_name(phase)  # raises ValueError if unknown
    env = _get_jinja_env(template_dir)
    wrapper = env.get_template("codex_wrapper.j2")
    return wrapper.render(base_template_name=base_template_name, **kwargs)


def get_section_keywords(
    output_formats_path: Path,
    project_type: str,
) -> list[str]:
    """Extract section-title keywords from *output-formats.md*.

    Parses ``## `` headers under the *project_type* block and returns a
    de-duplicated list of keywords suitable for Phase 4-1 prompt injection.

    Parameters
    ----------
    output_formats_path:
        Path to the ``output-formats.md`` reference file.
    project_type:
        Project type string, e.g. ``"webapp"``, ``"api"``, ``"cli"``.

    Returns
    -------
    list[str]
        Section title keywords (e.g. ``["데이터", "API", "Data", "Schema",
        "엔티티", "디렉토리", "Directory", "구조", "Structure"]``).
    """
    # Default keywords (always included for cross-referencing)
    default_keywords: list[str] = [
        "데이터",
        "API",
        "Data",
        "Schema",
        "엔티티",
        "디렉토리",
        "Directory",
        "구조",
        "Structure",
    ]

    if not output_formats_path.exists():
        return default_keywords

    text = output_formats_path.read_text(encoding="utf-8")

    # Extract ## headers from the file
    headers = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)

    # Filter headers relevant to the project type section
    # We collect keywords from all headers as they are section titles
    keywords: list[str] = list(default_keywords)
    for header in headers:
        # Split header into individual words and add meaningful ones
        words = re.findall(r"[가-힣]+|[A-Za-z]+", header)
        for word in words:
            if len(word) >= 2 and word not in keywords:
                keywords.append(word)

    return keywords
