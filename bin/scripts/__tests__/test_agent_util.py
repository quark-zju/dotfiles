import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

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


class StateTest(unittest.TestCase):
    def test_suspended_takes_precedence_over_working(self):
        self.assertEqual(
            agent_util.state(agent("one", working=True, suspended=True)),
            "suspended",
        )

    def test_non_working_session_is_idle(self):
        self.assertEqual(agent_util.state(agent("one")), "idle")


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


if __name__ == "__main__":
    unittest.main()
