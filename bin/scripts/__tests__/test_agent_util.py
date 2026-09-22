import importlib.machinery
import importlib.util
import io
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "agent-util"
LOADER = importlib.machinery.SourceFileLoader("agent_util", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
agent_util = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(agent_util)


def agent(session_id, *, working=False, suspended=False):
    return {
        "session_id": session_id,
        "working": working,
        "suspended": suspended,
    }


class FakeAppServerClient:
    threads_by_socket = {}
    items_by_socket = {}
    turns_by_socket = {}
    notifications_by_socket = {}
    requests = []

    def __init__(self, socket_path):
        self.socket_path = socket_path

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def set_timeout(self, _timeout):
        pass

    def request(self, method, params):
        self.requests.append((self.socket_path, method, params))
        if method == "thread/list":
            return {
                "data": self.threads_by_socket[self.socket_path],
                "nextCursor": None,
            }
        if method == "thread/resume":
            return {"thread": {"id": params["threadId"]}}
        if method == "thread/items/list":
            return self.items_by_socket[self.socket_path].pop(0)
        if method == "thread/turns/list":
            return self.turns_by_socket[self.socket_path].pop(0)
        if method == "turn/start":
            return {"turn": {"id": "turn-id"}}
        raise AssertionError(method)

    def next_notification(self):
        return self.notifications_by_socket[self.socket_path].pop(0)


class StateTest(unittest.TestCase):
    def test_suspended_takes_precedence_over_working(self):
        self.assertEqual(
            agent_util.state(agent("one", working=True, suspended=True)),
            "suspended",
        )

    def test_non_working_session_is_idle(self):
        self.assertEqual(agent_util.state(agent("one")), "idle")


class WebSocketFrameTest(unittest.TestCase):
    def setUp(self):
        self.client_socket, self.server_socket = socket.socketpair()
        self.addCleanup(self.client_socket.close)
        self.addCleanup(self.server_socket.close)
        self.client = agent_util.AppServerClient.__new__(agent_util.AppServerClient)
        self.client.socket = self.client_socket
        self.client.buffer = b""

    def test_writes_masked_text_frame(self):
        self.client._write_frame(0x1, b"hello")

        frame = self.server_socket.recv(1024)
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 0x80 | 5)
        mask = frame[2:6]
        payload = bytes(
            value ^ mask[index % 4] for index, value in enumerate(frame[6:])
        )
        self.assertEqual(payload, b"hello")

    def test_reads_unmasked_text_frame(self):
        payload = b"x" * 130
        self.server_socket.sendall(
            b"\x81\x7e" + len(payload).to_bytes(2, "big") + payload
        )

        self.assertEqual(self.client._read_text(), payload.decode())


class ResolveSessionTest(unittest.TestCase):
    def test_accepts_unique_prefix(self):
        expected = agent("abcdef")
        self.assertIs(agent_util.resolve_session([expected], "abc"), expected)

    def test_prefers_exact_match(self):
        expected = agent("abc")
        self.assertIs(
            agent_util.resolve_session([expected, agent("abcdef")], "abc"),
            expected,
        )

    def test_rejects_ambiguous_prefix(self):
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            agent_util.resolve_session([agent("abc1"), agent("abc2")], "abc")

    def test_rejects_unknown_session(self):
        with self.assertRaisesRegex(ValueError, "no current session"):
            agent_util.resolve_session([], "abc")


class WaitForSessionTest(unittest.TestCase):
    def test_waits_until_session_is_idle(self):
        snapshots = iter(
            [
                [agent("abcdef", working=True)],
                [agent("abcdef", working=True)],
                [agent("abcdef")],
            ]
        )
        sleeps = []

        session_id, result = agent_util.wait_for_session(
            "abc", 0.25, lambda: next(snapshots), sleeps.append
        )

        self.assertEqual(session_id, "abcdef")
        self.assertEqual(agent_util.state(result), "idle")
        self.assertEqual(sleeps, [0.25, 0.25])

    def test_returns_when_session_exits(self):
        snapshots = iter([[agent("abcdef", working=True)], []])

        session_id, result = agent_util.wait_for_session(
            "abcdef", 1, lambda: next(snapshots), lambda _interval: None
        )

        self.assertEqual(session_id, "abcdef")
        self.assertIsNone(result)

    def test_returns_immediately_if_session_is_already_idle(self):
        calls = 0

        def list_agents():
            nonlocal calls
            calls += 1
            return [agent("abcdef")]

        _session_id, result = agent_util.wait_for_session(
            "abcdef", 1, list_agents, lambda _interval: self.fail("slept")
        )

        self.assertEqual(agent_util.state(result), "idle")
        self.assertEqual(calls, 1)


class SendMessageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.socket_dir = Path(self.tmp.name)
        self.first_socket = self.socket_dir / "1.sock"
        self.second_socket = self.socket_dir / "2.sock"
        self.first_socket.touch()
        self.second_socket.touch()
        FakeAppServerClient.requests = []
        FakeAppServerClient.items_by_socket = {}
        FakeAppServerClient.turns_by_socket = {}
        FakeAppServerClient.notifications_by_socket = {}
        FakeAppServerClient.threads_by_socket = {
            self.first_socket: [
                {"id": "old-session", "status": {"type": "notLoaded"}},
                {"id": "abcdef-123", "status": {"type": "idle"}},
            ],
            self.second_socket: [
                {"id": "second-session", "status": {"type": "active"}},
            ],
        }

    def test_sends_turn_to_matching_loaded_session(self):
        session_id, summary = agent_util.send_message(
            "abcdef",
            "hello there",
            socket_dir=self.socket_dir,
            client_factory=FakeAppServerClient,
        )

        self.assertEqual(session_id, "abcdef-123")
        self.assertIsNone(summary)
        self.assertIn(
            (
                self.first_socket,
                "turn/start",
                {
                    "threadId": "abcdef-123",
                    "input": [{"type": "text", "text": "hello there"}],
                },
            ),
            FakeAppServerClient.requests,
        )

    def test_does_not_match_session_not_loaded_by_app_server(self):
        with self.assertRaisesRegex(ValueError, "no current session"):
            agent_util.send_message(
                "old-session",
                "hello",
                socket_dir=self.socket_dir,
                client_factory=FakeAppServerClient,
            )

    def test_waits_for_matching_turn_and_returns_final_message(self):
        FakeAppServerClient.notifications_by_socket[self.first_socket] = [
            {
                "method": "item/completed",
                "params": {
                    "threadId": "abcdef-123",
                    "turnId": "turn-id",
                    "item": {
                        "type": "agentMessage",
                        "text": "still working",
                        "phase": "commentary",
                    },
                },
            },
            {
                "method": "item/completed",
                "params": {
                    "threadId": "abcdef-123",
                    "turnId": "turn-id",
                    "item": {
                        "type": "mcpToolCall",
                        "server": "large MCP output",
                    },
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "another-session",
                    "turn": {"id": "turn-id", "status": "completed", "items": []},
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "abcdef-123",
                    "turn": {
                        "id": "turn-id",
                        "status": "completed",
                        "items": [
                            {
                                "type": "agentMessage",
                                "text": "still working",
                                "phase": "commentary",
                            },
                            {
                                "type": "agentMessage",
                                "text": "final answer",
                                "phase": "final_answer",
                            },
                        ],
                    },
                },
            },
        ]
        intermediate = []

        session_id, summary = agent_util.send_message(
            "abcdef",
            "hello",
            wait=True,
            on_intermediate=intermediate.append,
            socket_dir=self.socket_dir,
            client_factory=FakeAppServerClient,
        )

        self.assertEqual(session_id, "abcdef-123")
        self.assertEqual(intermediate, ["still working"])
        self.assertEqual(summary, "final answer")

    def test_wait_returns_when_turn_is_interrupted_without_a_summary(self):
        FakeAppServerClient.notifications_by_socket[self.first_socket] = [
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "abcdef-123",
                    "turn": {
                        "id": "turn-id",
                        "status": "interrupted",
                        "items": [],
                    },
                },
            }
        ]

        session_id, summary = agent_util.send_message(
            "abcdef",
            "hello",
            wait=True,
            socket_dir=self.socket_dir,
            client_factory=FakeAppServerClient,
        )

        self.assertEqual(session_id, "abcdef-123")
        self.assertEqual(summary, "")


class TailMessagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.socket_dir = Path(self.tmp.name)
        self.socket_path = self.socket_dir / "1.sock"
        self.socket_path.touch()
        FakeAppServerClient.requests = []
        FakeAppServerClient.threads_by_socket = {
            self.socket_path: [
                {"id": "abcdef-123", "status": {"type": "idle"}},
            ]
        }
        FakeAppServerClient.items_by_socket = {
            self.socket_path: [
                {
                    "data": [
                        {
                            "turnId": "new-turn",
                            "item": {
                                "type": "agentMessage",
                                "text": "new final",
                                "phase": "final_answer",
                            },
                        },
                        {
                            "turnId": "new-turn",
                            "item": {"type": "mcpToolCall", "result": "large"},
                        },
                        {
                            "turnId": "new-turn",
                            "item": {
                                "type": "agentMessage",
                                "text": "working",
                                "phase": "commentary",
                            },
                        },
                    ],
                    "nextCursor": "older",
                },
                {
                    "data": [
                        {
                            "turnId": "new-turn",
                            "item": {
                                "type": "userMessage",
                                "content": [
                                    {"type": "text", "text": "new request"},
                                    {"type": "image", "url": "large"},
                                ],
                            },
                        },
                        {
                            "turnId": "old-turn",
                            "item": {
                                "type": "agentMessage",
                                "text": "old final",
                                "phase": None,
                            },
                        },
                    ],
                    "nextCursor": None,
                },
            ]
        }
        FakeAppServerClient.turns_by_socket = {
            self.socket_path: [
                {
                    "data": [
                        {
                            "id": "new-turn",
                            "startedAt": 200,
                            "completedAt": 210,
                        },
                        {
                            "id": "old-turn",
                            "startedAt": 100,
                            "completedAt": 110,
                        },
                    ],
                    "nextCursor": None,
                }
            ]
        }

    def test_returns_recent_messages_in_chronological_order(self):
        session_id, messages = agent_util.tail_messages(
            "abcdef",
            4,
            socket_dir=self.socket_dir,
            client_factory=FakeAppServerClient,
        )

        self.assertEqual(session_id, "abcdef-123")
        self.assertEqual(
            messages,
            [
                ("final", "old final", 110),
                ("user", "new request", 200),
                ("commentary", "working", None),
                ("final", "new final", 210),
            ],
        )

    def test_filters_message_types(self):
        _session_id, messages = agent_util.tail_messages(
            "abcdef",
            2,
            frozenset(("final",)),
            socket_dir=self.socket_dir,
            client_factory=FakeAppServerClient,
        )

        self.assertEqual(
            messages,
            [("final", "old final", 110), ("final", "new final", 210)],
        )


class MessageTextTest(unittest.TestCase):
    def test_joins_command_line_words(self):
        self.assertEqual(agent_util.message_text(["hello", "there"]), "hello there")

    def test_reads_entire_message_from_stdin(self):
        self.assertEqual(
            agent_util.message_text([], io.StringIO("first line\nsecond line\n")),
            "first line\nsecond line\n",
        )

    def test_rejects_empty_stdin(self):
        with self.assertRaisesRegex(ValueError, "arguments or stdin"):
            agent_util.message_text([], io.StringIO("\n"))


class ParseArgsTest(unittest.TestCase):
    def test_timestamps_are_enabled_by_default(self):
        for argv in (
            ["agent-util", "tail", "abc"],
            ["agent-util", "send", "abc", "hello"],
        ):
            with self.subTest(argv=argv), mock.patch.object(
                agent_util.sys, "argv", argv
            ):
                self.assertTrue(agent_util.parse_args().timestamp)

    def test_no_timestamp_disables_timestamps(self):
        for argv in (
            ["agent-util", "tail", "abc", "--no-timestamp"],
            ["agent-util", "send", "abc", "hello", "--no-timestamp"],
        ):
            with self.subTest(argv=argv), mock.patch.object(
                agent_util.sys, "argv", argv
            ):
                self.assertFalse(agent_util.parse_args().timestamp)


if __name__ == "__main__":
    unittest.main()
