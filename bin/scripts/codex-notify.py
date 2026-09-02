#!/usr/bin/env python3
"""Notify when a local Codex turn completes and focus it on demand."""

from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

TERMINAL_APP_IDS = frozenset(("foot", "xfce4-terminal"))
TITLE_PROMPT_PREFIX = "Generate a concise, single-line task title "


def process_stat(pid: int) -> tuple[int, int] | None:
    """Return a process's parent PID and start time in clock ticks."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat[stat.rfind(")") + 2 :].split()
        return int(fields[1]), int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def process_name(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return None


def ancestors(pid: int):
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        yield pid
        stat = process_stat(pid)
        if stat is None:
            return
        pid = stat[0]


def codex_process() -> tuple[int, int] | None:
    for pid in ancestors(os.getppid()):
        if process_name(pid) == "codex":
            stat = process_stat(pid)
            if stat is not None:
                return pid, stat[1]
    return None


def state_path(session_id: str) -> Path | None:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir or not os.path.isabs(runtime_dir):
        return None
    directory = Path(runtime_dir, "codex-notify")
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        return None
    name = hashlib.sha256(session_id.encode()).hexdigest() + ".json"
    return directory / name


def save_prompt(payload: dict[str, Any]) -> None:
    session_id = payload.get("session_id")
    prompt = payload.get("prompt")
    if (
        not isinstance(session_id, str)
        or not isinstance(prompt, str)
        or prompt.startswith(TITLE_PROMPT_PREFIX)
    ):
        return
    process = codex_process()
    if not process:
        return
    path = state_path(session_id)
    if path is None:
        return
    pid, start_time = process
    path.write_text(
        json.dumps(
            {"prompt": prompt, "pid": pid, "process_start_time": start_time},
            ensure_ascii=False,
        )
    )


def load_prompt(session_id: str) -> dict[str, Any] | None:
    path = state_path(session_id)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text())
        path.unlink()
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def terminal_containers(node: dict[str, Any], result: dict[int, int]) -> None:
    pid = node.get("pid")
    container_id = node.get("id")
    if (
        node.get("app_id") in TERMINAL_APP_IDS
        and isinstance(pid, int)
        and isinstance(container_id, int)
    ):
        result[pid] = container_id
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        terminal_containers(child, result)


def focus_process(pid: object, expected_start_time: object) -> None:
    if not isinstance(pid, int) or not isinstance(expected_start_time, int):
        return
    stat = process_stat(pid)
    if stat is None or stat[1] != expected_start_time:
        return
    try:
        completed = subprocess.run(
            ["swaymsg", "-t", "get_tree", "-r"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        tree = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return
    containers: dict[int, int] = {}
    terminal_containers(tree, containers)
    for ancestor in ancestors(pid):
        container_id = containers.get(ancestor)
        if container_id is None:
            continue
        subprocess.run(
            ["swaymsg", f"[con_id={container_id}]", "focus"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return


def notify(payload: dict[str, Any]) -> None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return
    saved = load_prompt(session_id)
    if saved is None or not isinstance(saved.get("prompt"), str):
        return
    prompt = " ".join(saved["prompt"].split())
    if len(prompt) > 1000:
        prompt = prompt[:999] + "…"
    try:
        completed = subprocess.run(
            [
                "notify-send",
                "--app-name=Codex",
                "--action=default=Focus window",
                "--action=focus=Focus window",
                "--expire-time=10000",
                "Codex turn complete",
                html.escape(prompt),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return
    if completed.stdout.strip() in ("default", "focus"):
        focus_process(saved.get("pid"), saved.get("process_start_time"))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or not os.environ.get("SWAYSOCK"):
            return
        event = payload.get("hook_event_name")
        if event == "UserPromptSubmit":
            save_prompt(payload)
        elif event == "Stop":
            notify(payload)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    finally:
        print("{}")


if __name__ == "__main__":
    main()
