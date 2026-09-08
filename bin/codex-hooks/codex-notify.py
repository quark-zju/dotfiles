#!/usr/bin/env python3
"""Notify when a local coding-agent turn completes and focus it on demand."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

TITLE_PROMPT_PREFIX = "Generate a concise, single-line task title "
RECAP_PROMPT_PREFIX = "Write a brief catch-up for a user returning to this Codex task. "
NOTIFICATION_EXPIRE_MS = 30_000
WORKSPACE_HIGHLIGHT_PATH = "/tmp/workspace-highlight.css"
WORKSPACE_HIGHLIGHT_STATE_PATH = "/tmp/workspace-highlight.json"


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


def agent_name(payload: dict[str, Any]) -> str:
    # Codex hooks do not inherit CODEX_THREAD_ID, so use Codex-specific fields.
    if isinstance(payload.get("model"), str) and isinstance(
        payload.get("turn_id"), str
    ):
        return "Codex"
    return "Claude"


def agent_process(payload: dict[str, Any]) -> tuple[str, int, int] | None:
    name = agent_name(payload)
    for pid in ancestors(os.getppid()):
        if process_name(pid) == name.lower():
            stat = process_stat(pid)
            if stat is not None:
                return name, pid, stat[1]
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


def save_prompt(payload: dict[str, Any]) -> dict[str, object] | None:
    session_id = payload.get("session_id")
    prompt = payload.get("prompt")
    if not isinstance(session_id, str):
        log_event("prompt_skipped", reason="invalid_session_id")
        return
    if not isinstance(prompt, str):
        log_event("prompt_skipped", session_id=session_id, reason="invalid_prompt")
        return
    if prompt.startswith((TITLE_PROMPT_PREFIX, RECAP_PROMPT_PREFIX)):
        log_event("prompt_skipped", session_id=session_id, reason="internal_prompt")
        return
    process = agent_process(payload)
    if not process:
        log_event(
            "prompt_skipped",
            session_id=session_id,
            reason="agent_process_not_found",
            parent_pid=os.getppid(),
            has_codex_fields=agent_name(payload) == "Codex",
            ancestors=[
                {"pid": pid, "name": process_name(pid)}
                for pid in ancestors(os.getppid())
            ],
        )
        return
    path = state_path(session_id)
    if path is None:
        log_event("prompt_skipped", session_id=session_id, reason="no_state_path")
        return
    agent_name, pid, start_time = process
    try:
        state = {
            "agent_name": agent_name,
            "prompt": prompt,
            "pid": pid,
            "process_start_time": start_time,
        }
        path.write_text(json.dumps(state, ensure_ascii=False))
    except OSError as error:
        log_event(
            "prompt_save_failed",
            session_id=session_id,
            path=str(path),
            error=repr(error),
        )
        return
    log_event(
        "prompt_saved",
        session_id=session_id,
        agent_name=agent_name,
        pid=pid,
        path=str(path),
    )
    return state


def load_prompt(session_id: str) -> dict[str, Any] | None:
    path = state_path(session_id)
    if path is None:
        log_event("prompt_load_failed", session_id=session_id, reason="no_state_path")
        return None
    try:
        value = json.loads(path.read_text())
        path.unlink()
    except OSError as error:
        log_event(
            "prompt_load_failed",
            session_id=session_id,
            path=str(path),
            reason="io_error",
            error=repr(error),
        )
        return None
    except json.JSONDecodeError as error:
        log_event(
            "prompt_load_failed",
            session_id=session_id,
            path=str(path),
            reason="invalid_json",
            error=repr(error),
        )
        return None
    if not isinstance(value, dict):
        log_event(
            "prompt_load_failed",
            session_id=session_id,
            path=str(path),
            reason="invalid_state",
        )
        return None
    log_event("prompt_loaded", session_id=session_id, path=str(path))
    return value


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
    terminals: dict[int, tuple[int, int | None, str | None]],
    focused: dict[str, int],
    workspace_id: int | None = None,
    workspace_name: str | None = None,
) -> None:
    if node.get("type") == "workspace" and isinstance(node.get("id"), int):
        workspace_id = node["id"]
        if isinstance(node.get("name"), str):
            workspace_name = node["name"]
    pid = node.get("pid")
    container_id = node.get("id")
    if (
        node.get("app_id") in ("foot", "xfce4-terminal")
        and isinstance(pid, int)
        and isinstance(container_id, int)
    ):
        terminals[pid] = (container_id, workspace_id, workspace_name)
    if node.get("focused") is True and isinstance(container_id, int):
        focused["container"] = container_id
        if workspace_id is not None:
            focused["workspace"] = workspace_id
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        sway_state(child, terminals, focused, workspace_id, workspace_name)


def run_swaymsg(*args: str, **kwargs: object):
    import glob
    import os
    import subprocess

    environment = os.environ.copy()
    sway_socket = environment.get("SWAYSOCK")
    if not sway_socket or not os.path.exists(sway_socket):
        runtime_dir = environment.get("XDG_RUNTIME_DIR")
        candidates = (
            glob.glob(os.path.join(runtime_dir, "sway-ipc.*.sock"))
            if runtime_dir
            else []
        )
        if candidates:
            recovered_socket = max(candidates, key=os.path.getmtime)
            environment["SWAYSOCK"] = recovered_socket
            log_event(
                "sway_socket_recovered",
                old_socket=sway_socket,
                new_socket=recovered_socket,
            )
    return subprocess.run(["swaymsg", *args], env=environment, **kwargs)


def process_sway_state(
    pid: object, expected_start_time: object
) -> tuple[int, str | None, bool, bool] | None:
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
        completed = run_swaymsg(
            "-t",
            "get_tree",
            "-r",
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        tree = json.loads(completed.stdout)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        log_event("sway_query_failed", pid=pid, error=repr(error))
        return None
    terminals: dict[int, tuple[int, int | None, str | None]] = {}
    focused: dict[str, int] = {}
    sway_state(tree, terminals, focused)
    process_ancestors = []
    for ancestor in ancestors(pid):
        process_ancestors.append(ancestor)
        location = terminals.get(ancestor)
        if location is None:
            continue
        container_id, workspace_id, workspace_name = location
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
        return container_id, workspace_name, is_focused, workspace_is_focused
    log_event(
        "window_not_found",
        pid=pid,
        ancestors=process_ancestors,
        terminal_pids=sorted(terminals),
    )
    return None


def css_identifier_escape(value: str) -> str:
    """Escape a workspace name for use in a GTK CSS ID selector."""
    return "".join(
        char
        if char.isalnum() or char in "-_" or ord(char) >= 0x80
        else f"\\{ord(char):x} "
        for char in value
    )


def write_workspace_highlights(
    run_id: str,
    workspace_name: str | None,
    pid: int | None = None,
    process_start_time: int | None = None,
) -> None:
    """Add or remove one session's running workspace and regenerate its CSS."""
    import fcntl
    import json
    from pathlib import Path

    try:
        with Path(WORKSPACE_HIGHLIGHT_PATH).open("r+") as style:
            fcntl.flock(style, fcntl.LOCK_EX)
            try:
                state_path = Path(WORKSPACE_HIGHLIGHT_STATE_PATH)
                value = json.loads(state_path.read_text())
                sessions = value if isinstance(value, dict) else {}
            except (OSError, json.JSONDecodeError):
                sessions = {}

            for key, entry in list(sessions.items()):
                if not isinstance(entry, dict):
                    del sessions[key]
                    continue
                entry_pid = entry.get("pid")
                entry_start_time = entry.get("process_start_time")
                stat = process_stat(entry_pid) if isinstance(entry_pid, int) else None
                if (
                    stat is None
                    or not isinstance(entry_start_time, int)
                    or stat[1] != entry_start_time
                ):
                    del sessions[key]

            if workspace_name is None:
                sessions.pop(run_id, None)
            elif isinstance(pid, int) and isinstance(process_start_time, int):
                sessions[run_id] = {
                    "workspace": workspace_name,
                    "pid": pid,
                    "process_start_time": process_start_time,
                }

            state_path.write_text(
                json.dumps(sessions, ensure_ascii=False, sort_keys=True)
            )
            workspaces = sorted(
                {
                    entry["workspace"]
                    for entry in sessions.values()
                    if isinstance(entry, dict)
                    and isinstance(entry.get("workspace"), str)
                }
            )
            if workspaces:
                selectors = ",\n".join(
                    "#workspaces button#sway-workspace-"
                    f"{css_identifier_escape(name)}:not(.urgent)"
                    for name in workspaces
                )
                css = (
                    "/* Generated by codex-notify.py: running Codex workspaces. */\n"
                    f"{selectors} {{\n"
                    "    background: #2e7d32;\n"
                    "    color: #ffffff;\n"
                    "}\n"
                )
            else:
                css = ""
            style.seek(0)
            style.write(css)
            style.truncate()
    except OSError as error:
        log_event(
            "workspace_highlight_failed",
            run_id=run_id,
            workspace=workspace_name,
            error=repr(error),
        )
        return
    log_event(
        "workspace_highlight_updated",
        run_id=run_id,
        workspace=workspace_name,
        running_workspaces=workspaces,
    )


def mark_process_workspace_running(
    run_id: str,
    pid: object,
    expected_start_time: object | None = None,
) -> None:
    if expected_start_time is None:
        stat = process_stat(pid) if isinstance(pid, int) else None
        if stat is None:
            return
        expected_start_time = stat[1]
    state = process_sway_state(pid, expected_start_time)
    if state is None:
        return
    workspace_name = state[1]
    if workspace_name is not None and isinstance(pid, int):
        write_workspace_highlights(
            run_id, workspace_name, pid, expected_start_time
        )


def focus_process(pid: object, expected_start_time: object) -> None:
    import subprocess

    state = process_sway_state(pid, expected_start_time)
    if state is not None:
        container_id = state[0]
        completed = run_swaymsg(
            f"[con_id={container_id}]",
            "focus",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log_event(
            "focus_requested",
            container=container_id,
            returncode=completed.returncode,
        )


def update_running_workspace(
    payload: dict[str, Any], saved: dict[str, object] | None
) -> None:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        return
    turn_id = payload.get("turn_id")
    run_id = (
        f"{session_id}:{turn_id}" if isinstance(turn_id, str) else session_id
    )
    ssh_client_pid = os.environ.get("SSH_CLIENT_PID")
    if ssh_client_pid is not None:
        try:
            pid = int(ssh_client_pid)
            if pid <= 0:
                raise ValueError("non-positive SSH_CLIENT_PID")
            import ssh_sync

            hosts = ssh_sync.list_hosts()
            if not hosts:
                log_event(
                    "workspace_highlight_failed",
                    session_id=session_id,
                    reason="remote_no_hosts",
                )
                return
            if saved is None:
                ssh_sync.call_remote(
                    hosts[0],
                    write_workspace_highlights,
                    run_id,
                    None,
                    call_timeout=20,
                )
            else:
                ssh_sync.call_remote(
                    hosts[0],
                    mark_process_workspace_running,
                    run_id,
                    pid,
                    call_timeout=20,
                )
        except Exception as error:
            log_event(
                "workspace_highlight_failed",
                session_id=session_id,
                reason="remote_dispatch_failed",
                error=repr(error),
            )
        return
    if saved is None:
        write_workspace_highlights(run_id, None)
    else:
        mark_process_workspace_running(
            run_id, saved.get("pid"), saved.get("process_start_time")
        )


def show_notify(
    agent_name: str,
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
    container_id, _, is_focused, workspace_is_focused = state
    if is_focused:
        log_event("notification_skipped", container=container_id, reason="focused")
        return
    completed = run_swaymsg(
        f"[con_id={container_id}]",
        "urgent",
        "enable",
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
                f"--app-name={agent_name}",
                "--action=default=Focus window",
                f"--expire-time={NOTIFICATION_EXPIRE_MS}",
                html.escape(
                    f"{agent_name} · {title}"
                    if title
                    else f"{agent_name} turn complete"
                ),
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
        log_event("notification_skipped", reason="invalid_session_id")
        return
    saved = load_prompt(session_id)
    if saved is None:
        log_event("notification_skipped", session_id=session_id, reason="no_prompt")
        return
    if not isinstance(saved.get("prompt"), str):
        log_event(
            "notification_skipped", session_id=session_id, reason="invalid_prompt"
        )
        return
    agent_name = saved.get("agent_name", "Codex")
    if agent_name not in ("Codex", "Claude"):
        log_event(
            "notification_skipped", session_id=session_id, reason="invalid_agent"
        )
        return
    prompt = " ".join(saved["prompt"].split())
    if len(prompt) > 1000:
        prompt = prompt[:999] + "…"
    last_assistant_message = payload.get("last_assistant_message")
    if isinstance(last_assistant_message, str):
        summary = " ".join(last_assistant_message.split())
        if len(summary) > 1000:
            summary = summary[:999] + "…"
        if summary:
            prompt += f"\n\n{summary}"
    title = load_thread_title(session_id) if agent_name == "Codex" else None
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
            ssh_sync.call_remote(
                host,
                show_notify,
                agent_name,
                title,
                prompt,
                pid,
                call_timeout=20,
            )
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
        agent_name=agent_name,
        pid=saved.get("pid"),
        session_id=session_id,
    )
    show_notify(
        agent_name,
        title,
        prompt,
        saved.get("pid"),
        saved.get("process_start_time"),
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            log_event("hook_skipped", reason="invalid_payload")
            return
        event = payload.get("hook_event_name")
        session_id = payload.get("session_id")
        log_event(
            "hook_received",
            hook_event=event,
            session_id=session_id,
            parent_pid=os.getppid(),
            has_swaysock=bool(os.environ.get("SWAYSOCK")),
            has_ssh_client_pid="SSH_CLIENT_PID" in os.environ,
            has_codex_fields=agent_name(payload) == "Codex",
        )
        if not os.environ.get("SWAYSOCK") and "SSH_CLIENT_PID" not in os.environ:
            log_event(
                "hook_skipped",
                hook_event=event,
                session_id=session_id,
                reason="no_display_route",
            )
            return
        if event == "UserPromptSubmit":
            saved = save_prompt(payload)
            if saved is not None:
                update_running_workspace(payload, saved)
        elif event == "Stop":
            update_running_workspace(payload, None)
            notify(payload)
        else:
            log_event(
                "hook_skipped",
                hook_event=event,
                session_id=session_id,
                reason="unsupported_event",
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        log_event("hook_failed", error=repr(error))
    finally:
        print("{}")


if __name__ == "__main__":
    main()
