import email
import email.policy
import io
import runpy
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


pi_mail = runpy.run_path(str(Path(__file__).parents[1] / "pi-mail"))
Index = pi_mail["Index"]
OLD_SCHEMA = Index.SCHEMA.replace(
    "subject_sid INTEGER NOT NULL REFERENCES strings(id)", "subject TEXT NOT NULL"
).replace("user_version = 4", "user_version = 3")


class ThreadIndexTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = str(Path(self.temp.name) / "index.sqlite3")
        self.gitdir = str(Path(self.temp.name) / "0.git")
        self.patch = mock.patch.dict(Index.__init__.__globals__, {
            "CACHE": self.cache, "epochs": lambda: [self.gitdir],
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def open_index(self):
        index = Index()
        self.addCleanup(index.db.close)
        return index

    def index_mail(self, index, mails, subjects=None):
        blobs = {}
        entries = []
        for mid, parent, refs in mails:
            headers = [f"Message-ID: <{mid}>"]
            if parent:
                headers.append(f"In-Reply-To: <{parent}>")
            if refs:
                headers.append("References: " + " ".join(f"<{ref}>" for ref in refs))
            blobs[mid] = ("\n".join(headers) + "\n\nBody\n").encode()
            entries.append((mid, "Author", 1, subjects[mid] if subjects else mid))
        reader = mock.Mock()
        reader.read.side_effect = lambda _, commit: blobs[commit]
        with index.db:
            index._index_entries(self.gitdir, index.epoch_ids[0], entries,
                                 reader, mock.Mock())

    def threads(self, index):
        return dict(index.db.execute(
            "SELECT mid.value, thread.value FROM messages m "
            "JOIN strings mid ON mid.id = m.message_sid "
            "JOIN strings thread ON thread.id = m.thread_sid"))

    def test_short_references_and_reply_without_references(self):
        index = self.open_index()
        # Git's log lists newest first; don't rely on parent-before-child order.
        self.index_mail(index, [
            ("reply", "v2", ["v2"]),
            ("v2", "v1", ["v1"]),
            ("v1", None, []),
            ("other", None, []),
        ])
        self.index_mail(index, [("reply2", "reply", [])])
        self.assertEqual(self.threads(index), {
            "v1": "v1", "v2": "v1", "reply": "v1", "reply2": "v1",
            "other": "other",
        })
        mid, thread = index.thread_target("v1")
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            pi_mail["print_tree"](index.thread_nodes(thread, 100000), {mid})
        self.assertIn("reply2", output.getvalue())

    def test_missing_parent_arrives_later(self):
        index = self.open_index()
        self.index_mail(index, [
            ("reply", "v2", []),
            ("sibling", "v2", ["v2"]),
        ])
        self.assertEqual(set(self.threads(index).values()), {"v2"})
        self.index_mail(index, [("v2", "v1", ["v1"])])
        self.assertEqual(set(self.threads(index).values()), {"v1"})
        self.index_mail(index, [("v1", None, [])])
        self.assertEqual(set(self.threads(index).values()), {"v1"})

    def test_missing_parent_with_a_different_reference_root(self):
        index = self.open_index()
        with index.db:
            index.db.execute("INSERT INTO strings(value) VALUES ('older')")
        self.index_mail(index, [("reply", "v2", ["older", "v2"])])
        self.assertEqual(self.threads(index), {"reply": "older"})
        self.index_mail(index, [("v2", "v1", ["v1"]), ("v1", None, [])])
        self.assertEqual(len(set(self.threads(index).values())), 1)

    def test_migration_runs_once_and_keeps_index_progress(self):
        db = sqlite3.connect(self.cache)
        db.executescript(OLD_SCHEMA.replace(
            "CREATE INDEX messages_parent_sid ON messages(parent_sid);", ""
        ).replace("user_version = 3", "user_version = 2"))
        with db:
            db.execute("INSERT INTO epochs(id, path, tip_oid) VALUES (1, ?, 'tip')",
                       (self.gitdir,))
            db.executemany("INSERT INTO strings(id, value) VALUES (?, ?)",
                           enumerate(("v1", "v2", "reply", "no-refs", "Author"), 1))
            db.executemany(
                "INSERT INTO messages(epoch_id, git_commit_oid, message_sid, "
                "parent_sid, thread_sid, commit_time, author_sid, subject) "
                "VALUES (1, ?, ?, ?, ?, 1, 5, ?)", [
                    ("v1", 1, None, 1, "v1"),
                    ("v2", 2, 1, 1, "v2"),
                    ("reply", 3, 2, 2, "reply"),
                    ("no-refs", 4, 2, 4, "no-refs"),
                ])
        db.close()
        # An earlier interrupted upgrade may already have created the index.
        db = sqlite3.connect(self.cache)
        db.execute("CREATE INDEX messages_parent_sid ON messages(parent_sid)")
        db.close()
        index = self.open_index()
        self.assertEqual(set(self.threads(index).values()), {"v1"})
        self.assertEqual(index.db.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertEqual(index.db.execute("SELECT tip_oid FROM epochs").fetchone()[0], "tip")
        with mock.patch.object(Index, "_merge_threads", side_effect=AssertionError("reran")), \
                mock.patch.object(Index, "_migrate_subjects", side_effect=AssertionError("reran")):
            self.open_index()

    def test_failed_migration_rolls_back_schema_and_version(self):
        db = sqlite3.connect(self.cache)
        db.executescript(OLD_SCHEMA.replace(
            "CREATE INDEX messages_parent_sid ON messages(parent_sid);", ""
        ).replace("user_version = 3", "user_version = 2"))
        db.close()
        index = Index.__new__(Index)
        with mock.patch.object(Index, "_merge_threads", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                index.__init__()
        index.db.close()
        db = sqlite3.connect(self.cache)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(db.execute(
            "SELECT name FROM sqlite_master WHERE name = 'messages_parent_sid'"
        ).fetchall(), [])
        self.open_index()

    def test_reference_cycle(self):
        index = self.open_index()
        self.index_mail(index, [("a", "b", ["b"]), ("b", "a", ["a"])])
        self.assertEqual(len(set(self.threads(index).values())), 1)

    def test_subjects_are_shared_and_all_queries_resolve_them(self):
        index = self.open_index()
        subjects = {
            "cover@example.com": "[PATCH v2 0/2] Cover",
            "patch@example.com": "[PATCH v2 1/2] Title",
            "duplicate@example.com": "[PATCH v2 1/2] Title",
            "reply@example.com": "Re: [PATCH v2 1/2] Title",
        }
        self.index_mail(index, [
            ("cover@example.com", None, []),
            ("patch@example.com", "cover@example.com", ["cover@example.com"]),
            ("duplicate@example.com", "cover@example.com", ["cover@example.com"]),
            ("reply@example.com", "patch@example.com", ["patch@example.com"]),
        ], subjects)
        shared = index.db.execute(
            "SELECT subject_sid FROM messages WHERE git_commit_oid IN (?, ?)",
            ("patch@example.com", "duplicate@example.com")).fetchall()
        self.assertEqual(shared[0], shared[1])
        self.assertEqual({row[1]: row[4] for row in index.recent(100000)}, subjects)
        _, thread = index.thread_target("cover@example.com")
        self.assertEqual({row[0]: row[3] for row in index.thread_nodes(thread, 100000).values()}, subjects)
        for records in (
            index.related_messages("Author", "example.com"),
            index.recent_messages(100000, "Author", "example.com"),
            index.messages_for_commits(["patch@example.com"], "Author", "example.com"),
        ):
            self.assertEqual({row["commit"]: row["subject"] for row in records}, subjects)
        _, _, contributors, reviewers = index.author_stats(100000)
        self.assertEqual(contributors[0][2], 3)
        self.assertEqual(reviewers, [])

        patch = Path(self.temp.name) / "patch"
        patch.write_text("Subject: [PATCH v3 1/2] Title\n\nBody\n")
        args = mock.Mock(index=index, patches=[str(patch)])
        output = io.StringIO()
        with mock.patch.dict(pi_mail["cmd_prev_cover"].__globals__, {
            "sendemail_identity": lambda: ("Author", "example.com"),
        }), mock.patch("sys.stdout", output), mock.patch("sys.stderr", io.StringIO()):
            pi_mail["cmd_prev_cover"](args)
        self.assertEqual(output.getvalue(), "<cover@example.com>\n")

    def test_subject_migration_preserves_rows_and_reuses_strings(self):
        db = sqlite3.connect(self.cache)
        db.executescript(OLD_SCHEMA)
        with db:
            db.execute("INSERT INTO epochs(id, path, tip_oid) VALUES (1, ?, 'tip')",
                       (self.gitdir,))
            db.executemany("INSERT INTO strings(id, value) VALUES (?, ?)",
                           [(1, "a"), (2, "b"), (3, "Author")])
            db.executemany(
                "INSERT INTO messages VALUES (?, 1, ?, ?, NULL, ?, 1, 3, ?)",
                [(10, "a", 1, 1, "Author"), (20, "b", 2, 2, "Author")])
        before = db.execute("SELECT * FROM messages").fetchall()
        indexes = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'messages'"
        ).fetchall()
        db.close()
        index = self.open_index()
        after = index.db.execute(
            "SELECT m.id, m.epoch_id, m.git_commit_oid, m.message_sid, m.parent_sid, "
            "m.thread_sid, m.commit_time, m.author_sid, s.value "
            "FROM messages m JOIN strings s ON s.id = m.subject_sid").fetchall()
        self.assertEqual(after, before)
        self.assertEqual(index.db.execute("SELECT subject_sid FROM messages").fetchall(), [(3,), (3,)])
        self.assertEqual(index.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(index.db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'messages'"
        ).fetchall(), indexes)
        columns = {row[1]: row for row in index.db.execute("PRAGMA table_info(messages)")}
        self.assertNotIn("subject", columns)
        self.assertEqual(columns["subject_sid"][3], 1)  # NOT NULL

    def test_failed_subject_migration_rolls_back(self):
        db = sqlite3.connect(self.cache)
        db.executescript(OLD_SCHEMA)
        db.close()
        index = Index.__new__(Index)
        original = Index._migrate_subjects

        def interrupted(index):
            original(index)
            raise RuntimeError("interrupted")

        with mock.patch.object(Index, "_migrate_subjects", interrupted):
            with self.assertRaises(RuntimeError):
                index.__init__()
        index.db.close()
        db = sqlite3.connect(self.cache)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertIn("subject", {row[1] for row in db.execute("PRAGMA table_info(messages)")})
        self.open_index()


class MailViewTest(unittest.TestCase):
    def test_raw_view_preserves_headers_and_mime_content(self):
        view = pi_mail["cmd_view_mail"]
        raw = (b"Received: from example.com\r\n\tby archive.example.com\r\n"
               b"Subject: =?UTF-8?Q?raw_mail?=\r\n"
               b"Content-Type: text/plain; charset=UTF-8\r\n"
               b"Content-Transfer-Encoding: quoted-printable\r\n\r\n"
               b"Body=0D=0A\r\n")
        opened = []

        def editor(command, check):
            self.assertEqual(command[0], "editor")
            path = Path(command[1])
            opened.append(path)
            self.assertEqual(path.read_bytes(), raw)

        blobs = mock.Mock()
        blobs.read.return_value = raw
        index = mock.Mock()
        index.message_location.return_value = ("inbox", "a" * 40)
        with mock.patch.dict(view.__globals__, {
            "Blobs": lambda: blobs, "editor_command": lambda: ["editor"],
        }), mock.patch("subprocess.run", side_effect=editor):
            view(mock.Mock(index=index, commit="a" * 40), raw=True)
        blobs.read.assert_called_once_with("inbox", "a" * 40)
        self.assertEqual(len(opened), 1)
        self.assertFalse(opened[0].exists())

    def test_normalizes_decoded_body_before_opening_editor(self):
        view = pi_mail["cmd_view_mail"]
        for encoding, body in (
            (b"8bit", b"Body\r\n> quoted\rAnother line\n"),
            (b"quoted-printable", b"Body=0D\n> quoted=0DAnother line=0D\n"),
        ):
            with self.subTest(encoding=encoding):
                raw = (b"From: Author <author@example.com>\r\nSubject: Reply\r\n"
                       b"Message-ID: <reply@example.com>\r\n"
                       b"Content-Type: text/plain; charset=UTF-8\r\n"
                       b"Content-Transfer-Encoding: " + encoding + b"\r\n\r\n" + body)
                message = email.message_from_bytes(raw, policy=email.policy.default)
                opened = []

                def editor(command, check):
                    self.assertEqual(command[0], "editor")
                    path = Path(command[1])
                    opened.append(path)
                    content = path.read_bytes()
                    self.assertNotIn(b"\r", content)
                    self.assertEqual(content.partition(b"\n\n")[2],
                                     b"Body\n> quoted\nAnother line\n")

                with mock.patch.dict(view.__globals__, {
                    "load": lambda *args: message, "editor_command": lambda: ["editor"],
                }), mock.patch("subprocess.run", side_effect=editor):
                    index = mock.Mock()
                    index.message_location.return_value = ("inbox", "a" * 40)
                    view(mock.Mock(index=index, commit="a" * 40))
                self.assertEqual(len(opened), 1)
                self.assertFalse(opened[0].exists())
                self.assertEqual(message.as_bytes(), email.message_from_bytes(
                    raw, policy=email.policy.default).as_bytes())


class DraftHistoryTest(unittest.TestCase):
    def test_records_lf_content_and_ignores_line_ending_only_edits(self):
        record_change = pi_mail["record_draft_change"]
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temp:
            def git(*args):
                return subprocess.check_output([
                    "git", "-C", temp, "-c", "user.name=Test", "-c",
                    "user.email=test@example.com", *args,
                ])

            git("init", "-q")
            git("config", "core.autocrlf", "false")
            path = Path(temp) / (commit + ".eml")
            expected = "Subject: Reply\n\n中文 reply\n> quoted line\n".encode()
            path.write_bytes("Subject: Reply\r\n\r\n中文 reply\r> quoted line\n".encode())
            with mock.patch.dict(record_change.__globals__, {"DRAFT_DIR": temp}), \
                    mock.patch.dict("os.environ", {
                        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
                        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
                    }):
                record_change(commit, "Edit reply")
                self.assertEqual(path.read_bytes(), expected)
                self.assertEqual(git("show", "HEAD:" + path.name), expected)
                revision = git("rev-parse", "HEAD")
                path.write_bytes(expected.replace(b"\n", b"\r\n"))
                record_change(commit, "Edit reply again")
                self.assertEqual(path.read_bytes(), expected)
                self.assertEqual(git("rev-parse", "HEAD"), revision)
                path.unlink()
                record_change(commit, "Delete reply")
                self.assertEqual(git("ls-tree", "--name-only", "HEAD"), b"")
                self.assertEqual(git("status", "--porcelain"), b"")


class DraftSendTest(unittest.TestCase):
    def test_normalizes_line_endings_before_send(self):
        send = pi_mail["cmd_draft_send"]
        commit = "a" * 40
        for endings in (b"\n", b"\r\n", b"\r", None):
            with self.subTest(endings=endings), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / (commit + ".eml")
                lines = [b"Subject: Reply", b"Content-Transfer-Encoding: 8bit", b"",
                         "中文 reply".encode(), b"> quoted line", b""]
                expected = b"\n".join(lines)
                original = (endings.join(lines) if endings is not None else
                            b"Subject: Reply\r\nContent-Transfer-Encoding: 8bit\n\n" +
                            "中文 reply".encode() + b"\r> quoted line\r\n")
                path.write_bytes(original)

                def send_email(command):
                    self.assertEqual(command, ["git", "send-email", str(path)])
                    self.assertEqual(path.read_bytes(), expected)
                    return mock.Mock(returncode=0)

                record_change = mock.Mock()
                with mock.patch.dict(send.__globals__, {
                    "DRAFT_DIR": temp, "record_draft_change": record_change,
                }), mock.patch("subprocess.run", side_effect=send_email):
                    send(mock.Mock(commit=commit))
                    messages = [call.args[1] for call in
                                record_change.call_args_list]
                self.assertFalse(path.exists())
                self.assertEqual(messages[-1], f"Send reply to {commit[:12]}")
                self.assertEqual(len(messages), 1 if original == expected else 2)

    def test_failed_send_keeps_normalized_draft(self):
        send = pi_mail["cmd_draft_send"]
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / (commit + ".eml")
            path.write_bytes(b"Subject: Reply\r\n\r\nBody\r\n")
            with mock.patch.dict(send.__globals__, {
                "DRAFT_DIR": temp, "record_draft_change": mock.Mock(),
            }), mock.patch("subprocess.run", return_value=mock.Mock(returncode=1)), \
                    mock.patch("builtins.input", return_value=""):
                with self.assertRaises(SystemExit) as caught:
                    send(mock.Mock(commit=commit))
            self.assertEqual(caught.exception.code, 1)
            self.assertEqual(path.read_bytes(), b"Subject: Reply\n\nBody\n")


if __name__ == "__main__":
    unittest.main()
