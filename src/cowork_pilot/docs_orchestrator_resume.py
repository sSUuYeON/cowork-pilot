"""Pure resume helpers for the docs-orchestrator Codex backend.

This module holds the state-mutation logic for a waiting docs-orchestrator
step, extracted from ``main.py`` so it can be reused from:

  1. The one-shot CLI wrapper ``_run_docs_orchestrator_resume()`` in
     ``main.py`` (see Chunk 5).
  2. The in-process interactive loop inside ``docs_orchestrator.py``
     (``_resolve_waiting_runtime_interactively``, see Chunk 4).

Design principles (see docs-orchestrator-interactive-resume-spec.md):

* No ``print`` / ``sys.exit``. The helper raises ``RuntimeError`` for
  programmer errors (missing runtime, wrong state) and otherwise returns
  a ``DocsResumeOutcome`` describing the result.
* No recursive call back into ``run_docs_orchestrator()``. Callers decide
  what to do with the returned state.
* The helper always returns the *latest* ``OrchestratorState`` — callers
  must **not** call ``load_state()`` afterwards. The returned state is the
  single source of truth for that execution path (MUST 4).
* Write ordering contract (spec §5.2, §7, §11.3):
    - ``completed`` → ``save_state`` FIRST, then ``clear_runtime``.
    - ``waiting``   → ``write_runtime`` only; state is untouched.
    - ``failed``    → ``save_state``, then ``write_runtime`` with
      ``runtime_state="failed"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cowork_pilot.auto_answer_models import PendingQuestionPacket
from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.orchestrator_state import (
    OrchestratorState,
    load_state,
    save_state,
)

# NOTE: these imports are intentionally module-level. ``docs_orchestrator``
# is a large module, but importing it here does not create a cycle because
# ``docs_orchestrator`` does not import from this module.
from cowork_pilot.docs_orchestrator import (
    _GENERATED_DIR,
    _STATE_FILENAME,
    _update_state_completed,
    _update_state_error,
)
from cowork_pilot.docs_orchestrator_codex import resume_codex_step
from cowork_pilot.docs_orchestrator_runtime import (
    clear_runtime,
    load_runtime,
    runtime_is_waiting,
    write_runtime,
)
from cowork_pilot.source_contradictions import contradiction_resolution_path


@dataclass
class DocsResumeOutcome:
    """Outcome of a single docs-orchestrator resume attempt.

    Attributes
    ----------
    status:
        ``"completed"`` — step finished, state advanced, runtime cleared.
        ``"waiting"``   — step is still waiting for further user input;
                           runtime has been updated with the new payload.
        ``"failed"``    — step failed; state has been updated with the
                           error and runtime marked ``failed``.
    state:
        The latest ``OrchestratorState`` after the attempt. Callers MUST
        treat this as the single source of truth and not re-read state
        from disk.
    step:
        The step identifier that was resumed.
    error:
        Error text when ``status == "failed"``. Empty otherwise.
    """

    status: Literal["completed", "waiting", "failed"]
    state: OrchestratorState
    step: str
    error: str = ""


def _docs_resume_expected_files(step: str, project_dir: Path) -> list[Path]:
    """Return canonical expected outputs for docs-orchestrator resume.

    Moved verbatim from ``main.py`` to keep a single source of truth for
    expected-file resolution. ``main.py`` imports this symbol.
    """
    generated = project_dir / "docs" / "generated"

    if step == "phase_1":
        return [
            generated / "analysis-report.md",
            generated / "domain-extracts",
            generated / "domain-extracts" / "shared.md",
        ]
    if step.startswith("phase_1:"):
        parts = step.split(":")
        if len(parts) >= 2:
            domain = parts[1]
            domain_dir = generated / "domain-extracts" / domain
            return [domain_dir, domain_dir / "_overview.md"]
        return []
    if step.startswith("phase_2:"):
        rest = step[len("phase_2:"):]
        files: list[Path] = []
        for pair in rest.split("+"):
            parts = pair.split(":", 1)
            if len(parts) != 2:
                continue
            domain, feature = parts
            files.append(generated / "gap-reports" / f"{domain}--{feature}.md")
        if files:
            return files
        return []
    if step.startswith("phase_2_conflict:"):
        contradiction_id = step[len("phase_2_conflict:"):]
        return [
            contradiction_resolution_path(
                generated,
                contradiction_id,
            )
        ]
    if step == "phase_3_A":
        design_docs = project_dir / "docs" / "design-docs"
        return [
            design_docs / "core-beliefs.md",
            design_docs / "data-model.md",
            design_docs / "auth.md",
            design_docs / "deployment.md",
            design_docs / "index.md",
        ]
    if step.startswith("phase_3_B:"):
        rest = step[len("phase_3_B:"):]
        specs_dir = project_dir / "docs" / "product-specs"
        files: list[Path] = []
        for pair in rest.split("+"):
            parts = pair.split(":", 1)
            if len(parts) == 2:
                domain, feature = parts
                files.append(specs_dir / f"{domain}--{feature}.md")
        return files
    if step == "phase_3_C":
        docs_dir = project_dir / "docs"
        return [
            docs_dir / "ARCHITECTURE.md",
            docs_dir / "DESIGN_GUIDE.md",
            docs_dir / "SECURITY.md",
        ]
    if step == "phase_3_D":
        return [project_dir / "AGENTS.md"]
    if step == "phase_4_1":
        return [generated / "phase4-consistency.md"]
    if step == "phase_4_2":
        return [generated / "phase4-rescore.md"]
    if step == "phase_4_3":
        return [project_dir / "docs" / "QUALITY_SCORE.md"]
    if step == "phase_5_outline":
        return [generated / "exec-plan-outline.md"]
    if step.startswith("phase_5_outline_unit:"):
        return [generated / "exec-plan-outline.md"]
    if step == "phase_5_outline_finalize":
        return [generated / "exec-plan-outline.md"]
    if step.startswith("phase_5_detail:"):
        plan_name = step[len("phase_5_detail:"):]
        return [project_dir / "docs" / "exec-plans" / "planning" / f"{plan_name}.md"]
    return []


def resume_waiting_docs_step(
    config: Config,
    orch_config: DocsOrchestratorConfig,
    *,
    response_text: str,
    response_kind: str,
    expected_files_override: list[Path] | None = None,
) -> DocsResumeOutcome:
    """Resume a single waiting docs-orchestrator step and return the outcome.

    This is the pure helper the interactive loop and the CLI wrapper share.
    It performs exactly one ``codex exec resume`` call, updates state and
    runtime according to the write-ordering contract, and returns a
    :class:`DocsResumeOutcome`.

    Parameters
    ----------
    config:
        The top-level :class:`Config` (used for ``project_dir``).
    orch_config:
        The :class:`DocsOrchestratorConfig` (used for ``engine_command``).
    response_text:
        The user's response. Opaque to this layer — its meaning depends on
        ``response_kind``. For ``response_kind="approval"`` the caller MUST
        pass exactly ``"approved"`` or ``"rejected"`` (MUST 3), but this
        function does not re-validate that contract.
    response_kind:
        ``"answer"`` or ``"approval"``.

    Returns
    -------
    DocsResumeOutcome
        Describes the result of the single resume attempt.

    Raises
    ------
    RuntimeError
        If there is no runtime sidecar, the runtime is not in a waiting
        state, or the runtime has no ``resume_handle``. These are
        programmer / caller errors — callers must ensure the runtime is
        waiting before invoking this helper.
    """
    project_dir = Path(config.project_dir)
    state_path = project_dir / _GENERATED_DIR / _STATE_FILENAME

    # --- 1. Load runtime and validate it is waiting ---------------------
    runtime = load_runtime(project_dir)
    if runtime is None:
        raise RuntimeError(
            "No orchestrator-runtime.json found. Nothing to resume.",
        )

    if not runtime_is_waiting(project_dir):
        raise RuntimeError(
            "Runtime is not in a waiting state "
            f"(current: {runtime.get('runtime_state')})",
        )

    resume_handle = runtime.get("resume_handle", "")
    if not resume_handle:
        raise RuntimeError("runtime file has no resume_handle.")

    step = str(runtime.get("step", ""))

    # --- 2. Load state and resolve expected files -----------------------
    state = load_state(state_path)
    expected_files = (
        list(expected_files_override)
        if expected_files_override is not None
        else _docs_resume_expected_files(step, project_dir)
    )

    # --- 3. Call the Codex backend --------------------------------------
    codex_cmd = getattr(orch_config, "engine_command", "codex")
    result = resume_codex_step(
        project_dir=project_dir,
        step=step,
        response_text=response_text,
        response_kind=response_kind,
        runtime_payload=dict(runtime),
        expected_files=expected_files,
        codex_command=codex_cmd,
    )

    # --- 4. Apply the write-ordering contract ---------------------------
    if result.status == "completed":
        updated_state = _update_state_completed(state, step, "Codex resume 완료")
        save_state(updated_state, state_path)   # state first
        clear_runtime(project_dir)              # then remove runtime
        return DocsResumeOutcome(
            status="completed",
            state=updated_state,
            step=step,
        )

    if result.status == "waiting":
        new_runtime: dict[str, object] = {
            "backend": "codex",
            "step": step,
            "runtime_state": (
                "waiting_for_input"
                if result.waiting_kind == "input"
                else "waiting_for_approval"
            ),
            "resume_handle": result.resume_handle,
            "resume_handle_kind": "codex_thread_id",
            "pending_event_id": result.pending_event_id or "",
            "pending_question": result.pending_question,
            "pending_approval": result.pending_approval,
        }
        if "question_context_seed" in runtime:
            seed = dict(runtime["question_context_seed"])
            if (
                result.waiting_kind == "input"
                and isinstance(result.pending_question, dict)
                and result.pending_question.get("question")
                and result.pending_question.get("options")
            ):
                seed["question_fingerprint"] = (
                    PendingQuestionPacket.compute_fingerprint(
                        step=step,
                        event_id=result.pending_event_id or "",
                        question=str(result.pending_question["question"]),
                        options=[
                            str(option)
                            for option in result.pending_question["options"]
                        ],
                    )
                )
            new_runtime["question_context_seed"] = seed
        if "auto_answer_state" in runtime:
            new_runtime["auto_answer_state"] = runtime["auto_answer_state"]
        write_runtime(project_dir, new_runtime)
        # State is intentionally NOT touched on waiting (MUST 4 still
        # holds: we return the freshly-loaded state as-is).
        return DocsResumeOutcome(
            status="waiting",
            state=state,
            step=step,
        )

    # failed
    error_text = result.error or "Codex resume failed"
    updated_state = _update_state_error(state, step, error_text)
    save_state(updated_state, state_path)
    failed_runtime = dict(runtime)
    failed_runtime["runtime_state"] = "failed"
    write_runtime(project_dir, failed_runtime)
    return DocsResumeOutcome(
        status="failed",
        state=updated_state,
        step=step,
        error=error_text,
    )
