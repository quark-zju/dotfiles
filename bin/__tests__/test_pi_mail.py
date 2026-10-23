import io
import runpy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock


pi_mail = runpy.run_path(str(Path(__file__).parents[1] / "pi-mail"))
Index = pi_mail["Index"]


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

    def index_mail(self, index, mails):
        blobs = {}
        entries = []
        for mid, parent, refs in mails:
            headers = [f"Message-ID: <{mid}>"]
            if parent:
                headers.append(f"In-Reply-To: <{parent}>")
            if refs:
                headers.append("References: " + " ".join(f"<{ref}>" for ref in refs))
            blobs[mid] = ("\n".join(headers) + "\n\nBody\n").encode()
            entries.append((mid, "Author", 1, mid))
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
        db.executescript(Index.SCHEMA.replace(
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
        self.assertEqual(index.db.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertEqual(index.db.execute("SELECT tip_oid FROM epochs").fetchone()[0], "tip")
        with mock.patch.object(Index, "_merge_threads", side_effect=AssertionError("reran")):
            self.open_index()

    def test_failed_migration_rolls_back_schema_and_version(self):
        db = sqlite3.connect(self.cache)
        db.executescript(Index.SCHEMA.replace(
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


if __name__ == "__main__":
    unittest.main()
