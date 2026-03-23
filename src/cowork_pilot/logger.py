from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


class StructuredLogger:
    def __init__(self, path: str | Path, level: str = "INFO"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.level = level
        self._levels = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}

    def _should_log(self, level: str) -> bool:
        return self._levels.get(level, 0) >= self._levels.get(self.level, 0)

    def log(self, level: str, component: str, message: str, **extra):
        if not self._should_log(level):
            return
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "component": component,
            "message": message,
            **extra,
        }
        line = json.dumps(record, ensure_ascii=False)
        with open(self.path, "a") as f:
            f.write(line + "\n")
        if level in ("WARN", "ERROR"):
            print(f"[{level}] {component}: {message}", file=sys.stderr)

    def info(self, component: str, message: str, **extra):
        self.log("INFO", component, message, **extra)

    def warn(self, component: str, message: str, **extra):
        self.log("WARN", component, message, **extra)

    def error(self, component: str, message: str, **extra):
        self.log("ERROR", component, message, **extra)

    def debug(self, component: str, message: str, **extra):
        self.log("DEBUG", component, message, **extra)
