#!/usr/bin/env python3
"""Add model-specific guidance to Codex sessions and log hook inputs."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_PATH = Path("/tmp/codex-model-context.log")
GPT6_CONTEXT = """
## Use sub-agents
- Prefer `gpt-5.6-luna` for bounded exploration and execution; keep difficult reasoning and consequential review with the main agent.
- Delegate when it saves overall usage or time. GPT-5.6 Luna uses roughly 1/50 as much quota.
- Define scope, file ownership, and expected results. Return concise evidence; distinguish findings from hypotheses.
- Give one agent ownership of testing and commits; avoid concurrent edits during finalization. Batch routine steps and stop on failure.
- Continue independent necessary work while agents run; otherwise use `wait_agent`. Avoid short polling and invented busywork.
"""

OTHER_CONTEXT = """
## Do not use sub-agents
Do not start sub-agents.
"""


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


def _agents_md_is_in_dotfiles():
    try:
        path = os.path.realpath(os.path.expanduser("~/.codex/AGENTS.md"))
        return "/dotfiles/" in path
    except OSError:
        return False


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

    if _agents_md_is_in_dotfiles():
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
