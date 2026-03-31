# Phase 3 버그 수정 + planning/ 폴더 도입

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 코드 리뷰에서 발견된 5개 이슈(#1, #3, #4, #5, #6) 수정 + exec-plan 3단 폴더 구조(`planning/`, `active/`, `completed/`) 도입

**Architecture:** `planning/` 폴더를 추가하여 미실행 plan과 실행 중 plan을 분리한다. `run_harness()` 진입 시 `active/`가 비어있으면 `planning/`에서 파일명 정렬 순으로 다음 plan을 가져온다. scaffolder는 첫 번째 plan만 `active/`에, 나머지는 `planning/`에 생성한다.

**Tech Stack:** Python 3.11+, Jinja2, pytest

## Metadata
- project_dir: /Users/yeonsu/autoagent/cowork-pilot
- spec: docs/specs/2026-03-25-meta-agent-design.md
- created: 2026-03-25
- status: pending

---

## File Structure

### 수정하는 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/cowork_pilot/scaffolder.py` | `planning/` 디렉토리 생성 + `docs-setup-plan`을 `active/`에, 후속 plan 경로를 `planning/`으로 변경 + `slugify()`에서 `_`를 `-`로 변환 |
| `src/cowork_pilot/meta_runner.py` | `ignored_sessions` 주석/로직 정리 + `planning/ → active/` 이동 함수 추가 + Step 4 진입 전 promote 호출 |
| `src/cowork_pilot/main.py` | `run_harness()` 진입 시 `active/` 비어있으면 `planning/`에서 promote + active에 2개 이상이면 에러 |
| `src/cowork_pilot/session_manager.py` | `promote_next_plan()` 유틸리티 함수, `move_to_completed()` 후 자동 promote 옵션 |
| `src/cowork_pilot/brief_parser.py` | `_parse_pages()` 등에서 들여쓰기 감지를 탭/2칸/4칸 모두 허용 |
| `src/cowork_pilot/brief_templates/docs-setup-plan.md.j2` | Chunk 4의 `implementation.md` 출력 경로를 `docs/exec-plans/planning/`으로 변경 |
| `docs/project-conventions.md` | 섹션 1, 7의 폴더 구조에 `planning/` 추가 |
| `tests/test_brief_parser.py` | 탭/4칸 들여쓰기 엣지케이스 테스트 추가 |
| `tests/test_scaffolder.py` | `planning/` 디렉토리 생성 확인 + `slugify("my_page")` 테스트 |
| `tests/test_meta_runner.py` | `wait_for_brief_completion` 실제 호출 테스트 + `promote_next_plan` 테스트 |
| `tests/test_session_manager.py` | `promote_next_plan` 단위 테스트 |

---

## Chunk 1: planning/ 폴더 인프라 + promote_next_plan

### Completion Criteria
- [ ] `pytest tests/test_session_manager.py -v -k promote` 통과
- [ ] `promote_next_plan()` 함수가 `session_manager.py`에 존재
- [ ] `promote_next_plan()`이 `planning/`에서 정렬 순 첫 번째 `.md`를 `active/`로 이동

### Tasks

#### Task 1: promote_next_plan 테스트 작성

- [ ] **Step 1: `tests/test_session_manager.py` 끝에 테스트 추가**

```python
class TestPromoteNextPlan:
    """planning/ → active/ plan 이동."""

    def test_promotes_first_by_filename_sort(self, tmp_path):
        """파일명 정렬 순으로 첫 번째를 promote."""
        planning = tmp_path / "docs" / "exec-plans" / "planning"
        active = tmp_path / "docs" / "exec-plans" / "active"
        planning.mkdir(parents=True)
        active.mkdir(parents=True)
        (planning / "02-implementation.md").write_text("# Plan 2")
        (planning / "01-docs-setup.md").write_text("# Plan 1")

        from cowork_pilot.session_manager import promote_next_plan
        promoted = promote_next_plan(tmp_path / "docs" / "exec-plans")
        assert promoted is not None
        assert promoted.name == "01-docs-setup.md"
        assert (active / "01-docs-setup.md").exists()
        assert not (planning / "01-docs-setup.md").exists()

    def test_returns_none_when_planning_empty(self, tmp_path):
        """planning/이 비어있으면 None."""
        planning = tmp_path / "docs" / "exec-plans" / "planning"
        active = tmp_path / "docs" / "exec-plans" / "active"
        planning.mkdir(parents=True)
        active.mkdir(parents=True)

        from cowork_pilot.session_manager import promote_next_plan
        assert promote_next_plan(tmp_path / "docs" / "exec-plans") is None

    def test_returns_none_when_active_not_empty(self, tmp_path):
        """active/에 이미 plan이 있으면 promote하지 않음."""
        planning = tmp_path / "docs" / "exec-plans" / "planning"
        active = tmp_path / "docs" / "exec-plans" / "active"
        planning.mkdir(parents=True)
        active.mkdir(parents=True)
        (planning / "02-implementation.md").write_text("# Plan 2")
        (active / "01-docs-setup.md").write_text("# Plan 1")

        from cowork_pilot.session_manager import promote_next_plan
        assert promote_next_plan(tmp_path / "docs" / "exec-plans") is None

    def test_planning_dir_missing(self, tmp_path):
        """planning/ 디렉토리가 없으면 None."""
        active = tmp_path / "docs" / "exec-plans" / "active"
        active.mkdir(parents=True)

        from cowork_pilot.session_manager import promote_next_plan
        assert promote_next_plan(tmp_path / "docs" / "exec-plans") is None
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
cd /Users/yeonsu/autoagent/cowork-pilot
pytest tests/test_session_manager.py -v -k promote
```
Expected: FAIL — `ImportError: cannot import name 'promote_next_plan'`

#### Task 2: promote_next_plan 구현

- [ ] **Step 3: `src/cowork_pilot/session_manager.py`에 함수 추가**

`move_to_completed` 함수 아래에 추가:

```python
def promote_next_plan(exec_plans_dir: Path) -> Path | None:
    """Move the next plan from planning/ to active/.

    Selects by filename sort order (e.g. 01-xxx before 02-yyy).
    Returns the new path in active/, or None if nothing to promote
    or active/ already has a plan.
    """
    planning_dir = exec_plans_dir / "planning"
    active_dir = exec_plans_dir / "active"

    if not planning_dir.exists():
        return None

    # Don't promote if active/ already has a plan
    if list(active_dir.glob("*.md")):
        return None

    candidates = sorted(planning_dir.glob("*.md"))
    if not candidates:
        return None

    next_plan = candidates[0]
    dest = active_dir / next_plan.name
    shutil.move(str(next_plan), str(dest))
    return dest
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_session_manager.py -v -k promote
```
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/session_manager.py tests/test_session_manager.py
git commit -m "feat: add promote_next_plan for planning/ → active/ transition"
```

---

## Chunk 2: scaffolder + 템플릿 수정 (planning/ 폴더 + slugify 수정)

### Completion Criteria
- [ ] `pytest tests/test_scaffolder.py -v` 통과
- [ ] scaffolder가 `docs/exec-plans/planning/` 디렉토리를 생성함
- [ ] `docs-setup-plan.md.j2`의 Chunk 4가 `docs/exec-plans/planning/` 경로 + `{NN}-{이름}.md` 파일명 규칙 사용
- [ ] `slugify("my_page name")` → `"my-page-name"` (밑줄을 하이픈으로 변환)

### Tasks

#### Task 1: slugify 수정 + 테스트

- [ ] **Step 1: `tests/test_scaffolder.py` TestSlugify에 테스트 추가**

```python
    def test_underscore_to_hyphen(self):
        assert slugify("my_page name") == "my-page-name"

    def test_underscore_only(self):
        assert slugify("hello_world") == "hello-world"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_scaffolder.py::TestSlugify -v
```
Expected: FAIL — `assert 'my_page-name' == 'my-page-name'`

- [ ] **Step 3: `src/cowork_pilot/scaffolder.py`의 `slugify()` 수정**

기존:
```python
    text = re.sub(r'[\s/\\()\[\]{}]+', '-', text)
```

변경:
```python
    text = re.sub(r'[\s_/\\()\[\]{}]+', '-', text)
```

(`_`를 치환 대상에 추가)

그리고 아래 정규식도 수정 — `\w`는 `_`를 포함하므로 `_` 제거 후 남은 `_`가 없도록:

기존:
```python
    text = re.sub(r'[^\w\-]', '', text, flags=re.UNICODE)
```

이건 그대로 둬도 됨 — 위에서 `_`를 이미 `-`로 변환했으므로.

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_scaffolder.py::TestSlugify -v
```
Expected: 5 passed

#### Task 2: scaffolder에 planning/ 디렉토리 추가

- [ ] **Step 5: `tests/test_scaffolder.py` TestScaffoldDirectories에 테스트 추가**

```python
    def test_creates_planning_dir(self, tmp_path, minimal_brief):
        scaffold_project(minimal_brief, tmp_path)
        assert (tmp_path / "docs" / "exec-plans" / "planning").is_dir()
```

- [ ] **Step 6: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_scaffolder.py::TestScaffoldDirectories::test_creates_planning_dir -v
```
Expected: FAIL

- [ ] **Step 7: `src/cowork_pilot/scaffolder.py`의 `scaffold_project()`에 `planning/` 추가**

`dirs` 리스트에 추가:
```python
    dirs = [
        "docs/design-docs",
        "docs/product-specs",
        "docs/exec-plans/active",
        "docs/exec-plans/planning",       # ← 추가
        "docs/exec-plans/completed",
        "docs/references",
        "docs/generated",
        "src",
        "tests",
    ]
```

- [ ] **Step 8: `src/cowork_pilot/scaffolder.py`의 exec-plan 출력 경로에 `01-` 접두사 추가**

기존 (L261-263):
```python
    _write_if_not_exists(
        project_dir / "docs" / "exec-plans" / "active" / "docs-setup.md",
        plan_content,
    )
```

변경:
```python
    _write_if_not_exists(
        project_dir / "docs" / "exec-plans" / "active" / "01-docs-setup.md",
        plan_content,
    )
```

- [ ] **Step 9: `tests/test_scaffolder.py` TestScaffoldFiles의 `test_exec_plan_generated` 수정**

기존:
```python
        plan = tmp_path / "docs" / "exec-plans" / "active" / "docs-setup.md"
```

변경:
```python
        plan = tmp_path / "docs" / "exec-plans" / "active" / "01-docs-setup.md"
```

- [ ] **Step 10: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_scaffolder.py -v
```
Expected: ALL passed

#### Task 3: docs-setup-plan.md.j2 Chunk 4 — 복수 plan 파일 + planning/ 경로

- [ ] **Step 11: `src/cowork_pilot/brief_templates/docs-setup-plan.md.j2` 수정**

11a. 파일 내 모든 `docs-setup.md` 참조를 `01-docs-setup.md`로 변경 (Chunk 2~5의 Session Prompt에서 `docs/exec-plans/active/docs-setup.md` → `docs/exec-plans/active/01-docs-setup.md`).

11b. Chunk 4 블록 전체를 아래로 교체:

```markdown
## Chunk 4: 구현 계획 (exec-plan) 생성

### Completion Criteria
- [ ] docs/exec-plans/planning/ 아래에 최소 1개 .md 파일 존재
- [ ] 모든 파일이 plan_parser.py로 파싱 성공 (형식 검증)
- [ ] 파일명이 {NN}-{이름}.md 형식 (예: 02-frontend.md, 03-backend.md)

### Tasks
- Task 1: 설계 문서 + 스펙을 기반으로 구현 exec-plan 작성
- Task 2: 프로젝트 규모에 따라 하나 또는 여러 파일로 분리
- Task 3: Chunk은 2~5개 Task, 2~5개 Completion Criteria로 구성

### Session Prompt
` ` `
docs/exec-plans/active/01-docs-setup.md를 읽고 Chunk 4를 진행해.
ARCHITECTURE.md, docs/design-docs/, docs/product-specs/를 전부 읽고
이 프로젝트의 구현 계획(exec-plan)을 작성해.
docs/project-conventions.md 섹션 4의 형식을 정확히 따라.

파일 위치: docs/exec-plans/planning/
파일명 규칙: {NN}-{이름}.md (02부터 시작. 예: 02-frontend.md, 03-backend.md)
프로젝트 규모에 따라 하나로 합쳐도 되고 여러 파일로 분리해도 된다.
단, 파일명의 번호 순서가 실행 순서가 된다.

exec-plan 형식:
- # 제목 + ## Metadata (project_dir, spec, created, status)
- ## Chunk N: 이름 + ### Completion Criteria (- [ ] 체크박스) + ### Tasks (- Task N:) + ### Session Prompt (코드블록)
- Chunk당 Task 2~5개, Completion Criteria 2~5개
완료 조건을 모두 만족시켜.
` ` `
```

(위 Session Prompt 코드블록의 ` ` ` 은 실제 적용 시 백틱 3개로 교체)

- [ ] **Step 12: 기존 테스트 전체 통과 확인**

```bash
pytest tests/test_scaffolder.py -v
```

- [ ] **Step 13: 커밋**

```bash
git add src/cowork_pilot/scaffolder.py src/cowork_pilot/brief_templates/docs-setup-plan.md.j2 tests/test_scaffolder.py
git commit -m "feat: add planning/ dir, fix slugify underscore, update template paths"
```

---

## Chunk 3: brief_parser 들여쓰기 감지 개선

### Completion Criteria
- [ ] `pytest tests/test_brief_parser.py -v` 통과
- [ ] 탭 들여쓰기 브리프를 `parse_brief()`로 파싱 가능
- [ ] 4칸 스페이스 들여쓰기 브리프를 `parse_brief()`로 파싱 가능

### Tasks

#### Task 1: 엣지케이스 테스트 추가

- [ ] **Step 1: `tests/test_brief_parser.py` TestParseBriefEdgeCases에 추가**

```python
    def test_tab_indented_children(self, tmp_path):
        """탭 들여쓰기도 child로 인식."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "tab-app"
            - description: "탭 테스트"
            - type: "web-app"

            ## 2. Tech Stack
            - language: "Python"
            - framework: "FastAPI"

            ## 3. Pages / Features

            - page: "대시보드"
            \tdescription: "메인 대시보드"
            \tkey_elements: ["차트", "테이블"]
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        brief = parse_brief(p)
        assert len(brief.pages) == 1
        assert brief.pages[0].description == "메인 대시보드"
        assert "차트" in brief.pages[0].key_elements

    def test_four_space_indented_children(self, tmp_path):
        """4칸 스페이스도 child로 인식."""
        md = textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "four-app"
            - description: "4칸 테스트"
            - type: "web-app"

            ## 2. Tech Stack
            - language: "Python"
            - framework: "Django"

            ## 3. Pages / Features

            - page: "설정"
                description: "설정 페이지"
                key_elements: ["폼", "저장 버튼"]
        """)
        p = tmp_path / "project-brief.md"
        p.write_text(md)
        brief = parse_brief(p)
        assert len(brief.pages) == 1
        assert brief.pages[0].description == "설정 페이지"
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

```bash
pytest tests/test_brief_parser.py -v -k "tab_indent or four_space"
```
Expected: FAIL

#### Task 2: brief_parser 들여쓰기 감지 수정

- [ ] **Step 3: `src/cowork_pilot/brief_parser.py`에서 `is_child` 조건 수정**

`_parse_pages`, `_parse_entities`, `_parse_decisions`, `_parse_references` 4개 함수에서 공통으로 사용하는 패턴:

기존:
```python
        is_child = line.startswith("  ") and not line.startswith("- ")
```

변경:
```python
        is_child = (
            (line.startswith("  ") or line.startswith("\t") or line.startswith("    "))
            and not stripped.startswith("- ")
        )
```

주의: `stripped.startswith("- ")`로 변경해야 한다. `line.startswith("- ")`는 들여쓰기가 있을 때 False이므로 기존에 문제가 없었지만, 명확성을 위해 `stripped` 기준으로 통일.

더 간결한 방법 — 들여쓰기가 있고 dash로 시작하지 않으면 child:

```python
        is_child = (line != stripped) and not stripped.startswith("- ")
```

`line != stripped`이면 앞에 어떤 종류든 공백/탭이 있다는 뜻. `stripped`가 `-`로 시작하지 않으면 parent가 아닌 child.

이 패턴을 `_parse_pages`, `_parse_entities`, `_parse_decisions`, `_parse_references` 4곳에 모두 적용.

- [ ] **Step 4: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_brief_parser.py -v
```
Expected: ALL passed

- [ ] **Step 5: 커밋**

```bash
git add src/cowork_pilot/brief_parser.py tests/test_brief_parser.py
git commit -m "fix: support tab and 4-space indentation in brief parser"
```

---

## Chunk 4: meta_runner + main.py 통합 (ignored_sessions 정리 + promote 호출)

### Completion Criteria
- [ ] `pytest tests/test_meta_runner.py -v` 통과
- [ ] `meta_runner.py`의 `ignored_sessions` 로직에 목적 설명 주석 존재
- [ ] `meta_runner.py` Step 4 진입 전에 `promote_next_plan()` 호출
- [ ] `main.py`의 `run_harness()` 진입 시 `active/`가 비어있으면 `promote_next_plan()` 호출
- [ ] `main.py`의 `run_harness()` 진입 시 `active/`에 2개 이상이면 에러 + ESCALATE

### Tasks

#### Task 1: test_meta_runner.py 개선 — wait_for_brief_completion 실제 테스트

- [ ] **Step 1: `tests/test_meta_runner.py`의 no-op 테스트를 실제 테스트로 교체**

기존 `test_detects_brief_file` 삭제, 아래로 교체:

```python
class TestWaitForBriefCompletion:
    """브리프 세션 완료 감지."""

    def test_returns_path_when_file_exists(self, tmp_path):
        """project-brief.md가 이미 존재하면 즉시 반환."""
        docs = tmp_path / "docs"
        docs.mkdir()
        brief_path = docs / "project-brief.md"
        brief_path.write_text("# Project Brief\n\n## 1. Overview\n- name: test\n")

        mc = MetaConfig(project_dir=str(tmp_path))
        jsonl_path = tmp_path / "fake.jsonl"
        jsonl_path.write_text("")

        result = wait_for_brief_completion(
            jsonl_path, mc, poll_interval=0.1, timeout=1.0,
        )
        assert result == brief_path

    def test_timeout_when_file_missing(self, tmp_path):
        """project-brief.md가 없으면 TimeoutError."""
        mc = MetaConfig(project_dir=str(tmp_path))
        jsonl_path = tmp_path / "fake.jsonl"
        jsonl_path.write_text("")

        (tmp_path / "docs").mkdir()

        with pytest.raises(TimeoutError):
            wait_for_brief_completion(
                jsonl_path, mc, poll_interval=0.1, timeout=0.3,
            )

    def test_detects_session_end_without_brief(self, tmp_path):
        """세션이 끝났는데 brief가 없으면 RuntimeError."""
        mc = MetaConfig(project_dir=str(tmp_path))
        (tmp_path / "docs").mkdir()

        jsonl_path = tmp_path / "session.jsonl"
        import json
        jsonl_path.write_text(json.dumps({"type": "summary"}) + "\n")

        with pytest.raises(RuntimeError, match="Brief session ended"):
            wait_for_brief_completion(
                jsonl_path, mc, poll_interval=0.1, timeout=1.0,
            )
```

- [ ] **Step 2: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_meta_runner.py -v
```
Expected: ALL passed (이 테스트들은 기존 코드로도 통과해야 함)

#### Task 2: meta_runner.py ignored_sessions 주석 정리 + promote 호출

- [ ] **Step 3: `src/cowork_pilot/meta_runner.py` Step 0 부분의 `ignored_sessions` 주석 보강**

L272-276 부근의 코드에 설명 주석 추가:

```python
    # ignored_sessions는 run_harness()에 전달되어 Phase 1 auto-response를
    # 특정 세션에서 비활성화하는 데 사용.
    # Step 0에서는 run_meta()가 동기적으로 wait_for_brief_completion을 호출하므로
    # Phase 1 watcher가 동시에 돌지 않지만, Step 2/4에서 run_harness()에 전달 시 의미가 있다.
    # brief_jsonl은 Step 2 진입 전에 discard됨 (L309).
    ignored_sessions: set[Path] = set()
    ignored_sessions.add(brief_jsonl)
```

- [ ] **Step 4: `src/cowork_pilot/meta_runner.py` Step 4에 promote 호출 추가**

Step 3과 Step 4 사이 (L334 부근), `run_harness()` 호출 전에:

```python
    # ── Step 4: Implementation (Phase 2 harness) ─────────────────
    logger.info("meta", "Step 4: Implementation via harness")
    print("\nStep 4: 구현 시작 (Phase 2 하네스)...")

    # Promote next plan from planning/ to active/
    from cowork_pilot.session_manager import promote_next_plan
    exec_plans_dir = project_dir / harness_cfg.exec_plans_dir
    promoted = promote_next_plan(exec_plans_dir)
    if promoted:
        logger.info("meta", "Promoted plan to active", plan=str(promoted))
        print(f"  Plan promoted: {promoted.name}")
    else:
        # Check if active/ already has a plan (from Step 2 leftovers or manual placement)
        impl_plan_dir = exec_plans_dir / "active"
        impl_plans = list(impl_plan_dir.glob("*.md")) if impl_plan_dir.exists() else []
        if not impl_plans:
            logger.error(
                "meta",
                "No plan in active/ or planning/. "
                "Step 2 should have generated {NN}-*.md files in planning/ via docs-setup Chunk 4.",
                dir=str(exec_plans_dir),
            )
            print(
                f"Error: active/와 planning/ 모두 exec-plan이 없습니다.\n"
                "docs-setup Chunk 4에서 planning/에 구현 계획이 생성되어야 합니다.",
                file=sys.stderr,
            )
            sys.exit(1)

    run_harness(config, harness_cfg, ignored_sessions=ignored_sessions)
```

기존의 `impl_plan_dir` / `impl_plans` 체크 블록 (L338-354)을 위 코드로 **교체**.

- [ ] **Step 5: 테스트 실행**

```bash
pytest tests/test_meta_runner.py -v
```
Expected: ALL passed

#### Task 3: main.py run_harness()에 promote + active 검증 추가

- [ ] **Step 6: `src/cowork_pilot/main.py`의 `run_harness()` 함수 수정**

L336-341 부근 (`# Find active exec-plan` 이후)을 다음으로 교체:

```python
    # Promote from planning/ if active/ is empty
    from cowork_pilot.session_manager import promote_next_plan
    promoted = promote_next_plan(active_dir.parent)
    if promoted:
        logger.info("harness", "Promoted plan from planning/", plan=str(promoted))
        print(f"Harness: Promoted {promoted.name} to active/")

    # Find active exec-plan
    plan_files = list(active_dir.glob("*.md"))
    if not plan_files:
        logger.error("harness", "No active exec-plan found", dir=str(active_dir))
        print(f"Error: No exec-plan files in {active_dir}", file=sys.stderr)
        sys.exit(1)

    if len(plan_files) > 1:
        names = [p.name for p in plan_files]
        logger.error("harness", "Multiple plans in active/ — ambiguous", files=names)
        from cowork_pilot.session_manager import notify_escalate
        notify_escalate(f"active/에 plan이 {len(plan_files)}개 있음: {names}")
        print(f"Error: active/에 plan이 2개 이상 — 어떤 것을 실행할지 모호합니다: {names}", file=sys.stderr)
        sys.exit(1)

    plan_path = plan_files[0]
```

- [ ] **Step 7: 전체 테스트 실행**

```bash
pytest -v
```
Expected: ALL passed

- [ ] **Step 8: 커밋**

```bash
git add src/cowork_pilot/meta_runner.py src/cowork_pilot/main.py tests/test_meta_runner.py
git commit -m "fix: clean up ignored_sessions, add promote logic, guard active/ uniqueness"
```

---

## Chunk 5: 문서 업데이트 + 전체 검증

### Completion Criteria
- [ ] `docs/project-conventions.md` 섹션 1과 섹션 7에 `planning/` 폴더가 명시됨
- [ ] `pytest -v` 전체 통과
- [ ] `grep -c "planning/" docs/project-conventions.md` ≥ 2

### Tasks

#### Task 1: project-conventions.md 업데이트

- [ ] **Step 1: 섹션 1 폴더 구조에 `planning/` 추가**

기존:
```
    exec-plans/
      active/                   ← 현재 진행 중인 구현 계획
        {이름}.md               ← 예: auth-system.md
      completed/                ← 완료된 구현 계획 (하네스가 자동 이동)
```

변경:
```
    exec-plans/
      planning/                 ← 생성됐지만 아직 실행 안 한 구현 계획
        {NN}-{이름}.md          ← 예: 02-implementation.md (번호순 실행)
      active/                   ← 현재 실행 중인 구현 계획 (항상 0~1개)
        {이름}.md               ← 예: 01-docs-setup.md
      completed/                ← 완료된 구현 계획 (하네스가 자동 이동)
```

- [ ] **Step 2: 섹션 7.2 폴더 구조에도 `planning/` 반영**

기존:
```
    exec-plans/
      active/                        ← Step 1에서 docs-setup.md 자동 생성
      completed/
```

변경:
```
    exec-plans/
      planning/                      ← 후속 plan 대기 (Step 2 Chunk 4에서 implementation.md 생성)
      active/                        ← 현재 실행 중 plan (항상 0~1개)
      completed/                     ← 완료된 plan
```

- [ ] **Step 3: 섹션 1.1 표에 `planning/` 추가**

| 항목 | 필수 여부 | 설명 |
|------|-----------|------|
| `docs/exec-plans/planning/` | 선택 | 미실행 plan 대기 (meta 모드에서 사용) |

- [ ] **Step 4: AGENTS.md에 planning/ 경로 추가 (Directory Map)**

기존의 `docs/exec-plans/active/` 라인 아래에:
```
- `docs/exec-plans/planning/` — 대기 중인 실행 계획 (meta 모드)
```

- [ ] **Step 5: 전체 테스트**

```bash
pytest -v
```
Expected: ALL passed

- [ ] **Step 6: 커밋**

```bash
git add docs/project-conventions.md AGENTS.md
git commit -m "docs: add planning/ folder to conventions and AGENTS.md"
```
