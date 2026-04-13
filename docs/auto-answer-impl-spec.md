# Auto-Answer 구현 설명서

> phase2 하위 세션의 blocking 질문을 상위 one-shot 에이전트가 자동 응답하는 시스템.
> 이 문서만 보고 구현 가능하도록 작성됨.

---

## 0. 용어

| 용어 | 의미 |
|------|------|
| **하위 세션** | `codex exec`로 실행되는 phase2 gap-analysis 세션. 질문을 만드는 주체. |
| **상위 에이전트** | 질문에 답하는 별도 one-shot 프로세스. `codex exec --sandbox read-only` 또는 `claude -p`. |
| **runtime sidecar** | `docs/generated/orchestrator-runtime.json`. 하위 세션의 waiting 상태를 저장하는 파일. |
| **seed** | `question_context_seed`. runtime에 저장되는, 상위 에이전트가 읽어야 할 파일 목록과 step 정보. |
| **packet** | `PendingQuestionPacket`. 상위 에이전트에 보내는 입력 단위. |

---

## 1. v1 범위 제한 (하드코딩)

아래 4개를 코드와 config에 명시적으로 제한한다.

| 축 | v1 허용 값 | 제외 |
|----|-----------|------|
| 대상 단계 | `docs-orchestrator phase_2`만 | phase1, phase3, phase4, phase5 |
| 질문 타입 | `blocking INPUT_REQUIRED`만 | `APPROVAL_REQUIRED`, `NEEDS_HUMAN` |
| 질문 형태 | `single-select` (options ≥ 2, recommended 존재)만 | multiSelect, 자유 텍스트, options 비어있는 경우 |
| 하위 세션 백엔드 | `codex exec`만 | Claude Desktop JSONL 경로 |

상위 에이전트 엔진은 `codex` 또는 `claude` 선택 가능.

v2에서 Claude Desktop 하위 세션 경로 추가 예정 (UI 자동화 fragile하므로 분리).

---

## 2. 읽어야 할 기존 파일 (구현 전 필독)

### 핵심 (반드시 읽고 이해해야 하는 파일)

| 파일 | 왜 읽어야 하는지 |
|------|-----------------|
| `src/cowork_pilot/config.py` | `DocsOrchestratorConfig` 패턴을 따라 `AutoAnswerConfig` 추가 |
| `src/cowork_pilot/docs_orchestrator.py` L923-1039 | `_run_phase_2()` — bundle 순회, prompt 빌드, `_execute_orchestrator_step()` 호출, waiting 분기. **여기에 auto-answer 호출 지점 삽입** |
| `src/cowork_pilot/docs_orchestrator.py` L1940-1962 | `_save_codex_waiting_runtime()` — runtime payload 구조. **여기에 `question_context_seed` 필드 추가** |
| `src/cowork_pilot/docs_orchestrator.py` L184-279 | `_resolve_waiting_runtime_interactively()` — 기존 interactive resume loop. auto-answer는 이 패턴을 참조하되 별도 경로. |
| `src/cowork_pilot/docs_orchestrator_resume.py` 전체 | `resume_waiting_docs_step()` — 하위 세션 resume의 single entry point. auto-answer 성공 시 이 함수를 호출. |
| `src/cowork_pilot/docs_orchestrator_runtime.py` 전체 | `load_runtime()`, `write_runtime()`, `clear_runtime()`, `runtime_is_waiting()` — runtime sidecar CRUD. |
| `src/cowork_pilot/docs_orchestrator_codex.py` L39-50 | `CodexStepResult` — waiting 판단에 사용되는 필드들. |
| `src/cowork_pilot/orchestrator_prompts.py` 전체 | `build_session_prompt()`, `compute_available_extracts()`, `load_overview_reasons()`, `AvailableExtracts` — phase2 prompt 빌드의 모든 요소. |
| `src/cowork_pilot/orchestrator_templates/phase2_manual.j2` | phase2 manual 모드 템플릿. "읽어야 할 파일" 섹션이 read set의 ground truth. |
| `src/cowork_pilot/orchestrator_templates/phase2_auto.j2` | phase2 auto 모드 템플릿. 동일 구조. |

### 참조 (구현 시 참고하는 파일)

| 파일 | 참고 포인트 |
|------|------------|
| `src/cowork_pilot/docs_orchestrator_terminal_ui.py` | `pending_question` payload 구조 (question, options, recommended 필드). auto-answer에서 동일 payload를 읽음. |
| `src/cowork_pilot/planning/marker_protocol.py` L23-29 | `MarkerEnvelope` — `INPUT_REQUIRED` 마커의 구조 (type, stage, event_id, reason, payload). |
| `src/cowork_pilot/planning/marker_protocol.py` L39-45 | `_TYPE_REQUIRED_FIELDS` — `INPUT_REQUIRED`의 필수 필드: `(question, options, recommended, blocking)`. |
| `src/cowork_pilot/codex/command_builder.py` 전체 | `build_exec_command()`, `build_exec_resume_command()` — codex 서브프로세스 argv 빌드 패턴. 상위 에이전트 exec 명령도 이 패턴 참조. |
| `src/cowork_pilot/planning/codex_bridge.py` | `run_exec_stage()`, `run_exec_resume()` — subprocess 실행 패턴. |
| `src/cowork_pilot/codex/codex_runner.py` | `create_subprocess_runner()` — stdin으로 prompt 전달하는 패턴. |
| `src/cowork_pilot/codex/event_stream.py` | `extract_terminal_assistant_message()` — `codex exec --json` NDJSON에서 최종 assistant message 추출. |
| `src/cowork_pilot/responder.py` L21-98 | `build_applescript()` — Claude Desktop UI 입력 패턴 (v2에서 필요). |
| `src/cowork_pilot/watcher.py` L76-80 | `DIALOG_TOOLS`, `parse_jsonl_line()` — JSONL 감지 패턴 (v2에서 필요). |
| `src/cowork_pilot/main.py` L537+ | `_run_docs_orchestrator_resume()` — CLI resume wrapper. auto-answer는 이 경로를 타지 않음. |

---

## 3. 새 파일 목록

```
src/cowork_pilot/auto_answer_config.py      # AutoAnswerConfig + loader
src/cowork_pilot/auto_answer_models.py       # Phase2StepInputs, PendingQuestionPacket, UpperAgentAnswer
src/cowork_pilot/auto_answer_context.py      # resolve_phase2_step_inputs()
src/cowork_pilot/auto_answer_engines.py      # PromptMaterializer, CodexPathMaterializer, ClaudeInlineMaterializer
src/cowork_pilot/auto_answer_validator.py    # validate_upper_answer()
src/cowork_pilot/auto_answer_resolver.py     # QuestionResolver — 전체 흐름 조율
tests/test_auto_answer_context.py
tests/test_auto_answer_validator.py
tests/test_auto_answer_resolver.py
```

---

## 4. 데이터 모델

### 4.1 `AutoAnswerConfig` — `auto_answer_config.py`

```python
# src/cowork_pilot/auto_answer_config.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@dataclass
class AutoAnswerConfig:
    """[docs_orchestrator.auto_answer] 섹션에서 로드."""
    enabled: bool = False
    phase2_only: bool = True          # v1에서는 True 고정
    engine: str = "codex"             # "codex" | "claude" — 상위 에이전트 엔진
    engine_command: str = "codex"
    engine_args: list[str] = field(default_factory=list)
    timeout_seconds: float = 90.0
    max_attempts_per_event: int = 2
    allow_escalate: bool = True
    claude_max_chars: int = 120_000   # claude 모드 인라인 토큰 예산 (chars)

    # v1 하드 제한
    allowed_question_types: frozenset[str] = frozenset({"INPUT_REQUIRED"})
    require_single_select: bool = True  # options ≥ 2 + recommended 존재


def load_auto_answer_config(
    config_path: Path,
    base_engine: str = "codex",
    base_engine_command: str = "codex",
    base_engine_args: list[str] | None = None,
) -> AutoAnswerConfig:
    """config.toml의 [docs_orchestrator.auto_answer] 로드."""
    cfg = AutoAnswerConfig()

    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        aa = data.get("docs_orchestrator", {}).get("auto_answer", {})
        cfg.enabled = aa.get("enabled", cfg.enabled)
        cfg.phase2_only = aa.get("phase2_only", cfg.phase2_only)
        cfg.engine = aa.get("engine", base_engine)
        cfg.engine_command = aa.get("engine_command", base_engine_command)
        cfg.engine_args = aa.get("engine_args", base_engine_args or [])
        cfg.timeout_seconds = aa.get("timeout_seconds", cfg.timeout_seconds)
        cfg.max_attempts_per_event = aa.get("max_attempts_per_event", cfg.max_attempts_per_event)
        cfg.allow_escalate = aa.get("allow_escalate", cfg.allow_escalate)
        cfg.claude_max_chars = aa.get("claude_max_chars", cfg.claude_max_chars)

    return cfg
```

config.toml 예시:
```toml
[docs_orchestrator.auto_answer]
enabled = true
engine = "codex"          # 상위 에이전트. 하위 세션과 별개.
engine_command = "codex"
timeout_seconds = 90.0
max_attempts_per_event = 2
```

### 4.2 `Phase2StepInputs` — `auto_answer_models.py`

이 객체가 phase2 실행의 **single source of truth**.
prompt, read set, output set을 모두 여기서 파생.

```python
# src/cowork_pilot/auto_answer_models.py
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Phase2StepInputs:
    """phase2 한 step의 모든 입력을 캡슐화."""
    step_name: str
    phase_template: str                 # "phase2_auto" | "phase2_manual"
    render_kwargs: dict[str, object]    # build_session_prompt()에 넘길 kwargs
    required_inputs: list[Path]         # 항상 있어야 하고 반드시 읽는 파일
    optional_inputs: list[Path]         # 존재하면 읽는 파일
    output_files: list[Path]            # 하위 세션이 소유하는 출력 파일

    @property
    def all_existing_inputs(self) -> list[Path]:
        """실제로 존재하는 모든 입력 파일."""
        result = [p for p in self.required_inputs if p.exists()]
        result.extend(p for p in self.optional_inputs if p.exists())
        return result


@dataclass(frozen=True)
class PendingQuestionPacket:
    """상위 에이전트에 보내는 입력 단위."""
    event_id: str
    step: str
    question_text: str
    options: list[str]
    recommended: str | None
    seed_required_inputs: list[Path]
    seed_optional_inputs: list[Path]
    seed_output_files: list[Path]
    question_fingerprint: str           # sha256

    @staticmethod
    def compute_fingerprint(
        step: str, event_id: str, question: str, options: list[str],
    ) -> str:
        blob = json.dumps(
            {"step": step, "event_id": event_id,
             "question": question, "options": options},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class UpperAgentAnswer:
    """상위 에이전트의 구조화된 응답."""
    event_id: str
    question_fingerprint: str
    decision: Literal["answer", "escalate"]
    response_text: str
    selected_option: str | None         # "A", "B", "C" 등
    confidence: Literal["low", "medium", "high"]
    rationale: str


@dataclass
class AutoAnswerState:
    """runtime에 저장되는 loop guard 상태."""
    event_id: str = ""
    question_fingerprint: str = ""
    attempt_count: int = 0
    last_response_hash: str = ""
    last_selected_option: str = ""
    status: str = ""                    # "applied" | "failed" | "escalated"

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "question_fingerprint": self.question_fingerprint,
            "attempt_count": self.attempt_count,
            "last_response_hash": self.last_response_hash,
            "last_selected_option": self.last_selected_option,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AutoAnswerState:
        return cls(
            event_id=str(d.get("event_id", "")),
            question_fingerprint=str(d.get("question_fingerprint", "")),
            attempt_count=int(d.get("attempt_count", 0)),
            last_response_hash=str(d.get("last_response_hash", "")),
            last_selected_option=str(d.get("last_selected_option", "")),
            status=str(d.get("status", "")),
        )
```

### 4.3 `UpperAgentAnswer` JSON schema

상위 에이전트가 stdout으로 반환해야 하는 형식:

```json
{
  "event_id": "share_link_qr_non_goals_q2",
  "question_fingerprint": "sha256hex...",
  "decision": "answer",
  "response_text": "A. v1 Non-Goals는 ...",
  "selected_option": "A",
  "confidence": "high",
  "rationale": "현재 문서 기준으로 v1 범위를 가장 보수적으로 닫아 이후 gap-report 수렴이 쉽다."
}
```

- `event_id`: 현재 pending event와 반드시 일치
- `question_fingerprint`: 현재 pending question의 fingerprint를 그대로 echo-back
- `decision`: `"answer"` | `"escalate"` (v1에서 `"approval"` 없음)
- `response_text`: 하위 세션 resume에 넣을 최종 답변 텍스트
- `selected_option`: validator용. 실제 옵션 레이블의 첫 글자 또는 전체 문자열
- `confidence`, `rationale`: 로그용

---

## 5. Phase2 입력 객체 구성 — `auto_answer_context.py`

### 5.1 `resolve_phase2_step_inputs()`

이 함수가 phase2 template의 "읽어야 할 파일" 섹션과 **동일한 로직**으로 read set을 계산.
`_run_phase_2()`는 직접 prompt를 만들지 않고 반드시 이 함수를 통해서만 실행.

```python
# src/cowork_pilot/auto_answer_context.py
from __future__ import annotations

from pathlib import Path

from cowork_pilot.auto_answer_models import Phase2StepInputs
from cowork_pilot.orchestrator_prompts import (
    AvailableExtracts,
    compute_available_extracts,
    load_overview_reasons,
)


def resolve_phase2_step_inputs(
    *,
    project_dir: Path,
    step_name: str,
    phase_template: str,          # "phase2_auto" | "phase2_manual"
    bundle: list[tuple[str, str]],  # [(domain, feature), ...]
    extracts: AvailableExtracts,
    overview_reasons: dict[str, str],
) -> Phase2StepInputs:
    """phase2 step의 전체 입력을 하나의 객체로 계산.

    이 함수가 반환하는 Phase2StepInputs 에서:
    - render_kwargs → build_session_prompt()에 그대로 전달
    - required_inputs / optional_inputs → runtime sidecar의 question_context_seed에 저장
    - output_files → expected_files로 사용

    중요: phase2 템플릿의 "읽어야 할 파일" 섹션과 이 함수의 read set은
    반드시 동일해야 한다. 템플릿을 수정하면 이 함수도 수정해야 한다.
    """
    gen = project_dir / "docs" / "generated"
    extracts_root = gen / "domain-extracts"

    first_domain, first_feature = bundle[0]
    features_for_prompt = [{"domain": d, "feature": f} for d, f in bundle]

    # ── required_inputs: 항상 존재해야 하고 반드시 읽는 파일 ──
    required: list[Path] = [
        gen / "references" / "checklists.md",
        gen / "analysis-report.md",
        extracts_root / "shared.md",
    ]
    # bundle 내 각 feature의 extract
    for domain, feature in bundle:
        required.append(extracts_root / domain / f"{feature}.md")

    # ── optional_inputs: 존재하면 읽는 파일 ──
    optional: list[Path] = []

    # overview 파일 (extracts.overviews에서 True인 도메인)
    for d, present in extracts.overviews.items():
        if present:
            overview_path = extracts_root / d / "_overview.md"
            if overview_path not in required:
                optional.append(overview_path)

    # 기존 gap-report (같은 bundle의 이전 실행 결과)
    for domain, feature in bundle:
        gap = gen / "gap-reports" / f"{domain}--{feature}.md"
        if gap.exists():
            optional.append(gap)

    # ── output_files ──
    output_files = [
        gen / "gap-reports" / f"{domain}--{feature}.md"
        for domain, feature in bundle
    ]

    # ── render_kwargs ──
    render_kwargs: dict[str, object] = {
        "project_dir": str(project_dir),
        "features": features_for_prompt,
        "domain": first_domain,
        "feature": first_feature,
        "extracts": extracts,
        "overview_reasons": overview_reasons,
    }

    return Phase2StepInputs(
        step_name=step_name,
        phase_template=phase_template,
        render_kwargs=render_kwargs,
        required_inputs=required,
        optional_inputs=optional,
        output_files=output_files,
    )
```

### 5.2 `_run_phase_2()` 리팩토링

**변경 위치**: `docs_orchestrator.py` L977-1022

**Before** (현재 코드):
```python
# L981-1015 직접 prompt 빌드
features_for_prompt = [{"domain": d, "feature": f} for d, f in bundle]
extracts_info = compute_available_extracts(...)
overview_reasons = load_overview_reasons(project_dir)
prompt = build_session_prompt(phase_template, ...)
expected_files = _parse_expected_files(prompt)
outcome = _execute_orchestrator_step(
    step_name=step_name,
    prompt=prompt,
    prompt_phase=phase_template,
    prompt_kwargs=dict(...),
    expected_files=expected_files,
    ...
)
```

**After** (Phase2StepInputs 경유):
```python
from cowork_pilot.auto_answer_context import resolve_phase2_step_inputs

extracts_info = compute_available_extracts(
    project_dir / "docs" / "generated" / "domain-extracts"
)
overview_reasons = load_overview_reasons(project_dir)

inputs = resolve_phase2_step_inputs(
    project_dir=project_dir,
    step_name=step_name,
    phase_template=phase_template,
    bundle=bundle,
    extracts=extracts_info,
    overview_reasons=overview_reasons,
)

prompt = build_session_prompt(
    inputs.phase_template,
    **inputs.render_kwargs,
)
expected_files = _parse_expected_files(prompt)
# expected_files와 inputs.output_files가 일치하는지 assert (디버깅용)
assert set(expected_files) == set(inputs.output_files), (
    f"expected_files drift: template={expected_files}, inputs={inputs.output_files}"
)

outcome = _execute_orchestrator_step(
    step_name=step_name,
    prompt=prompt,
    prompt_phase=inputs.phase_template,
    prompt_kwargs=inputs.render_kwargs,
    expected_files=expected_files,
    watch_mode=watch_mode,
    config=config,
    orch_config=orch_config,
    project_dir=project_dir,
    base_path=base_path,
)
```

핵심: `resolve_phase2_step_inputs()`가 `_parse_expected_files()`보다 먼저 실행되고,
결과를 runtime에 저장하므로 waiting 시점에 read set이 이미 확정되어 있다.

---

## 6. Runtime Sidecar 확장

### 6.1 `_save_codex_waiting_runtime()` 변경

**변경 위치**: `docs_orchestrator.py` L1940-1962

`_save_codex_waiting_runtime()`에 `inputs: Phase2StepInputs | None` 파라미터 추가:

```python
def _save_codex_waiting_runtime(
    *,
    project_dir: Path,
    step_name: str,
    result: CodexStepResult,
    phase2_inputs: Phase2StepInputs | None = None,  # 추가
) -> None:
    """Write orchestrator-runtime.json for a waiting Codex step."""
    runtime_state = (
        "waiting_for_input"
        if result.waiting_kind == "input"
        else "waiting_for_approval"
    )
    payload: dict[str, object] = {
        "backend": "codex",
        "step": step_name,
        "runtime_state": runtime_state,
        "resume_handle": result.resume_handle,
        "resume_handle_kind": "codex_thread_id",
        "pending_event_id": result.pending_event_id or "",
        "pending_question": result.pending_question,
        "pending_approval": result.pending_approval,
    }

    # ── Auto-answer seed (phase2 전용) ──
    if phase2_inputs is not None:
        fp = ""
        pq = result.pending_question or {}
        if pq.get("question") and pq.get("options"):
            from cowork_pilot.auto_answer_models import PendingQuestionPacket
            fp = PendingQuestionPacket.compute_fingerprint(
                step=step_name,
                event_id=result.pending_event_id or "",
                question=str(pq["question"]),
                options=[str(o) for o in pq["options"]],
            )
        payload["question_context_seed"] = {
            "phase": "phase_2",
            "phase_template": phase2_inputs.phase_template,
            "required_inputs": [str(p) for p in phase2_inputs.required_inputs],
            "optional_inputs": [str(p) for p in phase2_inputs.optional_inputs],
            "output_files": [str(p) for p in phase2_inputs.output_files],
            "question_fingerprint": fp,
        }

    write_runtime(project_dir, payload)
```

### 6.2 호출부 변경

`_execute_orchestrator_step()` 내부(또는 호출 chain)에서 `_save_codex_waiting_runtime()` 호출 시
`phase2_inputs`를 전달해야 한다.

**방법 A** (간단): `_execute_orchestrator_step()`에 `phase2_inputs` optional 파라미터 추가.
phase2 step에서만 전달, 다른 phase에서는 None.

**방법 B** (정밀): `_save_codex_waiting_runtime()`을 직접 호출하는 지점에서
step_name이 `phase_2:`로 시작하면 `inputs`를 같이 넘기도록 분기.

추천: **방법 A**. `_execute_orchestrator_step()` 시그니처에 `phase2_inputs: Phase2StepInputs | None = None`을
추가하고, waiting 분기에서 그대로 전달.

### 6.3 최종 runtime payload 예시

```json
{
  "backend": "codex",
  "step": "phase_2:entry:join-code+entry:share-link-qr",
  "runtime_state": "waiting_for_input",
  "resume_handle": "thread_abc123",
  "resume_handle_kind": "codex_thread_id",
  "pending_event_id": "share_link_qr_non_goals_q2",
  "pending_question": {
    "question": "entry/share-link-qr의 v1 Non-Goals를 아래 셋 중 무엇으로 고정할지 선택해 달라.",
    "options": [
      "A. QR 이미지 다운로드/인쇄용 export, OS native share sheet, 커스텀 브랜딩/짧은 도메인/QR 스타일 편집",
      "B. ...",
      "C. ..."
    ],
    "recommended": "A. QR 이미지 다운로드/인쇄용 export, ...",
    "blocking": true
  },
  "pending_approval": null,
  "question_context_seed": {
    "phase": "phase_2",
    "phase_template": "phase2_manual",
    "required_inputs": [
      "/abs/path/docs/generated/references/checklists.md",
      "/abs/path/docs/generated/analysis-report.md",
      "/abs/path/docs/generated/domain-extracts/shared.md",
      "/abs/path/docs/generated/domain-extracts/entry/join-code.md",
      "/abs/path/docs/generated/domain-extracts/entry/share-link-qr.md"
    ],
    "optional_inputs": [
      "/abs/path/docs/generated/domain-extracts/host/_overview.md",
      "/abs/path/docs/generated/gap-reports/entry--join-code.md",
      "/abs/path/docs/generated/gap-reports/entry--share-link-qr.md"
    ],
    "output_files": [
      "/abs/path/docs/generated/gap-reports/entry--join-code.md",
      "/abs/path/docs/generated/gap-reports/entry--share-link-qr.md"
    ],
    "question_fingerprint": "sha256hex..."
  },
  "updated_at": "2026-04-12T15:30:00+00:00"
}
```

### 6.4 `docs_orchestrator_resume.py` 변경

Auto-answer는 기존 resume single-entry-point를 재사용하되, bundle phase2와
연속 질문(waiting → waiting)을 지원하도록 helper 계약을 확장해야 한다.

```python
# src/cowork_pilot/docs_orchestrator_resume.py
def _docs_resume_expected_files(step: str, project_dir: Path) -> list[Path]:
    generated = project_dir / "docs" / "generated"

    if step.startswith("phase_2:"):
        rest = step[len("phase_2:"):]
        files: list[Path] = []
        for pair in rest.split("+"):
            parts = pair.split(":", 1)
            if len(parts) != 2:
                continue
            domain, feature = parts
            files.append(generated / "gap-reports" / f"{domain}--{feature}.md")
        return files
    ...


def resume_waiting_docs_step(
    config: Config,
    orch_config: DocsOrchestratorConfig,
    *,
    response_text: str,
    response_kind: str,
    expected_files_override: list[Path] | None = None,
) -> DocsResumeOutcome:
    ...
    expected_files = (
        list(expected_files_override)
        if expected_files_override is not None
        else _docs_resume_expected_files(step, project_dir)
    )
    ...
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
        # phase2 연속 질문에서도 seed/loop-state가 유지되어야 함
        if "question_context_seed" in runtime:
            new_runtime["question_context_seed"] = runtime["question_context_seed"]
        if "auto_answer_state" in runtime:
            new_runtime["auto_answer_state"] = runtime["auto_answer_state"]
        write_runtime(project_dir, new_runtime)
        return DocsResumeOutcome(status="waiting", state=state, step=step)
```

핵심:
- `expected_files_override`는 auto-answer 경로에서만 사용.
- bundle phase2는 `phase_2:d1:f1+d2:f2`를 모두 풀어 gap-report list를 만든다.
- resume 후 또 waiting이면 기존 `question_context_seed`를 그대로 carry-forward 해야 한다.

---

## 7. 상위 에이전트 엔진 — `auto_answer_engines.py`

### 7.1 `PromptMaterializer` 프로토콜

```python
# src/cowork_pilot/auto_answer_engines.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from cowork_pilot.auto_answer_config import AutoAnswerConfig
from cowork_pilot.auto_answer_models import PendingQuestionPacket
from cowork_pilot.codex.event_stream import extract_terminal_assistant_message


class PromptMaterializer(Protocol):
    def build_prompt(self, packet: PendingQuestionPacket) -> str: ...


# ── 공통 프롬프트 헤더 ──

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
    """패킷에서 질문 섹션 텍스트 생성."""
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
    for opt in packet.options:
        lines.append(f"- {opt}")
    if packet.recommended:
        lines.append(f"\nRecommended: {packet.recommended}")
    return "\n".join(lines)
```

### 7.2 `CodexPathMaterializer`

Codex 상위 에이전트는 read-only sandbox에서 직접 파일을 읽으므로 경로만 전달.

```python
class CodexPathMaterializer:
    """Codex 상위 에이전트용: 파일 경로만 프롬프트에 포함."""

    def build_prompt(self, packet: PendingQuestionPacket) -> str:
        read_files = [
            p for p in packet.seed_required_inputs if p.exists()
        ] + [
            p for p in packet.seed_optional_inputs if p.exists()
        ]

        lines = [_SYSTEM_HEADER, "Read ONLY these files:"]
        for f in read_files:
            lines.append(f"- {f}")
        lines.append("")
        lines.append(_build_question_section(packet))
        return "\n".join(lines)
```

### 7.3 `ClaudeInlineMaterializer`

Claude `-p` 모드는 파일 시스템 접근 불가 → 파일 내용을 인라인.

```python
class ClaudeInlineMaterializer:
    """Claude 상위 에이전트용: 파일 내용을 프롬프트에 인라인."""

    def __init__(self, max_chars: int = 120_000):
        self.max_chars = max_chars

    def build_prompt(self, packet: PendingQuestionPacket) -> str | None:
        """프롬프트 생성. 예산 초과 시 None 반환 (AUTO_ANSWER_UNSUPPORTED)."""

        # 인라인 우선순위 (고정)
        ordered_paths: list[Path] = []

        # 1. checklists.md
        for p in packet.seed_required_inputs:
            if p.name == "checklists.md":
                ordered_paths.append(p)

        # 2. 현재 bundle의 feature extract
        for p in packet.seed_required_inputs:
            if p.name != "checklists.md" and p.name != "shared.md" and p.name != "analysis-report.md":
                ordered_paths.append(p)

        # 3. 기존 gap-report (optional)
        for p in packet.seed_optional_inputs:
            if "gap-reports" in str(p):
                ordered_paths.append(p)

        # 4. shared.md
        for p in packet.seed_required_inputs:
            if p.name == "shared.md":
                ordered_paths.append(p)

        # 5. overview (optional)
        for p in packet.seed_optional_inputs:
            if "_overview.md" in p.name:
                ordered_paths.append(p)

        # 6. analysis-report.md
        for p in packet.seed_required_inputs:
            if p.name == "analysis-report.md":
                ordered_paths.append(p)

        # 인라인 내용 구성
        header = _SYSTEM_HEADER + "\n" + _build_question_section(packet) + "\n\n"
        header += "=== File Contents ===\n\n"

        total = len(header)
        file_blocks: list[str] = []
        included_paths: set[Path] = set()

        for p in ordered_paths:
            if not p.exists():
                continue
            try:
                content = p.read_text(encoding="utf-8")
            except OSError:
                continue

            block = f"--- {p.name} ---\n{content}\n\n"
            if total + len(block) > self.max_chars:
                break  # 예산 초과 — 여기서 자름
            file_blocks.append(block)
            total += len(block)
            included_paths.add(p)

        # 최소 필수: 존재하는 required_inputs 전부가 인라인되어야 함.
        # 하나라도 빠지면 codex/claude 간 근거 비대칭이 생기므로 v1에서는 unsupported.
        for p in packet.seed_required_inputs:
            if p.exists() and p not in included_paths:
                return None  # AUTO_ANSWER_UNSUPPORTED

        return header + "".join(file_blocks)
```

### 7.4 엔진 실행 함수

```python
def run_upper_agent(
    prompt: str,
    cfg: AutoAnswerConfig,
    project_dir: Path,
) -> str:
    """상위 에이전트를 one-shot 실행하고 stdout을 반환.

    Raises subprocess.TimeoutExpired, subprocess.CalledProcessError.
    """
    if cfg.engine == "codex":
        cmd = [
            cfg.engine_command,
            "exec",
            "--sandbox", "read-only",
            "--skip-git-repo-check",
            "-C", str(project_dir),
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
            result.returncode, cmd, result.stdout, result.stderr,
        )

    if cfg.engine == "codex":
        event_lines = [line for line in result.stdout.splitlines() if line.strip()]
        return extract_terminal_assistant_message(event_lines).strip()

    return result.stdout.strip()
```

---

## 8. Validator — `auto_answer_validator.py`

7개 규칙. 하나라도 실패하면 자동 적용 금지.

```python
# src/cowork_pilot/auto_answer_validator.py
from __future__ import annotations

import json
from dataclasses import dataclass

from cowork_pilot.auto_answer_models import PendingQuestionPacket, UpperAgentAnswer


@dataclass
class ValidationResult:
    ok: bool
    error: str = ""
    answer: UpperAgentAnswer | None = None


def validate_upper_answer(
    raw_json: str,
    packet: PendingQuestionPacket,
) -> ValidationResult:
    """상위 에이전트 응답을 검증.

    규칙:
    1. JSON 파싱 성공
    2. event_id 일치
    3. question_fingerprint 일치
    4. decision in {"answer", "escalate"}
    5. answer면 response_text 비어 있지 않음
    6. selected_option이 실제 option set 안에 있음
    7. selected_option이 있으면 response_text가 그 option label로 시작
    """

    # 1. JSON 파싱
    try:
        data = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError) as e:
        return ValidationResult(ok=False, error=f"JSON 파싱 실패: {e}")

    if not isinstance(data, dict):
        return ValidationResult(ok=False, error="응답이 JSON object가 아님")

    # 2. event_id 일치
    if data.get("event_id") != packet.event_id:
        return ValidationResult(
            ok=False,
            error=f"event_id 불일치: expected={packet.event_id}, got={data.get('event_id')}",
        )

    # 3. question_fingerprint 일치
    if data.get("question_fingerprint") != packet.question_fingerprint:
        return ValidationResult(
            ok=False,
            error=(
                "question_fingerprint 불일치: "
                f"expected={packet.question_fingerprint}, "
                f"got={data.get('question_fingerprint')}"
            ),
        )

    # 4. decision enum
    decision = data.get("decision", "")
    if decision not in ("answer", "escalate"):
        return ValidationResult(ok=False, error=f"잘못된 decision: {decision}")

    # 5. answer면 response_text 필수
    response_text = str(data.get("response_text", "")).strip()
    if decision == "answer" and not response_text:
        return ValidationResult(ok=False, error="decision=answer인데 response_text가 비어있음")

    # 6. selected_option 검증
    selected = data.get("selected_option")
    if decision == "answer" and selected is not None:
        selected = str(selected).strip()
        # option label의 prefix (첫 글자 또는 "A.", "B." 등)와 일치하는지
        option_prefixes = _extract_option_prefixes(packet.options)
        if selected not in option_prefixes and selected not in packet.options:
            return ValidationResult(
                ok=False,
                error=f"selected_option '{selected}'가 옵션 집합에 없음. 유효: {option_prefixes}",
            )

    # 7. response_text가 selected_option label로 시작하는지
    if decision == "answer" and selected:
        selected = str(selected).strip()
        matching_option = _find_matching_option(selected, packet.options)
        if matching_option and not response_text.startswith(selected):
            # 완화된 검증: option label prefix로 시작하거나, option 본문의 핵심 부분 포함
            if not _response_matches_option(response_text, matching_option):
                return ValidationResult(
                    ok=False,
                    error=f"response_text가 selected_option '{selected}'와 불일치",
                )

    # replay/loop 방지는 validator가 아니라 loop guard의 책임.
    # validator는 "현재 질문에 대한 응답인지"만 확인한다.

    confidence = data.get("confidence", "medium")
    if confidence not in ("low", "medium", "high"):
        confidence = "medium"

    answer = UpperAgentAnswer(
        event_id=str(data["event_id"]),
        question_fingerprint=str(data["question_fingerprint"]),
        decision=decision,
        response_text=response_text,
        selected_option=str(selected) if selected else None,
        confidence=confidence,
        rationale=str(data.get("rationale", "")),
    )

    return ValidationResult(ok=True, answer=answer)


def _extract_option_prefixes(options: list[str]) -> set[str]:
    """옵션 목록에서 prefix set 추출. "A. xxx" → {"A", "A."} """
    prefixes: set[str] = set()
    for opt in options:
        opt = opt.strip()
        if len(opt) >= 2 and opt[1] in (".", ")"):
            prefixes.add(opt[0])
            prefixes.add(opt[:2])
        if opt:
            prefixes.add(opt)  # 전체 옵션 텍스트도 허용
    return prefixes


def _find_matching_option(selected: str, options: list[str]) -> str | None:
    """selected_option에 매칭되는 전체 옵션 텍스트 반환."""
    for opt in options:
        opt_stripped = opt.strip()
        if opt_stripped.startswith(selected):
            return opt_stripped
        if len(selected) == 1 and len(opt_stripped) >= 2 and opt_stripped[0] == selected:
            return opt_stripped
    return None


def _response_matches_option(response_text: str, option_text: str) -> bool:
    """response_text가 option_text와 실질적으로 일치하는지 (완화된 검증)."""
    # option label prefix (A, B, C 등)로 시작
    if option_text and response_text.startswith(option_text[0]):
        return True
    # option 본문의 처음 20자가 response_text에 포함
    option_body = option_text[3:].strip() if len(option_text) > 3 else option_text
    if option_body and option_body[:20] in response_text:
        return True
    return False
```

---

## 9. QuestionResolver — `auto_answer_resolver.py`

전체 흐름을 조율하는 핵심 모듈.

```python
# src/cowork_pilot/auto_answer_resolver.py
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from cowork_pilot.auto_answer_config import AutoAnswerConfig
from cowork_pilot.auto_answer_engines import (
    ClaudeInlineMaterializer,
    CodexPathMaterializer,
    run_upper_agent,
)
from cowork_pilot.auto_answer_models import (
    AutoAnswerState,
    PendingQuestionPacket,
)
from cowork_pilot.auto_answer_validator import validate_upper_answer
from cowork_pilot.config import Config, DocsOrchestratorConfig
from cowork_pilot.docs_orchestrator_resume import (
    DocsResumeOutcome,
    resume_waiting_docs_step,
)
from cowork_pilot.docs_orchestrator_runtime import load_runtime, write_runtime

logger = logging.getLogger(__name__)


# ── 결과 타입 ──

class AutoAnswerResult:
    """자동 응답 시도의 결과."""
    def __init__(
        self,
        status: str,  # "applied" | "escalated" | "unsupported" | "failed"
        outcome: DocsResumeOutcome | None = None,
        reason: str = "",
    ):
        self.status = status
        self.outcome = outcome
        self.reason = reason


# ── Packet Builder ──

def _build_packet_from_runtime(
    runtime: dict[str, object],
) -> PendingQuestionPacket | None:
    """runtime payload에서 PendingQuestionPacket 생성.

    v1 범위 검증도 여기서 수행:
    - phase_2 step만
    - INPUT_REQUIRED만 (waiting_for_input)
    - single-select만 (options ≥ 2, recommended 존재)
    """
    step = str(runtime.get("step", ""))
    if not step.startswith("phase_2:"):
        return None  # phase2 아님

    state = str(runtime.get("runtime_state", ""))
    if state != "waiting_for_input":
        return None  # approval 등은 v1 미지원

    pq = runtime.get("pending_question")
    if not isinstance(pq, dict):
        return None

    question = str(pq.get("question", "")).strip()
    raw_options = pq.get("options", [])
    if not isinstance(raw_options, (list, tuple)):
        return None
    options = [str(o) for o in raw_options]

    # single-select 검증: options ≥ 2, recommended 존재
    recommended = str(pq.get("recommended", "")).strip() or None
    if len(options) < 2 or not recommended:
        return None  # 자유 텍스트 또는 선택지 부족

    event_id = str(runtime.get("pending_event_id", ""))

    # seed에서 read files 가져오기
    seed = runtime.get("question_context_seed", {})
    if not isinstance(seed, dict):
        return None

    required = [Path(p) for p in seed.get("required_inputs", [])]
    optional = [Path(p) for p in seed.get("optional_inputs", [])]
    output_files = [Path(p) for p in seed.get("output_files", [])]
    seed_fp = str(seed.get("question_fingerprint", "")).strip()

    fp = PendingQuestionPacket.compute_fingerprint(step, event_id, question, options)
    if seed_fp and seed_fp != fp:
        return None  # runtime seed와 현재 질문이 불일치 → stale runtime

    return PendingQuestionPacket(
        event_id=event_id,
        step=step,
        question_text=question,
        options=options,
        recommended=recommended,
        seed_required_inputs=required,
        seed_optional_inputs=optional,
        seed_output_files=output_files,
        question_fingerprint=fp,
    )


# ── Loop Guard ──

def _check_loop_guard(
    runtime: dict[str, object],
    packet: PendingQuestionPacket,
    response_hash: str,
) -> str | None:
    """loop guard 검사. 문제 있으면 에러 메시지 반환, 없으면 None."""
    aas = runtime.get("auto_answer_state", {})
    if not isinstance(aas, dict):
        return None

    prev = AutoAnswerState.from_dict(aas)

    # 같은 event_id + 같은 fingerprint + 같은 response_hash → loop
    if (
        prev.event_id == packet.event_id
        and prev.question_fingerprint == packet.question_fingerprint
        and prev.last_response_hash == response_hash
        and prev.status == "applied"
    ):
        return "loop detected: same event_id + fingerprint + response"

    # 같은 event_id + 같은 fingerprint + attempt_count 초과
    if (
        prev.event_id == packet.event_id
        and prev.question_fingerprint == packet.question_fingerprint
    ):
        # fingerprint 같으면 같은 질문
        if prev.attempt_count >= 2:  # max_attempts_per_event 기본값
            return f"max attempts reached for event {packet.event_id}"

    return None


# ── 로그 ──

def _write_log(project_dir: Path, entry: dict[str, object]) -> None:
    """logs/auto-answer.jsonl에 한 줄 추가."""
    log_dir = project_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "auto-answer.jsonl"
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 메인 진입점 ──

def try_auto_answer(
    config: Config,
    orch_config: DocsOrchestratorConfig,
    aa_config: AutoAnswerConfig,
    project_dir: Path,
) -> AutoAnswerResult:
    """waiting 상태의 runtime에 대해 자동 응답 시도.

    호출 시점: _run_phase_2()에서 outcome.kind == "waiting" 직후.
    또는 _resolve_waiting_runtime_interactively() 대신 호출.

    Returns:
        AutoAnswerResult
        - "applied": 성공. outcome에 DocsResumeOutcome 포함.
        - "escalated": 상위 에이전트가 escalate 결정.
        - "unsupported": v1 범위 밖 질문.
        - "failed": validator 실패 또는 subprocess 에러.
    """
    if not aa_config.enabled:
        return AutoAnswerResult(status="unsupported", reason="auto-answer disabled")

    # 1. runtime 로드
    runtime = load_runtime(project_dir)
    if runtime is None:
        return AutoAnswerResult(status="failed", reason="no runtime found")

    # 2. packet 생성 (v1 범위 검증 포함)
    packet = _build_packet_from_runtime(runtime)
    if packet is None:
        return AutoAnswerResult(status="unsupported", reason="question not eligible for auto-answer")

    # 3. materializer 선택
    if aa_config.engine == "codex":
        materializer = CodexPathMaterializer()
    elif aa_config.engine == "claude":
        materializer = ClaudeInlineMaterializer(max_chars=aa_config.claude_max_chars)
    else:
        return AutoAnswerResult(status="failed", reason=f"unknown engine: {aa_config.engine}")

    prompt = materializer.build_prompt(packet)
    if prompt is None:
        return AutoAnswerResult(status="unsupported", reason="claude mode: input files exceed token budget")

    # 4. loop guard 검사 (사전)
    # response_hash는 아직 모르므로 attempt_count만 체크
    aas = runtime.get("auto_answer_state", {})
    if isinstance(aas, dict):
        prev = AutoAnswerState.from_dict(aas)
        if (
            prev.event_id == packet.event_id
            and prev.question_fingerprint == packet.question_fingerprint
            and prev.attempt_count >= aa_config.max_attempts_per_event
        ):
            return AutoAnswerResult(
                status="failed",
                reason=f"max attempts ({aa_config.max_attempts_per_event}) reached",
            )

    # 5. 상위 에이전트 실행
    try:
        raw_output = run_upper_agent(prompt, aa_config, project_dir)
    except Exception as e:
        _write_log(project_dir, {
            "step": packet.step, "event_id": packet.event_id,
            "upper_engine": aa_config.engine, "error": str(e), "result": "failed",
        })
        return AutoAnswerResult(status="failed", reason=f"upper agent failed: {e}")

    # 6. validate
    vr = validate_upper_answer(raw_output, packet)
    if not vr.ok:
        _write_log(project_dir, {
            "step": packet.step, "event_id": packet.event_id,
            "upper_engine": aa_config.engine, "validation_error": vr.error,
            "raw_output": raw_output[:500], "result": "failed",
        })
        # attempt_count 증가
        _update_auto_answer_state(
            project_dir, runtime, packet,
            response_hash="", status="failed", selected_option="",
        )
        return AutoAnswerResult(status="failed", reason=f"validation failed: {vr.error}")

    answer = vr.answer
    assert answer is not None

    # 7. escalate 처리
    if answer.decision == "escalate":
        _write_log(project_dir, {
            "step": packet.step, "event_id": packet.event_id,
            "upper_engine": aa_config.engine, "decision": "escalate",
            "rationale": answer.rationale, "result": "escalated",
        })
        _update_auto_answer_state(
            project_dir, runtime, packet,
            response_hash="", status="escalated", selected_option="",
        )
        return AutoAnswerResult(status="escalated", reason=answer.rationale)

    # 8. loop guard 검사 (사후 — response_hash 포함)
    resp_hash = hashlib.sha256(answer.response_text.encode("utf-8")).hexdigest()
    loop_error = _check_loop_guard(runtime, packet, resp_hash)
    if loop_error:
        _write_log(project_dir, {
            "step": packet.step, "event_id": packet.event_id,
            "loop_error": loop_error, "result": "failed",
        })
        return AutoAnswerResult(status="failed", reason=loop_error)

    # 9. 하위 세션 resume
    try:
        outcome = resume_waiting_docs_step(
            config,
            orch_config,
            response_text=answer.response_text,
            response_kind="answer",
            expected_files_override=list(packet.seed_output_files),
        )
    except RuntimeError as e:
        _write_log(project_dir, {
            "step": packet.step, "event_id": packet.event_id,
            "resume_error": str(e), "result": "failed",
        })
        return AutoAnswerResult(status="failed", reason=f"resume failed: {e}")

    # 10. auto_answer_state 갱신
    _update_auto_answer_state(
        project_dir, load_runtime(project_dir) or {}, packet,
        response_hash=resp_hash, status="applied",
        selected_option=answer.selected_option or "",
    )

    # 11. 로그
    _write_log(project_dir, {
        "step": packet.step,
        "event_id": packet.event_id,
        "source": "docs_runtime",
        "upper_engine": aa_config.engine,
        "read_files": [str(p) for p in packet.seed_required_inputs + packet.seed_optional_inputs],
        "decision": answer.decision,
        "selected_option": answer.selected_option,
        "response_text": answer.response_text[:200],
        "confidence": answer.confidence,
        "rationale": answer.rationale,
        "applied_via": "docs_resume",
        "result": outcome.status,
    })

    return AutoAnswerResult(status="applied", outcome=outcome)


def _update_auto_answer_state(
    project_dir: Path,
    runtime: dict[str, object],
    packet: PendingQuestionPacket,
    *,
    response_hash: str,
    status: str,
    selected_option: str,
) -> None:
    """runtime에 auto_answer_state 갱신."""
    prev_aas = runtime.get("auto_answer_state", {})
    if not isinstance(prev_aas, dict):
        prev_aas = {}
    prev = AutoAnswerState.from_dict(prev_aas)

    # fingerprint가 바뀌면 새 질문 → attempt reset
    if prev.question_fingerprint != packet.question_fingerprint:
        new_attempt = 1
    else:
        new_attempt = prev.attempt_count + 1

    new_state = AutoAnswerState(
        event_id=packet.event_id,
        question_fingerprint=packet.question_fingerprint,
        attempt_count=new_attempt,
        last_response_hash=response_hash,
        last_selected_option=selected_option,
        status=status,
    )

    # runtime이 아직 존재하면 auto_answer_state만 업데이트
    current = load_runtime(project_dir)
    if current is not None:
        current["auto_answer_state"] = new_state.to_dict()
        write_runtime(project_dir, current)
```

---

## 10. 연결 지점 — `_run_phase_2()` 수정

**변경 위치**: `docs_orchestrator.py` L1023-1028

현재 코드:
```python
if outcome.kind == "waiting":
    return state
```

변경 후:
```python
if outcome.kind == "waiting":
    # ── Auto-answer 시도 ──
    from cowork_pilot.auto_answer_config import load_auto_answer_config
    from cowork_pilot.auto_answer_resolver import try_auto_answer

    aa_config = load_auto_answer_config(
        Path(config.project_dir) / "config.toml",
        base_engine=config.engine,
        base_engine_command=config.codex_command if config.engine == "codex" else config.claude_command,
    )

    if aa_config.enabled:
        aa_result = try_auto_answer(config, orch_config, aa_config, project_dir)

        if aa_result.status == "applied" and aa_result.outcome:
            if aa_result.outcome.status == "completed":
                # resume_waiting_docs_step()가 이미 state 갱신 + save + clear_runtime 완료
                state = aa_result.outcome.state
                continue  # 다음 bundle로

            if aa_result.outcome.status == "waiting":
                # 또 다른 질문 → 다시 auto-answer 시도 (재귀 대신 loop)
                # 이 부분은 아래 10.1절 참조
                pass

            if aa_result.outcome.status == "failed":
                return _update_state_error(
                    state, step_name,
                    aa_result.outcome.error or "auto-answer resume failed",
                )

        # unsupported / escalated / failed → 기존 동작 (human 대기)
    return state
```

### 10.1 연속 질문 처리 (auto-answer loop)

하위 세션이 resume 후 또 다른 질문을 낼 수 있음.
`_run_phase_2()`의 waiting 분기를 loop로 변경:

```python
if outcome.kind == "waiting":
    aa_config = load_auto_answer_config(...)

    if aa_config.enabled:
        max_auto_rounds = 10  # 무한 loop 방지
        for _round in range(max_auto_rounds):
            aa_result = try_auto_answer(config, orch_config, aa_config, project_dir)

            if aa_result.status != "applied" or aa_result.outcome is None:
                break  # human 필요

            if aa_result.outcome.status == "completed":
                # resume helper가 최신 state를 single source of truth로 반환
                state = aa_result.outcome.state
                break

            if aa_result.outcome.status == "failed":
                return _update_state_error(
                    state, step_name,
                    aa_result.outcome.error or "auto-answer resume failed",
                )

            # outcome.status == "waiting" → loop 계속
            continue
        else:
            # max_auto_rounds 도달 — human 필요
            pass

        # completed면 다음 bundle로 continue
        if aa_result.status == "applied" and aa_result.outcome and aa_result.outcome.status == "completed":
            continue

    return state  # human 대기
```

---

## 11. 구현 순서

| # | 작업 | 산출물 | 의존 |
|---|------|--------|------|
| 1 | `AutoAnswerConfig` + loader | `auto_answer_config.py` | 없음 |
| 2 | `Phase2StepInputs`, `PendingQuestionPacket`, `UpperAgentAnswer`, `AutoAnswerState` | `auto_answer_models.py` | 없음 |
| 3 | `resolve_phase2_step_inputs()` | `auto_answer_context.py` | #2, `orchestrator_prompts.py` |
| 4 | `_run_phase_2()` 리팩토링 — `Phase2StepInputs` 경유 | `docs_orchestrator.py` 변경 | #3 |
| 5 | `_save_codex_waiting_runtime()` 확장 — `question_context_seed` 저장 | `docs_orchestrator.py` 변경 | #2, #4 |
| 6 | `resume_waiting_docs_step()` 확장 — `expected_files_override`, bundle phase2, seed carry-forward | `docs_orchestrator_resume.py` 변경 | #2, #5 |
| 7 | `CodexPathMaterializer` + `ClaudeInlineMaterializer` | `auto_answer_engines.py` | #2 |
| 8 | `run_upper_agent()` (`event_stream` 파서 재사용) | `auto_answer_engines.py` | #1, #7 |
| 9 | `validate_upper_answer()` | `auto_answer_validator.py` | #2 |
| 10 | Loop guard (`AutoAnswerState`, `_check_loop_guard`) | `auto_answer_resolver.py` | #2 |
| 11 | `try_auto_answer()` (전체 조율) | `auto_answer_resolver.py` | #6, #7, #8, #9, #10 |
| 12 | `_run_phase_2()` waiting 분기에 auto-answer 연결 | `docs_orchestrator.py` 변경 | #11 |
| 13 | 로그 (`auto-answer.jsonl`) | `auto_answer_resolver.py` | #11 |
| 14 | 테스트 작성 | `tests/test_auto_answer_*.py` | 전체 |

---

## 12. 테스트 명세

### 12.1 `test_auto_answer_context.py`

```python
def test_resolve_phase2_step_inputs_read_set_matches_template():
    """Phase2StepInputs.required_inputs가 phase2_manual.j2의 '읽어야 할 파일' 섹션과 일치."""
    # setup: 임시 project_dir에 필요한 파일 생성
    # act: resolve_phase2_step_inputs() 호출
    # act: build_session_prompt() + 정규식으로 "읽어야 할 파일" 파싱
    # assert: 두 집합이 동일

def test_resolve_phase2_step_inputs_optional_gap_report():
    """기존 gap-report가 있으면 optional_inputs에 포함."""

def test_resolve_phase2_step_inputs_bundle_multiple_features():
    """2-feature bundle의 required_inputs에 두 feature extract 포함."""
```

### 12.2 `test_auto_answer_validator.py`

```python
def test_valid_answer_passes():
    """정상 JSON → ok=True, answer 파싱 성공."""

def test_wrong_event_id_fails():
    """event_id 불일치 → ok=False."""

def test_invalid_json_fails():
    """파싱 불가 → ok=False."""

def test_option_mismatch_fails():
    """selected_option이 실제 옵션에 없음 → ok=False."""

def test_empty_response_text_fails():
    """decision=answer, response_text="" → ok=False."""

def test_escalate_passes():
    """decision=escalate → ok=True, answer.decision="escalate"."""

def test_response_text_option_prefix_mismatch():
    """selected_option=A인데 response_text가 B로 시작 → ok=False."""

def test_question_fingerprint_mismatch_fails():
    """question_fingerprint 불일치 → ok=False."""
```

### 12.3 `test_auto_answer_resolver.py`

```python
def test_codex_waiting_to_applied(monkeypatch):
    """codex waiting → packet 생성 → upper answer → resume 호출 → applied."""
    # monkeypatch: run_upper_agent → 고정 JSON 반환
    # monkeypatch: resume_waiting_docs_step → completed 반환
    # assert: result.status == "applied"

def test_unsupported_non_phase2():
    """phase_1 step → unsupported."""

def test_unsupported_free_text():
    """options=[], recommended=None → unsupported."""

def test_loop_guard_blocks_repeat():
    """같은 event_id + fingerprint + response_hash → failed (loop)."""

def test_max_attempts_blocks():
    """attempt_count >= max → failed."""

def test_escalate_returns_escalated(monkeypatch):
    """upper agent가 escalate → result.status == "escalated"."""

def test_runtime_question_context_seed_saved():
    """_save_codex_waiting_runtime에 phase2_inputs 전달 시 seed 저장 확인."""

def test_resume_waiting_carries_forward_question_context_seed(monkeypatch):
    """resume 후 또 waiting이면 기존 question_context_seed가 새 runtime에도 유지."""

def test_docs_resume_expected_files_bundle():
    """phase_2:d1:f1+d2:f2 → 두 gap-report path 모두 반환."""
```

---

## 13. Acceptance Criteria

이 6개가 모두 통과해야 설계가 닫힌 것.

| # | 기준 | 검증 방법 |
|---|------|----------|
| 1 | phase2 waiting 시 runtime에 `question_context_seed`가 항상 기록된다 | `test_runtime_question_context_seed_saved` |
| 2 | same step, same bundle, same question에서 upper-agent input이 deterministic하다 | `test_resolve_phase2_step_inputs_read_set_matches_template` |
| 3 | upper-agent가 stale event/fingerprint에 답하면 validator가 막는다 | `test_wrong_event_id_fails`, `test_question_fingerprint_mismatch_fails` |
| 4 | Codex lower backend에서 auto-answer 후 실제 gap-report가 변경된다 | `test_codex_waiting_to_applied` (통합) |
| 5 | 같은 질문에 같은 응답이 반복 적용되면 human handoff로 멈춘다 | `test_loop_guard_blocks_repeat` |
| 6 | resume 후 또 waiting이어도 seed가 보존되어 다음 auto-answer가 가능하다 | `test_resume_waiting_carries_forward_question_context_seed` |

---

## 14. config.toml 전체 예시

```toml
[engine]
default = "codex"
[engine.codex]
command = "codex"

[docs_orchestrator]
docs_mode = "manual"
interactive_resume = false

[docs_orchestrator.auto_answer]
enabled = true
engine = "codex"
engine_command = "codex"
timeout_seconds = 90.0
max_attempts_per_event = 2
# claude_max_chars = 120000  # claude 모드 전용
```

---

## 15. 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────┐
│ _run_phase_2()                                          │
│                                                         │
│  resolve_phase2_step_inputs()                           │
│       │                                                 │
│       ▼                                                 │
│  Phase2StepInputs ──────┐                               │
│       │                 │                               │
│       ▼                 ▼                               │
│  build_session_prompt() │  _save_codex_waiting_runtime()│
│       │                 │  + question_context_seed      │
│       ▼                 │                               │
│  codex exec (하위)      │                               │
│       │                 │                               │
│  ┌────┴────┐            │                               │
│  │ waiting │            │                               │
│  └────┬────┘            │                               │
│       │                 │                               │
│       ▼                 │                               │
│  try_auto_answer() ◄────┘                               │
│       │                                                 │
│       ├─ _build_packet_from_runtime()                   │
│       │       ▼                                         │
│       │  PendingQuestionPacket                          │
│       │                                                 │
│       ├─ materializer.build_prompt()                    │
│       │  (CodexPath / ClaudeInline)                     │
│       │                                                 │
│       ├─ run_upper_agent()                              │
│       │  (codex exec --sandbox read-only / claude -p)   │
│       │       ▼                                         │
│       │  raw JSON stdout                                │
│       │                                                 │
│       ├─ validate_upper_answer()                        │
│       │       ▼                                         │
│       │  UpperAgentAnswer                               │
│       │                                                 │
│       ├─ _check_loop_guard()                            │
│       │                                                 │
│       ├─ resume_waiting_docs_step()                     │
│       │  (기존 resume 경로 재사용)                      │
│       │       ▼                                         │
│       │  DocsResumeOutcome                              │
│       │                                                 │
│       └─ _write_log()                                   │
│                                                         │
│  outcome: applied / escalated / unsupported / failed    │
└─────────────────────────────────────────────────────────┘
```

---

## 16. 주의사항

1. **`resolve_phase2_step_inputs()`와 phase2 템플릿의 동기화가 가장 중요하다.**
   템플릿의 "읽어야 할 파일" 섹션을 수정하면 반드시 이 함수도 수정해야 한다.
   테스트 `test_resolve_phase2_step_inputs_read_set_matches_template`이 이를 감지한다.

2. **`_execute_orchestrator_step()` 시그니처 변경은 최소화.**
   `phase2_inputs: Phase2StepInputs | None = None` 하나만 추가.
   다른 phase에서는 None으로 전달하므로 기존 동작에 영향 없음.

3. **auto_answer_state와 runtime의 write 충돌.**
   `auto_answer_state`는 runtime JSON 안에 nested dict로 저장.
   `_update_auto_answer_state()`는 `load_runtime()` → 수정 → `write_runtime()`으로 atomic update.
   resume 후 runtime이 clear된 경우(completed) `_update_auto_answer_state()` 호출 불필요 — applied 로그만 남기면 됨.

4. **Codex upper-agent는 기존 NDJSON 파서를 재사용해야 한다.**
   `event_stream.extract_terminal_assistant_message()`를 그대로 써서
   `response_item`, `event_msg.task_complete`, `event_msg.agent_message` 우선순위를 일치시킨다.
   새 NDJSON 파서를 로컬로 다시 만들지 않는다.

5. **Claude 상위 에이전트는 required_inputs 전부가 들어가야만 허용.**
   `analysis-report.md`, `shared.md`가 예산 초과로 잘리면 `unsupported`로 빠진다.
   codex/claude 간 근거 비대칭을 허용하지 않는다.

6. **Claude 상위 에이전트의 JSON-only 출력 보장.**
   `claude -p`는 프롬프트에서 "Output EXACTLY one JSON object"라고 지시하지만
   보장은 안 됨. validator가 JSON 파싱 실패를 처리하므로 재시도로 커버.
