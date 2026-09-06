#!/usr/bin/env python3
"""Add model-specific guidance to Codex sessions and log hook inputs."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


LOG_PATH = Path("/tmp/codex-model-context.log")
GPT6_CONTEXT = "偏好使用 Subagent"
OTHER_CONTEXT = "不要使用 Subagent"


def log_input(raw_input: str, payload: Any) -> None:
    """Append the received hook JSON and local timestamp for diagnostics."""
    record = {
        "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "input": payload if payload is not None else raw_input,
    }
    try:
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # Diagnostics must never prevent Codex from continuing the session.
        pass


def main() -> int:
    raw_input = sys.stdin.read()
    try:
        payload = json.loads(raw_input)
    except json.JSONDecodeError:
        log_input(raw_input, None)
        return 0

    log_input(raw_input, payload)
    model = payload.get("model", "") if isinstance(payload, dict) else ""
    model_name = model if isinstance(model, str) else ""
    context = GPT6_CONTEXT if "gpt-6" in model_name.lower() else OTHER_CONTEXT
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
