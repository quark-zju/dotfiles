#!/usr/bin/env python3
"""Operations primarily intended for use with :func:`ssh_sync.call_remote`.

Functions in this module may reference other top-level functions from the same
module, but must not depend on other names from the module's global scope.
"""


def _repo_name(cwd):
    """Return the repository directory name containing cwd, if any."""
    import os

    if cwd is None:
        return None
    path = os.path.realpath(cwd)
    while True:
        if any(
            os.path.exists(os.path.join(path, marker))
            for marker in (".git", ".sl", ".hg")
        ):
            return os.path.basename(path)
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def list_running_agents():
    """Return Codex sessions whose rollout files are open by local processes."""
    import datetime
    import functools
    import json
    import mmap
    import os

    def match_obj(obj, template, matched_out):
        if (
            isinstance(template, str)
            and template.startswith("$")
            and matched_out is not None
        ):
            matched_out[template] = obj
            return True
        if type(obj) is not type(template):
            return False
        if isinstance(template, dict):
            for key, value in template.items():
                if key not in obj or not match_obj(obj[key], value, matched_out):
                    return False
            return True
        return obj == template

    def is_synthetic_user_message(text):
        stripped = text.lstrip()
        return (
            stripped.startswith("# AGENTS.md instructions")
            or stripped.startswith("The following is the Codex agent history")
            or stripped.startswith("<environment_context>")
            or stripped.startswith("<turn_aborted>")
            or stripped.startswith("<user_shell_command>")
        )

    repo_name = functools.lru_cache(_repo_name)

    def user_message(obj):
        matched = {}
        if not match_obj(
            obj,
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": "$content",
                },
            },
            matched,
        ):
            return None
        content = matched["$content"]
        if not isinstance(content, list):
            return None
        metadata = {}
        match_obj(
            obj,
            {
                "payload": {
                    "internal_chat_message_metadata_passthrough": {
                        "content_item_kinds": "$content_item_kinds"
                    }
                }
            },
            metadata,
        )
        kinds = metadata.get("$content_item_kinds")
        parts = []
        for index, item in enumerate(content):
            text = {}
            if not match_obj(item, {"type": "$type", "text": "$text"}, text):
                continue
            if isinstance(kinds, list):
                if (
                    index >= len(kinds)
                    or kinds[index] != "user.text"
                    or text["$type"] != "input_text"
                ):
                    continue
            elif text["$type"] not in ("input_text", "output_text", "text"):
                continue
            value = text["$text"]
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        message = "\n".join(parts)
        if message and not is_synthetic_user_message(message):
            timestamp = datetime.datetime.fromisoformat(
                obj["timestamp"].replace("Z", "+00:00")
            ).timestamp()
            return {"message": message[:1000], "timestamp": timestamp}
        return None

    def inspect_rollout(fd_path, pid, cwd):
        try:
            stream = open(fd_path, "rb")
        except OSError:
            return None
        with stream:
            try:
                size = os.fstat(stream.fileno()).st_size
                if not size:
                    return None
                data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                return None
            with data:
                first_end = data.find(b"\n")
                if first_end < 0:
                    first_end = len(data)
                try:
                    first = json.loads(data[:first_end])
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                matched = {}
                if not match_obj(
                    first,
                    {"type": "session_meta", "payload": {"id": "$session_id"}},
                    matched,
                ):
                    return None
                session_id = matched["$session_id"]
                if not isinstance(session_id, str) or not session_id:
                    return None

                working = None
                user_messages = []
                end = len(data)
                while end:
                    if data[end - 1] == 10:
                        end -= 1
                        continue
                    start = data.rfind(b"\n", 0, end) + 1
                    try:
                        obj = json.loads(data[start:end])
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        end = start
                        continue

                    if working is None:
                        event = {}
                        if match_obj(
                            obj,
                            {
                                "type": "event_msg",
                                "payload": {"type": "$event_type"},
                            },
                            event,
                        ):
                            event_type = event["$event_type"]
                            if event_type == "task_started":
                                working = True
                            elif event_type == "task_complete":
                                working = False
                    message = user_message(obj)
                    if message is not None:
                        user_messages.append(message)
                    end = start

                if not user_messages:
                    return None
                return {
                    "session_id": session_id,
                    "harness": "codex",
                    "user_messages": list(reversed(user_messages)),
                    "working": bool(working),
                    "pid": pid,
                    "cwd": cwd,
                    "repo_name": repo_name(cwd),
                }

    agents = {}
    try:
        processes = os.scandir("/proc")
    except OSError:
        return []
    with processes:
        pids = sorted(
            int(entry.name)
            for entry in processes
            if entry.name.isdigit() and entry.is_dir(follow_symlinks=False)
        )
    for pid in pids:
        fd_dir = "/proc/%d/fd" % pid
        try:
            descriptors = os.scandir(fd_dir)
        except OSError:
            continue
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            cwd = None
        seen_files = set()
        with descriptors:
            for descriptor in descriptors:
                fd_path = descriptor.path
                try:
                    target = os.readlink(fd_path)
                    stat = os.stat(fd_path)
                except OSError:
                    continue
                if ".jsonl" not in target:
                    continue
                identity = (stat.st_dev, stat.st_ino)
                if identity in seen_files:
                    continue
                seen_files.add(identity)
                agent = inspect_rollout(fd_path, pid, cwd)
                if agent is not None and agent["session_id"] not in agents:
                    agents[agent["session_id"]] = agent
    return sorted(
        agents.values(), key=lambda agent: (agent["pid"], agent["session_id"])
    )


def list_editors():
    """Return open buffers for Neovim processes on this host."""
    import json
    import os
    import shutil
    import subprocess

    markers = ("BUCK", "Cargo.toml", ".git", ".hg", ".sl")

    def simplify_path(path):
        path = os.path.abspath(os.path.expanduser(path))
        directory = path if os.path.isdir(path) else os.path.dirname(path)
        while True:
            if any(
                os.path.exists(os.path.join(directory, marker)) for marker in markers
            ):
                return os.path.relpath(path, os.path.dirname(directory))
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent

        home = os.path.expanduser("~")
        try:
            if os.path.commonpath((path, home)) == home:
                relative = os.path.relpath(path, home)
                return "~" if relative == "." else os.path.join("~", relative)
        except ValueError:
            pass
        return path

    def read_cmdline(pid):
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as stream:
                return [os.fsdecode(arg) for arg in stream.read().split(b"\0") if arg]
        except OSError:
            return []

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    runtime_sockets = {}
    try:
        entries = os.scandir(runtime_dir)
    except OSError:
        entries = None
    if entries is not None:
        with entries:
            for entry in entries:
                parts = entry.name.split(".", 2)
                if len(parts) == 3 and parts[0] == "nvim" and parts[1].isdigit():
                    runtime_sockets.setdefault(int(parts[1]), []).append(entry.path)

    expression = (
        'json_encode({"pid":getpid(),"paths":map('
        'filter(getbufinfo({"buflisted":1}), "!empty(v:val.name) && '
        "empty(getbufvar(v:val.bufnr, '&buftype'))\"), "
        '"fnamemodify(v:val.name, \\":p\\")")})'
    )
    editors = []
    for pid, sockets in sorted(runtime_sockets.items()):
        cmdline = read_cmdline(pid)
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            cwd = None
        executables = ["/proc/%d/exe" % pid]
        if cmdline:
            if os.path.sep in cmdline[0]:
                executable = cmdline[0]
                if not os.path.isabs(executable):
                    if cwd is not None:
                        executable = os.path.join(cwd, executable)
                executables.append(executable)
            else:
                executable = shutil.which(cmdline[0])
                if executable is not None:
                    executables.append(executable)
        executable = shutil.which("nvim")
        if executable is not None:
            executables.append(executable)
        executables = list(dict.fromkeys(executables))

        paths = None
        for socket_path in sorted(sockets):
            for executable in executables:
                try:
                    completed = subprocess.run(
                        [
                            executable,
                            "--server",
                            socket_path,
                            "--remote-expr",
                            expression,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        timeout=1,
                        check=False,
                        encoding="utf-8",
                    )
                    result = json.loads(completed.stdout)
                except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                    continue
                if (
                    completed.returncode == 0
                    and isinstance(result, dict)
                    and result.get("pid") == pid
                    and isinstance(result.get("paths"), list)
                ):
                    paths = [path for path in result["paths"] if isinstance(path, str)]
                    break
            if paths is not None:
                break

        if paths is None:
            continue

        buffers = []
        for path in dict.fromkeys(paths):
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                mtime = None
            buffers.append({"path": simplify_path(path), "mtime": mtime})
        editors.append(
            {
                "pid": pid,
                "name": "nvim",
                "repo_name": _repo_name(cwd),
                "buffers": buffers,
            }
        )

    return editors
