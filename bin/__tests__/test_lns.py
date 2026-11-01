"""Run lns against an isolated repository and HOME, never the real dotfiles."""

import contextlib
import errno
import io
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(
    os.environ.get("LNS_TEST_SCRIPT", Path(__file__).resolve().parents[2] / "lns")
)
loader = importlib.machinery.SourceFileLoader("lns", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
lns = importlib.util.module_from_spec(spec)
loader.exec_module(lns)


class LnsTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name).resolve()
        self.home = self.base / "home"
        self.root = self.home / "src/dotfiles"
        self.root.mkdir(parents=True)
        shutil.copyfile(SCRIPT, self.root / "lns")

    def source(self, relative, directory=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if directory:
            path.mkdir()
        else:
            path.write_text("source\n")
        return path

    def run_lns(self, *paths, cwd=None):
        result = subprocess.run(
            [sys.executable, str(self.root / "lns"), *map(str, paths)],
            cwd=cwd or self.root,
            env=dict(os.environ, HOME=str(self.home)),
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.stderr, "")
        return result

    def test_create_relative_links_and_repeat(self):
        for name in (".config/foo", ".zshrc", "folder with spaces/file"):
            self.source(name)
        result = self.run_lns(".config/foo", ".zshrc", "folder with spaces/file")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            result.stdout.splitlines(),
            [
                f"{name} -> symlinked"
                for name in (".config/foo", ".zshrc", "folder with spaces/file")
            ],
        )
        for name in (".config/foo", ".zshrc", "folder with spaces/file"):
            target = self.home / name
            self.assertFalse(os.path.isabs(os.readlink(target)))
            self.assertEqual(target.resolve(), (self.root / name).resolve())
        self.assertIn(".zshrc -> already symlinked", self.run_lns(".zshrc").stdout)

    def test_directory_entry_is_linked_and_repeated_safely(self):
        source = self.source(".config/foo", directory=True)
        (source / "config").write_text("keep")
        self.assertEqual(
            self.run_lns(".config/foo").stdout, ".config/foo -> symlinked\n"
        )
        self.assertEqual(
            self.run_lns(".config/foo").stdout, ".config/foo -> already symlinked\n"
        )
        self.assertEqual((self.home / ".config/foo/config").read_text(), "keep")

    def test_all_argument_origins(self):
        source = self.source(".config/foo")
        (self.home / ".config").mkdir()
        cases = [
            (".config/foo", self.base),
            ("src/dotfiles/.config/foo", self.home),
            ("foo", self.root / ".config"),
            ("./foo", self.home / ".config"),
            ("../.config/foo", self.root / ".config"),
            (str(source), self.base),
            (str(self.home / ".config/foo"), self.base),
            ("~/.config/foo", self.base),
        ]
        for argument, cwd in cases:
            with self.subTest(argument=argument, cwd=cwd):
                result = self.run_lns(argument, cwd=cwd)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertTrue(
                    result.stdout.startswith(".config/foo -> "), result.stdout
                )
                self.assertEqual((self.home / ".config/foo").resolve(), source)

    def test_root_precedence_and_explicit_cwd(self):
        self.source("foo")
        self.source("nested/foo")
        self.assertEqual(
            self.run_lns("foo", cwd=self.root / "nested").stdout, "foo -> symlinked\n"
        )
        self.assertEqual(
            self.run_lns("./foo", cwd=self.root / "nested").stdout,
            "nested/foo -> symlinked\n",
        )

    def test_absolute_and_chained_links_are_already_linked(self):
        source = self.source("foo")
        target = self.home / "foo"
        target.symlink_to(source)
        self.assertEqual(self.run_lns("foo").stdout, "foo -> already symlinked\n")
        target.unlink()
        alias = self.base / "alias"
        alias.symlink_to(source)
        target.symlink_to(alias)
        self.assertEqual(self.run_lns("foo").stdout, "foo -> already symlinked\n")

    def test_parent_link_already_covers_entry(self):
        self.source(".config/foo")
        (self.home / ".config").symlink_to(self.root / ".config")
        self.assertEqual(
            self.run_lns(".config/foo").stdout, ".config/foo -> already symlinked\n"
        )
        self.assertFalse((self.root / ".config/foo").is_symlink())

    def test_link_target_relative_to_physical_parent(self):
        source = self.source(".config/foo")
        elsewhere = self.base / "external/config"
        elsewhere.mkdir(parents=True)
        (self.home / ".config").symlink_to(elsewhere)
        result = self.run_lns(".config/foo")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual((elsewhere / "foo").resolve(), source)
        self.assertFalse(os.path.isabs(os.readlink(elsewhere / "foo")))

    def test_conflicts_preserve_files_directories_and_links(self):
        for name in ("file", "directory", "link", "dangling", "loop"):
            self.source(name)
        (self.home / "file").write_text("keep")
        (self.home / "directory").mkdir()
        (self.home / "link").symlink_to(self.home / "file")
        (self.home / "dangling").symlink_to("missing")
        (self.home / "loop").symlink_to("loop")
        result = self.run_lns("file", "directory", "link", "dangling", "loop")
        self.assertEqual(result.returncode, 1)
        self.assertIn("file -> conflict (regular file)", result.stdout)
        self.assertIn("directory -> conflict (regular directory)", result.stdout)
        self.assertIn("dangling -> conflict (symlinked to missing)", result.stdout)
        self.assertIn("loop -> conflict (symlinked to loop)", result.stdout)
        self.assertEqual((self.home / "file").read_text(), "keep")
        self.assertEqual(os.readlink(self.home / "dangling"), "missing")

    def test_home_path_does_not_follow_wrong_leaf_link(self):
        self.source("foo")
        other = self.source("bar")
        (self.home / "foo").symlink_to(other)
        result = self.run_lns(self.home / "foo")
        self.assertIn("foo -> conflict (symlinked to ", result.stdout)
        self.assertEqual((self.home / "foo").resolve(), other)

    def test_missing_source_and_non_directory_parent_continue(self):
        self.source("blocked/foo")
        self.source("good")
        (self.home / "blocked").write_text("keep")
        result = self.run_lns("absent", "blocked/foo", "good")
        self.assertEqual(result.returncode, 1)
        self.assertIn("absent -> ENOENT", result.stdout)
        self.assertIn("blocked/foo -> ENOTDIR", result.stdout)
        self.assertIn("good -> symlinked", result.stdout)

    def test_reject_root_and_unrelated_absolute_paths(self):
        for argument in (
            ".",
            str(self.root),
            str(self.home),
            str(self.base / "outside"),
        ):
            with self.subTest(argument=argument):
                result = self.run_lns(argument)
                self.assertEqual(result.returncode, 1)
                self.assertIn(" -> EINVAL", result.stdout)

    def test_symlink_creation_error_propagates_errno(self):
        self.source("foo")
        with patch.object(
            lns.os, "symlink", side_effect=OSError(errno.EIO, "I/O error")
        ):
            with self.assertRaises(OSError) as error:
                lns.link_entry(Path("foo"), self.root, self.home)
        self.assertEqual(error.exception.errno, errno.EIO)
        self.assertFalse((self.home / "foo").exists())

    def test_main_reports_io_errno(self):
        self.source("foo")
        output = io.StringIO()
        with patch.object(lns, "__file__", str(self.root / "lns")), patch.object(
            lns.Path, "home", return_value=self.home
        ), patch.object(
            lns.os, "symlink", side_effect=OSError(errno.EIO, "I/O error")
        ), contextlib.redirect_stdout(
            output
        ):
            self.assertEqual(lns.main(["foo"]), 1)
        self.assertEqual(output.getvalue(), "foo -> EIO\n")

    def test_destination_race_does_not_overwrite(self):
        self.source("foo")

        def create_other_then_fail(*args):
            (self.home / "foo").write_text("racing writer")
            raise FileExistsError(errno.EEXIST, "already exists")

        with patch.object(lns.os, "symlink", side_effect=create_other_then_fail):
            self.assertEqual(
                lns.link_entry(Path("foo"), self.root, self.home),
                "conflict (regular file)",
            )
        self.assertEqual((self.home / "foo").read_text(), "racing writer")


if __name__ == "__main__":
    unittest.main()
