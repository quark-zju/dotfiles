#!/usr/bin/env python3
"""Track coding-agent turns and update their desktop workspaces.

handle_event owns the lifecycle, using one run ID for prompts and highlights:
  UserPromptSubmit: save the prompt and mark the turn running.
  Stop: consume the prompt, clear the turn, and notify.
  Interrupt: consume the prompt and clear the turn.
  SessionEnd: discard all prompts and highlights for the session.

dispatch_desktop selects local execution or ssh_sync; apply_desktop_event runs
the same desktop operations in either location.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

TITLE_PROMPT_PREFIX = "Generate a concise, single-line task title "
RECAP_PROMPT_PREFIX = "Write a brief catch-up for a user returning to this "
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
    from pathlib import Path

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


AGENT_PROCESS_NAMES = {
    "Codex": ("codex",),
    "Claude": ("claude",),
    # The muse launcher spawns the sandboxed agent as muse.real.
    "Muse": ("muse", "muse.real"),
}


def normalize_harness(harness: str) -> str:
    """Canonicalize known harness names; pass unknown names through."""
    lowered = harness.lower()
    for name in AGENT_PROCESS_NAMES:
        if name.lower() == lowered:
            return name
    return harness


def detect_harness() -> str | None:
    """Guess the harness from the nearest ancestor agent process."""
    for pid in ancestors(os.getppid()):
        name = process_name(pid)
        for harness, processes in AGENT_PROCESS_NAMES.items():
            if name in processes:
                return harness
    return None


def codex_client_process(session_id: str) -> tuple[int, int] | None:
    """Find the per-TUI wrapper, or a remote resume client by session ID.

    The shared-server fallback assumes the client stays on its initial session.
    If several clients are attached, use the most recently started one.
    """
    import subprocess

    tui_pid = os.environ.get("CODEX_TUI_PID")
    if tui_pid is not None:
        try:
            pid = int(tui_pid)
            start_time = int(os.environ["CODEX_TUI_START_TICKS"])
        except (KeyError, ValueError):
            return None
        stat = process_stat(pid)
        process = (
            (pid, start_time) if stat is not None and stat[1] == start_time else None
        )
        log_event(
            "client_process_resolved",
            session_id=session_id,
            process=process,
            source="tui_wrapper",
        )
        return process

    try:
        output = subprocess.check_output(
            ["ps", "-C", "codex", "-o", "pid="],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    session_arg = session_id.encode()
    process = None
    for value in output.split():
        pid = int(value)
        try:
            args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if (
            b"resume" not in args
            or not any(
                arg == b"--remote" or arg.startswith(b"--remote=") for arg in args
            )
            or session_arg not in args
        ):
            continue
        stat = process_stat(pid)
        if stat is not None and (process is None or stat[1] > process[1]):
            process = pid, stat[1]
    log_event("client_process_resolved", session_id=session_id, process=process)
    return process


def agent_process(agent: str, session_id: str | None = None) -> tuple[int, int] | None:
    """Return the nearest ancestor agent process's PID and start time.

    A Codex app-server runs hooks for its clients; find the per-TUI wrapper or
    the session's shared-server client instead of using the server's ancestry.
    """
    for pid in ancestors(os.getppid()):
        if process_name(pid) in AGENT_PROCESS_NAMES[agent]:
            stat = process_stat(pid)
            if stat is not None:
                if agent == "Codex" and session_id is not None:
                    try:
                        args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                    except OSError:
                        return None
                    if b"app-server" in args:
                        return codex_client_process(session_id)
                return pid, stat[1]
    return None


def runtime_dir() -> str | None:
    # ssh_sync uploads this helper with the desktop functions.
    import os

    path = os.environ.get("XDG_RUNTIME_DIR")
    if path and os.path.isabs(path):
        return path
    # Muse clears hook environments; fall back to the systemd runtime dir.
    path = f"/run/user/{os.getuid()}"
    if os.path.isdir(path):
        return path
    return None


def session_state_dir(session_id: str) -> Path | None:
    directory_base = runtime_dir()
    if directory_base is None:
        return None
    directory = Path(
        directory_base, "codex-notify", hashlib.sha256(session_id.encode()).hexdigest()
    )
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    return directory


def state_path(session_id: str, run_id: str) -> Path | None:
    directory = session_state_dir(session_id)
    if directory is None:
        return None
    name = hashlib.sha256(run_id.encode()).hexdigest() + ".json"
    return directory / name


def save_prompt(
    payload: dict[str, Any], agent: str, run_id: str
) -> dict[str, object] | None:
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
    process = agent_process(agent, session_id)
    if process is None:
        log_event(
            "prompt_skipped",
            session_id=session_id,
            reason="agent_process_not_found",
            parent_pid=os.getppid(),
            agent=agent,
            ancestors=[
                {"pid": pid, "name": process_name(pid)}
                for pid in ancestors(os.getppid())
            ],
        )
        return
    path = state_path(session_id, run_id)
    if path is None:
        log_event("prompt_skipped", session_id=session_id, reason="no_state_path")
        return
    pid, start_time = process
    try:
        state = {
            "run_id": run_id,
            "agent_name": agent,
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
        run_id=run_id,
        agent_name=agent,
        pid=pid,
        path=str(path),
    )
    return state


def load_prompt(session_id: str, run_id: str) -> dict[str, Any] | None:
    path = state_path(session_id, run_id)
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


def clear_session_prompts(session_id: str) -> None:
    directory = session_state_dir(session_id)
    if directory is not None:
        for path in directory.glob("*.json"):
            path.unlink()


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


def resolve_swaysock() -> str | None:
    """Return SWAYSOCK, inferring /run/user/<uid>/sway-ipc.*.sock if unset."""
    import glob
    import os

    sway_socket = os.environ.get("SWAYSOCK")
    if sway_socket and os.path.exists(sway_socket):
        return sway_socket
    directory = runtime_dir()
    candidates = (
        glob.glob(os.path.join(directory, "sway-ipc.*.sock")) if directory else []
    )
    if not candidates:
        return None
    recovered_socket = max(candidates, key=os.path.getmtime)
    log_event(
        "sway_socket_recovered",
        old_socket=sway_socket,
        new_socket=recovered_socket,
    )
    return recovered_socket


def run_swaymsg(*args: str, **kwargs: object):
    import os
    import subprocess

    environment = os.environ.copy()
    sway_socket = resolve_swaysock()
    if sway_socket is not None:
        environment["SWAYSOCK"] = sway_socket
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
        (
            char
            if char.isalnum() or char in "-_" or ord(char) >= 0x80
            else f"\\{ord(char):x} "
        )
        for char in value
    )


def write_workspace_highlights(
    run_id: str,
    workspace_name: str | None,
    pid: int | None = None,
    process_start_time: int | None = None,
    clear_session: bool = False,
    remote: bool = False,
    cleanup_stale: bool = False,
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
                    cleanup_stale
                    and (
                        entry.get("remote") is True
                        or (
                            "remote" not in entry
                            and isinstance(entry_pid, int)
                            and process_name(entry_pid)
                            not in ("codex", "claude", "muse", "muse.real")
                        )
                    )
                ) or (
                    stat is None
                    or not isinstance(entry_start_time, int)
                    or stat[1] != entry_start_time
                ):
                    del sessions[key]

            if not cleanup_stale:
                if clear_session:
                    prefix = f"{run_id}:"
                    for key in list(sessions):
                        if key == run_id or key.startswith(prefix):
                            del sessions[key]
                elif workspace_name is None:
                    sessions.pop(run_id, None)
                elif isinstance(pid, int) and isinstance(process_start_time, int):
                    sessions[run_id] = {
                        "workspace": workspace_name,
                        "pid": pid,
                        "process_start_time": process_start_time,
                        "remote": remote,
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
                    "/* Generated by codex-notify.py: running agent workspaces. */\n"
                    f"{selectors} {{\n"
                    "    border-bottom: 2px solid #4caf50;\n"
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


def clear_session_workspace_highlights(session_id: str) -> None:
    """Remove all running turns belonging to one agent session."""
    write_workspace_highlights(session_id, None, clear_session=True)


def cleanup_workspace_highlights() -> None:
    """Remove stale local sessions and all remote sessions from the CSS."""
    write_workspace_highlights("", None, cleanup_stale=True)


def mark_process_workspace_running(
    run_id: str,
    pid: object,
    expected_start_time: object | None = None,
    remote: bool = False,
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
            run_id, workspace_name, pid, expected_start_time, remote=remote
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


def apply_desktop_event(
    event: str,
    session_id: str,
    run_id: str,
    saved: dict[str, Any] | None,
    remote: bool = False,
) -> None:
    """Apply an event accepted by handle_event, locally or via ssh_sync.

    For remote execution, saved contains the desktop's SSH client PID; its
    start time is resolved here. Stop always clears the run, even without a
    saved prompt. SessionEnd clears every run belonging to the session.
    """
    if event == "SessionEnd":
        clear_session_workspace_highlights(session_id)
    elif event == "UserPromptSubmit":
        if saved is not None:
            mark_process_workspace_running(
                run_id, saved.get("pid"), saved.get("process_start_time"), remote
            )
    else:
        write_workspace_highlights(run_id, None)
        if event == "Stop" and saved is not None:
            show_notify(
                saved["agent_name"],
                saved["title"],
                saved["message"],
                saved.get("pid"),
                saved.get("process_start_time"),
            )


def dispatch_desktop(
    event: str, session_id: str, run_id: str, saved: dict[str, Any] | None
) -> None:
    """Select the desktop host and process once for all of a hook's effects."""
    ssh_client_pid = os.environ.get("SSH_CLIENT_PID")
    if ssh_client_pid is None:
        apply_desktop_event(event, session_id, run_id, saved)
        return

    try:
        pid = int(ssh_client_pid)
        if pid <= 0:
            raise ValueError("non-positive SSH_CLIENT_PID")
        import ssh_sync

        hosts = ssh_sync.list_hosts()
        if not hosts:
            log_event("remote_no_hosts", run_id=run_id, client_pid=pid)
            return
        if saved is not None:
            saved = {**saved, "pid": pid, "process_start_time": None}
        log_event(
            "remote_dispatch",
            run_id=run_id,
            client_pid=pid,
            selected_host=hosts[0],
            available_hosts=hosts,
        )
        ssh_sync.call_remote(
            hosts[0],
            apply_desktop_event,
            event,
            session_id,
            run_id,
            saved,
            True,
            call_timeout=20,
        )
    except Exception as error:
        log_event(
            "remote_dispatch_failed",
            run_id=run_id,
            client_pid=ssh_client_pid,
            error=repr(error),
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
    import os
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
        child_pid = os.fork()
    except OSError as error:
        log_event("notification_failed", container=container_id, error=repr(error))
        return
    if child_pid:
        log_event("notification_detached", container=container_id, pid=child_pid)
        return
    try:
        os.setsid()
        # Do not keep the ssh_sync worker's transport pipes open while waiting
        # for the notification action.
        os.closerange(3, os.sysconf("SC_OPEN_MAX"))
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        if devnull > 2:
            os.close(devnull)
        environment = os.environ.copy()
        # Muse clears hook environments; the session bus lives at the standard
        # systemd path.
        if not environment.get("DBUS_SESSION_BUS_ADDRESS"):
            environment["DBUS_SESSION_BUS_ADDRESS"] = (
                f"unix:path=/run/user/{os.getuid()}/bus"
            )
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
            timeout=NOTIFICATION_EXPIRE_MS / 1000 + 5,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        log_event("notification_failed", container=container_id, error=repr(error))
    else:
        action = completed.stdout.strip()
        log_event(
            "notification_finished",
            container=container_id,
            returncode=completed.returncode,
            action=action,
        )
        if action == "default":
            focus_process(pid, expected_start_time)
    finally:
        os._exit(0)


def prepare_notification(
    payload: dict[str, Any], saved: dict[str, Any]
) -> dict[str, Any] | None:
    """Build notification content without changing state or contacting a desktop."""
    session_id = payload.get("session_id")
    if not isinstance(saved.get("prompt"), str):
        log_event(
            "notification_skipped", session_id=session_id, reason="invalid_prompt"
        )
        return
    agent_name = saved.get("agent_name", "Codex")
    if not isinstance(agent_name, str):
        log_event("notification_skipped", session_id=session_id, reason="invalid_agent")
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
    return {**saved, "agent_name": agent_name, "title": title, "message": prompt}


def handle_event(payload: dict[str, Any], agent: str) -> None:
    """Own the prompt lifecycle and dispatch the matching desktop event."""
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        log_event("hook_skipped", reason="invalid_session_id")
        return
    # Claude and older harnesses have no turn ID; use their session as the run.
    turn_id = payload.get("turn_id")
    run_id = f"{session_id}:{turn_id}" if isinstance(turn_id, str) else session_id
    log_event(
        "hook_received",
        hook_event=event,
        session_id=session_id,
        run_id=run_id,
        parent_pid=os.getppid(),
        has_swaysock=bool(os.environ.get("SWAYSOCK")),
        has_ssh_client_pid="SSH_CLIENT_PID" in os.environ,
        agent=agent,
    )
    if resolve_swaysock() is None and "SSH_CLIENT_PID" not in os.environ:
        log_event("hook_skipped", run_id=run_id, reason="no_display_route")
        return

    saved = None
    if event == "UserPromptSubmit":
        saved = save_prompt(payload, agent, run_id)
        if saved is None:
            return
    elif event in ("Stop", "Interrupt"):
        saved = load_prompt(session_id, run_id)
        if event == "Stop":
            if saved is not None:
                saved = prepare_notification(payload, saved)
            else:
                log_event("notification_skipped", run_id=run_id, reason="no_prompt")
    elif event == "SessionEnd":
        clear_session_prompts(session_id)
    else:
        log_event("hook_skipped", run_id=run_id, reason="unsupported_event")
        return
    dispatch_desktop(event, session_id, run_id, saved)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--harness",
        help="harness name (default: auto-detect); unknown names are skipped",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove stale session workspace highlights",
    )
    args = parser.parse_args()
    if args.cleanup:
        cleanup_workspace_highlights()
        return
    # Never fail the hook on a bad flag: exit 2 would block the user's prompt.
    if args.harness is None:
        agent = detect_harness()
    else:
        agent = normalize_harness(args.harness)
        if agent not in AGENT_PROCESS_NAMES:
            agent = None
    if agent is None:
        log_event("hook_skipped", reason="unknown_harness", agent=args.harness)
        print("{}")
        return

    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            log_event("hook_skipped", reason="invalid_payload")
            return
        handle_event(payload, agent)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        log_event("hook_failed", error=repr(error))
    finally:
        print("{}")


if __name__ == "__main__":
    main()
