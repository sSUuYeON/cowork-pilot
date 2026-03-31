# docs-orchestrator 구현 계획

## Metadata
- project_dir: /sessions/great-elegant-bardeen/mnt/cowork-pilot
- spec: docs-orchestrator-design.md
- created: 2026-04-01
- status: pending

---

## Chunk 1: Config + State 모듈

### Completion Criteria
- [ ] src/cowork_pilot/orchestrator_state.py 파일 존재
- [ ] DocsOrchestratorConfig dataclass가 config.py에 존재
- [ ] load_docs_orchestrator_config() 함수가 config.py에 존재
- [ ] pytest tests/test_orchestrator_state.py 통과
- [ ] pytest tests/test_config.py 통과

### Tasks
- Task 1: config.py에 DocsOrchestratorConfig dataclass + load_docs_orchestrator_config() 추가
- Task 2: orchestrator_state.py 생성 — OrchestratorState dataclass, load/save JSON, estimate_sessions(), adaptive timeout 계산
- Task 3: test_orchestrator_state.py 작성 — 직렬화 라운드트립, estimate_sessions, 적응형 타임아웃 클램핑, running 상태 복구
- Task 4: test_config.py에 DocsOrchestratorConfig 로드 테스트 추가
- Task 5: tests/fixtures/sample_orchestrator_state.json 픽스처 생성

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 1을 진행해.
AGENTS.md와 docs-orchestrator-design.md를 참고해.

구현할 모듈:

1. src/cowork_pilot/config.py — 기존 파일에 DocsOrchestratorConfig 추가
   - 설계서 §12.3의 dataclass 정의를 정확히 따라라
   - load_docs_orchestrator_config(path, base_config) 함수 추가 — load_harness_config() 패턴과 동일
   - config.toml의 [docs_orchestrator] 섹션에서 로드

2. src/cowork_pilot/orchestrator_state.py — 새 파일
   설계서 §4.1 + §12.1의 역할 정의를 따라라:
   - OrchestratorState frozen dataclass (current, project_summary, completed, pending, errors 필드)
   - StepStatus dataclass (step, status, completed_at, result, note, actual_idle_seconds, marker_missing)
   - load_state(path) -> OrchestratorState
   - save_state(state, path) -> None
   - estimate_sessions(domains, features, source_line_count) -> int — §5.0의 산출 공식
   - compute_adaptive_timeout(completed_steps, config) -> float — 실측 평균 × multiplier, min/max 클램핑
   - generate_gap_summary(gap_reports_dir) -> str — §12.5의 정규식 파싱 (종합 점수 + AI_DECISION 수)
   - recover_running_step(state, project_dir) -> OrchestratorState — §8.3의 3단계 복구 정책

3. tests/test_orchestrator_state.py — 설계서 §12.4의 테스트 항목 전부:
   - 직렬화 → JSON → 역직렬화 라운드트립
   - estimate_sessions: 도메인 3개/기능 10개 → 예상 세션 수
   - 적응형 타임아웃: 실측 [80, 90, 100] → 평균 90 × 1.5 = 135초 (60~300 클램핑)
   - running 복구: 마커 있음 → completed, 마커 없음+파일 있음 → pending
   - generate_gap_summary: 점수 행 + [AI_DECISION] 파싱 검증 (tmp_path 사용)

4. tests/test_config.py에 DocsOrchestratorConfig 테스트 추가

5. tests/fixtures/sample_orchestrator_state.json 생성 — 다양한 상태 (idle, running, Phase 2 진행 중)

기존 코드 패턴을 반드시 따라라:
- config.py의 load_harness_config(), load_meta_config() 패턴 참고
- plan_parser.py의 dataclass 스타일 참고
- Python 3.10+, type hints everywhere
- Dataclasses for data, functions for logic

완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 2: Quality Gate 모듈

### Completion Criteria
- [ ] src/cowork_pilot/quality_gate.py 파일 존재
- [ ] pytest tests/test_quality_gate.py 통과
- [ ] tests/fixtures/sample_analysis_report.md 파일 존재

### Tasks
- Task 1: quality_gate.py 생성 — GateResult dataclass, check_phase1_quality() 순수 함수
- Task 2: test_quality_gate.py 작성 — 커버리지 비율, SOURCE 태그, 빈 파일 검사 3종 검증
- Task 3: tests/fixtures/sample_analysis_report.md 픽스처 생성

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 2를 진행해.
docs-orchestrator-design.md의 §5.1.1 (Phase 1.5 추출 품질 게이트)를 참고해.

구현할 모듈:

1. src/cowork_pilot/quality_gate.py — 새 파일
   설계서 §5.1.1과 §12.1의 정의를 따라라:

   @dataclass
   class GateResult:
       passed: bool
       coverage_ratio: float           # 검증 1: extracts/source 비율
       uncovered_sections: list[str]   # 검증 2: SOURCE 태그에 없는 원본 섹션
       missing_features: list[str]     # 검증 3: 파일 없거나 10줄 미만인 기능
       warnings: list[str]

   def check_phase1_quality(project_dir: Path, config: DocsOrchestratorConfig) -> GateResult:
       """Phase 1 산출물 품질 게이트. AI 세션 없이 파이썬으로 직접 검증."""

   내부 로직:
   - 검증 1 (커버리지 비율): 원본 기획서 총 줄 수 vs domain-extracts 총 줄 수. config.coverage_ratio_threshold (기본 0.8) 이상이면 pass
   - 검증 2 (SOURCE 태그): 원본에서 ^## 패턴으로 섹션 추출 → domain-extracts의 <!-- SOURCE: 파일명#섹션 --> 파싱 → 교차 확인
   - 검증 3 (빈 파일): analysis-report.md의 기능 목록 파싱 → 대응 domain-extract 파일 존재 + 10줄 이상 확인

   보조 함수:
   - _count_lines(path) -> int
   - _extract_source_tags(extracts_dir) -> set[str]
   - _extract_sections(source_file) -> list[str]  # ^## 헤더 추출
   - _parse_features_from_report(report_path) -> list[tuple[str, str]]  # (도메인, 기능) 튜플

2. tests/test_quality_gate.py — 설계서 §12.4:
   - 검증 1: tmp_path에 원본 100줄 + extracts 85줄 → pass, 70줄 → fail
   - 검증 2: 원본에 ## 섹션A, ## 섹션B → extracts에 SOURCE: file#섹션A만 → uncovered: [섹션B]
   - 검증 3: analysis-report에 기능 3개 → extract 2개만 존재 → missing: [기능3]
   - passed 필드: 3종 검증 모두 통과해야 True

3. tests/fixtures/sample_analysis_report.md — 도메인/기능 목록 포함

기존 패턴: plan_parser.py의 순수 함수 스타일, dataclass 사용.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 3: 프롬프트 템플릿 시스템

### Completion Criteria
- [ ] src/cowork_pilot/orchestrator_prompts.py 파일 존재
- [ ] src/cowork_pilot/orchestrator_templates/ 디렉토리에 13개 .j2 파일 존재
- [ ] pytest tests/test_orchestrator_prompts.py 통과

### Tasks
- Task 1: orchestrator_templates/ 디렉토리 생성 + 13개 Jinja2 템플릿 작성
- Task 2: orchestrator_prompts.py 생성 — Jinja2 환경 설정 + build_session_prompt() 함수
- Task 3: test_orchestrator_prompts.py 작성 — 각 템플릿 렌더링 결과에 필수 키워드 포함 검증

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 3를 진행해.
docs-orchestrator-design.md의 §5 (세션 분할 설계)와 §12.1 (모듈 분할)을 참고해.

구현할 모듈:

1. src/cowork_pilot/orchestrator_templates/ — 13개 Jinja2 템플릿
   설계서 §5의 각 Phase별 세션 프롬프트를 .j2 파일로 작성:

   - phase1_single.j2 — §5.1 1세션 처리 (소~중규모)
   - phase1_domain.j2 — §5.1 도메인별 추출 (대규모 1b-N)
   - phase2_auto.j2 — §5.2 auto 모드 갭 분석
   - phase2_manual.j2 — §5.2 manual 모드 갭 분석
   - phase3_design_docs.j2 — §5.3 세션 3-A (design-docs)
   - phase3_product_spec.j2 — §5.3 세션 3-B (product-specs)
   - phase3_architecture.j2 — §5.3 세션 3-C (ARCHITECTURE, DESIGN_GUIDE, SECURITY)
   - phase3_agents.j2 — §5.3 세션 3-D (AGENTS.md — 반드시 마지막)
   - phase4_consistency.j2 — §5.4 세션 4-1 (정합성 검사)
   - phase4_rescore.j2 — §5.4 세션 4-2 (체크리스트 재평가)
   - phase4_quality.j2 — §5.4 세션 4-3 (표현 품질 + QUALITY_SCORE)
   - phase5_outline.j2 — §5.5.1 (exec-plan 설계)
   - phase5_detail.j2 — §5.5.2 (exec-plan 상세)

   각 템플릿은 설계서의 세션 프롬프트 텍스트를 그대로 Jinja2 변수화한다.
   변수 예시: {{ project_dir }}, {{ source_docs }}, {{ domain }}, {{ features }}, {{ section_keywords }}
   모든 템플릿에 <!-- ORCHESTRATOR:DONE --> 마커 기록 지시가 포함되어야 한다.
   §7.2의 세션 프롬프트 생성 규칙(7가지 필수 항목)을 모든 템플릿이 충족해야 한다.

2. src/cowork_pilot/orchestrator_prompts.py — 새 파일
   설계서 §12.1의 역할: Jinja2 템플릿 로드 + 변수 치환

   - _get_jinja_env() -> jinja2.Environment  (scaffolder.py 패턴 참고)
   - build_session_prompt(phase: str, **kwargs) -> str
     phase 인자로 적절한 템플릿을 선택하고 kwargs로 변수 치환
   - get_section_keywords(output_formats_path: Path, project_type: str) -> list[str]
     output-formats.md에서 프로젝트 타입별 섹션 제목 키워드 추출 (Phase 4-1용)

3. tests/test_orchestrator_prompts.py — 설계서 §12.4:
   - 각 Phase 템플릿 렌더링에 필수 키워드 포함 검증:
     프로젝트 경로, 읽어야 할 파일 목록, <!-- ORCHESTRATOR:DONE --> 지시
   - Phase 4-1 프롬프트에 섹션 키워드 목록이 주입되는지 확인
   - 빈 features 리스트 → 에러 없이 동작 확인

기존 패턴: scaffolder.py의 Jinja2 환경 설정 참고.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 4: 메인 오케스트레이터 — Phase 0 + 1 + 1.5

### Completion Criteria
- [ ] src/cowork_pilot/docs_orchestrator.py 파일 존재
- [ ] run_docs_orchestrator() 함수가 Phase 0, 1, 1.5를 처리
- [ ] pytest tests/test_docs_orchestrator.py 통과 (Phase 0→1→1.5 전이 테스트)

### Tasks
- Task 1: docs_orchestrator.py 생성 — run_docs_orchestrator() 메인 루프, Phase 0 초기 설정
- Task 2: Phase 1 세션 관리 로직 (1세션/다세션 분기, cooperative loop)
- Task 3: Phase 1.5 quality gate 호출 + 실패 처리
- Task 4: test_docs_orchestrator.py 작성 — 상태 전이, Phase 1.5 게이트 연동

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 4를 진행해.
docs-orchestrator-design.md의 §3 (동작 흐름), §5.0 (Phase 0), §5.1 (Phase 1), §5.1.1 (Phase 1.5)를 참고해.

이전 Chunk에서 구현된 모듈들을 import해서 사용해:
- orchestrator_state.py (OrchestratorState, load_state, save_state, estimate_sessions, recover_running_step)
- quality_gate.py (check_phase1_quality, GateResult)
- orchestrator_prompts.py (build_session_prompt)
- config.py (DocsOrchestratorConfig, load_docs_orchestrator_config)

구현할 모듈:

1. src/cowork_pilot/docs_orchestrator.py — 새 파일
   설계서 §3, §12.1의 역할: Phase 판단 → 프롬프트 생성 → 세션 열기 → 완료 대기 → 상태 업데이트 루프.
   기존 main.py의 run_harness()를 참고하되 docs-orchestrator 전용 로직.

   def run_docs_orchestrator(config: Config, orch_config: DocsOrchestratorConfig) -> None:
       """메인 상태 머신 + 루프."""

   Phase 0 (§5.0 — 오케스트레이터 자체에서 수행, AI 세션 없음):
   - docs/generated/ 디렉토리 생성
   - 원본 기획서 파일 목록 확인
   - references/ 복사 (스킬 디렉토리 → docs/generated/references/)
   - estimate_sessions()로 예상 세션 수 산출 → 터미널에 출력 → y/n 확인
   - orchestrator-state.json 초기 생성

   Phase 1 (§5.1 — AI 세션):
   - 원본 줄 수 3000 이하면 1세션, 초과면 도메인별 다세션
   - _open_orchestrator_session(prompt, config, orch_config, base_path) 헬퍼:
     기존 session_opener.open_new_session() + detect_new_jsonl() 조합
   - _wait_for_session_completion(jsonl_path, expected_files, config, orch_config, watch_mode):
     §7.3의 완료 판정 로직 — idle 감지 + 출력 파일 존재 + 완료 마커 확인
     auto 모드면 Phase 1 Watch cooperative loop 실행 (run_harness 패턴)
     manual 모드면 출력 파일 폴링만
   - 적응형 타임아웃: 완료 시 actual_idle_seconds 기록, 3개 세션 후 자동 조정
   - 마커 누락 fallback (§2.7): Phase별 최소 줄 수 기준 하드코딩

   Phase 1.5 (§5.1.1 — 오케스트레이터 자체에서 수행):
   - check_phase1_quality() 호출
   - passed=True → Phase 2로 진행
   - passed=False → 검증 실패 유형에 따라 재시도/보충 세션/ESCALATE

   공통 헬퍼:
   - _determine_watch_mode(step, orch_config) -> bool  (auto/manual/hybrid 판단)
   - _update_state_completed(state, step, note) -> OrchestratorState
   - _update_state_error(state, step, error) -> OrchestratorState
   - _determine_next_step(state) -> str | None

2. tests/test_docs_orchestrator.py:
   - Phase 0 → 1 → 1.5 상태 전이 순서 검증 (mock으로 세션 열기/완료 시뮬레이션)
   - Phase 1.5 실패 시 Phase 2로 진행하지 않는 것 확인
   - _determine_watch_mode: auto → True, manual → False, hybrid → 도메인별 분기
   - recover_running_step: running 상태에서 재시작 시 복구 흐름

기존 패턴:
- main.py run_harness()의 cooperative loop 패턴 재활용
- session_manager.py의 open_chunk_session(), detect_new_jsonl() 재활용
- completion_detector.py의 is_idle_trigger() 재활용
- 모든 외부 호출(session_opener, subprocess)은 테스트에서 mock

완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 5: 메인 오케스트레이터 — Phase 2 + 3

### Completion Criteria
- [ ] docs_orchestrator.py에 Phase 2 갭 분석 로직 존재
- [ ] docs_orchestrator.py에 Phase 3 문서 생성 로직 존재
- [ ] 기능 묶음(bundle) 로직이 동작
- [ ] pytest tests/test_docs_orchestrator.py 통과 (Phase 2, 3 테스트 포함)
- [ ] tests/fixtures/sample_gap_report.md 파일 존재

### Tasks
- Task 1: Phase 2 갭 분석 세션 관리 — 기능별/묶음 세션, auto/manual 분기, _summary.md 생성
- Task 2: Phase 3 문서 생성 세션 관리 — 그룹 A/B/C/D 순서, 묶음 품질 자동 조정
- Task 3: 기능 묶음 로직 — domain-extract 줄 수 기반 판단, max_bundle_size 제한
- Task 4: test_docs_orchestrator.py에 Phase 2, 3 테스트 추가 — 묶음 로직, bundle_disabled 플래그
- Task 5: tests/fixtures/sample_gap_report.md 픽스처 생성

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 5를 진행해.
docs-orchestrator-design.md의 §5.2 (Phase 2), §5.3 (Phase 3), §6 (auto/manual 모드)를 참고해.
기존 src/cowork_pilot/docs_orchestrator.py를 수정해.

구현:

1. Phase 2 갭 분석 (§5.2):
   - _build_feature_bundles(features_with_lines, config) -> list[list[tuple[str, str]]]
     domain-extract 줄 수로 묶음 판단. config.feature_bundle_threshold_lines (기본 200줄) 이하면 묶음.
     config.max_bundle_size (기본 2)까지만 묶음.
   - 각 묶음(또는 단독 기능)에 대해 세션 프롬프트 생성 → 세션 열기 → 완료 대기
   - auto 모드: Watch cooperative loop, manual 모드: 폴링만
   - hybrid 모드 (§6.4): manual_override에 포함된 도메인은 Watch 안 함
   - Phase 2 완료 후: generate_gap_summary()로 _summary.md 기계 생성 (§12.5)

2. Phase 3 문서 생성 (§5.3):
   - 그룹 순서 강제: A (design-docs) → B (product-specs) → C (ARCHITECTURE 등) → D (AGENTS.md 마지막)
   - 그룹 B: Phase 2와 동일한 묶음 로직 적용
   - 묶음 품질 자동 조정 (§5.3): Phase 4-2에서 묶음 세션 마지막 문서의 품질 저하가 3건 이상이면
     orchestrator-state.json에 bundle_disabled: true 기록 → 이후 모두 단독 세션
   - 각 세션: build_session_prompt() → _open_orchestrator_session() → _wait_for_session_completion()

3. tests/test_docs_orchestrator.py에 추가:
   - _build_feature_bundles: 줄 수 [150, 180, 250, 100] → [[150, 180], [250], [100]] (250은 단독)
   - bundle_disabled=True일 때 모두 단독 세션으로 변환 확인
   - Phase 3 그룹 순서: A→B→C→D 검증
   - Phase 2 완료 후 _summary.md 생성 확인

4. tests/fixtures/sample_gap_report.md — 점수 행 + [AI_DECISION] 태그 포함

기존 패턴: Chunk 4에서 만든 헬퍼 함수 재활용.
완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 6: 메인 오케스트레이터 — Phase 4 + 5

### Completion Criteria
- [ ] docs_orchestrator.py에 Phase 4 품질 검토 로직 존재
- [ ] docs_orchestrator.py에 Phase 5 exec-plan 생성 로직 존재
- [ ] _determine_next_step()이 Phase 0→1→1.5→2→3→4→5 전체 흐름 처리
- [ ] pytest tests/test_docs_orchestrator.py 통과 (전체 Phase 테스트)

### Tasks
- Task 1: Phase 4 품질 검토 — 3세션 분할 (정합성/체크리스트 재평가/표현 품질)
- Task 2: Phase 5 exec-plan 생성 — 2단계 (outline + detail별 세션)
- Task 3: 최종 완료 처리 — 전체 상태 확인 + macOS 알림 + 터미널 요약
- Task 4: _determine_next_step() 완성 — 전체 Phase 흐름 상태 머신
- Task 5: test_docs_orchestrator.py에 Phase 4, 5 테스트 추가

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 6을 진행해.
docs-orchestrator-design.md의 §5.4 (Phase 4), §5.5 (Phase 5), §9 (전체 흐름 예시)를 참고해.
기존 src/cowork_pilot/docs_orchestrator.py를 수정해.

구현:

1. Phase 4 품질 검토 (§5.4 — 3세션 분할):
   - 세션 4-1 정합성 검사: orchestrator_prompts에서 section_keywords 주입
   - 세션 4-2 체크리스트 재평가: Phase 2와 동일 묶음 기준, 기능별 세션 가능
     묶음 세션의 마지막 문서 품질 저하 3건 이상 → bundle_disabled 설정
   - 세션 4-3 표현 품질 + QUALITY_SCORE.md: grep 기반 금지 표현 검색

2. Phase 5 exec-plan 생성 (§5.5 — 2단계):
   - Phase 5-outline (1세션): exec-plan 목차 설계 → docs/generated/exec-plan-outline.md
   - Phase 5-detail (exec-plan별 1세션씩): outline 기반으로 Session Prompt 채워 완성
     → docs/exec-plans/planning/{번호}-{이름}.md에 저장
   - outline에서 exec-plan 파일 목록 파싱: _parse_outline_plans(outline_path) -> list[dict]

3. 최종 완료 (§9):
   - orchestrator-state.json의 모든 단계 completed 확인
   - docs/exec-plans/planning/에 파일 생성 확인
   - 터미널에 최종 요약 출력 (총 세션 수, 소요 시간, 에러 수, marker_missing 경고 수)
   - macOS 알림으로 완료 통지

4. _determine_next_step() 완성:
   상태 파일의 completed/pending 목록을 보고 if/else로 다음 단계 결정:
   phase_0 → phase_1 → phase_1_5 → phase_2:{도메인}:{기능} (각각) → phase_2_summary
   → phase_3_A → phase_3_B:{도메인}:{기능} (각각) → phase_3_C → phase_3_D
   → phase_4_1 → phase_4_2 → phase_4_3 → phase_5_outline → phase_5_detail:{plan_name} (각각)
   → done

5. tests/test_docs_orchestrator.py에 추가:
   - Phase 4 → 5 전이 검증
   - _determine_next_step() 전체 Phase 흐름 — 각 상태에서 올바른 다음 단계 반환
   - Phase 5 outline 파싱 → detail 세션 수 결정
   - 최종 완료 상태 검증

완료 조건(Completion Criteria)을 모두 만족시켜.
```

---

## Chunk 7: CLI 통합 + 스킬 번들

### Completion Criteria
- [ ] cowork-pilot --mode docs-orchestrator가 동작
- [ ] --docs-mode auto/manual 인자가 동작
- [ ] --manual-override 인자가 동작
- [ ] skills/docs-orchestrator/SKILL.md 파일 존재
- [ ] skills/docs-orchestrator/references/ 디렉토리에 3개 파일 존재
- [ ] pytest tests/ 전체 통과

### Tasks
- Task 1: main.py cli()에 --mode docs-orchestrator, --docs-mode, --manual-override 추가
- Task 2: main.py에 run_docs_orchestrator 호출 로직 추가
- Task 3: skills/docs-orchestrator/SKILL.md 작성
- Task 4: skills/docs-orchestrator/references/ 생성 — 기존 docs-restructurer에서 복사
- Task 5: 전체 pytest 실행 + 기존 테스트 깨짐 없는지 확인

### Session Prompt
```
docs/exec-plans/active/01-docs-orchestrator.md를 읽고 Chunk 7을 진행해.
docs-orchestrator-design.md의 §3 (실행 방법), §10 (기존 스킬 관계), §12.1~12.3을 참고해.

구현:

1. src/cowork_pilot/main.py 수정:
   - cli()의 argparse에 추가:
     --mode choices에 "docs-orchestrator" 추가
     --docs-mode: auto/manual, 기본값 auto (docs-orchestrator 모드 전용)
     --manual-override: 콤마 구분 도메인 목록 (docs-orchestrator 모드 전용)
   - docs-orchestrator 모드 분기:
     config 로드 → load_docs_orchestrator_config() → orch_config에 docs_mode, manual_override 설정
     → run_docs_orchestrator(config, orch_config) 호출

2. skills/docs-orchestrator/SKILL.md 작성:
   - 스킬 이름: docs-orchestrator
   - 설명: 대규모 프로젝트의 기획서를 자동으로 분석하고 docs/ 구조를 생성하는 상태 기반 자동 세션 관리자
   - 트리거 키워드: 'docs-orchestrator', '대규모 docs 생성', '자동 문서 오케스트레이션'
   - 사용법: CLI 실행 안내 (cowork-pilot --mode docs-orchestrator)
   - 기존 docs-restructurer와의 관계 설명 (§10)

3. skills/docs-orchestrator/references/ 디렉토리:
   기존 skills/docs-restructurer/references/에서 3개 파일을 복사:
   - checklists.md
   - output-formats.md
   - quality-criteria.md
   이 파일들은 Phase 0에서 프로젝트의 docs/generated/references/로 복사됨.

4. config.toml에 [docs_orchestrator] 섹션 예시 추가 (주석으로):
   설계서 §7.3의 설정값들

5. 전체 테스트 확인:
   pytest tests/ 실행 → 기존 테스트 전부 통과 + 새 테스트 전부 통과
   기존 모듈(watcher, dispatcher, validator, responder 등)에 영향 없는지 확인

완료 조건(Completion Criteria)을 모두 만족시켜.
```
