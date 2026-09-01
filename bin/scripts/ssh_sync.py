#!/usr/bin/env python3
r"""Run small Python calls on a remote host through Eternal Terminal.

Execute source from the command line::

    ssh_sync.py exec HOST 'result = {"answer": 1 + 1}' \
        --et-command 'et -c {command} {host}' \
        --remote-python python3.14 \
        --timeout 30 \
        --max-frame 16777216

The flags override ``SSH_SYNC_ET_COMMAND``, ``SSH_SYNC_REMOTE_PYTHON``,
``SSH_SYNC_TIMEOUT``, and ``SSH_SYNC_MAX_FRAME`` respectively.  Use
``ssh_sync.py list`` and ``ssh_sync.py stop [HOST ...]`` to manage daemons.
Run ``ssh_sync.py install`` to symlink this file into the current Python
interpreter's user site-packages and ``~/.local/bin``.

For library use::

    import ssh_sync
    value = ssh_sync.call_remote(host, function, *args, call_timeout=30)

See :func:`call_remote` for complete function and source examples, supported
values, timeout behavior, and stdout/stderr handling.
"""

import argparse
import ast
import base64
import errno
import hashlib
import inspect
import json
import math
import os
import pty
import select
import shlex
import signal
import site
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
import tty
import uuid
import zlib
from multiprocessing.connection import Client, Connection


_FRAME_PREFIX = b"SS1:"
_READY = b"\nSSH_SYNC_STAGE0_READY_V1\n"
_DEFAULT_MAX_FRAME = 16 * 1024 * 1024
_DEFAULT_TIMEOUT = 300.0
_MAX_AGENT = 4 * 1024 * 1024
_PROTOCOL_VERSION = 1

_STAGE0_SOURCE = r'''
import hashlib
import os
import struct
import sys
import tty

def read_exact(size):
    chunks = []
    while size:
        chunk = os.read(0, size)
        if not chunk:
            raise EOFError("agent upload ended early")
        chunks.append(chunk)
        size -= len(chunk)
    return b"".join(chunks)

tty.setraw(0)
os.write(1, b"\nSSH_SYNC_STAGE0_READY_V1\n")
header = read_exact(36)
size = struct.unpack("!I", header[:4])[0]
if size > 4 * 1024 * 1024:
    raise ValueError("agent is too large")
payload = read_exact(size)
if hashlib.sha256(payload).digest() != header[4:]:
    raise ValueError("agent digest mismatch")
source = payload.decode("utf-8")
sys.argv = ["ssh_sync.py", "_remote_agent"]
namespace = {
    "__name__": "__main__",
    "__ssh_sync_source__": source,
    "__ssh_sync_digest__": header[4:].hex(),
    "__ssh_sync_python_argv__": __SSH_SYNC_PYTHON_ARGV__,
    "__ssh_sync_max_frame__": __SSH_SYNC_MAX_FRAME__,
    "__ssh_sync_peer_name__": __SSH_SYNC_PEER_NAME__,
}
exec(compile(source, "<ssh-sync-agent>", "exec"), namespace, namespace)
'''


class RemoteError(Exception):
    def __init__(self, error):
        self.remote_module = error.get("module", "")
        self.remote_qualname = error.get("qualname", "Exception")
        self.remote_args = error.get("args")
        self.remote_traceback = error.get("traceback", "")
        name = self.remote_qualname
        if self.remote_module and self.remote_module != "builtins":
            name = self.remote_module + "." + name
        message = "%s: %s" % (name, error.get("message", ""))
        if self.remote_traceback:
            message += "\nRemote traceback:\n" + self.remote_traceback
        super().__init__(message)


def _encode_value(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite floats are not supported")
        return value
    if isinstance(value, bytes):
        return {"$type": "bytes", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, list):
        return {"$type": "list", "items": [_encode_value(v) for v in value]}
    if isinstance(value, tuple):
        return {"$type": "tuple", "items": [_encode_value(v) for v in value]}
    if isinstance(value, set):
        return {"$type": "set", "items": [_encode_value(v) for v in value]}
    if isinstance(value, frozenset):
        return {"$type": "frozenset", "items": [_encode_value(v) for v in value]}
    if isinstance(value, dict):
        return {
            "$type": "dict",
            "items": [[_encode_value(k), _encode_value(v)] for k, v in value.items()],
        }
    raise TypeError("unsupported value type: %s" % type(value).__name__)


def _decode_value(value):
    if not isinstance(value, dict) or "$type" not in value:
        return value
    kind = value["$type"]
    if kind == "bytes":
        return base64.b64decode(value["data"], validate=True)
    items = value["items"]
    if kind == "list":
        return [_decode_value(v) for v in items]
    if kind == "tuple":
        return tuple(_decode_value(v) for v in items)
    if kind == "set":
        return set(_decode_value(v) for v in items)
    if kind == "frozenset":
        return frozenset(_decode_value(v) for v in items)
    if kind == "dict":
        return {_decode_value(k): _decode_value(v) for k, v in items}
    raise ValueError("unknown encoded type: %s" % kind)


def _json_dumps(value):
    return json.dumps(
        _encode_value(value), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")


def _json_loads(data):
    return _decode_value(json.loads(data.decode("utf-8")))


def _write_all(fd, data):
    # This intentionally uses blocking writes.  If ET stops reading after its
    # disconnect buffer fills, a call timeout cannot interrupt this write.
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except InterruptedError:
            continue
        if not written:
            raise EOFError("write returned zero")
        view = view[written:]


def _read_fd(fd, size, deadline=None):
    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for remote output")
            try:
                readable, _, _ = select.select([fd], [], [], remaining)
            except InterruptedError:
                continue
            if not readable:
                raise TimeoutError("timed out waiting for remote output")
        try:
            return os.read(fd, size)
        except InterruptedError:
            continue
        except OSError as exc:
            if exc.errno == errno.EIO:
                return b""
            raise


def _send_frame(fd, value, max_frame=None):
    payload = _json_dumps(value)
    checksum = "%08x" % (zlib.crc32(payload) & 0xFFFFFFFF)
    frame = _FRAME_PREFIX + checksum.encode("ascii") + b":"
    frame += base64.b64encode(payload) + b"\n"
    if max_frame is not None and len(frame) > max_frame:
        raise FrameTooLarge("frame exceeds %d bytes" % max_frame)
    _write_all(fd, frame)


class FrameTooLarge(Exception):
    """A single frame exceeded the configured limit, so the stream is unusable."""


class _FrameReader:
    def __init__(self, fd, initial=b"", max_frame=_DEFAULT_MAX_FRAME):
        self.fd = fd
        self.buffer = bytearray(initial)
        self.max_frame = max_frame

    def recv(self, deadline=None):
        while True:
            newline = self.buffer.find(b"\n")
            if newline >= 0:
                if newline + 1 > self.max_frame:
                    raise FrameTooLarge(
                        "frame exceeds %d bytes; raise SSH_SYNC_MAX_FRAME"
                        % self.max_frame
                    )
                line = bytes(self.buffer[:newline]).rstrip(b"\r")
                del self.buffer[: newline + 1]
                if not line.startswith(_FRAME_PREFIX):
                    continue
                try:
                    checksum, encoded = line[len(_FRAME_PREFIX) :].split(b":", 1)
                    payload = base64.b64decode(encoded, validate=True)
                    if "%08x" % (zlib.crc32(payload) & 0xFFFFFFFF) != checksum.decode("ascii"):
                        continue
                    return _json_loads(payload)
                except (ValueError, UnicodeError, json.JSONDecodeError):
                    continue
            # Dropping the partial frame would desynchronise the stream: the tail
            # would be parsed as a truncated line and the frame lost for good.
            if len(self.buffer) > self.max_frame:
                raise FrameTooLarge(
                    "frame exceeds %d bytes; raise SSH_SYNC_MAX_FRAME" % self.max_frame
                )
            chunk = _read_fd(self.fd, 65536, deadline)
            if not chunk:
                raise EOFError("connection closed")
            self.buffer.extend(chunk)


class _PendingResponse:
    def __init__(self):
        self.event = threading.Event()
        self.response = None
        self.error = None


class _Multiplexer:
    def __init__(self, reader, write_fd, max_frame, call_handler=None):
        self.reader = reader
        self.write_fd = write_fd
        self.max_frame = max_frame
        self.call_handler = call_handler
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.closed = threading.Event()
        self.reader_thread = threading.Thread(target=self._read, daemon=True)
        self.reader_thread.start()

    def request(self, request, deadline=None):
        request_id = request["request_id"]
        pending = _PendingResponse()
        with self.pending_lock:
            if request_id in self.pending:
                raise ValueError("duplicate request id")
            self.pending[request_id] = pending
        try:
            self._send(request)
        except BaseException:
            with self.pending_lock:
                self.pending.pop(request_id, None)
            raise

        timeout = None if deadline is None else max(deadline - time.monotonic(), 0)
        completed = pending.event.wait(timeout)
        with self.pending_lock:
            if not completed and pending.event.is_set():
                completed = True
            self.pending.pop(request_id, None)
        if not completed:
            raise TimeoutError("timed out waiting for remote output")
        if pending.error is not None:
            raise pending.error
        return pending.response

    def wait_closed(self):
        self.closed.wait()

    def _send(self, value):
        with self.write_lock:
            _send_frame(self.write_fd, value, self.max_frame)

    def _read(self):
        try:
            while True:
                message = self.reader.recv()
                if message.get("operation") == "call":
                    if self.call_handler is not None:
                        threading.Thread(
                            target=self._handle_call,
                            args=(message,),
                            daemon=True,
                        ).start()
                    continue
                request_id = message.get("request_id")
                with self.pending_lock:
                    pending = self.pending.get(request_id)
                    if pending is not None:
                        pending.response = message
                        pending.event.set()
        except BaseException as exc:
            with self.pending_lock:
                pending = list(self.pending.values())
                self.pending.clear()
                for response in pending:
                    response.error = exc
                    response.event.set()
        finally:
            self.closed.set()

    def _handle_call(self, request):
        try:
            response = self.call_handler(request)
        except BaseException as exc:
            response = {"ok": False, "error": _exception_data(exc)}
        response["request_id"] = request["request_id"]
        try:
            self._send(response)
        except FrameTooLarge:
            self._send(
                {
                    "request_id": request["request_id"],
                    "ok": False,
                    "error": {
                        "module": "ssh_sync",
                        "qualname": "RemoteResultTooLarge",
                        "message": "remote result and output exceed SSH_SYNC_MAX_FRAME",
                        "repr": "RemoteResultTooLarge()",
                        "args": None,
                        "traceback": "",
                    },
                }
            )


def _runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        base = os.path.join(tempfile.gettempdir(), "ssh-sync-%d" % os.getuid())
    path = os.path.join(base, "ssh-sync")
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _host_key(host):
    return hashlib.sha256(host.encode("utf-8")).hexdigest()[:24]


def _peer_name():
    return socket.gethostname()


def _socket_path(host):
    control = os.path.join(_runtime_dir(), "control")
    os.makedirs(control, mode=0o700, exist_ok=True)
    os.chmod(control, 0o700)
    return os.path.join(control, _host_key(host) + ".sock")


def _log_path(host):
    return os.path.join(_runtime_dir(), _host_key(host) + ".log")


def _daemon_hash_path(host):
    return os.path.join(_runtime_dir(), "control", _host_key(host) + ".code-hash")


def _function_spec(script):
    if isinstance(script, str):
        return {"kind": "exec", "source": script}
    if not inspect.isfunction(script):
        raise TypeError("script must be source text or a Python function")
    if "<locals>" in script.__qualname__:
        raise TypeError("nested functions and closures are not supported")
    closure = inspect.getclosurevars(script)
    if closure.nonlocals or closure.globals:
        names = sorted(set(closure.nonlocals) | set(closure.globals))
        raise TypeError("function depends on non-local names: %s" % ", ".join(names))
    source = textwrap.dedent(inspect.getsource(script))
    tree = ast.parse(source)
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(definitions) != 1 or definitions[0].name != script.__name__:
        raise TypeError("expected one top-level function definition")
    if definitions[0].decorator_list:
        raise TypeError("decorated functions are not supported")
    return {"kind": "call", "source": source, "name": script.__name__}


def _current_source():
    with open(os.path.abspath(__file__), "rb") as source_file:
        return source_file.read()


def _transport_command():
    template = os.environ.get("SSH_SYNC_ET_COMMAND")
    if not template:
        raise RuntimeError(
            "set SSH_SYNC_ET_COMMAND, for example: "
            "et -c {command} {host}"
        )
    return template


def _remote_python():
    return os.environ.get("SSH_SYNC_REMOTE_PYTHON", "python3")


def _max_frame():
    raw = os.environ.get("SSH_SYNC_MAX_FRAME")
    if not raw:
        return _DEFAULT_MAX_FRAME
    value = int(raw)
    if value < 65536:
        raise ValueError("SSH_SYNC_MAX_FRAME must be at least 65536")
    return value


def _resolve_timeout(timeout):
    """Return seconds to wait for a call, or None to wait forever."""
    if timeout is None:
        raw = os.environ.get("SSH_SYNC_TIMEOUT")
        timeout = float(raw) if raw else _DEFAULT_TIMEOUT
    return float(timeout) if timeout > 0 else None


def _transport_argv(template, host, command):
    argv = shlex.split(template)
    if "{host}" not in argv or "{command}" not in argv:
        raise ValueError("SSH_SYNC_ET_COMMAND must contain {host} and {command} arguments")
    return [host if arg == "{host}" else command if arg == "{command}" else arg for arg in argv]


def _read_daemon_hash(host):
    try:
        with open(_daemon_hash_path(host), encoding="ascii") as hash_file:
            return hash_file.read().strip()
    except OSError:
        return None


def _connect_daemon(host, code_hash, transport_factory):
    address = _socket_path(host)
    info = _daemon_command(address, "info")
    if info is not None:
        endpoint_hash = info.get("code_hash") or _read_daemon_hash(host)
        if endpoint_hash == code_hash:
            transport = None
            if info.get("kind", "outbound") == "outbound":
                transport = transport_factory()
            return Client(address, family="AF_UNIX"), info, transport
        if info.get("kind") == "peer":
            raise RuntimeError(
                "ssh-sync peer %s uses a different code version" % host
            )
        _daemon_command(address, "stop")
        deadline = time.monotonic() + 2
        while os.path.exists(address) and time.monotonic() < deadline:
            time.sleep(0.05)
        if os.path.exists(address):
            os.unlink(address)

    transport = transport_factory()
    log = open(_log_path(host), "ab", buffering=0)
    try:
        subprocess.Popen(
            [
                sys.executable,
                os.path.abspath(__file__),
                "_daemon",
                host,
                code_hash,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            start_new_session=True,
        )
    finally:
        log.close()

    deadline = time.monotonic() + 5
    while True:
        try:
            connection = Client(address, family="AF_UNIX")
            return (
                connection,
                {
                    "kind": "outbound",
                    "code_hash": code_hash,
                    "protocol_version": _PROTOCOL_VERSION,
                },
                transport,
            )
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError("ssh-sync daemon did not start; see %s" % _log_path(host))
            time.sleep(0.05)


def _write_captured(stream, data):
    if not data:
        return
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(data)
        buffer.flush()
    else:
        stream.write(data.decode("utf-8", "replace"))
        stream.flush()


def call_remote(host, script, *args, call_timeout=None, **kwargs):
    r"""Run source text or a top-level Python function on *host*.

    Configure the transport in the environment::

        export SSH_SYNC_ET_COMMAND='et -c {command} {host}'

    Pass a top-level ``def``; imports used by it should be inside the function.
    Lambdas and closures are not supported::

        import ssh_sync

        def disk_usage(path):
            import os
            stat = os.statvfs(path)
            return {"available": stat.f_bavail * stat.f_frsize}

        value = ssh_sync.call_remote(
            "user@remote.example.com",
            disk_usage,
            "/",
            call_timeout=30,
        )

    Source text is also accepted; assign its structured return value to
    ``result``::

        value = ssh_sync.call_remote(host, "result = {'answer': 1 + 1}")

    Function arguments and results must contain only standard supported values.

    ``call_timeout`` bounds session startup, remote execution, and response
    reads; ``None`` falls back to ``SSH_SYNC_TIMEOUT`` (default 300), and a
    value of zero or less waits forever. A PTY write blocked by a full ET
    disconnect buffer cannot be interrupted.

    Remote stdout and stderr are captured until the call finishes and then
    replayed locally.  The return value is transferred separately as structured
    data.
    """
    timeout = _resolve_timeout(call_timeout)
    spec = _function_spec(script)
    if spec["kind"] == "exec" and (args or kwargs):
        raise TypeError("source text calls do not accept arguments")
    _encode_value(args)
    _encode_value(kwargs)
    agent_source = _current_source()
    request = {
        "operation": "call",
        "host": host,
        "request_id": uuid.uuid4().hex,
        "function": spec,
        "args": args,
        "kwargs": kwargs,
        "agent_digest": hashlib.sha256(agent_source).hexdigest(),
        "agent_source": agent_source,
        "remote_python": _remote_python(),
        "max_frame": _max_frame(),
        "timeout": timeout,
    }
    connection, _endpoint, transport = _connect_daemon(
        host, request["agent_digest"], _transport_command
    )
    if transport is not None:
        request["transport_command"] = transport
    try:
        connection.send(request)
        # The daemon enforces the timeout and reports it as an error; only give
        # up locally if even that fails to arrive.
        if timeout is not None and not connection.poll(timeout + 10):
            raise TimeoutError("ssh-sync daemon did not answer within %.1fs" % (timeout + 10))
        response = connection.recv()
    finally:
        connection.close()
    if response.get("timeout_error"):
        raise TimeoutError(response["timeout_error"])
    if response.get("daemon_error"):
        raise RuntimeError(response["daemon_error"])
    _write_captured(sys.stdout, response.get("stdout", b""))
    _write_captured(sys.stderr, response.get("stderr", b""))
    if response.get("timeout"):
        raise TimeoutError(response["error"]["message"])
    if not response.get("ok"):
        raise RemoteError(response["error"])
    return response.get("value")


def _read_until(fd, marker, deadline=None):
    data = bytearray()
    while True:
        position = data.find(marker)
        if position >= 0:
            return bytes(data[position + len(marker) :])
        if len(data) > 1024 * 1024:
            del data[: len(data) - len(marker)]
        chunk = _read_fd(fd, 65536, deadline)
        if not chunk:
            raise EOFError("et exited before the remote Python loader was ready")
        data.extend(chunk)


class _Session:
    def __init__(
        self,
        host,
        agent_source,
        digest,
        transport_command,
        remote_python,
        max_frame,
        deadline=None,
    ):
        if len(agent_source) > _MAX_AGENT:
            raise ValueError("agent source exceeds 4 MiB")
        self.host = host
        self.digest = digest
        self.transport_command = transport_command
        self.remote_python = remote_python
        self.max_frame = max_frame
        python_argv = shlex.split(remote_python)
        if not python_argv:
            raise ValueError("SSH_SYNC_REMOTE_PYTHON is empty")
        stage0_source = _STAGE0_SOURCE.replace(
            "__SSH_SYNC_PYTHON_ARGV__", repr(python_argv)
        ).replace("__SSH_SYNC_MAX_FRAME__", repr(int(max_frame))).replace(
            "__SSH_SYNC_PEER_NAME__", repr(_peer_name())
        )
        loader = base64.b64encode(stage0_source.encode("utf-8")).decode("ascii")
        loader_code = "import base64;exec(base64.b64decode('%s'))" % loader
        command = "exec " + shlex.join(python_argv + ["-c", loader_code])
        argv = _transport_argv(transport_command, host, command)
        pid, master_fd = pty.fork()
        if pid == 0:
            try:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, signal.SIG_DFL)
                log_fd = os.open(_log_path(host), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                os.dup2(log_fd, 2)
                if log_fd > 2:
                    os.close(log_fd)
                os.execvp(argv[0], argv)
            finally:
                os._exit(127)
        self.pid = pid
        self.fd = master_fd
        try:
            # The transport usually puts its tty into raw mode itself, but until
            # it does the line discipline echoes everything we write back at us
            # and canonical mode truncates writes at MAX_CANON. Do not rely on it.
            tty.setraw(master_fd)
            initial = _read_until(master_fd, _READY, deadline)
            raw_digest = bytes.fromhex(digest)
            _write_all(
                master_fd,
                struct.pack("!I", len(agent_source)) + raw_digest + agent_source,
            )
            self.reader = _FrameReader(master_fd, initial, max_frame)
            hello = self.reader.recv(deadline)
            if hello.get("operation") != "hello" or hello.get("agent_digest") != digest:
                raise RuntimeError("invalid remote agent hello")
            if hello.get("error"):
                raise RuntimeError(hello["error"])
            self.multiplexer = _Multiplexer(
                self.reader,
                self.fd,
                self.max_frame,
                lambda request: _run_worker(
                    request,
                    [sys.executable, os.path.abspath(__file__), "_remote_worker"],
                ),
            )
        except BaseException:
            self.close()
            raise

    def call(self, request, worker_timeout=None, deadline=None):
        wire_request = {
            "operation": "call",
            "request_id": request["request_id"],
            "function": request["function"],
            "args": request["args"],
            "kwargs": request["kwargs"],
            "timeout": worker_timeout,
        }
        return self.multiplexer.request(wire_request, deadline)

    def close(self):
        fd = getattr(self, "fd", None)
        self.fd = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        pid = getattr(self, "pid", None)
        self.pid = None
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass


def _exception_data(exc):
    try:
        _encode_value(exc.args)
        args = exc.args
    except TypeError:
        args = None
    return {
        "module": type(exc).__module__,
        "qualname": type(exc).__qualname__,
        "message": str(exc),
        "repr": repr(exc),
        "args": args,
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def _remote_worker(result_path):
    try:
        request = _json_loads(sys.stdin.buffer.read())
        namespace = {"__name__": "__ssh_sync_call__"}
        function = request["function"]
        exec(compile(function["source"], "<ssh-sync-call>", "exec"), namespace, namespace)
        if function["kind"] == "call":
            value = namespace[function["name"]](*request["args"], **request["kwargs"])
        else:
            value = namespace.get("result")
        response = {"ok": True, "value": value}
        _encode_value(response)
    except BaseException as exc:
        response = {"ok": False, "error": _exception_data(exc)}
    with open(result_path, "wb") as result_file:
        result_file.write(_json_dumps(response))


def _run_worker(request, worker_argv):
    with tempfile.TemporaryDirectory(prefix="ssh-sync-") as temp_dir:
        result_path = os.path.join(temp_dir, "result.json")
        try:
            completed = subprocess.run(
                worker_argv + [result_path],
                input=_json_dumps(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=request.get("timeout"),
            )
            stdout = completed.stdout
            stderr = completed.stderr
            try:
                with open(result_path, "rb") as result_file:
                    response = _json_loads(result_file.read())
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                response = {"ok": False, "error": _exception_data(exc)}
                response["error"]["qualname"] = "RemoteWorkerError"
                response["error"]["message"] = (
                    "worker exited with status %d" % completed.returncode
                )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            response = {
                "ok": False,
                "timeout": True,
                "error": {
                    "module": "builtins",
                    "qualname": "TimeoutError",
                    "message": "remote call timed out",
                    "repr": "TimeoutError('remote call timed out')",
                    "args": ("remote call timed out",),
                    "traceback": "",
                },
            }
        response["request_id"] = request["request_id"]
        response["stdout"] = stdout
        response["stderr"] = stderr
        return response


def _bind_server(address):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(address)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            server.close()
            raise
        server.close()
        try:
            existing = Client(address, family="AF_UNIX")
            existing.close()
            return None
        except OSError:
            os.unlink(address)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(address)
    server.listen(8)
    stat = os.stat(address)
    return server, (stat.st_dev, stat.st_ino)


def _bind_peer_server(address):
    bound = _bind_server(address)
    if bound is not None:
        return bound
    info = _daemon_command(address, "info")
    if info is None or info.get("kind") != "peer":
        return None
    _daemon_command(address, "stop")
    deadline = time.monotonic() + 2
    while os.path.exists(address) and time.monotonic() < deadline:
        time.sleep(0.05)
    if os.path.exists(address):
        os.unlink(address)
    return _bind_server(address)


def _serve_peer(server, socket_identity, peer_name, code_hash, multiplexer):
    address = _socket_path(peer_name)
    hash_path = _daemon_hash_path(peer_name)
    with open(hash_path, "w", encoding="ascii") as hash_file:
        hash_file.write(code_hash + "\n")
    server.settimeout(1)
    running = True
    try:
        while running and not multiplexer.closed.is_set():
            try:
                current = os.stat(address)
            except FileNotFoundError:
                return
            if (current.st_dev, current.st_ino) != socket_identity:
                return
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            connection = Connection(client.detach())
            try:
                try:
                    request = connection.recv()
                except EOFError:
                    continue
                operation = request.get("operation")
                if operation in ("info", "stop"):
                    running = operation != "stop"
                    connection.send(
                        {
                            "ok": True,
                            "host": peer_name,
                            "pid": os.getpid(),
                            "kind": "peer",
                            "code_hash": code_hash,
                            "protocol_version": _PROTOCOL_VERSION,
                        }
                    )
                    continue
                if operation != "call" or request.get("host") != peer_name:
                    raise ValueError("invalid peer request")
                timeout = request.get("timeout")
                deadline = None if timeout is None else time.monotonic() + timeout
                if deadline is None:
                    worker_timeout = None
                    response_deadline = None
                else:
                    worker_timeout = deadline - time.monotonic()
                    if worker_timeout <= 0:
                        raise TimeoutError("remote call timed out")
                    response_deadline = deadline + 1
                wire_request = {
                    "operation": "call",
                    "request_id": request["request_id"],
                    "function": request["function"],
                    "args": request["args"],
                    "kwargs": request["kwargs"],
                    "timeout": worker_timeout,
                }
                response = multiplexer.request(wire_request, response_deadline)
                connection.send(response)
            except TimeoutError as exc:
                try:
                    connection.send({"timeout_error": str(exc)})
                except OSError:
                    pass
            except Exception:
                try:
                    connection.send({"daemon_error": traceback.format_exc()})
                except OSError:
                    pass
            finally:
                connection.close()
    finally:
        server.close()
        try:
            current = os.stat(address)
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == socket_identity:
                os.unlink(address)
                try:
                    os.unlink(hash_path)
                except FileNotFoundError:
                    pass


def _remote_agent():
    source = globals()["__ssh_sync_source__"]
    digest = globals()["__ssh_sync_digest__"]
    python_argv = globals()["__ssh_sync_python_argv__"]
    max_frame = globals()["__ssh_sync_max_frame__"]
    peer_name = globals()["__ssh_sync_peer_name__"]
    address = _socket_path(peer_name)
    bound = _bind_peer_server(address)
    if bound is None:
        _send_frame(
            1,
            {
                "operation": "hello",
                "agent_digest": digest,
                "error": "ssh-sync endpoint %s is already running" % peer_name,
            },
            max_frame,
        )
        return
    server, socket_identity = bound
    reader = _FrameReader(0, max_frame=max_frame)
    _send_frame(
        1,
        {
            "operation": "hello",
            "agent_digest": digest,
            "python": list(sys.version_info[:3]),
        },
        max_frame,
    )

    def handle_call(request):
        return _run_worker(
            request, python_argv + ["-c", source, "_remote_worker"]
        )

    multiplexer = _Multiplexer(reader, 1, max_frame, handle_call)
    _serve_peer(
        server,
        socket_identity,
        peer_name,
        digest,
        multiplexer,
    )


def _run_daemon(host, code_hash):
    def stop(_signum, _frame):
        raise SystemExit

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    address = _socket_path(host)
    bound = _bind_server(address)
    if bound is None:
        return
    server, socket_identity = bound
    with open(_daemon_hash_path(host), "w", encoding="ascii") as hash_file:
        hash_file.write(code_hash + "\n")

    def check_socket(_signum, _frame):
        try:
            current = os.stat(address)
        except FileNotFoundError:
            raise SystemExit
        if (current.st_dev, current.st_ino) != socket_identity:
            raise SystemExit

    signal.signal(signal.SIGALRM, check_socket)
    signal.setitimer(signal.ITIMER_REAL, 1, 1)

    session = None
    running = True
    try:
        while running:
            client, _ = server.accept()
            connection = Connection(client.detach())
            try:
                try:
                    request = connection.recv()
                except EOFError:
                    # The client hung up before asking for anything. Anything
                    # further below is a real failure and must be reported.
                    continue
                operation = request.get("operation")
                if operation in ("info", "stop"):
                    running = operation != "stop"
                    connection.send(
                        {
                            "ok": True,
                            "host": host,
                            "pid": os.getpid(),
                            "kind": "outbound",
                            "code_hash": code_hash,
                            "protocol_version": _PROTOCOL_VERSION,
                        }
                    )
                    continue
                if operation != "call" or request.get("host") != host:
                    raise ValueError("invalid daemon request")
                timeout = request.get("timeout")
                deadline = None if timeout is None else time.monotonic() + timeout
                max_frame = request.get("max_frame", _DEFAULT_MAX_FRAME)
                if (
                    session is None
                    or session.digest != request["agent_digest"]
                    or session.transport_command != request["transport_command"]
                    or session.remote_python != request["remote_python"]
                    or session.max_frame != max_frame
                ):
                    if session is not None:
                        session.close()
                        session = None
                    session = _Session(
                        host,
                        request["agent_source"],
                        request["agent_digest"],
                        request["transport_command"],
                        request["remote_python"],
                        max_frame,
                        deadline,
                    )
                try:
                    if deadline is None:
                        worker_timeout = None
                        response_deadline = None
                    else:
                        worker_timeout = deadline - time.monotonic()
                        if worker_timeout <= 0:
                            raise TimeoutError("remote call timed out")
                        response_deadline = deadline + 1
                    response = session.call(
                        request, worker_timeout, response_deadline
                    )
                except Exception:
                    # The stream position is unknown after a timeout or a
                    # oversized frame, so the session cannot be reused.
                    session.close()
                    session = None
                    raise
                connection.send(response)
            except TimeoutError as exc:
                try:
                    connection.send({"timeout_error": str(exc)})
                except OSError:
                    pass
            except Exception:
                try:
                    connection.send({"daemon_error": traceback.format_exc()})
                except OSError:
                    pass
            finally:
                connection.close()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if session is not None:
            session.close()
        server.close()
        try:
            current = os.stat(address)
        except FileNotFoundError:
            pass
        else:
            if (current.st_dev, current.st_ino) == socket_identity:
                os.unlink(address)
                try:
                    os.unlink(_daemon_hash_path(host))
                except FileNotFoundError:
                    pass


def _daemon_command(address, operation):
    """Send a control request to one daemon socket, or None if it is stale."""
    try:
        connection = Client(address, family="AF_UNIX")
    except OSError:
        return None
    try:
        connection.send({"operation": operation})
        return connection.recv()
    finally:
        connection.close()


def _daemon_sockets():
    control = os.path.join(_runtime_dir(), "control")
    try:
        names = sorted(os.listdir(control))
    except FileNotFoundError:
        return []
    return [os.path.join(control, name) for name in names if name.endswith(".sock")]


def _control_main(command, hosts):
    operation = "stop" if command == "stop" else "info"
    addresses = [_socket_path(host) for host in hosts] if hosts else _daemon_sockets()
    found = False
    for address in addresses:
        info = _daemon_command(address, operation)
        if info is None:
            # A stale socket; _run_daemon removes it when it next starts up.
            continue
        found = True
        if not info.get("ok"):
            print("%s\tunrecognised daemon: %s" % (address, info))
            continue
        verb = "stopped" if command == "stop" else "running"
        print("%s\t%s\tpid %d" % (info["host"], verb, info["pid"]))
    if not found:
        print("no ssh-sync daemon is running")


def _add_call_options(parser):
    parser.add_argument(
        "--et-command",
        help="ET argv template; overrides SSH_SYNC_ET_COMMAND",
    )
    parser.add_argument(
        "--remote-python",
        help="remote Python command; overrides SSH_SYNC_REMOTE_PYTHON",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="call timeout in seconds; overrides SSH_SYNC_TIMEOUT",
    )
    parser.add_argument(
        "--max-frame",
        type=int,
        help="maximum frame size; overrides SSH_SYNC_MAX_FRAME",
    )


def _command_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    execute = commands.add_parser("exec", help="execute Python source remotely")
    execute.add_argument("host")
    execute.add_argument("source", help="source may assign its result to 'result'")
    _add_call_options(execute)

    commands.add_parser("list", help="show running daemons")
    stop = commands.add_parser("stop", help="stop daemons")
    stop.add_argument("hosts", nargs="*")
    commands.add_parser(
        "install", help="symlink this module into user site-packages and ~/.local/bin"
    )
    return parser


def _exec_main(args):
    if args.et_command is not None:
        os.environ["SSH_SYNC_ET_COMMAND"] = args.et_command
    if args.remote_python is not None:
        os.environ["SSH_SYNC_REMOTE_PYTHON"] = args.remote_python
    if args.max_frame is not None:
        os.environ["SSH_SYNC_MAX_FRAME"] = str(args.max_frame)
    result = call_remote(
        args.host,
        args.source,
        call_timeout=args.timeout,
    )
    if result is not None:
        print(repr(result))


def _install_main():
    source = os.path.realpath(__file__)
    directories = [site.getusersitepackages(), os.path.expanduser("~/.local/bin")]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        destination = os.path.join(directory, "ssh_sync.py")
        if os.path.lexists(destination):
            if os.path.islink(destination) and os.path.realpath(destination) == source:
                print(destination + " already points to " + source)
                continue
            raise FileExistsError(destination + " already exists")
        os.symlink(source, destination)
        print(destination + " -> " + source)


def _main():
    command = sys.argv[1] if len(sys.argv) >= 2 else ""
    if command == "_daemon":
        code_hash = (
            sys.argv[3]
            if len(sys.argv) >= 4
            else hashlib.sha256(_current_source()).hexdigest()
        )
        _run_daemon(sys.argv[2], code_hash)
    elif command == "_remote_agent":
        _remote_agent()
    elif command == "_remote_worker" and len(sys.argv) >= 3:
        _remote_worker(sys.argv[2])
    else:
        args = _command_parser().parse_args()
        if args.command == "exec":
            _exec_main(args)
        elif args.command == "list":
            _control_main("list", [])
        elif args.command == "stop":
            _control_main("stop", args.hosts)
        else:
            _install_main()


if __name__ == "__main__":
    _main()
