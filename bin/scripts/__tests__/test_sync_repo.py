#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "sync_repo", Path(__file__).resolve().parents[1] / "sync_repo.py"
)
assert SPEC is not None and SPEC.loader is not None
sync_repo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_repo)


class ProcessEvent:
    def __init__(self, stream: str, data: bytes) -> None:
        self.stream = stream
        self.data = data


class LocalRemoteProcess:
    def __init__(self, argv: list[str], cwd: str | None) -> None:
        self.argv = argv
        self.cwd = cwd
        self.input = bytearray()
        self.events: list[ProcessEvent] = []
        self.returncode: int | None = None
        self.stdin_closed = False

    def send(self, data: bytes) -> None:
        self.input.extend(data)

    def close_stdin(self) -> None:
        if self.stdin_closed:
            return
        self.stdin_closed = True
        completed = subprocess.run(
            self.argv,
            cwd=self.cwd,
            input=bytes(self.input),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.returncode = completed.returncode
        self.events = [
            ProcessEvent("stdout", completed.stdout),
            ProcessEvent("stderr", completed.stderr),
        ]

    def __iter__(self):
        self.close_stdin()
        return iter(event for event in self.events if event.data)

    def wait(self) -> int | None:
        self.close_stdin()
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.wait()


class LocalSshSync:
    RemoteError = RuntimeError

    @staticmethod
    def list_hosts() -> list[str]:
        return ["test"]

    @staticmethod
    def call_remote(_host, function, *args, **_kwargs):
        return function(*args)

    @staticmethod
    def open_process(_host, argv, *, cwd=None, **_kwargs):
        return LocalRemoteProcess(argv, cwd)


class SyncRepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.remote = root / "remote"
        self.local = root / "local"
        self.remote.mkdir()
        self.git(self.remote, "init", "-b", "main")
        self.configure(self.remote)
        self.commit(self.remote, "base", "base")
        subprocess.run(
            ["git", "clone", "--quiet", str(self.remote), str(self.local)],
            check=True,
        )
        self.configure(self.local)
        self.original_ssh_sync = sync_repo.ssh_sync
        sync_repo.ssh_sync = LocalSshSync()

    def tearDown(self) -> None:
        sync_repo.ssh_sync = self.original_ssh_sync
        self.temporary_directory.cleanup()

    def git(self, repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout.strip()

    def configure(self, repo: Path) -> None:
        self.git(repo, "config", "user.email", "test@example.com")
        self.git(repo, "config", "user.name", "Test")

    def commit(self, repo: Path, name: str, contents: str) -> None:
        Path(repo, name).write_text(contents)
        self.git(repo, "add", name)
        self.git(repo, "commit", "-m", contents)

    def sync(self) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sync_repo.sync(str(self.local), str(self.remote), "test")
        return output.getvalue()

    def assert_tips_equal(self) -> None:
        self.assertEqual(
            self.git(self.local, "rev-parse", "main"),
            self.git(self.remote, "rev-parse", "main"),
        )

    def test_prints_repo_information_when_there_are_no_changes(self) -> None:
        self.assertEqual(
            self.sync(),
            f"sync: {self.local} <-> test:{self.remote} (main)\n",
        )

    def test_fast_forwards_in_both_directions(self) -> None:
        self.commit(self.local, "local", "local")
        self.assertIn("remote: updated main", self.sync())
        self.assert_tips_equal()

        self.commit(self.remote, "remote", "remote")
        self.assertIn("local: fast-forwarded main", self.sync())
        self.assert_tips_equal()

    def test_rebases_local_branch_when_histories_diverge(self) -> None:
        self.commit(self.local, "local", "local")
        self.commit(self.remote, "remote", "remote")
        output = self.sync()
        self.assertIn("local: rebased main onto remote", output)
        self.assert_tips_equal()
        self.assertEqual(
            self.git(self.local, "log", "--format=%s", "-2"),
            "local\nremote",
        )

    def test_keeps_checkout_when_files_would_be_overwritten(self) -> None:
        self.git(self.remote, "checkout", "--quiet", "-b", "other")
        Path(self.remote, "base").write_text("dirty remote tree")
        Path(self.local, "base").write_text("new committed value")
        self.git(self.local, "add", "base")
        self.git(self.local, "commit", "-m", "update base")

        output = self.sync()

        self.assertIn("remote: kept the existing checkout:", output)
        self.assertEqual(self.git(self.remote, "branch", "--show-current"), "other")
        self.assertEqual(Path(self.remote, "base").read_text(), "dirty remote tree")
        self.assert_tips_equal()


if __name__ == "__main__":
    unittest.main()
