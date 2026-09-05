import os
import io
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

LIB_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB_DIR))

import ssh_sync  # noqa: E402


class ShortenLinuxArgvTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux /proc")
    def test_replaces_process_arguments(self):
        source = (
            "import ssh_sync;"
            "ssh_sync._shorten_linux_argv('ssh-sync test');"
            "print(open('/proc/self/cmdline', 'rb').read().rstrip(b'\\0'))"
        )
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(LIB_DIR)

        output = subprocess.check_output(
            [sys.executable, "-c", source], env=environment, text=True
        )

        self.assertEqual(output.strip(), "b'ssh-sync test'")

    def test_worker_title_describes_function_and_peer(self):
        request = {
            "function": {"kind": "call", "name": "collect_status"},
            "peer_name": "laptop",
        }
        with mock.patch.object(ssh_sync, "_shorten_linux_argv") as shorten:
            ssh_sync._shorten_worker_argv(request, "call")

        shorten.assert_called_once_with("ssh-sync call collect_status from laptop")

    def test_worker_title_describes_source(self):
        request = {"function": {"kind": "exec"}}
        with mock.patch.object(ssh_sync, "_shorten_linux_argv") as shorten:
            ssh_sync._shorten_worker_argv(request, "call")

        shorten.assert_called_once_with("ssh-sync call source")


class Control:
    def __init__(self):
        self.cancelled = threading.Event()


class ListHostsTest(unittest.TestCase):
    def test_returns_sorted_hosts_and_skips_stale_sockets(self):
        infos = {
            "first.sock": {"ok": True, "host": "zebra"},
            "second.sock": None,
            "third.sock": {"ok": False},
            "fourth.sock": {"ok": True, "host": "alpha"},
        }

        sockets = mock.patch.object(ssh_sync, "_daemon_sockets", return_value=infos)
        command = mock.patch.object(
            ssh_sync,
            "_daemon_command",
            side_effect=lambda address, operation: infos[address],
        )
        with sockets, command as daemon_command:
            self.assertEqual(ssh_sync.list_hosts(), ["alpha", "zebra"])

        self.assertEqual(
            daemon_command.call_args_list,
            [mock.call(address, "info") for address in infos],
        )


class ExecCommandTest(unittest.TestCase):
    def test_uses_first_running_host_by_default(self):
        args = ssh_sync._command_parser().parse_args(["exec", "result = 42"])
        with mock.patch.object(
            ssh_sync, "list_hosts", return_value=["first", "second"]
        ), mock.patch.object(ssh_sync, "call_remote", return_value=None) as call:
            ssh_sync._exec_main(args)

        call.assert_called_once_with("first", "result = 42", call_timeout=None)

    def test_treats_simple_command_name_as_shell(self):
        args = ssh_sync._command_parser().parse_args(
            ["exec", "--host", "remote", "hostname"]
        )
        process = mock.MagicMock()
        process.forward_stdio.return_value = 7
        opened = mock.MagicMock()
        opened.__enter__.return_value = process
        with mock.patch.object(
            ssh_sync, "open_process", return_value=opened
        ) as open_process:
            returncode = ssh_sync._exec_main(args)

        open_process.assert_called_once_with(
            "remote", ["sh", "-c", "hostname"], call_timeout=None
        )
        process.forward_stdio.assert_called_once_with(
            sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer
        )
        self.assertEqual(returncode, 7)

    def test_parses_other_source_without_whitespace_as_python(self):
        args = ssh_sync._command_parser().parse_args(
            ["exec", "--host", "remote", "foo-bar"]
        )
        with mock.patch.object(ssh_sync, "call_remote", return_value=None) as call:
            ssh_sync._exec_main(args)

        call.assert_called_once_with("remote", "foo-bar", call_timeout=None)


def values(count):
    import sys

    print("stdout text")
    print("stderr text", file=sys.stderr)
    for value in range(count):
        yield {"value": value, "bytes": bytes([value])}
    return "finished"


def slow_values():
    import time

    yield "first"
    time.sleep(60)


class IteratorWorkerTest(unittest.TestCase):
    def request(self, function, *args, timeout=5):
        return {
            "request_id": "test",
            "function": ssh_sync._function_spec(function),
            "args": args,
            "kwargs": {},
            "timeout": timeout,
            "max_frame": ssh_sync._DEFAULT_MAX_FRAME,
        }

    def run_iterator(self, request, control=None):
        if control is None:
            control = Control()
        worker = [sys.executable, ssh_sync.__file__, "_remote_iterator"]
        return ssh_sync._run_iterator(request, worker, control)

    def test_yields_values_and_captures_output(self):
        responses = list(self.run_iterator(self.request(values, 3)))

        self.assertEqual(
            [response["value"] for response in responses[:-1]],
            [
                {"value": 0, "bytes": b"\0"},
                {"value": 1, "bytes": b"\1"},
                {"value": 2, "bytes": b"\2"},
            ],
        )
        self.assertEqual(responses[-1]["stream_event"], "end")
        self.assertTrue(responses[-1]["ok"])
        self.assertEqual(responses[-1]["value"], "finished")
        self.assertEqual(responses[-1]["stdout"], b"stdout text\n")
        self.assertEqual(responses[-1]["stderr"], b"stderr text\n")

    def test_cancel_terminates_worker(self):
        control = Control()
        responses = self.run_iterator(self.request(slow_values), control)

        self.assertEqual(next(responses)["value"], "first")
        control.cancelled.set()
        final = next(responses)
        self.assertEqual(final["stream_event"], "end")
        self.assertTrue(final["cancelled"])
        with self.assertRaises(StopIteration):
            next(responses)


class ProcessWorkerTest(unittest.TestCase):
    def test_streams_stdin_stdout_stderr_and_exit_status(self):
        control = ssh_sync._IncomingStream()
        request = {
            "argv": [
                sys.executable,
                "-c",
                "import sys; data = sys.stdin.buffer.read(); "
                "sys.stdout.buffer.write(data.upper()); "
                "sys.stderr.buffer.write(b'notice')",
            ],
            "cwd": None,
            "env": None,
            "timeout": 5,
        }
        control.deliver({"operation": "stream_input", "data": b"hello"})
        control.deliver({"operation": "stream_eof"})

        responses = list(ssh_sync._run_process(request, control))

        stdout = b"".join(
            event["data"] for event in responses if event["stream_event"] == "stdout"
        )
        stderr = b"".join(
            event["data"] for event in responses if event["stream_event"] == "stderr"
        )
        self.assertEqual(stdout, b"HELLO")
        self.assertEqual(stderr, b"notice")
        self.assertEqual(
            responses[-1], {"stream_event": "end", "ok": True, "returncode": 0}
        )

    def test_cancel_terminates_process(self):
        control = ssh_sync._IncomingStream()
        request = {
            "argv": [
                sys.executable,
                "-u",
                "-c",
                "import os,time; print(os.getpid()); time.sleep(60)",
            ],
            "cwd": None,
            "env": None,
            "timeout": 5,
        }
        responses = ssh_sync._run_process(request, control)
        pid = int(next(responses)["data"])

        control.cancelled.set()
        final = next(responses)

        self.assertTrue(final["cancelled"])
        with self.assertRaises(StopIteration):
            next(responses)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_timeout_terminates_process(self):
        control = ssh_sync._IncomingStream()
        request = {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "cwd": None,
            "env": None,
            "timeout": 0.05,
        }

        responses = list(ssh_sync._run_process(request, control))

        self.assertTrue(responses[-1]["timeout"])


class ServerConcurrencyTest(unittest.TestCase):
    class Stream:
        def __init__(self):
            self.closed = threading.Event()

        def receive(self, timeout=None):
            self.closed.wait(timeout)
            return None

        def send(self, _operation, **_values):
            pass

        def close(self, cancel=False):
            self.closed.set()

    class Multiplexer:
        def __init__(self):
            self.closed = threading.Event()
            self.opened = threading.Event()
            self.stream = ServerConcurrencyTest.Stream()

        def open_stream(self, _request):
            self.opened.set()
            return self.stream

    def test_peer_accepts_another_client_while_stream_is_open(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            with mock.patch.object(ssh_sync, "_runtime_dir", return_value=runtime_dir):
                peer_name = "test-peer"
                server, socket_identity = ssh_sync._bind_server(
                    ssh_sync._socket_path(peer_name)
                )
                multiplexer = self.Multiplexer()
                server_thread = threading.Thread(
                    target=ssh_sync._serve_peer,
                    args=(server, socket_identity, peer_name, "test-hash", multiplexer),
                    daemon=True,
                )
                server_thread.start()

                stream = ssh_sync.Client(
                    ssh_sync._socket_path(peer_name), family="AF_UNIX"
                )
                stream.send(
                    {
                        "operation": "process",
                        "host": peer_name,
                        "request_id": "stream",
                        "argv": ["true"],
                        "cwd": None,
                        "env": None,
                        "timeout": None,
                    }
                )
                self.assertTrue(multiplexer.opened.wait(1))

                control = ssh_sync.Client(
                    ssh_sync._socket_path(peer_name), family="AF_UNIX"
                )
                control.send({"operation": "info"})
                self.assertTrue(control.poll(1))
                self.assertTrue(control.recv()["ok"])
                control.close()

                stream.send({"operation": "stream_cancel"})
                stream.close()
                self.assertTrue(multiplexer.stream.closed.wait(1))

                control = ssh_sync.Client(
                    ssh_sync._socket_path(peer_name), family="AF_UNIX"
                )
                control.send({"operation": "stop"})
                self.assertTrue(control.recv()["ok"])
                control.close()
                server_thread.join(1)
                self.assertFalse(server_thread.is_alive())


class RemoteProcessTest(unittest.TestCase):
    class Connection:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.sent = []
            self.closed = False

        def send(self, value):
            self.sent.append(value)

        def poll(self, _timeout=None):
            return True

        def recv(self):
            return next(self.responses)

        def close(self):
            self.closed = True

    def test_chunks_input_and_iterates_output(self):
        connection = self.Connection(
            [
                {"stream_event": "stdout", "data": b"output"},
                {"stream_event": "end", "ok": True, "returncode": 7},
            ]
        )
        process = ssh_sync.RemoteProcess(connection, timeout=None)

        process.send(b"x" * (ssh_sync._STREAM_CHUNK_SIZE + 1))
        process.close_stdin()
        events = list(process)

        self.assertEqual(
            [(event.stream, event.data) for event in events], [("stdout", b"output")]
        )
        self.assertEqual(process.returncode, 7)
        self.assertEqual(
            [len(message["data"]) for message in connection.sent[:-1]],
            [ssh_sync._STREAM_CHUNK_SIZE, 1],
        )
        self.assertEqual(connection.sent[-1], {"operation": "stream_eof"})
        self.assertTrue(connection.closed)

    def test_communicate(self):
        connection = self.Connection(
            [
                {"stream_event": "stderr", "data": b"warning"},
                {"stream_event": "stdout", "data": b"result"},
                {"stream_event": "end", "ok": True, "returncode": 0},
            ]
        )
        process = ssh_sync.RemoteProcess(connection, timeout=None)

        stdout, stderr = process.communicate(b"input")

        self.assertEqual(stdout, b"result")
        self.assertEqual(stderr, b"warning")
        self.assertEqual(process.returncode, 0)
        self.assertEqual(
            connection.sent,
            [
                {"operation": "stream_input", "data": b"input"},
                {"operation": "stream_eof"},
            ],
        )

    def test_forward_stdio_closes_unpollable_stdin(self):
        connection = self.Connection(
            [
                {"stream_event": "stdout", "data": b"result"},
                {"stream_event": "end", "ok": True, "returncode": 0},
            ]
        )
        connection.fileno = mock.Mock(return_value=10)
        process = ssh_sync.RemoteProcess(connection, timeout=None)
        stdin = mock.Mock()
        stdin.fileno.side_effect = PermissionError(1, "Operation not permitted")
        selector = mock.MagicMock()
        selector.select.return_value = [(mock.Mock(data="remote"), None)]

        with mock.patch("selectors.DefaultSelector", return_value=selector):
            stdout = io.BytesIO()
            returncode = process.forward_stdio(stdin, stdout, io.BytesIO())

        self.assertEqual(returncode, 0)
        self.assertEqual(stdout.getvalue(), b"result")
        self.assertEqual(connection.sent, [{"operation": "stream_eof"}])


if __name__ == "__main__":
    unittest.main()
