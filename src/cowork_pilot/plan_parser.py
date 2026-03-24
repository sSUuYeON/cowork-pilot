"""Parse exec-plan Markdown files into structured dataclasses.

Reads an exec-plan file and produces an ExecPlan with Chunks,
CompletionCriteria, and Session Prompts.  Also supports updating
checkboxes in-place (``- [ ]`` → ``- [x]``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Dataclasses ──────────────────────────────────────────────────────

@dataclass
class CompletionCriterion:
    """A single checkbox item under ``### Completion Criteria``."""
    description: str    # e.g. "pytest tests/test_models.py 통과"
    checked: bool       # True if [x], False if [ ]


@dataclass
class Chunk:
    """One ``## Chunk N: Name`` block in an exec-plan."""
    name: str                                      # "Chunk 1: Foundation"
    number: int                                    # 1
    tasks: list[str] = field(default_factory=list) # ["Task 1: Project Scaffold", ...]
    completion_criteria: list[CompletionCriterion] = field(default_factory=list)
    session_prompt: str = ""                       # Cowork에 보낼 프롬프트
    status: str = "pending"                        # "pending" | "in_progress" | "completed"


@dataclass
class ExecPlan:
    """Top-level representation of an exec-plan file."""
    title: str = ""
    project_dir: str = ""
    spec: str = ""
    created: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    status: str = "pending"                        # "pending" | "in_progress" | "completed"


# ── Regex patterns ───────────────────────────────────────────────────

_RE_CHUNK_HEADER = re.compile(r"^## Chunk (\d+): (.+)$")
_RE_CHECKBOX = re.compile(r"^- \[([ x])\] (.+)$")
_RE_TASK = re.compile(r"^- Task \d+: .+$")
_RE_METADATA_KV = re.compile(r"^- (\w[\w_]*): (.+)$")


# ── Parsing helpers ──────────────────────────────────────────────────

def _parse_metadata(lines: list[str]) -> dict[str, str]:
    """Extract key-value pairs from the ``## Metadata`` section."""
    result: dict[str, str] = {}
    in_metadata = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Metadata":
            in_metadata = True
            continue
        if in_metadata:
            if stripped.startswith("## ") or stripped == "---":
                break
            m = _RE_METADATA_KV.match(stripped)
            if m:
                result[m.group(1)] = m.group(2).strip()
    return result


def _parse_title(lines: list[str]) -> str:
    """Extract the first ``# Title`` from the file."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return ""


def _split_chunks(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """Split lines into chunks by ``## Chunk N:`` headers.

    Returns list of (number, name, body_lines).
    """
    chunks: list[tuple[int, str, list[str]]] = []
    current_num: int | None = None
    current_name: str = ""
    current_body: list[str] = []

    for line in lines:
        m = _RE_CHUNK_HEADER.match(line.strip())
        if m:
            if current_num is not None:
                chunks.append((current_num, current_name, current_body))
            current_num = int(m.group(1))
            current_name = m.group(2).strip()
            current_body = []
        elif current_num is not None:
            current_body.append(line)

    if current_num is not None:
        chunks.append((current_num, current_name, current_body))

    return chunks


def _parse_completion_criteria(body: list[str]) -> list[CompletionCriterion]:
    """Parse ``- [ ]`` / ``- [x]`` lines under ``### Completion Criteria``."""
    criteria: list[CompletionCriterion] = []
    in_section = False
    for line in body:
        stripped = line.strip()
        if stripped == "### Completion Criteria":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("### ") or stripped == "---":
                break
            m = _RE_CHECKBOX.match(stripped)
            if m:
                checked = m.group(1) == "x"
                criteria.append(CompletionCriterion(description=m.group(2).strip(), checked=checked))
    return criteria


def _parse_tasks(body: list[str]) -> list[str]:
    """Parse ``- Task N:`` lines under ``### Tasks``."""
    tasks: list[str] = []
    in_section = False
    for line in body:
        stripped = line.strip()
        if stripped == "### Tasks":
            in_section = True
            continue
        if in_section:
            if stripped.startswith("### ") or stripped == "---":
                break
            if _RE_TASK.match(stripped):
                tasks.append(stripped[2:].strip())  # remove "- "
    return tasks


def _parse_session_prompt(body: list[str]) -> str:
    """Extract the session prompt text.

    Rules (from spec 4.1 / conventions 4.4):
    1. If a code block (``` fence) exists, use the FIRST code block's content only.
    2. If no code block, collect text from ``### Session Prompt`` to ``---`` / ``## `` / EOF.
    3. Empty result → parsing error.
    """
    in_section = False
    in_code_block = False
    code_block_lines: list[str] = []
    found_code_block = False
    plain_lines: list[str] = []

    for line in body:
        stripped = line.strip()

        if stripped == "### Session Prompt":
            in_section = True
            continue

        if not in_section:
            continue

        # Stop at next section or chunk separator
        if not in_code_block and (stripped.startswith("### ") or stripped.startswith("## ") or stripped == "---"):
            break

        # Code block handling
        if stripped.startswith("```"):
            if not in_code_block and not found_code_block:
                in_code_block = True
                continue  # skip opening fence
            elif in_code_block:
                in_code_block = False
                found_code_block = True
                continue  # skip closing fence; ignore further code blocks
            else:
                # Second+ code block — skip
                continue

        if in_code_block:
            code_block_lines.append(line.rstrip())
        elif not found_code_block:
            plain_lines.append(line.rstrip())

    if found_code_block:
        return "\n".join(code_block_lines).strip()

    return "\n".join(plain_lines).strip()


def _chunk_status(criteria: list[CompletionCriterion]) -> str:
    """Determine chunk status from its criteria."""
    if not criteria:
        return "pending"
    if all(c.checked for c in criteria):
        return "completed"
    return "pending"


# ── Public API ───────────────────────────────────────────────────────

def parse_exec_plan(path: Path) -> ExecPlan:
    """Parse an exec-plan Markdown file into an ``ExecPlan`` dataclass.

    Raises ``ValueError`` if a chunk has an empty session prompt.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = _parse_title(lines)
    metadata = _parse_metadata(lines)

    plan = ExecPlan(
        title=title,
        project_dir=metadata.get("project_dir", ""),
        spec=metadata.get("spec", ""),
        created=metadata.get("created", ""),
        status=metadata.get("status", "pending"),
    )

    raw_chunks = _split_chunks(lines)
    for num, name, body in raw_chunks:
        criteria = _parse_completion_criteria(body)
        tasks = _parse_tasks(body)
        prompt = _parse_session_prompt(body)

        if not prompt:
            raise ValueError(f"Chunk {num} ({name}) has an empty Session Prompt — ESCALATE")

        chunk = Chunk(
            name=name,
            number=num,
            tasks=tasks,
            completion_criteria=criteria,
            session_prompt=prompt,
            status=_chunk_status(criteria),
        )
        plan.chunks.append(chunk)

    # Update plan-level status
    if plan.chunks:
        if all(c.status == "completed" for c in plan.chunks):
            plan.status = "completed"
        elif any(c.status != "pending" for c in plan.chunks):
            plan.status = "in_progress"

    return plan


def update_checkboxes(path: Path, chunk_number: int, criteria_indices: list[int] | None = None) -> None:
    """Update ``- [ ]`` → ``- [x]`` for a specific chunk in the exec-plan file.

    If ``criteria_indices`` is None, check ALL criteria in the chunk.
    Otherwise, only check the specified 0-based indices.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    in_target_chunk = False
    in_criteria = False
    criterion_idx = 0
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Detect chunk boundaries
        m = _RE_CHUNK_HEADER.match(stripped)
        if m:
            in_target_chunk = int(m.group(1)) == chunk_number
            in_criteria = False
            criterion_idx = 0

        # Detect criteria section
        if in_target_chunk and stripped == "### Completion Criteria":
            in_criteria = True
            new_lines.append(line)
            continue

        if in_criteria and (stripped.startswith("### ") or stripped == "---"):
            in_criteria = False

        # Update checkbox
        if in_target_chunk and in_criteria:
            cm = _RE_CHECKBOX.match(stripped)
            if cm:
                if criteria_indices is None or criterion_idx in criteria_indices:
                    line = line.replace("- [ ]", "- [x]", 1)
                criterion_idx += 1

        new_lines.append(line)

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
