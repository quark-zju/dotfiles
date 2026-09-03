#!/usr/bin/env python3
r"""Run small Python calls on a remote host through Eternal Terminal.

Execute source from the command line::

    ssh_sync.py exec --host HOST --type py 'result = {"answer": 1 + 1}' \
        --et-command 'et -c {command} {host}' \
        --remote-python python3.14 \
        --timeout 30 \
        --max-frame 16777216

Omit ``--type`` to run a source without whitespace as shell, or otherwise parse
it as Python first and fall back to ``sh -c``. Shell commands stream stdin,
stdout, and stderr.

The flags override ``SSH_SYNC_ET_COMMAND``, ``SSH_SYNC_REMOTE_PYTHON``,
``SSH_SYNC_TIMEOUT``, and ``SSH_SYNC_MAX_FRAME`` respectively.  Use
``ssh_sync.py list`` and ``ssh_sync.py stop [HOST ...]`` to manage daemons.
Run ``ssh_sync.py install [-f]`` to symlink this file into the current Python
interpreter's user site-packages and ``~/.local/bin``. Starting a remote agent
also installs the uploaded version into those locations on the remote host.

For library use::

    import ssh_sync
    hosts = ssh_sync.list_hosts()
    value = ssh_sync.call_remote(host, function, *args, call_timeout=30)
    for item in ssh_sync.iter_remote(host, generator_function, call_timeout=30):
        print(item)
    with ssh_sync.open_process(host, ["command", "arg"], call_timeout=30) as process:
        process.send(b"input\n")
        process.close_stdin()
        for event in process:
            print(event.stream, event.data)

See :func:`call_remote`, :func:`iter_remote`, and :func:`open_process` for
complete function and source examples, supported values, timeout behavior,
and stdout/stderr handling.
"""

import ast
import base64
import builtins
import dis
import errno
import hashlib
import inspect
import json
import math
import os
import shlex
import socket
import subprocess
import sys
import textwrap
import threading
import time
import uuid
import zlib
from multiprocessing.connection import Client, Connection


_FRAME_PREFIX = b"SS1:"
_READY = b"\nSSH_SYNC_STAGE0_READY_V1\n"
_DEFAULT_MAX_FRAME = 16 * 1024 * 1024
_DEFAULT_TIMEOUT = 300.0
_MAX_AGENT = 4 * 1024 * 1024
_PROTOCOL_VERSION = 1
_STREAM_CHUNK_SIZE = 32 * 1024

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
            import select

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

    def deliver(self, message):
        self.response = message
        self.event.set()

    def fail(self, error):
        self.error = error
        self.event.set()


class _PendingStream:
    def __init__(self):
        import queue

        self.queue = queue.Queue(maxsize=16)

    def deliver(self, message):
        self.queue.put((message, None))

    def fail(self, error):
        self.queue.put((None, error))

    def receive(self, timeout=None):
        import queue

        try:
            message, error = self.queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if error is not None:
            raise error
        return message


class _IncomingStream:
    def __init__(self):
        import queue

        self.queue = queue.Queue(maxsize=16)
        self.cancelled = threading.Event()

    def deliver(self, message):
        if message["operation"] == "stream_cancel":
            self.cancelled.set()
        else:
            self.queue.put(message)

    def receive(self, timeout=None):
        import queue

        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None


class _Multiplexer:
    def __init__(
        self, reader, write_fd, max_frame, call_handler=None, stream_handler=None
    ):
        self.reader = reader
        self.write_fd = write_fd
        self.max_frame = max_frame
        self.call_handler = call_handler
        self.stream_handler = stream_handler
        self.pending = {}
        self.pending_lock = threading.Lock()
        self.incoming_streams = {}
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

    def open_stream(self, request):
        request_id = request["request_id"]
        pending = _PendingStream()
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
        return _MultiplexedStream(self, request_id, pending)

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
                if message.get("operation") in ("iterate", "process"):
                    if self.stream_handler is not None:
                        request_id = message["request_id"]
                        stream = _IncomingStream()
                        with self.pending_lock:
                            self.incoming_streams[request_id] = stream
                        threading.Thread(
                            target=self._handle_stream,
                            args=(message, stream),
                            daemon=True,
                        ).start()
                    continue
                if message.get("operation", "").startswith("stream_"):
                    with self.pending_lock:
                        stream = self.incoming_streams.get(message.get("request_id"))
                    if stream is not None:
                        stream.deliver(message)
                    continue
                request_id = message.get("request_id")
                with self.pending_lock:
                    pending = self.pending.get(request_id)
                    if pending is not None:
                        pending.deliver(message)
        except BaseException as exc:
            with self.pending_lock:
                pending = list(self.pending.values())
                self.pending.clear()
                for response in pending:
                    response.fail(exc)
                incoming = list(self.incoming_streams.values())
                self.incoming_streams.clear()
                for stream in incoming:
                    stream.cancelled.set()
        finally:
            self.closed.set()

    def _handle_stream(self, request, stream):
        try:
            for response in self.stream_handler(request, stream):
                response["request_id"] = request["request_id"]
                self._send(response)
        except BaseException as exc:
            self._send(
                {
                    "request_id": request["request_id"],
                    "stream_event": "end",
                    "ok": False,
                    "error": _exception_data(exc),
                }
            )
        finally:
            with self.pending_lock:
                self.incoming_streams.pop(request["request_id"], None)

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


class _MultiplexedStream:
    def __init__(self, multiplexer, request_id, pending):
        self.multiplexer = multiplexer
        self.request_id = request_id
        self.pending = pending
        self.closed = False

    def receive(self, timeout=None):
        return self.pending.receive(timeout)

    def send(self, operation, **values):
        if self.closed:
            raise ValueError("stream is closed")
        self.multiplexer._send(
            {"operation": operation, "request_id": self.request_id, **values}
        )

    def close(self, cancel=False):
        if self.closed:
            return
        self.closed = True
        if cancel:
            self.multiplexer._send(
                {"operation": "stream_cancel", "request_id": self.request_id}
            )
        with self.multiplexer.pending_lock:
            self.multiplexer.pending.pop(self.request_id, None)


def _runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base:
        import tempfile

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


def _function_source(function):
    if "<locals>" in function.__qualname__:
        raise TypeError("nested functions and closures are not supported")
    source = textwrap.dedent(inspect.getsource(function))
    tree = ast.parse(source)
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(definitions) != 1 or definitions[0].name != function.__name__:
        raise TypeError("expected one top-level function definition")
    if definitions[0].decorator_list:
        raise TypeError("decorated functions are not supported")
    return source


def _global_names(function):
    # co_names mixes globals with attributes (``os.path`` adds both names),
    # while Python 3.14's getclosurevars() reports LOAD_ATTR names as unbound.
    # Inspect LOAD_GLOBAL directly so attributes are not mistaken for globals.
    global_names = set()
    code_objects = [function.__code__]
    while code_objects:
        code = code_objects.pop()
        global_names.update(
            instruction.argval
            for instruction in dis.get_instructions(code)
            if instruction.opname == "LOAD_GLOBAL"
        )
        code_objects.extend(value for value in code.co_consts if inspect.iscode(value))
    return global_names


def _function_spec(script):
    if isinstance(script, str):
        return {"kind": "exec", "source": script}
    if not inspect.isfunction(script):
        raise TypeError("script must be source text or a Python function")

    module_globals = script.__globals__
    sources = []
    visited = set()
    unresolved = set()

    def add_function(function):
        if function in visited:
            return
        visited.add(function)
        for name in sorted(_global_names(function)):
            if name not in module_globals and name in vars(builtins):
                continue
            value = module_globals.get(name)
            if (
                inspect.isfunction(value)
                and value.__globals__ is module_globals
                and value.__name__ == name
            ):
                add_function(value)
            else:
                unresolved.add(name)
        sources.append(_function_source(function))

    add_function(script)
    if unresolved:
        raise TypeError(
            "function depends on non-builtin globals: %s"
            % ", ".join(sorted(unresolved))
        )
    return {"kind": "call", "source": "\n".join(sources), "name": script.__name__}


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

    Pass a top-level ``def``. Other top-level functions from the same module
    are included recursively; other globals are not supported, so imports used
    by these functions should be inside them. Lambdas and closures are not
    supported::

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


class _RemoteIterator:
    def __init__(self, connection, timeout):
        self.connection = connection
        self.deadline = None if timeout is None else time.monotonic() + timeout + 10
        self.return_value = None
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.connection.poll(remaining):
                self.close()
                raise TimeoutError("ssh-sync daemon did not answer before the deadline")
        try:
            response = self.connection.recv()
        except EOFError:
            self.close(send_cancel=False)
            raise RuntimeError("ssh-sync daemon closed the stream") from None
        if response.get("stream_event") == "yield":
            return response.get("value")
        self.close(send_cancel=False)
        if response.get("timeout_error"):
            raise TimeoutError(response["timeout_error"])
        if response.get("daemon_error"):
            raise RuntimeError(response["daemon_error"])
        _write_captured(sys.stdout, response.get("stdout", b""))
        _write_captured(sys.stderr, response.get("stderr", b""))
        if response.get("timeout"):
            raise TimeoutError(response["error"]["message"])
        if not response.get("ok"):
            if response.get("cancelled"):
                raise StopIteration
            raise RemoteError(response["error"])
        self.return_value = response.get("value")
        raise StopIteration

    def close(self, send_cancel=True):
        if self.closed:
            return
        self.closed = True
        if send_cancel:
            try:
                self.connection.send({"operation": "stream_cancel"})
            except OSError:
                pass
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()


def iter_remote(host, function, *args, call_timeout=None, **kwargs):
    """Iterate over values yielded by a remote generator function.

    The function follows the same source and argument restrictions as
    :func:`call_remote`, but must be a generator function. Closing the returned
    iterator asks the remote worker to stop.
    """
    if not inspect.isgeneratorfunction(function):
        raise TypeError("function must be a generator function")
    timeout = _resolve_timeout(call_timeout)
    spec = _function_spec(function)
    _encode_value(args)
    _encode_value(kwargs)
    agent_source = _current_source()
    request = {
        "operation": "iterate",
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
    except BaseException:
        connection.close()
        raise
    return _RemoteIterator(connection, timeout)


class ProcessEvent:
    """A chunk read from a remote process's stdout or stderr."""

    __slots__ = ("stream", "data")

    def __init__(self, stream, data):
        self.stream = stream
        self.data = data

    def __repr__(self):
        return "ProcessEvent(stream=%r, data=%r)" % (self.stream, self.data)


class RemoteProcess:
    """A bidirectional byte stream connected to a remote subprocess."""

    def __init__(self, connection, timeout):
        self.connection = connection
        self.deadline = None if timeout is None else time.monotonic() + timeout + 10
        self.returncode = None
        self.stdin_closed = False
        self.closed = False
        self.write_lock = threading.Lock()

    def send(self, data):
        if self.closed:
            raise ValueError("process is closed")
        if self.stdin_closed:
            raise ValueError("stdin is closed")
        if isinstance(data, memoryview):
            data = data.tobytes()
        elif isinstance(data, bytearray):
            data = bytes(data)
        if not isinstance(data, bytes):
            raise TypeError("process input must be bytes-like")
        with self.write_lock:
            for offset in range(0, len(data), _STREAM_CHUNK_SIZE):
                self.connection.send(
                    {
                        "operation": "stream_input",
                        "data": data[offset : offset + _STREAM_CHUNK_SIZE],
                    }
                )

    def close_stdin(self):
        with self.write_lock:
            if self.stdin_closed or self.closed:
                return
            self.connection.send({"operation": "stream_eof"})
            self.stdin_closed = True

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed:
            raise StopIteration
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.connection.poll(remaining):
                self.cancel()
                raise TimeoutError("ssh-sync daemon did not answer before the deadline")
        try:
            response = self.connection.recv()
        except EOFError:
            self._close(send_cancel=False)
            raise RuntimeError("ssh-sync daemon closed the stream") from None
        stream = response.get("stream_event")
        if stream in ("stdout", "stderr"):
            return ProcessEvent(stream, response["data"])
        self._close(send_cancel=False)
        if response.get("timeout_error"):
            raise TimeoutError(response["timeout_error"])
        if response.get("daemon_error"):
            raise RuntimeError(response["daemon_error"])
        if response.get("timeout"):
            raise TimeoutError(response["error"]["message"])
        if not response.get("ok"):
            if response.get("cancelled"):
                raise StopIteration
            raise RemoteError(response["error"])
        self.returncode = response["returncode"]
        raise StopIteration

    def wait(self):
        for _event in self:
            pass
        return self.returncode

    def communicate(self, data=b""):
        import io

        stdout = io.BytesIO()
        stderr = io.BytesIO()
        errors = []

        def write_input():
            try:
                self.send(data)
                self.close_stdin()
            except BaseException as error:
                errors.append(error)
                self.cancel()

        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()
        for event in self:
            (stdout if event.stream == "stdout" else stderr).write(event.data)
        writer.join()
        if errors:
            raise errors[0]
        return stdout.getvalue(), stderr.getvalue()

    def forward_stdio(self, stdin, stdout, stderr):
        import selectors

        selector = selectors.DefaultSelector()
        selector.register(self.connection.fileno(), selectors.EVENT_READ, "remote")
        selector.register(stdin.fileno(), selectors.EVENT_READ, "stdin")
        try:
            while not self.closed:
                for key, _events in selector.select():
                    if key.data == "stdin":
                        data = os.read(stdin.fileno(), _STREAM_CHUNK_SIZE)
                        if data:
                            self.send(data)
                        else:
                            selector.unregister(stdin.fileno())
                            self.close_stdin()
                        continue
                    try:
                        event = next(self)
                    except StopIteration:
                        break
                    output = stdout if event.stream == "stdout" else stderr
                    output.write(event.data)
                    output.flush()
        finally:
            selector.close()
        return self.returncode

    def cancel(self):
        self._close(send_cancel=True)

    def _close(self, send_cancel):
        if self.closed:
            return
        self.closed = True
        if send_cancel:
            try:
                self.connection.send({"operation": "stream_cancel"})
            except OSError:
                pass
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_value, _traceback):
        if exc_type is None:
            if not self.stdin_closed:
                self.close_stdin()
            self.wait()
        else:
            self.cancel()


def open_process(host, argv, *, cwd=None, env=None, call_timeout=None):
    """Start a remote process with independently streamed stdin and output."""
    if (
        isinstance(argv, (str, bytes))
        or not argv
        or not all(isinstance(arg, str) for arg in argv)
    ):
        raise TypeError("argv must be a non-empty sequence of strings")
    if cwd is not None and not isinstance(cwd, str):
        raise TypeError("cwd must be a string or None")
    if env is not None and (
        not isinstance(env, dict)
        or not all(isinstance(key, str) and isinstance(value, str) for key, value in env.items())
    ):
        raise TypeError("env must be a mapping of strings or None")

    timeout = _resolve_timeout(call_timeout)
    agent_source = _current_source()
    request = {
        "operation": "process",
        "host": host,
        "request_id": uuid.uuid4().hex,
        "argv": list(argv),
        "cwd": cwd,
        "env": env,
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
    except BaseException:
        connection.close()
        raise
    return RemoteProcess(connection, timeout)


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
        import pty
        import signal
        import struct
        import tty

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
                lambda request, control: _handle_remote_stream(
                    request,
                    [sys.executable, os.path.abspath(__file__), "_remote_iterator"],
                    control,
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

    def iterate(self, request, worker_timeout=None):
        return self.multiplexer.open_stream(
            _iteration_wire_request(request, worker_timeout)
        )

    def open_process(self, request, worker_timeout=None):
        return self.multiplexer.open_stream(
            _process_wire_request(request, worker_timeout)
        )

    def close(self):
        import signal

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


def _iteration_wire_request(request, worker_timeout=None):
    return {
        "operation": "iterate",
        "request_id": request["request_id"],
        "function": request["function"],
        "args": request["args"],
        "kwargs": request["kwargs"],
        "timeout": worker_timeout,
        "max_frame": request["max_frame"],
    }


def _process_wire_request(request, worker_timeout=None):
    return {
        "operation": "process",
        "request_id": request["request_id"],
        "argv": request["argv"],
        "cwd": request["cwd"],
        "env": request["env"],
        "timeout": worker_timeout,
    }


def _forward_stream(connection, stream):
    try:
        while True:
            handled_input = connection.poll()
            if handled_input:
                command = connection.recv()
                if command.get("operation") == "stream_cancel":
                    stream.close(cancel=True)
                    return
                if command.get("operation") in ("stream_input", "stream_eof"):
                    values = {key: value for key, value in command.items() if key != "operation"}
                    stream.send(command["operation"], **values)
            response = stream.receive(0 if handled_input else 0.05)
            if response is None:
                continue
            connection.send(response)
            if response.get("stream_event") == "end":
                stream.close()
                return
    except (EOFError, OSError):
        stream.close(cancel=True)


def _forward_stream_in_background(connection, stream):
    def run():
        import traceback

        try:
            _forward_stream(connection, stream)
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

    threading.Thread(target=run, daemon=True).start()


def _exception_data(exc):
    import traceback

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


def _remote_iterator_worker(event_fd):
    request = _json_loads(sys.stdin.buffer.read())
    try:
        namespace = {"__name__": "__ssh_sync_call__"}
        function = request["function"]
        exec(compile(function["source"], "<ssh-sync-call>", "exec"), namespace, namespace)
        iterator = namespace[function["name"]](*request["args"], **request["kwargs"])
        while True:
            try:
                value = next(iterator)
            except StopIteration as stopped:
                _send_frame(
                    event_fd,
                    {
                        "stream_event": "end",
                        "ok": True,
                        "value": stopped.value,
                    },
                    request["max_frame"],
                )
                return
            _send_frame(
                event_fd,
                {"stream_event": "yield", "value": value},
                request["max_frame"],
            )
    except BaseException as exc:
        _send_frame(
            event_fd,
            {
                "stream_event": "end",
                "ok": False,
                "error": _exception_data(exc),
            },
            request["max_frame"],
        )


def _terminate_process(process, process_group=False):
    import signal

    if process.poll() is not None:
        return
    try:
        if process_group:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        if process_group:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def _run_iterator(request, worker_argv, control):
    import tempfile

    deadline = (
        None
        if request.get("timeout") is None
        else time.monotonic() + request["timeout"]
    )
    with tempfile.TemporaryDirectory(prefix="ssh-sync-") as temp_dir:
        stdout_path = os.path.join(temp_dir, "stdout")
        stderr_path = os.path.join(temp_dir, "stderr")
        read_fd, write_fd = os.pipe()
        try:
            with open(stdout_path, "wb") as stdout, open(stderr_path, "wb") as stderr:
                process = subprocess.Popen(
                    worker_argv + [str(write_fd)],
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    pass_fds=(write_fd,),
                )
            os.close(write_fd)
            write_fd = None
            try:
                process.stdin.write(_json_dumps(request))
                process.stdin.close()
                reader = _FrameReader(read_fd, max_frame=request["max_frame"])
                while True:
                    if control.cancelled.is_set():
                        _terminate_process(process)
                        yield {
                            "stream_event": "end",
                            "ok": False,
                            "cancelled": True,
                        }
                        return
                    poll_deadline = time.monotonic() + 0.1
                    if deadline is not None:
                        poll_deadline = min(poll_deadline, deadline)
                    try:
                        response = reader.recv(poll_deadline)
                    except TimeoutError:
                        if deadline is None or time.monotonic() < deadline:
                            continue
                        _terminate_process(process)
                        yield {
                            "stream_event": "end",
                            "ok": False,
                            "timeout": True,
                            "error": {
                                "module": "builtins",
                                "qualname": "TimeoutError",
                                "message": "remote iteration timed out",
                                "repr": "TimeoutError('remote iteration timed out')",
                                "args": ("remote iteration timed out",),
                                "traceback": "",
                            },
                        }
                        return
                    if response.get("stream_event") == "end":
                        process.wait()
                        with open(stdout_path, "rb") as stdout:
                            response["stdout"] = stdout.read()
                        with open(stderr_path, "rb") as stderr:
                            response["stderr"] = stderr.read()
                        yield response
                        return
                    yield response
            finally:
                _terminate_process(process)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)


def _run_process(request, control):
    import queue

    child_environment = os.environ.copy()
    if request.get("env") is not None:
        child_environment.update(request["env"])
    process = subprocess.Popen(
        request["argv"],
        cwd=request.get("cwd"),
        env=child_environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    events = queue.Queue(maxsize=16)
    deadline = (
        None
        if request.get("timeout") is None
        else time.monotonic() + request["timeout"]
    )

    def read_output(name, stream):
        try:
            while data := os.read(stream.fileno(), _STREAM_CHUNK_SIZE):
                events.put({"stream_event": name, "data": data})
        except BaseException as error:
            events.put(error)
        finally:
            events.put({"stream_event": name + "_eof"})

    def write_input():
        try:
            while not control.cancelled.is_set():
                message = control.receive(0.1)
                if message is None:
                    if process.poll() is not None:
                        return
                    continue
                if message["operation"] == "stream_eof":
                    process.stdin.close()
                    return
                process.stdin.write(message["data"])
                process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    readers = [
        threading.Thread(target=read_output, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_output, args=("stderr", process.stderr), daemon=True),
    ]
    writer = threading.Thread(target=write_input, daemon=True)
    for thread in [*readers, writer]:
        thread.start()

    closed_streams = set()
    try:
        while len(closed_streams) < 2 or process.poll() is None:
            if control.cancelled.is_set():
                _terminate_process(process, process_group=True)
                yield {"stream_event": "end", "ok": False, "cancelled": True}
                return
            if deadline is not None and time.monotonic() >= deadline:
                _terminate_process(process, process_group=True)
                yield {
                    "stream_event": "end",
                    "ok": False,
                    "timeout": True,
                    "error": {
                        "module": "builtins",
                        "qualname": "TimeoutError",
                        "message": "remote process timed out",
                        "repr": "TimeoutError('remote process timed out')",
                        "args": ("remote process timed out",),
                        "traceback": "",
                    },
                }
                return
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(event, BaseException):
                raise event
            if event["stream_event"].endswith("_eof"):
                closed_streams.add(event["stream_event"])
            else:
                yield event
        returncode = process.wait()
        yield {"stream_event": "end", "ok": True, "returncode": returncode}
    finally:
        _terminate_process(process, process_group=True)
        try:
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        for stream in (process.stdout, process.stderr):
            stream.close()
        for thread in [*readers, writer]:
            thread.join(timeout=1)


def _handle_remote_stream(request, iterator_worker_argv, control):
    if request["operation"] == "iterate":
        return _run_iterator(request, iterator_worker_argv, control)
    if request["operation"] == "process":
        return _run_process(request, control)
    raise ValueError("unsupported stream operation")


def _run_worker(request, worker_argv):
    import tempfile

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


def _install_uploaded_source(source):
    import site
    import tempfile

    source_bytes = source.encode("utf-8")
    site_packages = site.getusersitepackages()
    os.makedirs(site_packages, exist_ok=True)
    destination = os.path.join(site_packages, "ssh_sync.py")
    try:
        with open(destination, "rb") as installed:
            current = installed.read()
    except OSError:
        current = None
    if current != source_bytes:
        fd, temporary = tempfile.mkstemp(
            prefix=".ssh_sync.py.", dir=site_packages
        )
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(source_bytes)
            os.chmod(temporary, 0o755)
            os.replace(temporary, destination)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
    os.chmod(destination, 0o755)

    bin_dir = os.path.expanduser("~/.local/bin")
    os.makedirs(bin_dir, exist_ok=True)
    command = os.path.join(bin_dir, "ssh_sync.py")
    if os.path.islink(command) and os.path.realpath(command) == destination:
        return
    temporary = os.path.join(bin_dir, ".ssh_sync.py.%s" % uuid.uuid4().hex)
    try:
        os.symlink(destination, temporary)
        os.replace(temporary, command)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


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
    import traceback

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
                if operation not in ("call", "iterate", "process") or request.get(
                    "host"
                ) != peer_name:
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
                if operation == "iterate":
                    stream = multiplexer.open_stream(
                        _iteration_wire_request(request, worker_timeout)
                    )
                    _forward_stream_in_background(connection, stream)
                    connection = None
                elif operation == "process":
                    stream = multiplexer.open_stream(
                        _process_wire_request(request, worker_timeout)
                    )
                    _forward_stream_in_background(connection, stream)
                    connection = None
                else:
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
                if connection is not None:
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
    try:
        _install_uploaded_source(source)
    except Exception as exc:
        _send_frame(
            1,
            {
                "operation": "hello",
                "agent_digest": digest,
                "error": "could not install ssh-sync: %s" % exc,
            },
            max_frame,
        )
        return
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

    def handle_stream(request, control):
        return _handle_remote_stream(
            request,
            python_argv + ["-c", source, "_remote_iterator"],
            control,
        )

    multiplexer = _Multiplexer(reader, 1, max_frame, handle_call, handle_stream)
    _serve_peer(
        server,
        socket_identity,
        peer_name,
        digest,
        multiplexer,
    )


def _run_daemon(host, code_hash):
    import signal
    import traceback

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
                if operation not in ("call", "iterate", "process") or request.get(
                    "host"
                ) != host:
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
                    if operation == "iterate":
                        stream = session.iterate(request, worker_timeout)
                        _forward_stream_in_background(connection, stream)
                        connection = None
                        response = None
                    elif operation == "process":
                        stream = session.open_process(request, worker_timeout)
                        _forward_stream_in_background(connection, stream)
                        connection = None
                        response = None
                    else:
                        response = session.call(
                            request, worker_timeout, response_deadline
                        )
                except Exception:
                    # The stream position is unknown after a timeout or a
                    # oversized frame, so the session cannot be reused.
                    session.close()
                    session = None
                    raise
                if response is not None:
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
                if connection is not None:
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


def list_hosts():
    """Return the hostnames of running local ssh-sync endpoints."""
    hosts = []
    for address in _daemon_sockets():
        info = _daemon_command(address, "info")
        if info is not None and info.get("ok"):
            hosts.append(info["host"])
    return sorted(hosts)


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
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    execute = commands.add_parser(
        "exec",
        help="execute Python source or a shell command remotely",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Python source may contain ordinary statements, imports, and print calls.
stdout and stderr are forwarded. A bare expression is not printed; assign a
value to `result` to return and print it locally. Supported result values are
None, bool, finite numbers, str, bytes, and containers of those types.""",
    )
    execute.add_argument(
        "--host",
        help="remote host (default: first host reported by ssh_sync list)",
    )
    execute.add_argument(
        "--type",
        choices=("sh", "py"),
        dest="source_type",
        help="source type (default: shell for one token or invalid Python)",
    )
    execute.add_argument("source", help="Python source or shell command")
    _add_call_options(execute)

    commands.add_parser("list", help="show running daemons")
    stop = commands.add_parser("stop", help="stop daemons")
    stop.add_argument("hosts", nargs="*")
    install = commands.add_parser(
        "install", help="symlink this module into user site-packages and ~/.local/bin"
    )
    install.add_argument(
        "-f", "--force", action="store_true", help="replace existing installations"
    )
    return parser


def _exec_main(args):
    if args.et_command is not None:
        os.environ["SSH_SYNC_ET_COMMAND"] = args.et_command
    if args.remote_python is not None:
        os.environ["SSH_SYNC_REMOTE_PYTHON"] = args.remote_python
    if args.max_frame is not None:
        os.environ["SSH_SYNC_MAX_FRAME"] = str(args.max_frame)
    host = args.host
    if host is None:
        hosts = list_hosts()
        if not hosts:
            raise RuntimeError("no running ssh-sync host; pass --host")
        host = hosts[0]
    source_type = args.source_type
    if source_type is None:
        if not any(character.isspace() for character in args.source):
            source_type = "sh"
        else:
            try:
                ast.parse(args.source)
            except SyntaxError:
                source_type = "sh"
            else:
                source_type = "py"
    if source_type == "sh":
        with open_process(
            host, ["sh", "-c", args.source], call_timeout=args.timeout
        ) as process:
            return process.forward_stdio(
                sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer
            )

    result = call_remote(host, args.source, call_timeout=args.timeout)
    if result is not None:
        print(repr(result))
    return 0


def _install_main(force=False):
    import site

    source = os.path.realpath(__file__)
    directories = [site.getusersitepackages(), os.path.expanduser("~/.local/bin")]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        destination = os.path.join(directory, "ssh_sync.py")
        if os.path.lexists(destination):
            if os.path.islink(destination) and os.path.realpath(destination) == source:
                print(destination + " already points to " + source)
                continue
            if not force:
                raise FileExistsError(destination + " already exists")
            os.unlink(destination)
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
    elif command == "_remote_iterator" and len(sys.argv) >= 3:
        _remote_iterator_worker(int(sys.argv[2]))
    else:
        args = _command_parser().parse_args()
        if args.command == "exec":
            return _exec_main(args)
        elif args.command == "list":
            _control_main("list", [])
        elif args.command == "stop":
            _control_main("stop", args.hosts)
        else:
            _install_main(args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
