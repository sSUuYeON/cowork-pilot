# Meta Mode Resume Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `--mode meta` resumable after a crash — each Step checks filesystem state and skips if already completed.

**Architecture:** Each Step in `run_meta()` gets an idempotency guard that checks filesystem artifacts (existing files, plan locations) to determine if it should skip. The only new guard is for Step 2; other Steps are already idempotent or handled by existing logic. `harness_cfg` initialization is moved before the Step 2 guard so Step 4 can use it even when Step 2 is skipped.

**Tech Stack:** Python, pytest, unittest.mock

**Spec:** `docs/specs/2026-03-25-meta-resume-design.md`

---

## Chunk 1: File Structure

**Files:**
- Modify: `src/cowork_pilot/meta_runner.py` (lines 354-374 — Step 2 block)
- Modify: `tests/test_meta_runner.py` (add resume test class)

---

## Chunk 2: Implementation

### Task 1: Write failing test — Step 2 skips when completed

**Files:**
- Modify: `tests/test_meta_runner.py`

- [ ] **Step 1: Write the failing test**

First, add `run_meta` to the module-level imports in `tests/test_meta_runner.py`:

```python
from cowork_pilot.meta_runner import (
    build_brief_prompt,
    harness_config_from,
    run_meta,
    wait_for_brief_completion,
)
```

Then add a new test class `TestMetaResumeStep2`:

```python
class TestMetaResumeStep2:
    """Step 2 resume — skip when 01-docs-setup.md already in completed/."""

    def _make_project(self, tmp_path):
        """Create a project dir with complete brief + scaffolded structure."""
        project_dir = tmp_path / "project"
        docs = project_dir / "docs"
        docs.mkdir(parents=True)

        brief_path = docs / "project-brief.md"
        brief_path.write_text(textwrap.dedent("""\
            # Project Brief

            ## 1. Overview
            - name: "Test"
            - description: "Test project"
            - type: "cli"

            ## 2. Tech Stack
            - language: "python"
            - framework: "none"
        """))

        (project_dir / "AGENTS.md").write_text("# AGENTS\n")

        ep = docs / "exec-plans"
        (ep / "active").mkdir(parents=True)
        (ep / "completed").mkdir(parents=True)
        (ep / "planning").mkdir(parents=True)

        return project_dir, ep

    def test_step2_skip_when_completed(self, tmp_path):
        """completed/에 01-docs-setup.md가 있으면 run_harness 호출 안 됨."""
        project_dir, ep = self._make_project(tmp_path)
        (ep / "completed" / "01-docs-setup.md").write_text("# Done\n")

        config = Config(project_dir=str(project_dir), log_path=str(tmp_path / "log.jsonl"))
        meta_config = MetaConfig(project_dir=str(project_dir), approval_mode="auto")

        with patch("cowork_pilot.main.run_harness") as mock_harness, \
             patch("cowork_pilot.session_manager.promote_next_plan", return_value=None), \
             patch("cowork_pilot.meta_runner.scaffold_project"):
            run_meta(config, meta_config)
            mock_harness.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PATH="$HOME/.local/bin:$PATH" pytest tests/test_meta_runner.py::TestMetaResumeStep2::test_step2_skip_when_completed -v`
Expected: FAIL — current code unconditionally calls `run_harness()` in Step 2

---

### Task 2: Write failing test — Step 2 resumes when active

- [ ] **Step 3: Write the failing test**

Add to `TestMetaResumeStep2`:

```python
    def test_step2_resume_when_active(self, tmp_path):
        """active/에 01-docs-setup.md가 있으면 run_harness 호출됨."""
        project_dir, ep = self._make_project(tmp_path)
        (ep / "active" / "01-docs-setup.md").write_text("# In Progress\n")

        config = Config(project_dir=str(project_dir), log_path=str(tmp_path / "log.jsonl"))
        meta_config = MetaConfig(project_dir=str(project_dir), approval_mode="auto")

        with patch("cowork_pilot.main.run_harness") as mock_harness, \
             patch("cowork_pilot.session_manager.promote_next_plan", return_value=None), \
             patch("cowork_pilot.meta_runner.scaffold_project"):
            run_meta(config, meta_config)
            mock_harness.assert_called()
```

- [ ] **Step 4: Run test to verify it fails**

Run: `PATH="$HOME/.local/bin:$PATH" pytest tests/test_meta_runner.py::TestMetaResumeStep2::test_step2_resume_when_active -v`
Expected: FAIL — `run_harness` is called but the mock setup may not match current code path

---

### Task 3: Write failing test — harness_cfg available after Step 2 skip

- [ ] **Step 5: Write the failing test**

Add to `TestMetaResumeStep2`:

```python
    def test_harness_cfg_available_after_step2_skip(self, tmp_path):
        """Step 2 스킵 후에도 Step 4에서 harness_cfg 사용 가능 (NameError 없음)."""
        project_dir, ep = self._make_project(tmp_path)
        (ep / "completed" / "01-docs-setup.md").write_text("# Done\n")
        (ep / "planning" / "02-impl.md").write_text("# Plan\n")

        config = Config(project_dir=str(project_dir), log_path=str(tmp_path / "log.jsonl"))
        meta_config = MetaConfig(project_dir=str(project_dir), approval_mode="auto")

        with patch("cowork_pilot.main.run_harness") as mock_harness, \
             patch("cowork_pilot.session_manager.promote_next_plan") as mock_promote, \
             patch("cowork_pilot.meta_runner.scaffold_project"):
            promoted_path = ep / "active" / "02-impl.md"
            mock_promote.side_effect = [promoted_path, None]

            # This should NOT raise NameError for harness_cfg
            run_meta(config, meta_config)
            mock_harness.assert_called()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `PATH="$HOME/.local/bin:$PATH" pytest tests/test_meta_runner.py::TestMetaResumeStep2::test_harness_cfg_available_after_step2_skip -v`
Expected: FAIL — with current code, Step 2 runs unconditionally and `harness_cfg` is always available, but after adding the guard without moving initialization, it would fail with NameError

---

### Task 4: Implement meta_runner.py changes

**Files:**
- Modify: `src/cowork_pilot/meta_runner.py` (lines 354-374)

- [ ] **Step 7: Move harness_cfg initialization before Step 2 guard**

In `meta_runner.py`, replace lines 354-374 (the entire Step 2 block) with:

```python
    # ── 공통 설정 준비 (Step 2, 4에서 사용) ──────────────────────
    config.project_dir = str(project_dir)
    harness_cfg = harness_config_from(meta_config)

    # Inherit engine settings
    harness_cfg.engine = config.engine
    if config.engine == "codex":
        harness_cfg.engine_command = config.codex_command
        harness_cfg.engine_args = config.codex_args or ["-q"]
    else:
        harness_cfg.engine_command = config.claude_command
        harness_cfg.engine_args = config.claude_args or ["-p"]

    # ── Step 2: Fill docs (Phase 2 harness) ──────────────────────
    completed_dir = project_dir / harness_cfg.exec_plans_dir / "completed"
    docs_setup_completed = (completed_dir / "01-docs-setup.md").exists()

    if docs_setup_completed:
        logger.info("meta", "Step 2: 01-docs-setup already in completed/, skipping",
                    completed_file=str(completed_dir / "01-docs-setup.md"))
        print("Step 2: 이미 완료, 스킵")
    else:
        logger.info("meta", "Step 2: Filling docs via harness")
        print("\nStep 2: docs/ 내용 채우기 (Phase 2 하네스)...")
        # Phase 1 ON — clear ignored sessions (brief session is done)
        ignored_sessions.clear()
        run_harness(config, harness_cfg, ignored_sessions=ignored_sessions)
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `PATH="$HOME/.local/bin:$PATH" pytest tests/test_meta_runner.py -v`
Expected: All tests PASS (existing 9 + new 3 = 12)

- [ ] **Step 9: Commit**

```bash
git add src/cowork_pilot/meta_runner.py tests/test_meta_runner.py
git commit -m "feat: add Step 2 resume guard for meta mode

Each Step in run_meta() now checks filesystem state before running.
Step 2 skips if 01-docs-setup.md is already in completed/.
harness_cfg initialization moved before Step 2 guard so Step 4
can use it even when Step 2 is skipped."
```
