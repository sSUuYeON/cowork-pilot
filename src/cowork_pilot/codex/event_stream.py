from __future__ import annotations

import json

_EVENT_TEXT_SNIPPET_CHARS = 400


def _truncate_text(text: str, limit: int = _EVENT_TEXT_SNIPPET_CHARS) -> str:
    """Collapse whitespace and trim text for terminal logging."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def summarize_codex_event(payload: dict) -> tuple[list[str], str]:
    """Convert a Codex JSONL event into human-readable log lines."""
    event_type = payload.get("type", "unknown")
    lines: list[str] = []
    last_message = ""

    if event_type == "thread.started":
        thread_id = payload.get("thread_id", "")
        if thread_id:
            lines.append(f"thread started: {thread_id}")
        return (lines, last_message)

    if event_type == "turn.started":
        lines.append("turn started")
        return (lines, last_message)

    if event_type == "turn.completed":
        usage = payload.get("usage", {})
        if usage:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            cached_input_tokens = usage.get("cached_input_tokens")
            parts = []
            if input_tokens is not None:
                parts.append(f"in={input_tokens}")
            if cached_input_tokens is not None:
                parts.append(f"cached={cached_input_tokens}")
            if output_tokens is not None:
                parts.append(f"out={output_tokens}")
            if parts:
                lines.append("turn completed: " + ", ".join(parts))
            else:
                lines.append("turn completed")
        else:
            lines.append("turn completed")
        return (lines, last_message)

    if not event_type.startswith("item."):
        lines.append(f"{event_type}: {_truncate_text(json.dumps(payload, ensure_ascii=False))}")
        return (lines, last_message)

    item = payload.get("item", {})
    item_type = item.get("type", "unknown")
    item_status = item.get("status") or (
        "completed" if event_type == "item.completed" else "in_progress"
    )

    if item_type == "agent_message":
        text = (item.get("text") or "").strip()
        if text:
            last_message = text
            prefix = "assistant" if event_type == "item.completed" else "assistant started"
            lines.append(f"{prefix}: {_truncate_text(text)}")
        return (lines, last_message)

    if item_type == "command_execution":
        command = item.get("command", "")
        if event_type == "item.started":
            lines.append(f"command started: {command}")
        else:
            exit_code = item.get("exit_code")
            lines.append(f"command {item_status} (rc={exit_code}): {command}")
            output = (item.get("aggregated_output") or "").strip()
            if output:
                lines.append(f"command output: {_truncate_text(output)}")
        return (lines, last_message)

    summary_bits = [item_type]
    if item_status:
        summary_bits.append(str(item_status))
    lines.append("item " + " ".join(summary_bits))
    return (lines, last_message)


def _parse_event_line(line: str) -> dict | None:
    stripped = line.strip()
    if not stripped:
        return None

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    return payload


def extract_thread_id(lines: list[str]) -> str:
    """Return the first thread id observed in a Codex JSONL event stream."""
    for line in lines:
        payload = _parse_event_line(line)
        if payload is None:
            continue
        if payload.get("type") != "thread.started":
            continue

        thread_id = payload.get("thread_id")
        if isinstance(thread_id, str):
            return thread_id

    return ""


def extract_terminal_assistant_message(lines: list[str]) -> str:
    """Return the last completed assistant message observed in the event stream."""
    last_message = ""

    for line in lines:
        payload = _parse_event_line(line)
        if payload is None:
            continue
        if payload.get("type") != "item.completed":
            continue

        item = payload.get("item", {})
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue

        text = item.get("text")
        if isinstance(text, str) and text.strip():
            last_message = text.strip()

    return last_message
