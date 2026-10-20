import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "codex-notify.py"
LOADER = importlib.machinery.SourceFileLoader("codex_notify", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
codex_notify = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(codex_notify)


class AgentProcess(unittest.TestCase):
    def test_finds_named_agent(self):
        names = {30: "muse.real", 20: "codex"}
        with mock.patch.object(
            codex_notify, "ancestors", side_effect=lambda pid: iter([30, 20, 10])
        ):
            with mock.patch.object(codex_notify, "process_name", side_effect=names.get):
                with mock.patch.object(
                    codex_notify, "process_stat", return_value=(1, 99)
                ):
                    self.assertEqual(codex_notify.agent_process("Muse"), (30, 99))

    def test_skips_other_agents(self):
        names = {30: "muse.real", 20: "codex"}
        with mock.patch.object(
            codex_notify, "ancestors", side_effect=lambda pid: iter([30, 20, 10])
        ):
            with mock.patch.object(codex_notify, "process_name", side_effect=names.get):
                with mock.patch.object(
                    codex_notify, "process_stat", return_value=(1, 99)
                ):
                    self.assertEqual(codex_notify.agent_process("Codex"), (20, 99))

    def test_no_match(self):
        with mock.patch.object(
            codex_notify, "ancestors", side_effect=lambda pid: iter([30, 20])
        ):
            with mock.patch.object(codex_notify, "process_name", return_value="bash"):
                self.assertIsNone(codex_notify.agent_process("Muse"))


class SavePrompt(unittest.TestCase):
    def test_stores_explicit_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                codex_notify, "agent_process", return_value=(123, 456)
            ):
                with mock.patch.object(
                    codex_notify, "state_path", return_value=Path(tmp) / "s.json"
                ):
                    state = codex_notify.save_prompt(
                        {"session_id": "s", "prompt": "hi"}, "Muse"
                    )
        self.assertEqual(state["agent_name"], "Muse")
        self.assertEqual(state["pid"], 123)
        self.assertEqual(state["process_start_time"], 456)


class MainAgentArg(unittest.TestCase):
    def run_main(self, argv):
        with mock.patch.object(sys, "argv", argv):
            with mock.patch.object(codex_notify, "log_event") as log_mock:
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    codex_notify.main()
        return out.getvalue(), log_mock

    def test_missing_agent_skips(self):
        out, log_mock = self.run_main(["codex-notify.py"])
        self.assertEqual(out, "{}\n")
        log_mock.assert_called_once_with(
            "hook_skipped", reason="invalid_agent", agent=None
        )

    def test_invalid_agent_skips(self):
        out, log_mock = self.run_main(["codex-notify.py", "--agent", "Foo"])
        self.assertEqual(out, "{}\n")
        log_mock.assert_called_once_with(
            "hook_skipped", reason="invalid_agent", agent="Foo"
        )


class RuntimeDir(unittest.TestCase):
    def test_env_preferred(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            self.assertEqual(codex_notify.runtime_dir(), "/run/user/1000")

    def test_uid_fallback(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(codex_notify.os, "getuid", return_value=1000):
                with mock.patch.object(
                    codex_notify.os.path, "isdir", return_value=True
                ):
                    self.assertEqual(codex_notify.runtime_dir(), "/run/user/1000")

    def test_no_runtime_dir(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(codex_notify.os.path, "isdir", return_value=False):
                self.assertIsNone(codex_notify.runtime_dir())


class Swaysock(unittest.TestCase):
    def test_env_socket_kept(self):
        with mock.patch.dict(os.environ, {"SWAYSOCK": "/run/user/1000/sway-ipc.sock"}):
            with mock.patch.object(codex_notify.os.path, "exists", return_value=True):
                self.assertEqual(
                    codex_notify.resolve_swaysock(), "/run/user/1000/sway-ipc.sock"
                )

    def test_newest_candidate_wins(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(
                codex_notify, "runtime_dir", return_value="/run/user/1000"
            ):
                with mock.patch(
                    "glob.glob", return_value=["a.sock", "b.sock"]
                ) as glob_mock:
                    with mock.patch("os.path.getmtime", side_effect=[1.0, 2.0]):
                        self.assertEqual(codex_notify.resolve_swaysock(), "b.sock")
                    glob_mock.assert_called_once_with("/run/user/1000/sway-ipc.*.sock")

    def test_no_candidate(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(codex_notify, "runtime_dir", return_value=None):
                self.assertIsNone(codex_notify.resolve_swaysock())
