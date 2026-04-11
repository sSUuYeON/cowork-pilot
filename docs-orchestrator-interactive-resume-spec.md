# docs-orchestrator Interactive Resume 구현 스펙

## 개요

핵심은 `docs-orchestrator`가 `waiting` 상태가 됐을 때 프로세스를 끝내지 말고, 같은 터미널에서 `input()`으로 답을 받아 즉시 `codex exec resume`를 호출하는 루프를 넣는 것이다. Claude Desktop 경로는 건드리지 않고, Codex 경로에만 붙인다.

---

## 원칙 (Principles)

1. `run_docs_orchestrator()` 안에서는 절대 CLI wrapper를 직접 부르지 않는다.
   현재 [main.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/main.py#L602)의 `_run_docs_orchestrator_resume()`는 `sys.exit()`와 `run_docs_orchestrator()` 재호출이 들어 있어서, 같은 프로세스 interactive loop에서 재사용하면 꼬인다.
2. 그래서 `resume` 로직을 "순수 함수 helper"로 분리해야 한다.
3. interactive prompt는 planning 쪽 패턴을 그대로 따라가되, planning 모듈을 억지로 재사용하지 말고 docs 전용 UI helper를 하나 만드는 게 가장 안전하다.

---

## MUST Rules (절대 규칙)

### MUST 1. Interactive loop safety

`_resolve_waiting_runtime_interactively(...)`는 무한 루프를 돌면 안 된다. `max_interactive_resumes` 기본값을 `20`으로 두고, same-process interactive resume를 시도할 때마다 카운트를 1씩 올린다. 사용자가 `EOF` 또는 `Ctrl-C`를 보내면 UI 레이어가 `None`을 반환하고 helper는 즉시 종료한다. 카운트가 상한을 넘기면 helper는 더 이상 resume를 시도하지 않고 pause로 빠진다. `cancelled` 상태값은 만들지 않고, "UI가 `None` 반환 -> 호출자가 pause 처리" 규약으로 고정한다.

### MUST 2. Failed handling is mandatory return

interactive helper가 `failed`를 돌려주면 caller는 무조건 `return outcome.state` 해야 한다. `continue`는 금지한다. runtime은 이미 `failed`로 기록되어 있으므로, 같은 프로세스에서 다음 step으로 넘어가거나 같은 loop를 더 돌리면 state/runtime 일관성이 깨진다. 이 규칙은 startup waiting 처리와 phase-after-step waiting 처리에 동일하게 적용한다.

### MUST 3. Response contract

`response_kind="answer"`일 때 `response_text`는 사용자가 직접 입력한 자유 텍스트 또는 선택지 텍스트다. `response_kind="approval"`일 때 `response_text`는 오직 `"approved"` 또는 `"rejected"`만 허용한다. docs terminal UI helper는 approval prompt에서 반드시 이 둘 중 하나만 만들어 넘긴다. lower layer인 `resume_codex_step()`은 이 문자열을 opaque 값으로 취급하고 별도 파싱 로직을 가지지 않는다.

### MUST 4. Helper return state is the single source of truth

`resume_waiting_docs_step()`와 `_resolve_waiting_runtime_interactively()`는 항상 최신 `OrchestratorState`를 반환해야 한다. caller는 추가 `load_state()`를 하지 말고 반드시 `state = outcome.state` 또는 `state = returned_state`로 덮어쓴다. startup branch와 phase branch 모두 이 규칙을 동일하게 따른다. 같은 실행 경로 안에서는 "파일을 다시 읽은 state"가 아니라 "helper가 반환한 state"가 진실원이다.

### MUST 5. CLI wrapper must not own the loop

`_run_docs_orchestrator_resume()`는 one-shot wrapper다. interactive가 켜져 있고 `--response`가 비어 있으면 터미널 prompt를 한 번 띄우는 것은 허용하지만, waiting이 다시 나왔다고 loop를 돌리면 안 된다. loop는 오직 `run_docs_orchestrator()` 본체만 소유한다. `_run_docs_orchestrator_resume()`는 `completed`면 `run_docs_orchestrator()`를 한 번 재호출하고, `waiting`이면 메시지만 출력하고 종료하고, `failed`면 에러를 출력하고 종료한다.

---

## Chunk 1: 설정과 CLI 연결

### 목표
`DocsOrchestratorConfig`에 `interactive_resume` 설정을 추가하고, 기존 `--interactive-resume` CLI 플래그를 docs-orchestrator branch에도 연결한다.

### 변경 파일
- `src/cowork_pilot/config.py`
- `src/cowork_pilot/main.py`

### 상세 내용

1. [config.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/config.py#L103)의 `DocsOrchestratorConfig`에 `interactive_resume: bool = False`를 추가한다.
2. [main.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/main.py#L781)의 `--interactive-resume`는 이미 있으니 새 플래그를 만들지 말고 그대로 재사용한다.
3. [main.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/main.py#L781) help 문구를 planning 전용 설명에서 "planning / docs-orchestrator resume에 사용"으로 바꾼다.
4. [main.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/main.py#L802) docs-orchestrator branch에서 `orch_config.interactive_resume = _should_use_interactive_resume(args.interactive_resume)`를 넣는다.
5. 의미는 이거다.
   - `auto`: 현재 터미널이 TTY면 interactive
   - `always`: 무조건 interactive
   - `never`: 지금처럼 waiting에서 멈추고 수동 `resume` 필요

### 완료 조건
- `DocsOrchestratorConfig.interactive_resume` 필드가 기본값 `False`로 존재한다.
- `--interactive-resume` 플래그가 docs-orchestrator 모드에서도 파싱되어 `orch_config.interactive_resume`에 반영된다.
- help 문구에 planning과 docs-orchestrator 양쪽에 적용됨이 명시되어 있다.

---

## Chunk 2: 순수 resume helper 분리

### 목표
resume 상태 변경 로직을 순수 함수로 분리해, print/sys.exit/재귀 호출 없는 재사용 가능한 helper를 만든다.

### 변경 파일
- 새 파일: `src/cowork_pilot/docs_orchestrator_resume.py`
- 수정: `src/cowork_pilot/main.py` (`_docs_resume_expected_files` 제거)

### 상세 내용

새 파일 [docs_orchestrator_resume.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator_resume.py)를 만든다.

여기에 3개를 둔다.

#### 2-1. `DocsResumeOutcome` dataclass
- `status: Literal["completed", "waiting", "failed"]`
- `state: OrchestratorState`
- `step: str`
- `error: str = ""`

#### 2-2. `_docs_resume_expected_files(step: str, project_dir: Path) -> list[Path]`
- 지금 [main.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/main.py#L537)에 있는 helper를 그대로 옮긴다.
- `main.py`에서 제거하고 이 모듈만 진실원으로 쓴다.

#### 2-3. `resume_waiting_docs_step(config, orch_config, *, response_text: str, response_kind: str) -> DocsResumeOutcome`

알고리즘은 정확히 이 순서다.

- `project_dir = Path(config.project_dir)`
- runtime 로드
- runtime 없으면 `RuntimeError`
- waiting 상태 아니면 `RuntimeError`
- `resume_handle` 없으면 `RuntimeError`
- `step = runtime["step"]`
- state 로드
- `expected_files = _docs_resume_expected_files(step, project_dir)`
- [docs_orchestrator_codex.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator_codex.py#L228)의 `resume_codex_step(...)` 호출
- `completed`면:
  - `_update_state_completed(...)`
  - `save_state(...)`
  - `clear_runtime(...)`
  - `return DocsResumeOutcome(status="completed", state=updated_state, step=step)`
- `waiting`이면:
  - 새 runtime payload 작성
  - `write_runtime(...)`
  - state는 건드리지 않음
  - `return DocsResumeOutcome(status="waiting", state=state, step=step)`
- `failed`면:
  - `_update_state_error(...)`
  - `save_state(...)`
  - runtime `runtime_state = "failed"`로 다시 기록
  - `return DocsResumeOutcome(status="failed", state=updated_state, step=step, error=result.error)`

중요:
- 여기서는 `print` 하지 않는다.
- `sys.exit` 하지 않는다.
- `run_docs_orchestrator()`를 다시 호출하지 않는다.

### 완료 조건
- `docs_orchestrator_resume.py`에 3개 심볼(`DocsResumeOutcome`, `_docs_resume_expected_files`, `resume_waiting_docs_step`)이 정의되어 있다.
- `main.py`의 기존 `_docs_resume_expected_files`는 제거되고, import로 새 모듈을 참조한다.
- helper 안에 `print`, `sys.exit`, `run_docs_orchestrator()` 호출이 **전혀** 없다.
- 세 가지 status 경로(completed / waiting / failed) 전부에서 최신 state가 반환된다 (MUST 4).

---

## Chunk 3: 터미널 입력 UI 추가

### 목표
waiting runtime payload를 받아 터미널에서 사용자 입력을 받는 docs 전용 UI helper를 만든다.

### 변경 파일
- 새 파일: `src/cowork_pilot/docs_orchestrator_terminal_ui.py`

### 상세 내용

새 파일 [docs_orchestrator_terminal_ui.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator_terminal_ui.py)를 만든다.

planning의 [terminal_ui.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/planning/terminal_ui.py#L1)를 거의 그대로 따라가면 된다.

구성은 이 정도면 충분하다.

#### 3-1. `TerminalResponse` dataclass
- `text: str`
- `kind: str` (`"answer"` | `"approval"`)

#### 3-2. `prompt_from_runtime_payload(runtime_payload: dict[str, object], input_fn=None) -> TerminalResponse | None`
- `runtime_state == "waiting_for_input"`이면 `pending_question` 기반으로 질문
- `runtime_state == "waiting_for_approval"`이면 `pending_approval` 기반으로 질문
- 아니면 `None`

#### 3-3. `_prompt_question(...)`
- 질문 문구 출력
- options 있으면 번호 출력
- recommended 있으면 Enter 기본값
- 숫자 입력이면 해당 option text 반환
- 임의 텍스트면 그대로 반환
- `EOFError` / `KeyboardInterrupt`면 `None`

#### 3-4. `_prompt_approval(...)`
- `Approval required: {subject}` 출력
- `Approve? [y/n]: `
- `y/yes -> TerminalResponse("approved", "approval")`
- `n/no -> TerminalResponse("rejected", "approval")`
- EOF / Ctrl-C -> `None`

### 완료 조건
- `docs_orchestrator_terminal_ui.py`에 4개 심볼(`TerminalResponse`, `prompt_from_runtime_payload`, `_prompt_question`, `_prompt_approval`)이 정의되어 있다.
- approval path는 MUST 3에 따라 `"approved"` 또는 `"rejected"`만 만들어 낸다.
- EOF/Ctrl-C에서 반드시 `None`을 반환한다 (MUST 1의 취소 경로).
- planning의 `terminal_ui.py`를 import하거나 재사용하지 않는다 (원칙 3).

---

## Chunk 4: docs-orchestrator 본체에 interactive loop 추가

### 목표
`docs_orchestrator.py`에 interactive resume loop helper를 만들고, startup 시점과 phase 실행 후 시점 양쪽에 붙인다.

### 변경 파일
- `src/cowork_pilot/docs_orchestrator.py`

### 상세 내용

핵심 변경 파일은 [docs_orchestrator.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator.py)다.

#### 4-1. 새 helper `_resolve_waiting_runtime_interactively`

`_resolve_waiting_runtime_interactively(config, orch_config, project_dir, state_path) -> OrchestratorState | None`

정확한 동작:

1. `while runtime_is_waiting(project_dir):`
2. runtime 로드
3. `prompt_from_runtime_payload(runtime)` 호출
4. 사용자가 취소하면 `return None`
5. `resume_waiting_docs_step(...)` 호출
6. 결과가 `waiting`이면 루프 계속
7. 결과가 `completed`면 `return load_state(state_path)`
8. 결과가 `failed`면 에러 메시지 출력 후 `return load_state(state_path)`

추가로 MUST 1에 따라:
- `max_interactive_resumes` 기본값을 `20`으로 두고, 매 resume 시도마다 카운트를 증가시킨다.
- 카운트가 상한을 넘기면 pause로 빠진다 (resume 시도 중단).
- UI가 `None`을 반환하면(EOF/Ctrl-C) 즉시 `return None`.

#### 4-2. 호출 지점 1: 시작 직후 waiting runtime 감지 부분

현재 [docs_orchestrator.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator.py#L176)에서는 waiting이면 바로 pause 후 return 한다.

이걸 이렇게 바꾼다.

- `engine != codex`면 기존 그대로
- `engine == codex and runtime_is_waiting(project_dir)`면:
  - `orch_config.interactive_resume`가 `True`면 helper 호출
  - helper가 `None` 반환하면 기존 pause 메시지 찍고 return
  - helper가 state 반환하면 `state = returned_state`로 갱신하고 계속 진행
  - interactive가 `False`면 기존 pause 그대로

#### 4-3. 호출 지점 2: phase 실행 후 waiting 체크 부분

현재 [docs_orchestrator.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator.py#L263)도 waiting이면 바로 return 한다.

여기도 같은 방식으로 바꾼다.

- interactive true면 helper 호출
- 취소면 pause 메시지 후 return
- 완료되면 `state = load_state(state_path)` 또는 helper 반환 state로 갱신 후 `continue`
- 실패면 `state = load_state(state_path)` 후 `continue` 또는 `return`

내 추천은 실패 시 바로 `return`이다. 이미 state/runtime에 실패가 기록됐으니 프로세스를 멈추는 쪽이 안전하다.

**MUST 2에 따라 failed는 선택지가 아니라 무조건 `return outcome.state`다. `continue`는 금지된다.**

**MUST 4에 따라 `load_state()` 재호출 대신 helper가 반환한 state를 그대로 `state =`로 덮어쓴다.**

### 완료 조건
- `_resolve_waiting_runtime_interactively` helper가 정의되고, `max_interactive_resumes=20` 기본값이 반영되어 있다.
- startup branch와 phase-after-step branch 양쪽에서 helper가 호출된다.
- interactive=False일 때는 기존 pause 동작이 그대로 유지된다.
- failed 경로는 양쪽 branch 모두 `return outcome.state`로 종료한다 (MUST 2).
- helper가 반환한 state가 단일 진실원으로 쓰인다 (MUST 4).

---

## Chunk 5: CLI wrapper는 얇게 바꾼다

### 목표
`_run_docs_orchestrator_resume()`을 one-shot wrapper로 축소하고, 실제 상태 변경 책임을 새 helper로 이관한다.

### 변경 파일
- `src/cowork_pilot/main.py`

### 상세 내용

[main.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/main.py#L602)의 `_run_docs_orchestrator_resume()`는 wrapper로만 남긴다.

정리하면:

1. runtime 확인
2. `response_text`가 없고 `orch_config.interactive_resume`가 true면 runtime payload로 prompt
3. prompt 취소 시 그냥 return 또는 `sys.exit(1)`
4. 순수 helper `resume_waiting_docs_step(...)` 호출
5. `completed`면 메시지 출력 후 `run_docs_orchestrator(config, orch_config)` 재호출
6. `waiting`이면 "다시 답변 입력 필요" 메시지 출력
7. `failed`면 에러 출력 후 `sys.exit(1)`

즉:
- CLI `resume`는 여전히 재진입용 wrapper
- 실제 상태 변경은 새 helper가 담당

**MUST 5에 따라 이 wrapper 안에서는 loop를 돌리지 않는다. prompt는 최대 한 번만 띄운다. waiting이 다시 나오면 메시지만 출력하고 종료한다. loop는 오직 `run_docs_orchestrator()` 본체만 소유한다.**

### 완료 조건
- `_run_docs_orchestrator_resume()`에는 `while` loop가 없다 (MUST 5).
- 상태 변경은 전부 `resume_waiting_docs_step()` 호출로 위임된다.
- `completed`시 `run_docs_orchestrator()`를 정확히 한 번 재호출한다.
- `waiting` / `failed`는 메시지 출력 후 종료한다.

---

## 불변 규칙 (절대 바꾸면 안 되는 것)

1. [docs_orchestrator.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator.py#L1621)의 `_execute_orchestrator_step()` Claude branch는 그대로 둔다.
2. Codex waiting 판정 순서는 그대로 둔다.
   [docs_orchestrator_codex.py](/Users/yeonsu/autoagent/cowork-pilot/src/cowork_pilot/docs_orchestrator_codex.py#L142)처럼 `waiting -> STAGE_COMPLETE`보다 먼저여야 한다.
3. 완료 검증은 지금처럼 `ORCHESTRATOR:DONE` 기준을 유지한다.
4. startup stale cleanup 규칙은 건드리지 않는다.

---

## 실제 런타임 동작

완성 후 흐름은 정확히 이렇게 된다.

1. `cowork-pilot --mode docs-orchestrator --engine codex --interactive-resume auto`
2. step 실행
3. Codex가 `INPUT_REQUIRED` 출력
4. runtime sidecar 저장
5. 같은 프로세스가 터미널에 질문 출력
6. 네가 터미널에 입력 후 Enter
7. 같은 프로세스가 `resume_waiting_docs_step()` 호출
8. 내부에서 `codex exec resume`
9. 또 질문 나오면 다시 터미널 질문
10. 완료되면 state 반영
11. outer loop가 다음 step으로 넘어감
12. 별도 `docs-subcommand resume` 호출이 필요 없어짐

---

## 테스트

반드시 이 테스트를 추가하거나 수정해야 한다.

### Test Chunk 1: `tests/test_docs_orchestrator_terminal_ui.py`

- 추천값 Enter
- 숫자 선택
- 자유 텍스트
- approval y/n
- EOF 취소

### Test Chunk 2: `tests/test_docs_orchestrator_resume.py`

- completed
- waiting 재진입
- failed
- missing runtime
- not-waiting runtime

### Test Chunk 3: `tests/test_docs_orchestrator.py`

- startup waiting + interactive true -> prompt 후 completed -> phase 실행 계속
- phase 중 waiting + interactive true -> prompt 후 completed -> 다음 step 계속
- waiting -> waiting -> completed 2회 루프
- Ctrl-C/EOF -> runtime 유지 + pause return
- interactive false -> 기존처럼 즉시 pause

### Test Chunk 4: `tests/test_main_cli.py`

- 기존 `test_docs_resume_requires_response`는 수정해야 한다.
  - `--interactive-resume never`일 때만 "response required"를 기대
  - `--interactive-resume always`이고 no response면 prompt path로 들어가야 함

---

## 최종 목표

이대로 구현하면 네가 원하는 1차 목표, 즉 "돌아가던 `cowork-pilot` 터미널에서 입력하고 Enter 치면 같은 세션이 `resume`돼서 계속 진행되는 구조"는 정확히 붙는다. 그 다음 단계에서만 상위 CLI 에이전트 자동응답을 얹으면 된다.

---

## 구현 체크리스트 (요약)

- [ ] Chunk 1: config.py에 `interactive_resume` 필드 추가, main.py CLI 연결
- [ ] Chunk 2: `docs_orchestrator_resume.py` 신규 생성, `_docs_resume_expected_files` main.py에서 이관
- [ ] Chunk 3: `docs_orchestrator_terminal_ui.py` 신규 생성
- [ ] Chunk 4: `docs_orchestrator.py`에 `_resolve_waiting_runtime_interactively` 추가, 2개 호출 지점 수정
- [ ] Chunk 5: `_run_docs_orchestrator_resume()` 얇게 리팩터링
- [ ] Test Chunk 1: `test_docs_orchestrator_terminal_ui.py`
- [ ] Test Chunk 2: `test_docs_orchestrator_resume.py`
- [ ] Test Chunk 3: `test_docs_orchestrator.py` 갱신
- [ ] Test Chunk 4: `test_main_cli.py` 갱신
- [ ] MUST 1~5 전부 실제 코드에 반영됐는지 최종 검증
- [ ] 불변 규칙 4개(Claude branch, Codex waiting 판정 순서, `ORCHESTRATOR:DONE`, startup stale cleanup)가 건드려지지 않았는지 diff로 확인
