from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from cowork_pilot.auto_answer_config import AutoAnswerConfig
from cowork_pilot.auto_answer_models import PendingQuestionPacket
from cowork_pilot.codex.event_stream import extract_terminal_assistant_message


class PromptMaterializer(Protocol):
    def build_prompt(self, packet: PendingQuestionPacket) -> str | None: ...


_SYSTEM_HEADER = """\
You are the upper auto-answer agent for docs-orchestrator phase 2.
Your job: answer the pending question by choosing one of the listed options.

Rules:
- Do not modify any files.
- Do not ask follow-up questions.
- Choose one of the listed options when possible.
- If the docs are insufficient or the decision is unsafe, return decision="escalate".
- Output EXACTLY one JSON object matching the schema below. No other text.

Required JSON schema:
{
  "event_id": "<same event id>",
  "question_fingerprint": "<same fingerprint>",
  "decision": "answer|escalate",
  "response_text": "<the exact text to feed back to the lower session>",
  "selected_option": "<option label prefix, e.g. A|B|C|null>",
  "confidence": "low|medium|high",
  "rationale": "<one short sentence>"
}
"""


def _build_question_section(packet: PendingQuestionPacket) -> str:
    lines = [
        f"Current step: {packet.step}",
        f"Event ID: {packet.event_id}",
        f"Question fingerprint: {packet.question_fingerprint}",
        "",
        "Question:",
        packet.question_text,
        "",
        "Options:",
    ]
    for option in packet.options:
        lines.append(f"- {option}")
    if packet.recommended:
        lines.append("")
        lines.append(f"Recommended: {packet.recommended}")
    return "\n".join(lines)


class CodexPathMaterializer:
    """Materialize a codex upper-agent prompt from file paths only."""

    def build_prompt(self, packet: PendingQuestionPacket) -> str:
        read_files = [
            path for path in packet.seed_required_inputs if path.exists()
        ] + [
            path for path in packet.seed_optional_inputs if path.exists()
        ]

        lines = [_SYSTEM_HEADER, "Read ONLY these files:"]
        for path in read_files:
            lines.append(f"- {path}")
        lines.append("")
        lines.append(_build_question_section(packet))
        return "\n".join(lines)


class ClaudeInlineMaterializer:
    """Inline file contents for the claude upper agent."""

    def __init__(self, max_chars: int = 120_000):
        self.max_chars = max_chars

    def build_prompt(self, packet: PendingQuestionPacket) -> str | None:
        ordered_paths: list[Path] = []

        def append_unique(paths: list[Path]) -> None:
            for path in paths:
                if path not in ordered_paths:
                    ordered_paths.append(path)

        append_unique(
            [p for p in packet.seed_required_inputs if p.name == "checklists.md"],
        )
        append_unique(
            [
                p for p in packet.seed_required_inputs
                if p.name not in {"checklists.md", "shared.md", "analysis-report.md"}
            ],
        )
        append_unique(
            [p for p in packet.seed_optional_inputs if "gap-reports" in str(p)],
        )
        append_unique(
            [p for p in packet.seed_required_inputs if p.name == "shared.md"],
        )
        append_unique(
            [p for p in packet.seed_optional_inputs if p.name == "_overview.md"],
        )
        append_unique(
            [p for p in packet.seed_required_inputs if p.name == "analysis-report.md"],
        )

        header = _SYSTEM_HEADER + "\n" + _build_question_section(packet) + "\n\n"
        header += "=== File Contents ===\n\n"

        total_chars = len(header)
        file_blocks: list[str] = []
        included_paths: set[Path] = set()

        for path in ordered_paths:
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue

            block = f"--- {path.name} ---\n{content}\n\n"
            if total_chars + len(block) > self.max_chars:
                break
            file_blocks.append(block)
            total_chars += len(block)
            included_paths.add(path)

        for path in packet.seed_required_inputs:
            if path.exists() and path not in included_paths:
                return None

        return header + "".join(file_blocks)


def run_upper_agent(
    prompt: str,
    cfg: AutoAnswerConfig,
    project_dir: Path,
) -> str:
    """Run the upper agent once and return its stdout."""

    if cfg.engine == "codex":
        cmd = [
            cfg.engine_command,
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "-C",
            str(project_dir),
            "--json",
            "-",
        ]
    elif cfg.engine == "claude":
        cmd = [cfg.engine_command] + (cfg.engine_args or ["-p"])
    else:
        raise ValueError(f"Unknown upper engine: {cfg.engine}")

    result = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=cfg.timeout_seconds,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            result.stdout,
            result.stderr,
        )

    if cfg.engine == "codex":
        event_lines = [line for line in result.stdout.splitlines() if line.strip()]
        return extract_terminal_assistant_message(event_lines).strip()

    return result.stdout.strip()
