"""Feature-file detector for Phase 1 domain extracts.

Walks a ``domain-extracts/`` directory and returns the markdown files that
represent *real* per-feature extracts. Support files (``shared.md``,
``_overview.md``) and non-feature directories (``references/``) are
excluded so the downstream quality gate never treats them as features.
"""

from __future__ import annotations

from pathlib import Path

_SUPPORT_NAMES: frozenset[str] = frozenset({"shared.md", "_overview.md"})
_SUPPORT_DIRS: frozenset[str] = frozenset({"references"})


def _is_feature_path(path: Path, extracts_root: Path) -> bool:
    """Return True iff *path* is a real feature extract under *extracts_root*.

    A feature extract is a markdown file that:
    - has the ``.md`` suffix,
    - is not named ``shared.md`` or ``_overview.md``,
    - is not located under a support directory such as ``references/``,
    - sits exactly one directory below the extracts root (i.e. ``domain/<feature>.md``).
    """
    if path.suffix != ".md":
        return False
    if path.name in _SUPPORT_NAMES:
        return False
    try:
        rel_parts = path.relative_to(extracts_root).parts
    except ValueError:
        return False
    if not rel_parts:
        return False
    if rel_parts[0] in _SUPPORT_DIRS:
        return False
    # Features live inside a domain directory: domain/<feature>.md
    return len(rel_parts) == 2


def detect_features(extracts_root: Path) -> list[Path]:
    """Return sorted list of feature-file paths under *extracts_root*.

    Returns an empty list if *extracts_root* does not exist or contains no
    feature files. Support files are filtered out by ``_is_feature_path``.
    """
    if not extracts_root.exists() or not extracts_root.is_dir():
        return []
    features = [
        p for p in sorted(extracts_root.rglob("*.md")) if _is_feature_path(p, extracts_root)
    ]
    return features
