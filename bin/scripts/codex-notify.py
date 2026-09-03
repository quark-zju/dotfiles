#!/usr/bin/env python3
"""Notify when a local Codex turn completes and focus it on demand."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

TITLE_PROMPT_PREFIX = "Generate a concise, single-line task title "
RECAP_PROMPT_PREFIX = "Write a brief catch-up for a user returning to this Codex task. "


def log_event(event: str, **fields: object) -> None:
    """Append one diagnostic event without affecting notification behavior."""
    import datetime
    import json
    import os
    import socket

    record = {
        "time": datetime.datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "host": socket.gethostname(),
        "event": event,
        **fields,
    }
    try:
        fd = os.open(
            "/tmp/codex-notify.log",
            os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        pass


def process_stat(pid: int) -> tuple[int, int] | None:
    """Return a process's parent PID and start time in clock ticks."""
    from pathlib import Path

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
        or prompt.startswith((TITLE_PROMPT_PREFIX, RECAP_PROMPT_PREFIX))
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


def load_thread_title(session_id: str) -> str | None:
    title = None
    try:
        with Path.home().joinpath(".codex/session_index.jsonl").open() as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if value.get("id") == session_id and isinstance(
                    value.get("thread_name"), str
                ):
                    title = value["thread_name"]
    except OSError:
        pass
    return title


def sway_state(
    node: dict[str, object],
    terminals: dict[int, tuple[int, int | None]],
    focused: dict[str, int],
    workspace_id: int | None = None,
) -> None:
    if node.get("type") == "workspace" and isinstance(node.get("id"), int):
        workspace_id = node["id"]
    pid = node.get("pid")
    container_id = node.get("id")
    if (
        node.get("app_id") in ("foot", "xfce4-terminal")
        and isinstance(pid, int)
        and isinstance(container_id, int)
    ):
        terminals[pid] = (container_id, workspace_id)
    if node.get("focused") is True and isinstance(container_id, int):
        focused["container"] = container_id
        if workspace_id is not None:
            focused["workspace"] = workspace_id
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        sway_state(child, terminals, focused, workspace_id)


def process_sway_state(
    pid: object, expected_start_time: object
) -> tuple[int, bool, bool] | None:
    import json
    import subprocess

    if not isinstance(pid, int) or not isinstance(expected_start_time, int):
        log_event("window_invalid_process", pid=pid)
        return None
    stat = process_stat(pid)
    if stat is None:
        log_event("window_process_missing", pid=pid)
        return None
    if stat[1] != expected_start_time:
        log_event("window_process_changed", pid=pid)
        return None
    try:
        completed = subprocess.run(
            ["swaymsg", "-t", "get_tree", "-r"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        tree = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        log_event("sway_query_failed", pid=pid, error=repr(error))
        return None
    terminals: dict[int, tuple[int, int | None]] = {}
    focused: dict[str, int] = {}
    sway_state(tree, terminals, focused)
    process_ancestors = []
    for ancestor in ancestors(pid):
        process_ancestors.append(ancestor)
        location = terminals.get(ancestor)
        if location is None:
            continue
        container_id, workspace_id = location
        is_focused = container_id == focused.get("container")
        workspace_is_focused = workspace_id == focused.get("workspace")
        log_event(
            "window_resolved",
            pid=pid,
            ancestors=process_ancestors,
            container=container_id,
            workspace=workspace_id,
            focused_container=focused.get("container"),
            focused_workspace=focused.get("workspace"),
            is_focused=is_focused,
            workspace_is_focused=workspace_is_focused,
        )
        return container_id, is_focused, workspace_is_focused
    log_event(
        "window_not_found",
        pid=pid,
        ancestors=process_ancestors,
        terminal_pids=sorted(terminals),
    )
    return None


def focus_process(pid: object, expected_start_time: object) -> None:
    import subprocess

    state = process_sway_state(pid, expected_start_time)
    if state is not None:
        container_id = state[0]
        completed = subprocess.run(
            ["swaymsg", f"[con_id={container_id}]", "focus"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log_event(
            "focus_requested",
            container=container_id,
            returncode=completed.returncode,
        )


def show_notify(
    title: str | None,
    message: str,
    pid: object,
    expected_start_time: object | None = None,
) -> None:
    """Mark a completed turn urgent and notify when it is off-workspace."""
    import html
    import subprocess

    if expected_start_time is None:
        stat = process_stat(pid) if isinstance(pid, int) else None
        if stat is None:
            return
        expected_start_time = stat[1]
    state = process_sway_state(pid, expected_start_time)
    if state is None:
        return
    container_id, is_focused, workspace_is_focused = state
    if is_focused:
        log_event("notification_skipped", container=container_id, reason="focused")
        return
    completed = subprocess.run(
        ["swaymsg", f"[con_id={container_id}]", "urgent", "enable"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log_event(
        "urgent_requested", container=container_id, returncode=completed.returncode
    )
    if workspace_is_focused:
        log_event(
            "notification_skipped", container=container_id, reason="focused_workspace"
        )
        return
    try:
        completed = subprocess.run(
            [
                "notify-send",
                "--app-name=Codex",
                "--action=default=Focus window",
                "--expire-time=10000",
                html.escape(f"Codex · {title}" if title else "Codex turn complete"),
                html.escape(message),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError as error:
        log_event("notification_failed", container=container_id, error=repr(error))
        return
    action = completed.stdout.strip()
    log_event(
        "notification_finished",
        container=container_id,
        returncode=completed.returncode,
        action=action,
    )
    if action == "default":
        focus_process(pid, expected_start_time)


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
    title = load_thread_title(session_id)
    ssh_client_pid = os.environ.get("SSH_CLIENT_PID")
    if ssh_client_pid is not None:
        try:
            pid = int(ssh_client_pid)
            if pid <= 0:
                log_event("remote_invalid_client_pid", client_pid=ssh_client_pid)
                return
            import ssh_sync

            hosts = ssh_sync.list_hosts()
            if not hosts:
                log_event("remote_no_hosts", client_pid=pid)
                return
            host = hosts[0]
            log_event(
                "remote_dispatch",
                client_pid=pid,
                selected_host=host,
                available_hosts=hosts,
            )
            ssh_sync.call_remote(host, show_notify, title, prompt, pid, call_timeout=20)
        except Exception as error:
            log_event(
                "remote_dispatch_failed",
                client_pid=ssh_client_pid,
                error=repr(error),
            )
            return
        return
    log_event(
        "local_dispatch",
        pid=saved.get("pid"),
        session_id=session_id,
    )
    show_notify(title, prompt, saved.get("pid"), saved.get("process_start_time"))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or (
            not os.environ.get("SWAYSOCK") and "SSH_CLIENT_PID" not in os.environ
        ):
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
