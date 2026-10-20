import importlib.machinery
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "codex-notify.py"
LOADER = importlib.machinery.SourceFileLoader("codex_notify", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
assert SPEC is not None
codex_notify = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(codex_notify)


class AgentDetection(unittest.TestCase):
    def test_muse_processes(self):
        self.assertEqual(codex_notify._PROCESS_AGENT_NAMES["muse"], "Muse")
        self.assertEqual(codex_notify._PROCESS_AGENT_NAMES["muse.real"], "Muse")

    def test_codex_fields(self):
        self.assertTrue(codex_notify.has_codex_fields({"model": "m", "turn_id": "t"}))
        self.assertFalse(codex_notify.has_codex_fields({"session_id": "s"}))

    def test_agent_process_prefers_nearest(self):
        names = {30: "muse.real", 20: "codex"}
        with mock.patch.object(
            codex_notify, "ancestors", return_value=iter([30, 20, 10])
        ):
            with mock.patch.object(codex_notify, "process_name", side_effect=names.get):
                with mock.patch.object(
                    codex_notify, "process_stat", return_value=(1, 99)
                ):
                    self.assertEqual(codex_notify.agent_process({}), ("Muse", 30, 99))

    def test_agent_name_without_agent_ancestor(self):
        with mock.patch.object(codex_notify, "agent_process", return_value=None):
            self.assertEqual(
                codex_notify.agent_name({"model": "m", "turn_id": "t"}), "Codex"
            )
            self.assertEqual(codex_notify.agent_name({"session_id": "s"}), "Claude")


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
