import importlib.machinery
import importlib.util
import io
import json
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


class NormalizeHarness(unittest.TestCase):
    def test_known_names_canonicalized(self):
        self.assertEqual(codex_notify.normalize_harness("muse"), "Muse")
        self.assertEqual(codex_notify.normalize_harness("Muse"), "Muse")
        self.assertEqual(codex_notify.normalize_harness("CODEX"), "Codex")
        self.assertEqual(codex_notify.normalize_harness("Claude"), "Claude")

    def test_unknown_names_pass_through(self):
        self.assertEqual(codex_notify.normalize_harness("MyBot"), "MyBot")


class DetectHarness(unittest.TestCase):
    def test_nearest_ancestor_wins(self):
        names = {30: "muse.real", 20: "codex"}
        with mock.patch.object(
            codex_notify, "ancestors", side_effect=lambda pid: iter([30, 20, 10])
        ):
            with mock.patch.object(codex_notify, "process_name", side_effect=names.get):
                self.assertEqual(codex_notify.detect_harness(), "Muse")

    def test_no_match(self):
        with mock.patch.object(
            codex_notify, "ancestors", side_effect=lambda pid: iter([30, 20])
        ):
            with mock.patch.object(codex_notify, "process_name", return_value="bash"):
                self.assertIsNone(codex_notify.detect_harness())


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


class MainHarnessArg(unittest.TestCase):
    def run_main(self, argv, payload=None):
        stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
        with mock.patch.object(sys, "argv", argv):
            with mock.patch.object(codex_notify, "log_event") as log_mock:
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    with mock.patch("sys.stdin", stdin):
                        codex_notify.main()
        return out.getvalue(), log_mock

    def test_missing_flag_falls_back_to_detect(self):
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s",
            "prompt": "hi",
        }
        with mock.patch.object(codex_notify, "detect_harness", return_value="Codex"):
            with mock.patch.object(
                codex_notify, "resolve_swaysock", return_value="/sock"
            ):
                with mock.patch.object(
                    codex_notify, "save_prompt", return_value=None
                ) as save_mock:
                    out, _ = self.run_main(["codex-notify.py"], payload)
        self.assertEqual(out, "{}\n")
        save_mock.assert_called_once_with(payload, "Codex")

    def test_missing_flag_and_no_detect_skips(self):
        with mock.patch.object(codex_notify, "detect_harness", return_value=None):
            out, log_mock = self.run_main(["codex-notify.py"])
        self.assertEqual(out, "{}\n")
        log_mock.assert_called_once_with(
            "hook_skipped", reason="unknown_harness", agent=None
        )

    def test_harness_reaches_save(self):
        payload = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s",
            "prompt": "hi",
        }
        with mock.patch.object(codex_notify, "resolve_swaysock", return_value="/sock"):
            with mock.patch.object(
                codex_notify, "save_prompt", return_value=None
            ) as save_mock:
                out, _ = self.run_main(
                    ["codex-notify.py", "--harness", "muse"], payload
                )
        self.assertEqual(out, "{}\n")
        save_mock.assert_called_once_with(payload, "Muse")

    def test_unknown_harness_skips(self):
        out, log_mock = self.run_main(["codex-notify.py", "--harness", "mybot"])
        self.assertEqual(out, "{}\n")
        log_mock.assert_called_once_with(
            "hook_skipped", reason="unknown_harness", agent="mybot"
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
            with mock.patch(
                "glob.glob", return_value=["a.sock", "b.sock"]
            ) as glob_mock:
                with mock.patch("os.path.getmtime", side_effect=[1.0, 2.0]):
                    with mock.patch.object(
                        codex_notify, "runtime_dir", return_value="/run/user/1000"
                    ):
                        self.assertEqual(codex_notify.resolve_swaysock(), "b.sock")
                glob_mock.assert_called_once_with("/run/user/1000/sway-ipc.*.sock")

    def test_no_candidate(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(codex_notify, "runtime_dir", return_value=None):
                self.assertIsNone(codex_notify.resolve_swaysock())
