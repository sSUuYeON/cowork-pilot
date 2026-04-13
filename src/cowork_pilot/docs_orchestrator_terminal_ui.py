"""Terminal input module for docs-orchestrator interactive resume.

Prompts the user in the current terminal for pending questions or approvals
read directly from the docs-orchestrator runtime sidecar payload
(``docs/generated/orchestrator-runtime.json``).

This module intentionally does NOT import from ``cowork_pilot.planning``.
Although the behaviour mirrors ``planning/terminal_ui.py``, the docs
orchestrator has its own runtime payload shape and a dedicated contract
(spec §MUST 3: approval prompts must emit only ``"approved"`` or
``"rejected"``), so reuse is avoided on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# ── Constants ────────────────────────────────────────────────────────

_WAITING_FOR_INPUT = "waiting_for_input"
_WAITING_FOR_APPROVAL = "waiting_for_approval"


@dataclass(frozen=True)
class TerminalResponse:
    """Value returned by a successful terminal prompt.

    ``kind`` is one of ``"answer"`` or ``"approval"``.

    Per spec MUST 3:
    - When ``kind == "answer"``, ``text`` is free-form user input or the
      text of a selected option.
    - When ``kind == "approval"``, ``text`` is exactly ``"approved"``
      or ``"rejected"`` — no other values are permitted.
    """

    text: str
    kind: str  # "answer" | "approval"


def _default_input_fn(prompt: str) -> str:
    """Thin wrapper around builtin ``input`` to allow monkeypatching in tests."""
    return input(prompt)


# ── Public API ───────────────────────────────────────────────────────

def prompt_from_runtime_payload(
    runtime_payload: dict[str, object],
    input_fn: Callable[[str], str] | None = None,
) -> TerminalResponse | None:
    """Prompt the user based on a docs-orchestrator runtime payload.

    Parameters
    ----------
    runtime_payload:
        The dict loaded from ``orchestrator-runtime.json``. Expected to
        contain a ``runtime_state`` field and, depending on the state,
        a ``pending_question`` or ``pending_approval`` sub-payload.
    input_fn:
        Optional override for ``input``.  Mainly used by tests.

    Returns
    -------
    ``TerminalResponse`` on successful prompt, or ``None`` if:
    - the runtime payload is not in a waiting state,
    - the user cancels via EOF / Ctrl-C (spec MUST 1 cancel path).
    """
    fn = input_fn if input_fn is not None else _default_input_fn
    state = str(runtime_payload.get("runtime_state", ""))

    if state == _WAITING_FOR_INPUT:
        pending_raw = runtime_payload.get("pending_question") or {}
        pending = dict(pending_raw) if isinstance(pending_raw, dict) else {}
        return _prompt_question(pending, input_fn=fn)

    if state == _WAITING_FOR_APPROVAL:
        pending_raw = runtime_payload.get("pending_approval") or {}
        pending = dict(pending_raw) if isinstance(pending_raw, dict) else {}
        return _prompt_approval(pending, input_fn=fn)

    return None


# ── Internal helpers ─────────────────────────────────────────────────

def _prompt_question(
    pending: dict,
    *,
    input_fn: Callable[[str], str],
) -> TerminalResponse | None:
    """Ask a free-form / multiple-choice question.

    Supports:
    - numbered options,
    - an optional ``recommended`` default selected by pressing Enter,
    - arbitrary free-form text as a fallback.

    Returns ``None`` on EOF / Ctrl-C (spec MUST 1 cancel path).
    """
    question = str(pending.get("question", "")).strip()
    raw_options = pending.get("options", [])
    if isinstance(raw_options, (list, tuple)):
        options = [str(x) for x in raw_options]
    else:
        options = []
    recommended = str(pending.get("recommended", "")).strip()
    escalation = pending.get("escalation")

    print()
    if isinstance(escalation, dict):
        reason = str(escalation.get("reason", "")).strip()
        if reason:
            print(f"[auto-answer escalation] {reason}")
        resolver_reason = str(escalation.get("resolver_reason", "")).strip()
        if resolver_reason:
            print(f"  resolver_reason: {resolver_reason}")
        applied_policy = str(escalation.get("applied_policy", "")).strip()
        if applied_policy:
            print(f"  applied_policy: {applied_policy}")
        note = str(escalation.get("ai_decision_note", "")).strip()
        if note:
            print(f"  note: {note}")
        raw_related = escalation.get("related_contradictions", [])
        if isinstance(raw_related, (list, tuple)):
            for raw_item in raw_related[:3]:
                if not isinstance(raw_item, dict):
                    continue
                contradiction_id = str(raw_item.get("contradiction_id", "")).strip()
                if contradiction_id:
                    print(f"  conflict: {contradiction_id}")
                raw_claims = raw_item.get("claims", [])
                if isinstance(raw_claims, (list, tuple)):
                    for raw_claim in raw_claims[:2]:
                        if not isinstance(raw_claim, dict):
                            continue
                        source_file = str(raw_claim.get("source_file", "")).strip()
                        source_section = str(raw_claim.get("source_section", "")).strip()
                        excerpt = str(raw_claim.get("excerpt", "")).strip()
                        location = (
                            f"{source_file}#{source_section}"
                            if source_section else source_file
                        )
                        if location or excerpt:
                            print(f"    - {location}: {excerpt}")
        raw_ai_decisions = escalation.get("related_ai_decision_files", [])
        if isinstance(raw_ai_decisions, (list, tuple)):
            for ai_path in raw_ai_decisions[:3]:
                resolved = str(ai_path).strip()
                if resolved:
                    print(f"  prior_ai_decision: {resolved}")
        original_question = str(escalation.get("original_question", "")).strip()
        if original_question and original_question != question:
            print("  original lower-question:")
            print(f"    {original_question}")
    if question:
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
        # Empty input with no recommended default — loop and re-prompt.


def _prompt_approval(
    pending: dict,
    *,
    input_fn: Callable[[str], str],
) -> TerminalResponse | None:
    """Ask for a yes/no approval on *pending.subject*.

    Per spec MUST 3, the returned ``text`` is always exactly
    ``"approved"`` or ``"rejected"``.  ``None`` on EOF / Ctrl-C.
    """
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
        # Invalid input — loop and re-prompt.
