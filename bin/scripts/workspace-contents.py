#!/usr/bin/env python3
"""List Codex and Neovim activity under each Sway workspace."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LIB_DIR = Path(__file__).resolve().parents[2] / ".local/lib/python"
TERMINAL_APP_IDS = frozenset(("foot", "xfce4-terminal"))
COLORS = {
    "codex": "\033[32m",
    "nvim": "\033[32m",
    "idle": "\033[33m",
    "suspended": "\033[35m",
    "working": "\033[33m",
}
RESET_COLOR = "\033[0m"
TIMESTAMP_RE = re.compile(r"(?:now|\d+[mhd] ago)$")
sys.path.insert(0, str(LIB_DIR))

import ssh_sync  # noqa: E402
import ssh_sync_ops  # noqa: E402


@dataclass(frozen=True)
class Remote:
    name: str
    host: str


@dataclass(frozen=True)
class Workspace:
    name: str
    number: int
    terminal_pids: frozenset[int]


def remote_arg(value: str) -> Remote:
    name, separator, host = value.partition("=")
    if not separator or not name or not host:
        raise argparse.ArgumentTypeError("expected NAME=HOST")
    return Remote(name, host)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="list Codex sessions and Neovim buffers by Sway workspace"
    )
    parser.add_argument(
        "--remote",
        action="append",
        default=[],
        type=remote_arg,
        metavar="NAME=HOST",
        help="query HOST and display it as NAME (repeatable)",
    )
    parser.add_argument(
        "--poll",
        nargs="?",
        const=2.0,
        type=float,
        metavar="SECONDS",
        help="refresh continuously (default interval: 2 seconds)",
    )
    parser.add_argument(
        "--timeout",
        default=10.0,
        type=float,
        metavar="SECONDS",
        help="timeout for each remote call (default: 10 seconds)",
    )
    args = parser.parse_args()
    if args.poll is not None and args.poll <= 0:
        parser.error("--poll interval must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    names = [remote.name for remote in args.remote]
    if len(names) != len(set(names)):
        parser.error("remote names must be unique")
    if "local" in names:
        parser.error("remote name 'local' is reserved")
    return args


def sway_workspaces() -> list[Workspace]:
    completed = subprocess.run(
        ["swaymsg", "-t", "get_tree", "-r"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    tree = json.loads(completed.stdout)
    workspaces: list[Workspace] = []

    def terminals(node: dict[str, Any]) -> set[int]:
        result: set[int] = set()
        if node.get("app_id") in TERMINAL_APP_IDS and isinstance(node.get("pid"), int):
            result.add(node["pid"])
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            result.update(terminals(child))
        return result

    def visit(node: dict[str, Any]) -> None:
        if node.get("type") == "workspace" and node.get("name") != "__i3_scratch":
            number = node.get("num")
            workspaces.append(
                Workspace(
                    name=node.get("name", ""),
                    number=number if isinstance(number, int) else -1,
                    terminal_pids=frozenset(terminals(node)),
                )
            )
            return
        for child in node.get("nodes", []) + node.get("floating_nodes", []):
            visit(child)

    visit(tree)
    return sorted(
        workspaces,
        key=lambda workspace: (
            workspace.number < 0,
            workspace.number if workspace.number >= 0 else 0,
            workspace.name,
        ),
    )


def parent_pids() -> dict[int, int]:
    parents: dict[int, int] = {}
    try:
        processes = os.scandir("/proc")
    except OSError:
        return parents
    with processes:
        for process in processes:
            if not process.name.isdigit():
                continue
            try:
                stat = Path(process.path, "stat").read_text()
                fields = stat[stat.rfind(")") + 2 :].split()
                parents[int(process.name)] = int(fields[1])
            except (OSError, ValueError, IndexError):
                continue
    return parents


def terminal_for_pid(
    pid: object, terminal_pids: set[int], parents: dict[int, int]
) -> int | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    seen: set[int] = set()
    while pid not in seen:
        if pid in terminal_pids:
            return pid
        seen.add(pid)
        pid = parents.get(pid, 0)
        if pid <= 0:
            return None
    return None


def local_items() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return ssh_sync_ops.list_running_agents(), ssh_sync_ops.list_editors()


def remote_items(
    remote: Remote, timeout: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    agents = ssh_sync.call_remote(
        remote.host, ssh_sync_ops.list_running_agents, call_timeout=timeout
    )
    editors = ssh_sync.call_remote(
        remote.host, ssh_sync_ops.list_editors, call_timeout=timeout
    )
    return agents, editors


def collect(
    remotes: list[Remote], timeout: float
) -> tuple[
    list[tuple[str, bool, list[dict[str, Any]], list[dict[str, Any]]]], list[str]
]:
    sources: list[tuple[str, bool, list[dict[str, Any]], list[dict[str, Any]]]] = []
    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(remotes) + 1) as pool:
        futures = {pool.submit(local_items): ("local", False)}
        futures.update(
            {
                pool.submit(remote_items, remote, timeout): (remote.name, True)
                for remote in remotes
            }
        )
        for future, (name, is_remote) in futures.items():
            try:
                agents, editors = future.result()
            except Exception as error:
                errors.append(f"{name}: {error}")
                continue
            sources.append((name, is_remote, agents, editors))
    sources.sort(key=lambda source: (source[0] != "local", source[0]))
    return sources, errors


def compact(text: object) -> str:
    return " ".join(str(text).split())


def age(timestamp: object, now: float) -> str:
    if not isinstance(timestamp, (int, float)):
        return ""
    seconds = max(0, int(now - timestamp))
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def align_line(text: str, timestamp: str, width: int) -> str:
    def cell_width(value: str) -> int:
        return sum(
            (
                0
                if unicodedata.combining(character)
                else 2 if unicodedata.east_asian_width(character) in ("F", "W") else 1
            )
            for character in value
        )

    def truncate(value: str, limit: int) -> str:
        used = 0
        end = 0
        for end, character in enumerate(value, 1):
            character_width = cell_width(character)
            if used + character_width > limit:
                return value[: end - 1]
            used += character_width
        return value[:end]

    prefix = "  " + text
    if not timestamp:
        return truncate(prefix, width)
    available = max(1, width - cell_width(timestamp) - 1)
    prefix = truncate(prefix, available).rstrip()
    padding = max(1, width - cell_width(prefix) - cell_width(timestamp))
    return prefix + " " * padding + timestamp


def colorize_line(line: str) -> str:
    parts = line.split(" · ")
    for index, part in enumerate(parts):
        token = part.strip()
        color = COLORS.get(token)
        if color is None:
            continue
        start = len(part) - len(part.lstrip())
        end = len(part.rstrip())
        parts[index] = part[:start] + color + token + RESET_COLOR + part[end:]
    line = " · ".join(parts)
    return TIMESTAMP_RE.sub(lambda match: "\033[36m" + match[0] + RESET_COLOR, line)


def render(args: argparse.Namespace) -> str:
    workspaces = sway_workspaces()
    sources, errors = collect(args.remote, args.timeout)
    parents = parent_pids()
    workspace_by_terminal = {
        pid: workspace.name
        for workspace in workspaces
        for pid in workspace.terminal_pids
    }
    terminal_pids = set(workspace_by_terminal)
    rows: dict[str, list[tuple[str, str]]] = {
        workspace.name: [] for workspace in workspaces
    }
    now = time.time()

    for source_name, is_remote, agents, editors in sources:
        pid_key = "ssh_client_pid" if is_remote else "pid"
        for agent in agents:
            terminal = terminal_for_pid(agent.get(pid_key), terminal_pids, parents)
            if terminal is None:
                continue
            messages = agent.get("user_messages")
            last_message = (
                messages[-1] if isinstance(messages, list) and messages else {}
            )
            state = (
                "suspended"
                if agent.get("suspended")
                else "working" if agent.get("working") else "idle"
            )
            text = " · ".join(
                filter(
                    None,
                    (
                        source_name,
                        str(agent.get("harness", "codex")).ljust(5),
                        compact(agent.get("repo_name", "")),
                        state,
                        compact(last_message.get("message", "")),
                    ),
                )
            )
            rows[workspace_by_terminal[terminal]].append(
                (text, age(last_message.get("timestamp"), now))
            )

        for editor in editors:
            terminal = terminal_for_pid(editor.get(pid_key), terminal_pids, parents)
            if terminal is None:
                continue
            buffers = editor.get("buffers")
            if isinstance(buffers, list) and buffers:
                for buffer in buffers:
                    text = " · ".join(
                        filter(
                            None,
                            (
                                source_name,
                                str(editor.get("name", "nvim")).ljust(5),
                                compact(editor.get("repo_name", "")),
                                compact(buffer.get("path", "")),
                            ),
                        )
                    )
                    timestamps = [
                        value
                        for value in (buffer.get("mtime"), editor.get("start_time"))
                        if isinstance(value, (int, float))
                    ]
                    rows[workspace_by_terminal[terminal]].append(
                        (text, age(max(timestamps, default=None), now))
                    )
            elif editor.get("suspended"):
                text = " · ".join(
                    filter(
                        None,
                        (
                            source_name,
                            str(editor.get("name", "nvim")).ljust(5),
                            compact(editor.get("repo_name", "")),
                            "suspended",
                        ),
                    )
                )
                rows[workspace_by_terminal[terminal]].append((text, ""))

    width = shutil.get_terminal_size(fallback=(100, 24)).columns
    lines: list[str] = []
    for workspace in workspaces:
        lines.append(workspace.name)
        lines.extend(
            align_line(text, timestamp, width)
            for text, timestamp in rows[workspace.name]
        )
    if errors:
        if lines:
            lines.append("")
        lines.extend("warning: " + compact(error) for error in errors)
    if sys.stdout.isatty():
        lines = [colorize_line(line) for line in lines]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    try:
        while True:
            started = time.monotonic()
            output = render(args)
            if args.poll is not None and sys.stdout.isatty():
                print("\033[H\033[2J", end="")
            print(output, flush=True)
            if args.poll is None:
                return
            time.sleep(max(0, args.poll - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
