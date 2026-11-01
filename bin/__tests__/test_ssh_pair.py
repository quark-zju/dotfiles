"""Exercise pairing using isolated homes; never change the real SSH configuration."""

import base64
import contextlib
import importlib.machinery
import io
import importlib.util
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPT = Path(
    os.environ.get(
        "SSH_PAIR_TEST_SCRIPT", Path(__file__).resolve().parents[1] / "ssh-pair"
    )
)
loader = importlib.machinery.SourceFileLoader("ssh_pair", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
pair = importlib.util.module_from_spec(spec)
loader.exec_module(pair)


class PairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.root = Path(cls.scratch.name)
        cls.keys = []
        for index in range(2):
            key = cls.root / f"key{index}"
            subprocess.run(
                ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                check=True,
            )
            cls.keys.append(
                pair.public_key(key.with_suffix(".pub").read_text().strip())
            )

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def peer(self, index=0, host_keys=None):
        return dict(
            protocol=pair.PROTOCOL,
            nonce=str(index) * 64,
            user="user",
            hostname="test",
            keys=[self.keys[index]],
            host_keys=host_keys or [],
        )

    def test_code_binds_all_keys_and_is_symmetric(self):
        a, b = self.peer(0), self.peer(1)
        code = pair.verification_code(a, b)
        self.assertEqual(code, pair.verification_code(b, a))
        b["keys"] = a["keys"]
        self.assertNotEqual(code, pair.verification_code(a, b))

    def test_reject_options_newlines_bad_blob(self):
        for key in [
            "restrict " + self.keys[0],
            self.keys[0] + "\n" + self.keys[1],
            "ssh-ed25519 AAAA",
            "ssh-rsa " + self.keys[0].split()[1],
        ]:
            with self.assertRaises(ValueError):
                pair.public_key(key)

    def test_rsa_and_ecdsa_public_keys_round_trip(self):
        for kind in ("rsa", "ecdsa"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as scratch:
                path = Path(scratch) / "key"
                subprocess.run(
                    ["ssh-keygen", "-q", "-t", kind, "-N", "", "-f", str(path)],
                    check=True,
                )
                key = pair.public_key(path.with_suffix(".pub").read_text().strip())
                self.assertEqual(pair.public_key(key), key)

    def test_rejected_key_is_warned_skipped_and_transcript_preserved(self):
        kind, data = self.keys[0].split()
        truncated = base64.b64encode(base64.b64decode(data)[:-1]).decode()
        peer = self.peer(host_keys=[self.keys[1], kind + " " + truncated])
        before = pair.encode(peer)
        code = pair.verification_code(self.peer(1), peer)
        warnings = io.StringIO()
        with contextlib.redirect_stderr(warnings):
            usable = pair.usable_peer(pair.validate(peer))
        self.assertEqual(usable["keys"], peer["keys"])
        self.assertEqual(usable["host_keys"], [self.keys[1]])
        self.assertEqual(pair.encode(peer), before)
        self.assertEqual(pair.verification_code(self.peer(1), peer), code)
        self.assertIn("host_keys[2]", warnings.getvalue())
        self.assertIn("ssh-ed25519", warnings.getvalue())
        self.assertIn("<public-key>", warnings.getvalue())

    def test_unrecognized_algorithm_does_not_block_other_keys(self):
        kind = b"ssh-unsupported-test"
        blob = len(kind).to_bytes(4, "big") + kind + b"unknown-key-data"
        unknown = kind.decode() + " " + base64.b64encode(blob).decode()
        peer = self.peer(host_keys=[unknown, self.keys[1]])
        with contextlib.redirect_stderr(io.StringIO()):
            usable = pair.usable_peer(pair.validate(peer))
        self.assertEqual(usable["host_keys"], [self.keys[1]])
        self.assertEqual(usable["keys"], [self.keys[0]])
        with tempfile.TemporaryDirectory() as home, patch.object(
            Path, "home", return_value=Path(home)
        ):
            pair.install(usable, "127.0.0.1")
            self.assertIn(
                self.keys[0], (Path(home) / ".ssh/authorized_keys").read_text()
            )
            hosts = (Path(home) / ".ssh/known_hosts").read_text()
            self.assertIn(self.keys[1], hosts)
            self.assertNotIn(unknown, hosts)

    def test_rejected_local_key_does_not_block_existing_valid_key(self):
        with tempfile.TemporaryDirectory() as scratch:
            bad, good = Path(scratch) / "bad.pub", Path(scratch) / "good.pub"
            bad.write_text("broken")
            good.write_text(self.keys[0])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(pair.read_keys([bad, good]), [self.keys[0]])

    def test_append_dedup_preserve_restrictions(self):
        with tempfile.TemporaryDirectory() as home, patch.object(
            Path, "home", return_value=Path(home)
        ):
            directory = Path(home) / ".ssh"
            directory.mkdir(mode=0o700)
            path = directory / "authorized_keys"
            old = f'command="echo hello",no-pty {self.keys[0]} old-comment'
            path.write_text(old)
            pair.install(self.peer(0), "127.0.0.1")
            self.assertEqual(path.read_text(), old)
            pair.install(self.peer(1), "127.0.0.1")
            pair.install(self.peer(1), "127.0.0.1")
            self.assertEqual(
                path.read_text(), old + "\n" + self.keys[1] + " ssh-pair\n"
            )

    def test_host_key_conflict_including_hashed_entries(self):
        with tempfile.TemporaryDirectory() as home, patch.object(
            Path, "home", return_value=Path(home)
        ):
            directory = Path(home) / ".ssh"
            directory.mkdir(mode=0o700)
            hosts = directory / "known_hosts"
            hosts.write_text("127.0.0.1 " + self.keys[0] + "\n")
            subprocess.run(
                ["ssh-keygen", "-H", "-f", str(hosts)], capture_output=True, check=True
            )
            old = hosts.read_bytes()
            with self.assertRaisesRegex(ValueError, "conflict"):
                pair.install(self.peer(1, [self.keys[1]]), "127.0.0.1")
            self.assertEqual(old, hosts.read_bytes())
            self.assertFalse((directory / "authorized_keys").exists())

    def test_symlink_refused(self):
        with tempfile.TemporaryDirectory() as home, patch.object(
            Path, "home", return_value=Path(home)
        ):
            directory = Path(home) / ".ssh"
            directory.mkdir(mode=0o700)
            target = Path(home) / "target"
            target.write_text("unchanged")
            (directory / "authorized_keys").symlink_to(target)
            with self.assertRaises(OSError):
                pair.install(self.peer(), "127.0.0.1")
            self.assertEqual(target.read_text(), "unchanged")

    def integration(self, approve=True, missing=False):
        with tempfile.TemporaryDirectory() as scratch, contextlib.ExitStack() as stack:
            homes = [Path(scratch) / str(index) for index in range(2)]
            for index, home in enumerate(homes):
                directory = home / ".ssh"
                directory.mkdir(parents=True, mode=0o700)
                if not (missing and index == 1):
                    (directory / "id_ed25519.pub").write_text(
                        self.keys[index] + " test\n"
                    )
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = str(sock.getsockname()[1])
            procs = []
            logs = [[], []]
            ready = threading.Event()
            verified = [threading.Event(), threading.Event()]
            for index, mode in enumerate(["serve", "join"]):
                if index:
                    self.assertTrue(ready.wait(5), logs)
                args = [sys.executable, str(SCRIPT), mode, "--port", port]
                if index:
                    args += ["--timeout", "1"]
                proc = subprocess.Popen(
                    args,
                    env=dict(os.environ, HOME=str(homes[index])),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                procs.append(proc)
                stack.callback(proc.stdout.close)
                stack.callback(proc.stdin.close)
                stack.callback(lambda p=proc: p.kill() if p.poll() is None else None)

                def reader(i=index, p=proc):
                    for line in p.stdout:
                        logs[i].append(line)
                        if "Waiting as" in line:
                            ready.set()
                        if "Verification code:" in line:
                            verified[i].set()

                threading.Thread(target=reader, daemon=True).start()
            for event in verified:
                self.assertTrue(event.wait(8), logs)
            codes = [
                re.search(r"Verification code: ([a-f0-9-]+)", "".join(log)).group(1)
                for log in logs
            ]
            self.assertEqual(codes[0], codes[1])
            procs[0].stdin.write("yes\n")
            procs[0].stdin.flush()
            procs[1].stdin.write("yes\n" if approve else "no\n")
            procs[1].stdin.flush()
            for proc in procs:
                self.assertEqual(proc.wait(timeout=10), 0, logs)
            for index, home in enumerate(homes):
                path = home / ".ssh" / "authorized_keys"
                expected = approve and not (missing and index == 0)
                self.assertEqual(path.exists(), expected, logs)
                if expected:
                    self.assertIn(self.keys[1 - index], path.read_text())

    def test_discovery_and_bidirectional_pairing(self):
        self.integration()

    def test_decline_writes_no_authorized_keys(self):
        self.integration(approve=False)

    def test_missing_default_key_is_skipped(self):
        self.integration(missing=True)


if __name__ == "__main__":
    unittest.main()
