"""Terminal input module for interactive planning resume.

Prompts the user in the current terminal for pending questions or approvals
instead of requiring a separate ``planning resume --response`` invocation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cowork_pilot.planning.runtime_models import PlanningRuntimeState
from cowork_pilot.planning.runtime_storage import read_run_state
from cowork_pilot.planning.stage_executor import PendingApproval, PendingQuestion


@dataclass(frozen=True)
class TerminalResponse:
    text: str
    kind: str  # "answer" | "approval"


def _default_input_fn(prompt: str) -> str:
    """Wrapper around builtin ``input`` to allow monkeypatching in tests."""
    return input(prompt)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def prompt_for_pending_response(
    run_dir: Path,
    *,
    input_fn: Callable[[str], str] | None = None,
) -> TerminalResponse | None:
    """Read pending payload from persisted *run-state.json* and prompt."""
    fn = input_fn if input_fn is not None else _default_input_fn
    run_state = read_run_state(run_dir)
    state = str(run_state.get("state", ""))

    if state == PlanningRuntimeState.WAITING_FOR_INPUT.value:
        pending = dict(run_state.get("pending_question", {}))  # type: ignore[arg-type]
        return _prompt_question(pending, input_fn=fn)

    if state == PlanningRuntimeState.WAITING_FOR_APPROVAL.value:
        pending = dict(run_state.get("pending_approval", {}))  # type: ignore[arg-type]
        return _prompt_approval(pending, input_fn=fn)

    return None


def prompt_from_stage_result(
    *,
    pending_question: PendingQuestion | None = None,
    pending_approval: PendingApproval | None = None,
    input_fn: Callable[[str], str] | None = None,
) -> TerminalResponse | None:
    """Prompt from in-memory *StageExecutionResult* payload (preferred path)."""
    fn = input_fn if input_fn is not None else _default_input_fn
    if pending_question is not None:
        return _prompt_question(
            {
                "question": pending_question.question,
                "options": list(pending_question.options),
                "recommended": pending_question.recommended,
            },
            input_fn=fn,
        )
    if pending_approval is not None:
        return _prompt_approval(
            {"subject": pending_approval.subject},
            input_fn=fn,
        )
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prompt_question(
    pending: dict,
    *,
    input_fn: Callable[[str], str],
) -> TerminalResponse | None:
    question = str(pending.get("question", "")).strip()
    options = [str(x) for x in pending.get("options", [])]
    recommended = str(pending.get("recommended", "")).strip()

    print()
    print(question)
    for i, option in enumerate(options, start=1):
        suffix = " (recommended)" if option == recommended and recommended else ""
        print(f"  {i}. {option}{suffix}")

    if options and recommended:
        prompt_text = f"Answer [1-{len(options)} / text, Enter={recommended}]: "
    elif options:
        prompt_text = f"Answer [1-{len(options)} / text]: "
    elif recommended:
        prompt_text = f"Answer [Enter={recommended}]: "
    else:
        prompt_text = "Answer: "

    while True:
        try:
            raw = input_fn(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not raw and recommended:
            return TerminalResponse(text=recommended, kind="answer")

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return TerminalResponse(text=options[idx], kind="answer")

        if raw:
            return TerminalResponse(text=raw, kind="answer")
        # Empty input with no recommended — loop again


def _prompt_approval(
    pending: dict,
    *,
    input_fn: Callable[[str], str],
) -> TerminalResponse | None:
    subject = str(pending.get("subject", "")).strip()

    print()
    print(f"Approval required: {subject}")

    while True:
        try:
            raw = input_fn("Approve? [y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw in ("y", "yes"):
            return TerminalResponse(text="approved", kind="approval")
        if raw in ("n", "no"):
            return TerminalResponse(text="rejected", kind="approval")
        # Invalid input — loop again
