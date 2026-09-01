#!/usr/bin/env python3

"""Clean disconnected Eternal Terminal process trees.

Cleanup happens only when at least one session is still connected. If every
session is disconnected, the script intentionally does nothing.

Connection state is reconstructed from the current etserver log. Client IDs
are mapped to etterminal PIDs through their open log files, and the result is
checked against the number of established TCP connections. Ambiguous or
changing observations are never cleaned.

Preview with ``./et-cleanup --dry-run`` and run with ``./et-cleanup``. The
server port is read from /etc/et.cfg by default; --port, --log, and
--server-pid override discovery.

Selected process trees receive SIGTERM, children first. Processes still alive
after the grace period receive SIGKILL. The process start time is checked
before every signal to avoid signaling a reused PID.
"""

from __future__ import annotations

import argparse
import configparser
import glob
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


SESSION_ID_RE = r"[A-Za-z0-9]{16}"
LOG_PREFIX_RE = re.compile(
    rf"^\[[A-Z]+ \S+ \S+ ({SESSION_ID_RE}) [^]]+\] (.*)$"
)
CONNECTED_RE = re.compile(rf"Got client with id: ({SESSION_ID_RE})$")
TERMINAL_LOG_RE = re.compile(
    rf"/etterminal-.+-({SESSION_ID_RE})-\d{{4}}-\d{{2}}-\d{{2}}_"
)
DISCONNECT_MESSAGES = (
    "Closing socket because ",
    "Got a serious error trying to read:",
    "Unexpected socket error:",
)
ONLINE_MESSAGES = (
    "Got keep alive",
    "Got terminal info",
)


class UnsafeState(RuntimeError):
    """The observed state is not reliable enough to perform cleanup."""


@dataclass(frozen=True)
class ProcessStat:
    ppid: int
    starttime: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clean disconnected etterminal process trees, but only while at "
            "least one ET session is connected. Ambiguous state is never cleaned."
        )
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would be killed"
    )
    parser.add_argument(
        "--port",
        type=int,
        help="etserver port (default: read /etc/et.cfg, then 2022)",
    )
    parser.add_argument(
        "--log", type=Path, help="current etserver log (default: infer from PID)"
    )
    parser.add_argument(
        "--server-pid", type=int, help="etserver PID (required if several exist)"
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=2.0,
        help="require two identical observations this far apart (default: 2)",
    )
    parser.add_argument(
        "--term-grace-seconds",
        type=float,
        default=5.0,
        help="wait this long between SIGTERM and SIGKILL (default: 5)",
    )
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.settle_seconds < 0 or args.term_grace_seconds < 0:
        parser.error("timeouts cannot be negative")
    return args


def read_process_stat(pid: int) -> ProcessStat | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    right_paren = raw.rfind(")")
    if right_paren < 0:
        return None
    fields = raw[right_paren + 2 :].split()
    if len(fields) < 20:
        return None
    return ProcessStat(ppid=int(fields[1]), starttime=int(fields[19]))


def process_comm(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/comm").read_text().rstrip("\n")
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None


def find_processes(comm: str, uid: int | None = None) -> list[int]:
    result: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            if uid is not None and entry.stat().st_uid != uid:
                continue
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if process_comm(pid) == comm:
            result.append(pid)
    return sorted(result)


def find_server_pid(requested_pid: int | None) -> int:
    if requested_pid is not None:
        if process_comm(requested_pid) != "etserver":
            raise UnsafeState(f"PID {requested_pid} is not etserver")
        return requested_pid
    pids = find_processes("etserver")
    if len(pids) != 1:
        raise UnsafeState(
            f"expected exactly one etserver, found {pids}; use --server-pid"
        )
    return pids[0]


def find_server_log(server_pid: int, requested_log: Path | None) -> Path:
    if requested_log is not None:
        candidates = [requested_log]
    else:
        candidates = [Path(p) for p in glob.glob(f"/tmp/etserver-*_{server_pid}.log")]
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        raise UnsafeState(f"cannot find readable log for etserver PID {server_pid}")
    log = max(candidates, key=lambda p: p.stat().st_mtime_ns)
    if not os.access(log, os.R_OK):
        raise UnsafeState(f"etserver log is not readable: {log}")
    return log


def read_port(requested_port: int | None) -> int:
    if requested_port is not None:
        return requested_port
    config = configparser.ConfigParser()
    try:
        config.read("/etc/et.cfg")
        port = config.getint("Networking", "port")
    except (configparser.Error, ValueError):
        port = 2022
    if not 1 <= port <= 65535:
        raise UnsafeState(f"invalid etserver port: {port}")
    return port


def session_id_for_process(pid: int) -> str | None:
    matches: list[tuple[int, str]] = []
    try:
        fd_entries = Path(f"/proc/{pid}/fd").iterdir()
        for fd_path in fd_entries:
            try:
                target = os.readlink(fd_path)
            except (FileNotFoundError, PermissionError, ProcessLookupError):
                continue
            match = TERMINAL_LOG_RE.search(target)
            if match:
                matches.append((int(fd_path.name), match.group(1)))
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        return None
    if not matches:
        return None
    return max(matches)[1]


def terminal_sessions() -> dict[str, int]:
    sessions: dict[str, int] = {}
    unmapped: list[int] = []
    duplicate_ids: list[str] = []
    for pid in find_processes("etterminal", os.getuid()):
        session_id = session_id_for_process(pid)
        if session_id is None:
            unmapped.append(pid)
        elif session_id in sessions:
            duplicate_ids.append(session_id)
        else:
            sessions[session_id] = pid
    if unmapped:
        raise UnsafeState(f"cannot determine client ID for etterminal PIDs {unmapped}")
    if duplicate_ids:
        raise UnsafeState(f"duplicate client IDs found: {sorted(duplicate_ids)}")
    return sessions


def online_ids_from_log(log: Path) -> set[str]:
    state: dict[str, bool] = {}
    with log.open(errors="replace") as stream:
        for line in stream:
            connected = CONNECTED_RE.search(line.rstrip("\n"))
            if connected:
                state[connected.group(1)] = True
                continue
            prefix = LOG_PREFIX_RE.match(line)
            if not prefix:
                continue
            session_id, message = prefix.groups()
            if message.startswith(DISCONNECT_MESSAGES):
                state[session_id] = False
            elif message.startswith(ONLINE_MESSAGES):
                state[session_id] = True
    return {session_id for session_id, online in state.items() if online}


def established_connection_count(port: int) -> int:
    try:
        result = subprocess.run(
            ["ss", "-Htn", "state", "established", "sport", "=", f":{port}"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise UnsafeState("ss is required") from error
    except subprocess.CalledProcessError as error:
        raise UnsafeState(f"ss failed: {error.stderr.strip()}") from error
    return sum(1 for line in result.stdout.splitlines() if line.strip())


def observe(log: Path, port: int) -> tuple[dict[str, int], frozenset[str]]:
    sessions = terminal_sessions()
    log_online = online_ids_from_log(log)
    online = frozenset(log_online & sessions.keys())
    established = established_connection_count(port)
    if len(online) != established:
        raise UnsafeState(
            "cannot safely map TCP connections to sessions: "
            f"log says {len(online)} online, ss says {established} established"
        )
    return sessions, online


def stable_observation(
    log: Path, port: int, settle_seconds: float
) -> tuple[dict[str, int], frozenset[str]]:
    first = observe(log, port)
    if settle_seconds:
        time.sleep(settle_seconds)
    second = observe(log, port)
    if first != second:
        raise UnsafeState("ET session state changed during observation; retry later")
    return second


def process_snapshot() -> dict[int, ProcessStat]:
    snapshot: dict[int, ProcessStat] = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            pid = int(entry.name)
            stat = read_process_stat(pid)
            if stat is not None:
                snapshot[pid] = stat
    return snapshot


def process_trees(roots: list[int]) -> list[list[int]]:
    snapshot = process_snapshot()
    children: dict[int, list[int]] = {}
    for pid, stat in snapshot.items():
        children.setdefault(stat.ppid, []).append(pid)

    trees: list[list[int]] = []
    claimed: set[int] = set()
    for root in roots:
        if root not in snapshot:
            continue
        tree: list[int] = []

        def visit(pid: int) -> None:
            if pid in claimed:
                return
            claimed.add(pid)
            for child in children.get(pid, []):
                visit(child)
            tree.append(pid)

        visit(root)
        trees.append(tree)
    return trees


def same_process(pid: int, expected_starttime: int) -> bool:
    stat = read_process_stat(pid)
    return stat is not None and stat.starttime == expected_starttime


def cleanup(trees: list[list[int]], grace_seconds: float, dry_run: bool) -> bool:
    targets = [pid for tree in trees for pid in tree]
    identities = {
        pid: stat.starttime
        for pid in targets
        if (stat := read_process_stat(pid)) is not None
    }
    for tree in trees:
        print("process tree (children first):")
        for pid in tree:
            print(f"  {pid:>8}  {process_comm(pid) or '<unavailable>'}")
    if dry_run:
        print("dry-run: no signals sent")
        return True

    failed = False
    for pid in targets:
        if pid not in identities or not same_process(pid, identities[pid]):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"cannot SIGTERM PID {pid}: permission denied", file=sys.stderr)
            failed = True

    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not any(same_process(pid, start) for pid, start in identities.items()):
            break
        time.sleep(0.1)

    for pid, starttime in identities.items():
        if not same_process(pid, starttime):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"cannot SIGKILL PID {pid}: permission denied", file=sys.stderr)
            failed = True
    time.sleep(0.1)
    survivors = [
        pid for pid, starttime in identities.items() if same_process(pid, starttime)
    ]
    if survivors:
        print(f"processes survived cleanup: {survivors}", file=sys.stderr)
        failed = True
    return not failed


def main() -> int:
    args = parse_args()
    try:
        server_pid = find_server_pid(args.server_pid)
        log = find_server_log(server_pid, args.log)
        port = read_port(args.port)
        sessions, online = stable_observation(log, port, args.settle_seconds)
    except UnsafeState as error:
        print(f"not cleaning: {error}", file=sys.stderr)
        return 2

    offline = sorted(sessions.keys() - online)
    print(
        f"etserver={server_pid} port={port} total={len(sessions)} "
        f"online={len(online)} offline={len(offline)}"
    )
    if not online:
        print("all sessions are offline; leaving them untouched")
        return 0
    if not offline:
        print("all sessions are online; nothing to clean")
        return 0

    print("offline sessions selected for cleanup:")
    for session_id in offline:
        print(f"  {session_id}  PID {sessions[session_id]}")
    trees = process_trees([sessions[session_id] for session_id in offline])
    return 0 if cleanup(trees, args.term_grace_seconds, args.dry_run) else 1


if __name__ == "__main__":
    sys.exit(main())
