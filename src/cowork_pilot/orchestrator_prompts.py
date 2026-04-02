"""Jinja2 template loader and prompt builder for docs-orchestrator sessions.

Loads .j2 templates from orchestrator_templates/ and renders them with
the provided variables.  Follows the same Jinja2 environment pattern as
scaffolder.py.
"""
from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


# ── Phase → template mapping ────────────────────────────────────────

_PHASE_TEMPLATE_MAP: dict[str, str] = {
    "phase1_single": "phase1_single.j2",
    "phase1_domain": "phase1_domain.j2",
    "phase2_auto": "phase2_auto.j2",
    "phase2_manual": "phase2_manual.j2",
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

    env = _get_jinja_env(template_dir)
    template = env.get_template(template_name)
    return template.render(**kwargs)


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
