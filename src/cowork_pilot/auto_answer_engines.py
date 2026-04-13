from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from cowork_pilot.auto_answer_config import AutoAnswerConfig
from cowork_pilot.auto_answer_models import PendingQuestionPacket
from cowork_pilot.codex.event_stream import extract_terminal_assistant_message


class PromptMaterializer(Protocol):
    def build_prompt(self, packet: PendingQuestionPacket) -> str | None: ...


class DecisionMaterializer(Protocol):
    def build_prompt(
        self,
        packet: PendingQuestionPacket,
        *,
        previous_rationale: str | None = None,
        existing_contract_exists: bool = False,
    ) -> str | None: ...


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

_DECISION_SYSTEM_HEADER = """\
You are the decision_resolver for docs-orchestrator phase 2.
Your job: explain why the first-pass auto-answer could not safely decide, then either choose one of the listed options or escalate.

Rules:
- Do not modify any files.
- Choose exactly one resolver_reason using this priority order:
  conflict > consistency_gap > insufficient_evidence > policy_uncertain
- Reuse an existing contradiction-resolution or prior [AI_DECISION] contract when one already exists.
- If resolver_reason="conflict":
  - existing contract exists -> applied_policy="existing_contract_first"
  - otherwise -> applied_policy="conservative_scope"
- If resolver_reason="consistency_gap":
  - applied_policy="existing_contract_first"
- If resolver_reason="insufficient_evidence":
  - applied_policy="recommended_plus_consistency"
- If resolver_reason="policy_uncertain":
  - if the choice is irreversible, return decision="escalate"
  - otherwise answer with applied_policy="irreversible_guard"
- conservative_scope means: avoid expanding permissions, write/update scope, new states/screens, or flow changes; if tied prefer recommended, then the simpler option.
- If decision="answer":
  - response_text must be the exact chosen option text
  - selected_option must identify that option
  - ai_decision_note must be a short human-readable Korean note
- If decision="escalate":
  - response_text must be ""
  - selected_option must be null
- Output EXACTLY one JSON object matching the schema below. No other text.

Required JSON schema:
{
  "event_id": "<same event id>",
  "question_fingerprint": "<same fingerprint>",
  "decision": "answer|escalate",
  "response_text": "<the exact text to feed back to the lower session>",
  "selected_option": "<option label prefix, e.g. A|B|C|null>",
  "confidence": "low|medium|high",
  "rationale": "<one short sentence>",
  "resolver_reason": "conflict|consistency_gap|insufficient_evidence|policy_uncertain|null",
  "applied_policy": "existing_contract_first|conservative_scope|recommended_plus_consistency|irreversible_guard|null",
  "ai_decision_note": "<short Korean note or null>"
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


def _build_decision_context(
    *,
    packet: PendingQuestionPacket,
    previous_rationale: str | None,
    existing_contract_exists: bool,
) -> list[str]:
    lines = [
        "Resolver context:",
        (
            "Existing contract detected: yes"
            if existing_contract_exists
            else "Existing contract detected: no"
        ),
    ]
    if previous_rationale:
        lines.append(f"First-pass escalate rationale: {previous_rationale}")
    if packet.escalation_context:
        original_question = str(
            packet.escalation_context.get("original_question", ""),
        ).strip()
        if original_question:
            lines.append(f"Original lower question: {original_question}")
    return lines


class CodexDecisionMaterializer:
    """Materialize a Codex decision_resolver prompt from file paths."""

    def build_prompt(
        self,
        packet: PendingQuestionPacket,
        *,
        previous_rationale: str | None = None,
        existing_contract_exists: bool = False,
    ) -> str:
        read_files = [
            path for path in packet.seed_required_inputs if path.exists()
        ] + [
            path for path in packet.seed_optional_inputs if path.exists()
        ]

        lines = [_DECISION_SYSTEM_HEADER, "Read ONLY these files:"]
        for path in read_files:
            lines.append(f"- {path}")
        lines.append("")
        lines.extend(
            _build_decision_context(
                packet=packet,
                previous_rationale=previous_rationale,
                existing_contract_exists=existing_contract_exists,
            )
        )
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


class ClaudeInlineDecisionMaterializer:
    """Inline file contents for the claude decision_resolver agent."""

    def __init__(self, max_chars: int = 120_000):
        self.max_chars = max_chars

    def build_prompt(
        self,
        packet: PendingQuestionPacket,
        *,
        previous_rationale: str | None = None,
        existing_contract_exists: bool = False,
    ) -> str | None:
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
                p
                for p in packet.seed_optional_inputs
                if "contradiction-resolutions" in str(p)
            ],
        )
        append_unique(
            [p for p in packet.seed_optional_inputs if "gap-reports" in str(p)],
        )
        append_unique(
            [
                p
                for p in packet.seed_required_inputs
                if p.name not in {"checklists.md", "shared.md", "analysis-report.md"}
            ],
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

        header = _DECISION_SYSTEM_HEADER + "\n"
        header += "\n".join(
            _build_decision_context(
                packet=packet,
                previous_rationale=previous_rationale,
                existing_contract_exists=existing_contract_exists,
            )
        )
        header += "\n\n"
        header += _build_question_section(packet) + "\n\n=== File Contents ===\n\n"

        total_chars = len(header)
        file_blocks: list[str] = []
        included_paths: set[Path] = set()

        for path in ordered_paths:
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

        required_paths = [path for path in packet.seed_required_inputs if path.exists()]
        for path in required_paths:
            if path not in included_paths:
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
