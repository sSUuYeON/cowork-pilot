from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_jsonl_line(line: str) -> dict[str, Any] | None:
    """Parse a single JSONL line and extract tool_use / tool_result info.

    Returns a normalized dict with keys:
      - type: "assistant" | "user"
      - tool_uses: list of {id, name, input} (assistant only)
      - tool_results: list of tool_use_ids (user only)
      - raw: the original parsed dict
    Returns None for non-message records or invalid JSON.
    """
    try:
        record = json.loads(line.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    record_type = record.get("type")
    if record_type not in ("assistant", "user"):
        return None

    message = record.get("message", {})
    content = message.get("content", [])

    if isinstance(content, str):
        # Plain text user message — no tool data
        return None

    if record_type == "assistant":
        tool_uses = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_uses.append({
                    "id": block["id"],
                    "name": block["name"],
                    "input": block.get("input", {}),
                })
        if not tool_uses:
            return None
        return {"type": "assistant", "tool_uses": tool_uses, "raw": record}

    if record_type == "user":
        tool_results = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_results.append(block["tool_use_id"])
        if not tool_results:
            return None
        return {"type": "user", "tool_results": tool_results, "raw": record}

    return None


import time as _time
from cowork_pilot.models import WatcherState, EventType, Event


class WatcherStateMachine:
    """State machine for detecting unanswered tool_use in JSONL stream.

    States: IDLE → TOOL_USE_DETECTED → DEBOUNCE_WAIT → PENDING_RESPONSE → RESPONDED → IDLE
    """

    def __init__(self, debounce_seconds: float = 2.0):
        self.state = WatcherState.IDLE
        self.debounce_seconds = debounce_seconds
        self.pending_tool_use: dict | None = None
        self._detected_at: float = 0.0

    def on_tool_use(self, tool_use: dict) -> None:
        """Called when a new tool_use block is parsed from JSONL."""
        self.pending_tool_use = tool_use
        self._detected_at = _time.monotonic()
        self.state = WatcherState.TOOL_USE_DETECTED

    def on_tool_result(self, tool_use_id: str) -> None:
        """Called when a tool_result matching a pending tool_use is found."""
        if self.pending_tool_use and self.pending_tool_use["id"] == tool_use_id:
            self.state = WatcherState.RESPONDED
            self.pending_tool_use = None

    def tick(self) -> None:
        """Advance the state machine based on elapsed time."""
        if self.state == WatcherState.TOOL_USE_DETECTED:
            self.state = WatcherState.DEBOUNCE_WAIT

        elif self.state == WatcherState.DEBOUNCE_WAIT:
            elapsed = _time.monotonic() - self._detected_at
            if elapsed >= self.debounce_seconds:
                self.state = WatcherState.PENDING_RESPONSE

        elif self.state == WatcherState.RESPONDED:
            self.state = WatcherState.IDLE
            self.pending_tool_use = None

    def get_pending_event(self) -> Event | None:
        """If state is PENDING_RESPONSE, return an Event for the pending tool_use."""
        if self.state != WatcherState.PENDING_RESPONSE:
            return None
        if self.pending_tool_use is None:
            return None

        tu = self.pending_tool_use
        name = tu["name"]
        inp = tu.get("input", {})

        if name == "AskUserQuestion":
            event_type = EventType.QUESTION
        else:
            event_type = EventType.PERMISSION

        return Event(
            event_type=event_type,
            tool_use_id=tu["id"],
            tool_name=name,
            questions=inp.get("questions", []),
            tool_input=inp,
            context_lines=[],  # filled by Dispatcher
        )


class JSONLTail:
    """Tail a JSONL file, yielding only new lines since last read.

    On init, seeks to end of file (skips existing content).
    Each call to read_new_lines() returns lines appended since last call.
    """

    def __init__(self, path: Path):
        self.path = path
        self._offset = self._get_file_size()

    def _get_file_size(self) -> int:
        try:
            return self.path.stat().st_size
        except (FileNotFoundError, OSError):
            return 0

    def read_new_lines(self) -> list[str]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                f.seek(self._offset)
                new_content = f.read()
                self._offset = f.tell()
        except (FileNotFoundError, OSError):
            return []

        if not new_content:
            return []

        lines = new_content.strip().split("\n")
        return [line for line in lines if line.strip()]

    def switch_file(self, new_path: Path) -> None:
        self.path = new_path
        self._offset = self._get_file_size()
