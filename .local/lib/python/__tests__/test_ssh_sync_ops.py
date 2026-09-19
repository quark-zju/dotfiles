import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB_DIR))

import ssh_sync_ops  # noqa: E402


def write_session(home, session_id, **overrides):
    record = {
        "pid": os.getpid(),
        "sessionId": session_id,
        "cwd": str(home),
        "procStart": ssh_sync_ops._process_start_ticks(os.getpid()),
        "status": "busy",
    }
    record.update(overrides)
    directory = home / ".claude" / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ("%d.json" % record["pid"])).write_text(json.dumps(record))
    return record


def write_transcript(home, session_id, records):
    directory = home / ".claude" / "projects" / "-slug"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (session_id + ".jsonl")
    path.write_text("".join(json.dumps(record) + "\n" for record in records))
    return path


def typed(text, timestamp="2026-09-18T22:00:00.000Z", **overrides):
    record = {
        "type": "user",
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }
    record.update(overrides)
    return record


class ClaudeAgentsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def list_agents(self):
        return ssh_sync_ops._list_claude_agents(home=str(self.home))

    def test_reports_live_session_status(self):
        write_session(self.home, "sid-live")

        (agent,) = self.list_agents()

        self.assertEqual(agent["session_id"], "sid-live")
        self.assertEqual(agent["harness"], "claude")
        self.assertTrue(agent["working"], "a busy session is working")

    def test_waiting_and_idle_are_not_working(self):
        # `agent-util wait` only keeps polling while `working` is true, so a
        # session blocked on the user must not look busy.
        for status in ("waiting", "idle"):
            with self.subTest(status=status):
                write_session(self.home, "sid", status=status)
                (agent,) = self.list_agents()
                self.assertFalse(agent["working"])
                self.assertEqual(agent["status"], status)

    def test_skips_registry_left_by_a_crash(self):
        # Same PID, different start time: the process was replaced.
        write_session(self.home, "sid-stale", procStart="1")

        self.assertEqual(self.list_agents(), [])

    def test_skips_session_whose_process_exited(self):
        write_session(self.home, "sid-dead", pid=2**22 - 1, procStart=None)

        self.assertEqual(self.list_agents(), [])

    def test_reports_newest_typed_prompt(self):
        write_transcript(
            self.home,
            "sid-live",
            [
                typed("first question"),
                typed("<system-reminder>ignored</system-reminder>"),
                {
                    "type": "user",
                    "timestamp": "2026-09-18T22:01:00.000Z",
                    "toolUseResult": {"stdout": "..."},
                    "message": {"content": [{"type": "tool_result"}]},
                },
                typed("subagent prompt", isSidechain=True),
                typed("newest question", timestamp="2026-09-18T22:02:00.000Z"),
                {"type": "assistant", "message": {"content": "answer"}},
            ],
        )
        write_session(self.home, "sid-live")

        (agent,) = self.list_agents()

        self.assertEqual(
            [message["message"] for message in agent["user_messages"]],
            ["newest question"],
        )

    def test_synthetic_prompts_never_shadow_a_real_one(self):
        write_transcript(
            self.home,
            "sid-live",
            [
                typed("real question"),
                typed("<command-name>/export</command-name>"),
                typed("<local-command-stdout>exported</local-command-stdout>"),
            ],
        )
        write_session(self.home, "sid-live")

        (agent,) = self.list_agents()

        self.assertEqual(agent["user_messages"][0]["message"], "real question")

    def test_session_without_a_transcript_is_still_listed(self):
        write_session(self.home, "sid-fresh")

        (agent,) = self.list_agents()

        self.assertEqual(agent["user_messages"], [])


if __name__ == "__main__":
    unittest.main()
