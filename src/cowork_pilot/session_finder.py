from __future__ import annotations

from pathlib import Path


IGNORED_FILENAMES = {"audit.jsonl"}


def find_active_jsonl(base_path: Path | str) -> Path | None:
    """Find the most recently modified non-empty .jsonl file under base_path.

    Scans recursively for .jsonl files in the Cowork session directory structure.
    Ignores known non-session files (e.g. audit.jsonl).
    Returns the file with the most recent mtime, or None if no valid files exist.
    """
    base = Path(base_path).expanduser()
    if not base.exists():
        return None

    candidates: list[tuple[float, Path]] = []
    for jsonl_file in base.rglob("*.jsonl"):
        if jsonl_file.name in IGNORED_FILENAMES:
            continue
        s = jsonl_file.stat()
        if s.st_size > 0:
            candidates.append((s.st_mtime, jsonl_file))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]
