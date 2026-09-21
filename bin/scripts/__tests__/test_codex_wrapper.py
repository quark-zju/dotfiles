import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

WRAPPER = Path(__file__).parents[3] / ".local" / "bin" / "codex"


class CodexWrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin_dir = self.root / "bin"
        self.runtime_dir = self.root / "runtime"
        self.log = self.root / "calls.jsonl"
        self.bin_dir.mkdir()
        self.runtime_dir.mkdir()
        fake = self.bin_dir / "codex"
        fake.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json
                import os
                import signal
                import socket
                import sys

                args = sys.argv[1:]
                record = {
                    "args": args,
                    "pid": os.getpid(),
                    "ppid": os.getppid(),
                    "socket": os.environ.get("CODEX_APP_SERVER_SOCKET"),
                    "tui_pid": os.environ.get("CODEX_TUI_PID"),
                }
                with open(os.environ["FAKE_CODEX_LOG"], "a") as stream:
                    print(json.dumps(record), file=stream, flush=True)
                if args[:2] == ["app-server", "--listen"]:
                    path = args[2].removeprefix("unix://")
                    listener = socket.socket(socket.AF_UNIX)
                    listener.bind(path)
                    listener.listen()
                    signal.pause()
                sys.exit(int(os.environ.get("FAKE_CODEX_EXIT", "0")))
                """))
        fake.chmod(0o755)

    def run_wrapper(self, *args, exit_status=0, include_runtime=True):
        environment = os.environ.copy()
        environment["PATH"] = os.pathsep.join(
            (str(WRAPPER.parent), str(self.bin_dir), environment["PATH"])
        )
        environment["FAKE_CODEX_LOG"] = str(self.log)
        environment["FAKE_CODEX_EXIT"] = str(exit_status)
        environment["FAKE_LEASH_LOG"] = str(self.root / "leash.jsonl")
        environment["HOME"] = str(self.root)
        if include_runtime:
            environment["XDG_RUNTIME_DIR"] = str(self.runtime_dir)
        else:
            environment.pop("XDG_RUNTIME_DIR", None)
        return subprocess.run(
            [str(WRAPPER), *args],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def install_fake_leash(self):
        leash = self.root / ".cargo/bin/leash"
        leash.parent.mkdir(parents=True)
        leash.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                with open(os.environ["FAKE_LEASH_LOG"], "a") as stream:
                    print(json.dumps(sys.argv[1:]), file=stream, flush=True)
                assert sys.argv[1] == "run"
                os.execv(sys.argv[2], sys.argv[2:])
                """))
        leash.chmod(0o755)
        return leash

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def leash_calls(self):
        return [
            json.loads(line)
            for line in (self.root / "leash.jsonl").read_text().splitlines()
        ]

    def test_no_args_runs_tui_through_per_process_socket(self):
        completed = self.run_wrapper()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        server, tui = self.calls()
        self.assertEqual(server["args"][:2], ["app-server", "--listen"])
        self.assertEqual(tui["args"], ["--remote", server["args"][2]])
        self.assertEqual(server["socket"], tui["socket"])
        self.assertEqual(server["tui_pid"], tui["tui_pid"])
        self.assertNotEqual(tui["tui_pid"], str(tui["pid"]))
        self.assertFalse(Path(server["socket"]).exists())

    def test_resume_preserves_its_arguments(self):
        completed = self.run_wrapper("resume", "--last", "hello")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        server, tui = self.calls()
        self.assertEqual(
            tui["args"],
            ["resume", "--remote", server["args"][2], "--last", "hello"],
        )

    def test_other_commands_exec_real_codex_without_server(self):
        completed = self.run_wrapper("exec", "hello", exit_status=17)

        self.assertEqual(completed.returncode, 17)
        self.assertEqual(self.calls()[0]["args"], ["exec", "hello"])

    def test_app_server_runs_through_leash_when_available(self):
        leash = self.install_fake_leash()

        completed = self.run_wrapper()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        server, _tui = self.calls()
        self.assertEqual(
            self.leash_calls(),
            [["run", str(self.bin_dir / "codex"), *server["args"]]],
        )
        self.assertTrue(leash.exists())

    def test_other_commands_run_through_leash_when_available(self):
        self.install_fake_leash()

        completed = self.run_wrapper("exec", "hello", exit_status=17)

        self.assertEqual(completed.returncode, 17)
        self.assertEqual(
            self.leash_calls(),
            [["run", str(self.bin_dir / "codex"), "exec", "hello"]],
        )

    def test_interactive_mode_requires_xdg_runtime_dir(self):
        completed = self.run_wrapper(include_runtime=False)

        self.assertEqual(completed.returncode, 1)
        self.assertIn("XDG_RUNTIME_DIR", completed.stderr)


if __name__ == "__main__":
    unittest.main()
