from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cowork_pilot.config import Config
from cowork_pilot.models import EventType, Event, Response


def classify_tool_use(tool_use: dict) -> EventType:
    """Classify a tool_use block by its name. Pure algorithm, no intelligence.

    Note: FREE_TEXT is not triggered by tool_use — it's a separate detection
    path in the main loop when Cowork is waiting for plain user input without
    a tool_use block. This function only classifies tool_use-based events.
    """
    name = tool_use.get("name", "")
    if name == "AskUserQuestion":
        return EventType.QUESTION
    return EventType.PERMISSION


def extract_context(jsonl_path: Path, max_lines: int = 10) -> list[str]:
    """Extract recent conversation lines from JSONL for CLI context.

    Reads from the end of the file, filters to user/assistant records,
    returns up to max_lines of summarized conversation.
    """
    records: list[dict] = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") in ("user", "assistant"):
                    records.append(record)
    except (FileNotFoundError, OSError):
        return []

    # Take the most recent max_lines records
    recent = records[-max_lines:]

    context_lines = []
    for record in recent:
        msg = record.get("message", {})
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, str):
            context_lines.append(f"[{role}] {content}")
        elif isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        texts.append(f"(called {block.get('name', 'unknown')})")
                    elif block.get("type") == "tool_result":
                        texts.append("(tool result)")
            if texts:
                context_lines.append(f"[{role}] {' '.join(texts)}")

    return context_lines


def build_prompt(event: Event, docs_content: str = "") -> str:
    """Build the prompt that will be sent to the CLI agent.

    Injects question/options, recent context, and project docs directly
    into the prompt (no reliance on AGENTS.md auto-discovery).
    """
    parts: list[str] = []

    # Project docs injection
    if docs_content:
        parts.append("=== PROJECT DOCUMENTS ===")
        parts.append(docs_content)
        parts.append("=== END DOCUMENTS ===\n")

    # Recent context
    if event.context_lines:
        parts.append("=== RECENT CONVERSATION ===")
        for line in event.context_lines:
            parts.append(line)
        parts.append("=== END CONVERSATION ===\n")

    # Event-specific prompt
    if event.event_type == EventType.QUESTION:
        parts.append("=== QUESTION FROM COWORK ===")
        for q in event.questions:
            parts.append(f"Question: {q.get('question', '')}")
            options = q.get("options", [])
            for i, opt in enumerate(options, 1):
                label = opt.get("label", "")
                desc = opt.get("description", "")
                parts.append(f"  {i}. {label} — {desc}")
            if q.get("multiSelect"):
                parts.append("(Multiple selections allowed)")
        parts.append("")
        parts.append("Based on the project documents and conversation context, choose the best option.")
        parts.append("RESPOND WITH ONLY the option number (e.g. '1'), 'Other: your custom text', or 'ESCALATE'.")
        parts.append("Use ESCALATE if the question matches a blacklist category (payment, secrets, production deploy, etc.) or you're not confident — let the human decide.")
        parts.append("Do not explain your reasoning. Just the answer.")

    elif event.event_type == EventType.PERMISSION:
        parts.append("=== TOOL APPROVAL REQUEST ===")
        parts.append(f"Tool: {event.tool_name}")
        parts.append(f"Input: {json.dumps(event.tool_input, ensure_ascii=False)}")
        parts.append("")
        parts.append("Based on the project documents (especially golden-rules), should this tool call be allowed?")
        parts.append("RESPOND WITH ONLY one of: 'allow', 'deny', or 'ESCALATE'.")
        parts.append("")
        parts.append("AUTO-ALLOW these (always respond 'allow'):")
        parts.append("- allow_cowork_file_delete, allow_cowork_directory — meta-permissions, not actual deletions")
        parts.append("- Bash commands for build/test/dev (npm, npx, next build, tsc, eslint, prettier, etc.)")
        parts.append("- Bash commands for package install (npm install, pip install, etc.)")
        parts.append("- Bash commands for file cleanup during build (.next, node_modules, dist, __pycache__)")
        parts.append("")
        parts.append("ESCALATE these (respond 'ESCALATE'):")
        parts.append("- Commands touching secrets, env files, or credentials")
        parts.append("- Commands that deploy to production (git push, vercel deploy, etc.)")
        parts.append("- Commands that modify system files outside the project directory")
        parts.append("- Anything you're not confident about")
        parts.append("")
        parts.append("Do not explain your reasoning. Just the answer.")

    elif event.event_type == EventType.FREE_TEXT:
        parts.append("=== FREE TEXT INPUT NEEDED ===")
        parts.append("Cowork is waiting for user text input.")
        parts.append("")
        parts.append("Based on the project documents and conversation context, provide the appropriate response.")
        parts.append("RESPOND WITH ONLY the text to input. No quotes, no explanation.")

    return "\n".join(parts)


def call_cli(prompt: str, config: Config) -> str | None:
    """Call the CLI agent (Claude CLI or Codex CLI) with the given prompt.

    Returns the CLI's stdout stripped, or None on failure.
    Uses stdin to pass the prompt to avoid OS argument length limits.
    """
    if config.engine == "codex":
        cmd = [config.codex_command] + config.codex_args
    else:
        cmd = [config.claude_command] + config.claude_args

    import sys as _sys
    print(f"  [dispatcher] engine={config.engine} cmd={cmd}", file=_sys.stderr)
    print(f"  [dispatcher] prompt length={len(prompt)} chars", file=_sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=120,  # CLI agent decision timeout (seconds)
            cwd=config.project_dir,
        )
        if result.returncode != 0:
            print(f"  [dispatcher] returncode={result.returncode}", file=_sys.stderr)
            print(f"  [dispatcher] stderr={result.stderr[:500]}", file=_sys.stderr)
            return None
        print(f"  [dispatcher] success, stdout={result.stdout[:200]}", file=_sys.stderr)
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("  [dispatcher] TIMEOUT (120s)", file=_sys.stderr)
        return None
    except FileNotFoundError:
        print(f"  [dispatcher] command not found: {cmd[0]}", file=_sys.stderr)
        return None
    except OSError as e:
        print(f"  [dispatcher] OSError: {e}", file=_sys.stderr)
        return None


def load_docs(project_dir: Path) -> str:
    """Load key project documents for prompt injection.

    Reads decision-criteria.md and golden-rules.md from docs/.
    Returns concatenated content, or empty string if missing.
    """
    docs_dir = Path(project_dir) / "docs"
    if not docs_dir.exists():
        return ""

    parts: list[str] = []
    doc_files = [
        "golden-rules.md",
        "decision-criteria.md",
    ]

    for filename in doc_files:
        filepath = docs_dir / filename
        if filepath.exists():
            parts.append(f"--- {filename} ---")
            parts.append(filepath.read_text(encoding="utf-8"))

    # Also check for active exec plans
    active_plans = docs_dir / "exec-plans" / "active"
    if active_plans.exists():
        for plan_file in sorted(active_plans.glob("*.md")):
            parts.append(f"--- active plan: {plan_file.name} ---")
            parts.append(plan_file.read_text(encoding="utf-8"))

    return "\n".join(parts)
