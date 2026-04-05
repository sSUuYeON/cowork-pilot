"""Data models for Codex CLI exec-plan execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChunkRunStatus(str, Enum):
    """Result of running a single chunk via ``codex exec``."""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"       # already completed


@dataclass
class ChunkResult:
    """Outcome of a single ``codex exec`` invocation."""
    chunk_number: int
    chunk_name: str
    status: ChunkRunStatus
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    event_log: str = ""
    last_message: str = ""
    duration_seconds: float = 0.0
    attempt: int = 1


@dataclass
class PlanRunResult:
    """Aggregate outcome of running an entire exec-plan."""
    plan_title: str
    plan_path: str
    chunk_results: list[ChunkResult] = field(default_factory=list)
    all_succeeded: bool = False

    def summary(self) -> str:
        """Human-readable one-line summary."""
        total = len(self.chunk_results)
        ok = sum(1 for r in self.chunk_results if r.status == ChunkRunStatus.SUCCESS)
        skip = sum(1 for r in self.chunk_results if r.status == ChunkRunStatus.SKIPPED)
        fail = total - ok - skip
        return (
            f"{self.plan_title}: {ok}/{total} succeeded"
            f"{f', {skip} skipped' if skip else ''}"
            f"{f', {fail} failed' if fail else ''}"
        )
