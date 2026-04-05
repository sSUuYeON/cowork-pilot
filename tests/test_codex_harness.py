from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from cowork_pilot.codex.config import CodexExecConfig
from cowork_pilot.codex.exec_runner import (
    _build_exec_command,
    _build_subprocess_env,
    _read_codex_event_stream,
    _summarize_codex_event,
    run_chunk,
)
from cowork_pilot.codex.harness import _harness_prompt_builder, run_codex_harness
from cowork_pilot.codex.models import ChunkResult, ChunkRunStatus
from cowork_pilot.plan_parser import parse_exec_plan


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SAMPLE_PLAN = FIXTURE_DIR / "sample_exec_plan.md"
SAMPLE_BUILD_PLAN = FIXTURE_DIR / "sample_exec_plan_build.md"
SAMPLE_BUILD_PARTIAL_PLAN = FIXTURE_DIR / "sample_exec_plan_build_partial.md"


def test_build_exec_command_passes_prompt_as_argument():
    cmd = _build_exec_command(
        "hello world",
        "/tmp/project",
        codex_command="/usr/local/bin/codex",
        codex_extra_args=["--json"],
    )

    assert cmd == [
        "/usr/local/bin/codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-C",
        "/tmp/project",
        "--json",
        "hello world",
    ]


def test_build_subprocess_env_restores_system_path_entries():
    env = _build_subprocess_env({"PATH": "/custom/bin"})
    entries = env["PATH"].split(os.pathsep)

    assert entries[:6] == [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    assert entries[-1] == "/custom/bin"


def test_summarize_codex_event_formats_command_and_message():
    command_lines, command_message = _summarize_codex_event({
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "status": "completed",
            "command": "/bin/zsh -lc pwd",
            "aggregated_output": "/tmp/project\n",
            "exit_code": 0,
        },
    })
    message_lines, message_text = _summarize_codex_event({
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": "작업을 마쳤습니다.",
        },
    })

    assert command_message == ""
    assert command_lines == [
        "command completed (rc=0): /bin/zsh -lc pwd",
        "command output: /tmp/project",
    ]
    assert message_lines == ["assistant: 작업을 마쳤습니다."]
    assert message_text == "작업을 마쳤습니다."


def test_read_codex_event_stream_handles_large_json_line():
    class FakeStream:
        def __init__(self, chunks: list[bytes]):
            self._chunks = list(chunks)

        async def read(self, _size: int = -1) -> bytes:
            if self._chunks:
                return self._chunks.pop(0)
            return b""

    long_text = "가" * 70000
    line = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": long_text,
                },
            },
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")

    stdout, event_log, last_message = asyncio.run(
        _read_codex_event_stream(
            FakeStream([line[:20000], line[20000:45000], line[45000:]]),
            chunk_number=7,
        )
    )

    assert long_text in stdout
    assert "assistant:" in event_log
    assert last_message == long_text


def test_dry_run_harness_does_not_modify_active_plan(tmp_path):
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_PLAN.name
    shutil.copy(SAMPLE_PLAN, plan_path)

    before = plan_path.read_text(encoding="utf-8")

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(),
            dry_run=True,
        )
    )

    after = plan_path.read_text(encoding="utf-8")

    assert result is True
    assert after == before


def test_harness_prompt_reuses_original_build_session_prompt(tmp_path):
    (tmp_path / "config.toml").write_text(
        "[review]\nenabled = true\nskip_chunks = []\n",
        encoding="utf-8",
    )

    plan_path = tmp_path / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    prompt = _harness_prompt_builder(chunk, str(tmp_path))

    assert "/engineering:code-review" in prompt
    assert "/chunk-complete:chunk-complete" in prompt
    assert "VM에서 실행하지 마라" in prompt
    assert "Codex Exec Compatibility" in prompt
    assert "## Skill Reference: code-review" in prompt
    assert "Security: SQL injection, XSS, CSRF" in prompt
    assert "## Skill Reference: chunk-complete" in prompt
    assert "Never move the exec-plan file from `active/` to `completed/`." in prompt


def test_harness_prints_remaining_criteria_on_chunk_failure(tmp_path, monkeypatch, capsys):
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_PLAN.name
    shutil.copy(SAMPLE_PLAN, plan_path)

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Foundation",
            status=ChunkRunStatus.FAILED,
            returncode=1,
            stderr="codex failed",
            duration_seconds=1.0,
            attempt=3,
        )

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(),
        )
    )

    stderr = capsys.readouterr().err
    assert result is False
    assert "Recognized Completion Criteria (3):" in stderr
    assert "      - [ ] pytest tests/test_models.py 통과" in stderr
    assert "      - [ ] pytest tests/test_config.py 통과" in stderr
    assert "      - [ ] src/models.py 파일 존재" in stderr
    assert "Remaining Completion Criteria:" in stderr
    assert "pytest tests/test_models.py 통과" in stderr
    assert "src/models.py 파일 존재" in stderr
    assert escalations


def test_harness_stops_on_build_failed_and_keeps_unchecked_criteria(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Build failed → repair loop attempted → repair loop fails (always fails) → escalate.

    Unchecked build criteria should remain unchecked (not force-checked).
    """
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        lambda *args, **kwargs: ("FAILED", "npm run build exit 1"),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(build_repair_max_retries=2),
        )
    )

    stderr = capsys.readouterr().err
    after = plan_path.read_text(encoding="utf-8")

    assert result is False
    assert "Recognized Completion Criteria (3):" in stderr
    assert "      - [ ] vercel.json 파일 존재" in stderr
    assert "      - [ ] [BUILD] npm run lint" in stderr
    assert "      - [ ] [BUILD] npm run build" in stderr
    # Should enter repair loop
    assert "entering repair loop" in stderr
    assert "Build repair attempt" in stderr
    # Should show repair failed in stderr
    assert "build repair failed" in stderr
    # Should escalate after repair loop exhausts
    assert escalations
    assert "build repair" in escalations[0]
    assert "Remaining Completion Criteria:" in stderr
    assert "[BUILD] npm run lint" in stderr
    assert "[BUILD] npm run build" in stderr
    assert "- [ ] [BUILD] npm run lint" in after
    assert "- [ ] [BUILD] npm run build" in after


def test_run_chunk_times_out_when_codex_event_stream_stalls(monkeypatch, tmp_path):
    class FakeStream:
        def __init__(self, chunks: list[bytes] | None = None):
            self._chunks = list(chunks or [])
            self.closed = False

        async def read(self, _size: int = -1) -> bytes:
            while not self._chunks and not self.closed:
                await asyncio.sleep(0.005)
            if self._chunks:
                return self._chunks.pop(0)
            return b""

    class FakeProc:
        def __init__(self):
            self.pid = 4242
            self.returncode: int | None = None
            self.stdout = FakeStream([b'{"type":"turn.started"}\n'])
            self.stderr = FakeStream()

        async def wait(self) -> int:
            while self.returncode is None:
                await asyncio.sleep(3600)
            return self.returncode

        def kill(self) -> None:
            self.returncode = -9
            self.stdout.closed = True
            self.stderr.closed = True

    fake_proc = FakeProc()

    async def fake_create_subprocess_exec(*args, **kwargs):
        return fake_proc

    monkeypatch.setattr(
        "cowork_pilot.codex.exec_runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.exec_runner._SUBPROCESS_HEARTBEAT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.exec_runner._SUBPROCESS_STALL_SECONDS",
        0.03,
    )

    chunk = parse_exec_plan(SAMPLE_PLAN).chunks[0]
    result = asyncio.run(
        run_chunk(
            chunk,
            str(tmp_path),
            timeout_seconds=1.0,
            prompt_builder=lambda c, p: "prompt",
        )
    )

    assert result.status == ChunkRunStatus.TIMEOUT
    assert "no codex event output" in result.stderr


def test_verify_returns_incomplete_when_non_build_criteria_unchecked(
    tmp_path,
    monkeypatch,
    capsys,
):
    """codex exec 성공 + 빌드 통과했지만 non-build 체크박스가 남아있으면
    force-check 하지 않고 INCOMPLETE → incomplete repair loop → max_retries 소진 후 escalate."""
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PARTIAL_PLAN.name
    shutil.copy(SAMPLE_BUILD_PARTIAL_PLAN, plan_path)

    run_count = [0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        run_count[0] += 1
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        lambda *args, **kwargs: ("PASSED", ""),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(max_retries=2),
        )
    )

    stderr = capsys.readouterr().err
    after = plan_path.read_text(encoding="utf-8")

    # non-build criterion "vercel.json 파일 존재" should NOT be force-checked
    assert "- [ ] vercel.json 파일 존재" in after
    # 1 initial run + 2 incomplete repair attempts = 3 total
    assert run_count[0] == 3
    assert "entering incomplete repair loop" in stderr
    assert "Incomplete repair attempt" in stderr
    assert "incomplete repair failed" in stderr
    # Plan should fail overall because chunk couldn't be completed
    assert result is False
    # Escalation should have been sent after repair exhausted
    assert escalations
    assert "incomplete repair" in escalations[0]


def test_codex_exec_config_loads_build_repair_max_retries(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[codex.exec]\n"
        "command = \"codex\"\n"
        "build_repair_max_retries = 5\n",
        encoding="utf-8",
    )
    from cowork_pilot.codex.config import load_codex_exec_config
    cfg = load_codex_exec_config(config_file)
    assert cfg.build_repair_max_retries == 5


def test_codex_exec_config_default_build_repair_max_retries():
    from cowork_pilot.codex.config import CodexExecConfig
    cfg = CodexExecConfig()
    assert cfg.build_repair_max_retries == 3


def test_build_repair_prompt_contains_required_sections(tmp_path):
    """build-repair prompt에는 원래 session prompt, 에러 로그, 수리 지시,
    [BUILD] 실행 금지가 포함되어야 한다.
    code-review/chunk-complete 스킬 레퍼런스는 포함하면 안 된다."""
    from cowork_pilot.codex.harness import _build_repair_prompt

    plan_path = tmp_path / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    prompt = _build_repair_prompt(
        chunk,
        str(tmp_path),
        "Error: Cannot find module './App'\nnpm ERR! code ELIFECYCLE",
    )

    # 필수 포함
    assert "Build Repair Mode" in prompt
    assert "프로젝트 설정을 완료하라" in prompt  # original session prompt
    assert "Cannot find module './App'" in prompt  # error log
    assert "최소 수정" in prompt
    assert "비빌드" in prompt  # non-build criteria 유지 지시
    assert "[BUILD] 항목은 직접 실행하지 말 것" in prompt

    # 포함하면 안 됨
    assert "Skill Reference: code-review" not in prompt
    assert "Skill Reference: chunk-complete" not in prompt


def test_incomplete_repair_prompt_contains_required_sections(tmp_path):
    """incomplete-repair prompt에는 미충족 criteria 목록, 원래 session prompt,
    기존 구현 보존 지시가 포함되어야 한다."""
    from cowork_pilot.codex.harness import _build_incomplete_repair_prompt

    plan_path = tmp_path / SAMPLE_BUILD_PARTIAL_PLAN.name
    shutil.copy(SAMPLE_BUILD_PARTIAL_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    prompt = _build_incomplete_repair_prompt(
        chunk,
        str(tmp_path),
        ["vercel.json 파일 존재", "[BUILD] npm run lint"],
    )

    # 필수 포함
    assert "Incomplete Criteria Repair Mode" in prompt
    assert "프로젝트 설정을 완료하라" in prompt  # original session prompt
    assert "vercel.json 파일 존재" in prompt  # unchecked criteria
    assert "[BUILD] npm run lint" in prompt
    assert "이미 통과한 criteria" in prompt
    assert "[BUILD] 항목은 직접 실행하지 말 것" in prompt

    # 포함하면 안 됨
    assert "Skill Reference: code-review" not in prompt
    assert "Skill Reference: chunk-complete" not in prompt


def test_incomplete_repair_loop_succeeds_on_first_attempt(tmp_path, monkeypatch):
    """incomplete repair 1회차에서 미충족 criteria 해결 → COMPLETED."""
    from cowork_pilot.codex.harness import _run_incomplete_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PARTIAL_PLAN.name
    shutil.copy(SAMPLE_BUILD_PARTIAL_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        lambda *args, **kwargs: ("COMPLETED", ""),
    )

    status, detail = asyncio.run(
        _run_incomplete_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            unchecked_descriptions=["vercel.json 파일 존재"],
            exec_config=CodexExecConfig(max_retries=3),
        )
    )

    assert status == "COMPLETED"


def test_incomplete_repair_loop_delegates_to_build_repair(tmp_path, monkeypatch):
    """incomplete repair 중 BUILD_FAILED 발생 시 build repair loop로 위임."""
    from cowork_pilot.codex.harness import _run_incomplete_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PARTIAL_PLAN.name
    shutil.copy(SAMPLE_BUILD_PARTIAL_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        lambda *args, **kwargs: ("BUILD_FAILED", "npm ERR! build failed"),
    )

    build_repair_called = [False]

    async def fake_build_repair_loop(*args, **kwargs):
        build_repair_called[0] = True
        return ("COMPLETED", "")

    monkeypatch.setattr(
        "cowork_pilot.codex.harness._run_build_repair_loop",
        fake_build_repair_loop,
    )

    status, detail = asyncio.run(
        _run_incomplete_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            unchecked_descriptions=["vercel.json 파일 존재"],
            exec_config=CodexExecConfig(max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert build_repair_called[0]


def test_build_repair_loop_succeeds_on_first_attempt(tmp_path, monkeypatch):
    """build-repair 1회차에서 빌드 통과 → COMPLETED 반환."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    repair_call_count = 0

    async def fake_run_chunk_with_retry(*args, **kwargs):
        nonlocal repair_call_count
        repair_call_count += 1
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    verify_calls = [0]
    def fake_verify(plan_path, chunk, project_dir, build_timeout=600.0):
        verify_calls[0] += 1
        return ("COMPLETED", "")
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        fake_verify,
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR! code ELIFECYCLE",
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert repair_call_count == 1
    assert verify_calls[0] == 1


def test_build_repair_loop_succeeds_on_second_attempt(tmp_path, monkeypatch):
    """1회차 빌드 여전히 실패, 2회차에 통과 → COMPLETED."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )

    verify_calls = [0]
    def fake_verify(plan_path, chunk, project_dir, build_timeout=600.0):
        verify_calls[0] += 1
        if verify_calls[0] == 1:
            return ("BUILD_FAILED", "still failing")
        return ("COMPLETED", "")
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        fake_verify,
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR! initial error",
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert verify_calls[0] == 2


def test_build_repair_loop_exhausts_retries(tmp_path, monkeypatch):
    """모든 repair 시도 실패 → BUILD_FAILED 반환."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        lambda *args, **kwargs: ("BUILD_FAILED", "persistent error"),
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR!",
            exec_config=CodexExecConfig(build_repair_max_retries=2),
        )
    )

    assert status == "BUILD_FAILED"
    assert "persistent error" in detail


def test_build_repair_loop_handles_codex_exec_failure(tmp_path, monkeypatch):
    """codex exec 자체가 실패하면 해당 attempt를 소모하고 다음으로."""
    from cowork_pilot.codex.harness import _run_build_repair_loop

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)
    chunk = parse_exec_plan(plan_path).chunks[0]

    call_count = [0]
    async def fake_run_chunk_with_retry(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return ChunkResult(
                chunk_number=1,
                chunk_name="Setup",
                status=ChunkRunStatus.FAILED,
                returncode=1,
                duration_seconds=1.0,
            )
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )

    verify_calls = [0]
    def fake_verify(*args, **kwargs):
        verify_calls[0] += 1
        return ("COMPLETED", "")
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._verify_and_update_chunk",
        fake_verify,
    )

    status, detail = asyncio.run(
        _run_build_repair_loop(
            plan_path=plan_path,
            chunk=chunk,
            project_dir=str(tmp_path),
            build_error_log="npm ERR!",
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    assert status == "COMPLETED"
    assert call_count[0] == 2  # 1st failed, 2nd succeeded
    assert verify_calls[0] == 1  # only called after successful codex exec


def test_harness_runs_build_repair_on_build_failed(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Codex exec succeeds, initial build fails, repair loop fixes it on 2nd attempt.

    - run_chunk_with_retry always returns SUCCESS
    - run_build_criteria fails on 1st call, succeeds on subsequent calls
    - Expected: plan completes successfully, plan moves to completed/
    - Assert "completed after build repair" in stderr
    """
    from cowork_pilot.codex.harness import run_codex_harness

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    # Pre-check non-build criteria so when build passes, plan is complete
    plan_text = plan_path.read_text(encoding="utf-8")
    # Chunk 1 non-build criteria
    plan_text = plan_text.replace(
        "- [ ] vercel.json 파일 존재",
        "- [x] vercel.json 파일 존재"
    )
    # Chunk 2 non-build criteria
    plan_text = plan_text.replace(
        "- [ ] README.md 파일 존재",
        "- [x] README.md 파일 존재"
    )
    plan_path.write_text(plan_text, encoding="utf-8")

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    build_calls = [0]

    def fake_run_build_criteria(chunk, project_dir, plan_path, timeout=600.0):
        build_calls[0] += 1
        if build_calls[0] == 1:
            # First call (initial verification) fails
            return ("FAILED", "npm ERR! module not found")
        # Subsequent calls (repair attempts) succeed
        # Mock updating the checkboxes
        from cowork_pilot.plan_parser import update_checkboxes_by_description
        for cr in chunk.completion_criteria:
            if cr.build_command and not cr.checked:
                update_checkboxes_by_description(plan_path, chunk.number, cr.description)
        return ("PASSED", "")

    escalations: list[str] = []

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        fake_run_build_criteria,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(build_repair_max_retries=3),
        )
    )

    stderr = capsys.readouterr().err
    completed_dir = exec_plans_dir / "completed"

    # Plan should complete successfully
    assert result is True
    # File should move to completed/
    assert not plan_path.exists()
    assert (completed_dir / SAMPLE_BUILD_PLAN.name).exists()
    # Should show repair loop in action
    assert "Build repair attempt" in stderr
    assert "completed after build repair" in stderr
    # Should NOT escalate
    assert not escalations


def test_harness_escalates_after_build_repair_exhausted(
    tmp_path,
    monkeypatch,
    capsys,
):
    """Codex exec succeeds, build always fails, repair loop exhausts.

    - run_chunk_with_retry always returns SUCCESS
    - run_build_criteria always returns FAILED
    - build_repair_max_retries = 2
    - Expected: plan fails, escalation sent with "build repair" in message
    - Build criteria should remain unchecked
    """
    from cowork_pilot.codex.harness import run_codex_harness

    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PLAN.name
    shutil.copy(SAMPLE_BUILD_PLAN, plan_path)

    async def fake_run_chunk_with_retry(*args, **kwargs):
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        lambda *args, **kwargs: ("FAILED", "persistent build error"),
    )

    escalations: list[str] = []

    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(build_repair_max_retries=2),
        )
    )

    stderr = capsys.readouterr().err
    after = plan_path.read_text(encoding="utf-8")

    # Plan should fail
    assert result is False
    # Should attempt repair
    assert "Build repair attempt" in stderr
    # Should show repair failed
    assert "build repair failed" in stderr
    # Should escalate with "build repair" in message
    assert escalations
    assert "build repair" in escalations[0]
    # Build criteria should remain unchecked
    assert "- [ ] [BUILD] npm run lint" in after
    assert "- [ ] [BUILD] npm run build" in after


def test_harness_retries_incomplete_chunk_and_succeeds(
    tmp_path,
    monkeypatch,
    capsys,
):
    """INCOMPLETE → incomplete repair loop → codex fixes remaining criteria on 1st repair → COMPLETED.

    Uses SAMPLE_BUILD_PARTIAL_PLAN which has one non-build criterion unchecked.
    The repair loop's codex exec simulates codex checking the remaining criterion.
    """
    exec_plans_dir = tmp_path / "docs" / "exec-plans"
    active_dir = exec_plans_dir / "active"
    active_dir.mkdir(parents=True)
    plan_path = active_dir / SAMPLE_BUILD_PARTIAL_PLAN.name
    shutil.copy(SAMPLE_BUILD_PARTIAL_PLAN, plan_path)

    run_count = [0]

    async def fake_run_chunk_with_retry(*args, **kwargs):
        run_count[0] += 1
        if run_count[0] == 2:
            # On repair attempt (2nd overall run), simulate codex fixing the non-build criterion
            text = plan_path.read_text(encoding="utf-8")
            text = text.replace(
                "- [ ] vercel.json 파일 존재",
                "- [x] vercel.json 파일 존재",
            )
            plan_path.write_text(text, encoding="utf-8")
        return ChunkResult(
            chunk_number=1,
            chunk_name="Setup",
            status=ChunkRunStatus.SUCCESS,
            returncode=0,
            duration_seconds=1.0,
        )

    def fake_run_build_criteria(chunk, project_dir, pp, timeout=600.0):
        """Simulate build pass + checkbox update (like real run_build_criteria)."""
        from cowork_pilot.plan_parser import update_checkboxes_by_description
        for cr in chunk.completion_criteria:
            if cr.build_command and not cr.checked:
                update_checkboxes_by_description(pp, chunk.number, cr.description)
        return ("PASSED", "")

    escalations: list[str] = []
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_chunk_with_retry",
        fake_run_chunk_with_retry,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.run_build_criteria",
        fake_run_build_criteria,
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness.notify_escalate",
        lambda message: escalations.append(message),
    )
    monkeypatch.setattr(
        "cowork_pilot.codex.harness._notify",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        run_codex_harness(
            exec_plans_dir=str(exec_plans_dir),
            project_dir=str(tmp_path),
            exec_config=CodexExecConfig(max_retries=3),
        )
    )

    stderr = capsys.readouterr().err
    completed_dir = exec_plans_dir / "completed"

    # 1 initial run + 1 incomplete repair run = 2 total
    assert run_count[0] == 2
    assert "entering incomplete repair loop" in stderr
    assert "Incomplete repair attempt 1/3" in stderr
    assert "completed after incomplete repair" in stderr
    # Plan should complete successfully
    assert result is True
    assert not plan_path.exists()
    assert (completed_dir / SAMPLE_BUILD_PARTIAL_PLAN.name).exists()
    # No escalation
    assert not escalations
