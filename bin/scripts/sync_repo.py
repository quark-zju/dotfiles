#!/usr/bin/env python3
"""Synchronize the current Git branch with a repo through ssh_sync."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import ssh_sync


class SyncError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="sync the current Git branch with a remote repo"
    )
    parser.add_argument("local_path", nargs="?", metavar="LOCAL_PATH")
    parser.add_argument(
        "--remote-path",
        metavar="PATH",
        help="remote repo path (default: LOCAL_PATH)",
    )
    parser.add_argument(
        "--remote",
        metavar="USER@HOST",
        help="ssh_sync host (default: first running host)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print ssh_sync operations before running them",
    )
    return parser.parse_args()


def abbreviated_cwd() -> str:
    cwd = os.getcwd()
    home = os.path.expanduser("~")
    try:
        relative = os.path.relpath(cwd, home)
    except ValueError:
        return cwd
    if relative == ".":
        return "~"
    if relative != ".." and not relative.startswith(".." + os.sep):
        return os.path.join("~", relative)
    return cwd


def run_git(repo: Path, *args: str, input: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = completed.stderr.decode(errors="replace").strip()
        if not detail:
            detail = completed.stdout.decode(errors="replace").strip()
        raise SyncError(detail or "git %s failed" % args[0])
    return completed.stdout


def local_repo(path: str) -> tuple[Path, str, str]:
    repo = Path(path).expanduser().resolve()
    try:
        root = Path(run_git(repo, "rev-parse", "--show-toplevel").decode().strip())
    except (OSError, SyncError) as error:
        raise SyncError(f"{path}: not a Git repository") from error
    if not os.path.samefile(repo, root):
        raise SyncError(f"{path}: not the Git repository root ({root})")
    try:
        branch = run_git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
        tip = run_git(repo, "rev-parse", "--verify", "HEAD")
    except SyncError as error:
        raise SyncError(f"{repo}: HEAD must be an existing local branch") from error
    return repo, branch.decode().strip(), tip.decode().strip()


def remote_repo_info(path: str, branch: str) -> dict[str, str | None]:
    import os
    import subprocess

    path = os.path.realpath(os.path.expanduser(path))

    def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.run(
            ["git", "-C", path, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if check and completed.returncode:
            message = completed.stderr.decode(errors="replace").strip()
            raise RuntimeError(message or "git %s failed" % args[0])
        return completed

    root = git("rev-parse", "--show-toplevel").stdout.decode().strip()
    if os.path.realpath(root) != path:
        raise RuntimeError(f"{path}: not the Git repository root ({root})")
    ref = "refs/heads/" + branch
    tip_result = git("rev-parse", "--verify", ref, check=False)
    current_result = git("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    return {
        "path": path,
        "tip": (
            tip_result.stdout.decode().strip() if tip_result.returncode == 0 else None
        ),
        "current_branch": (
            current_result.stdout.decode().strip()
            if current_result.returncode == 0
            else None
        ),
    }


def remote_has_ancestor(path: str, ancestor: str, branch: str) -> bool:
    import subprocess

    completed = subprocess.run(
        [
            "git",
            "-C",
            path,
            "merge-base",
            "--is-ancestor",
            ancestor,
            "refs/heads/" + branch,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def remote_find_common(path: str, branch: str, candidates: list[str]) -> str | None:
    import subprocess

    ref = "refs/heads/" + branch
    for candidate in candidates:
        completed = subprocess.run(
            ["git", "-C", path, "merge-base", "--is-ancestor", candidate, ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return candidate
    return None


def remote_update_branch(
    path: str, branch: str, old_tip: str | None, new_tip: str
) -> dict[str, str | bool | None]:
    import subprocess

    ref = "refs/heads/" + branch

    def git(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "-C", path, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    current_result = git("symbolic-ref", "--quiet", "--short", "HEAD")
    current = (
        current_result.stdout.decode().strip()
        if current_result.returncode == 0
        else None
    )
    if current == branch:
        completed = git("merge", "--ff-only", "--quiet", new_tip)
        if completed.returncode:
            message = completed.stderr.decode(errors="replace").strip()
            raise RuntimeError(
                message or "could not fast-forward the checked-out branch"
            )
        return {
            "checked_out": True,
            "checkout_changed": False,
            "checkout_error": None,
        }

    update_args = ["update-ref", ref, new_tip]
    if old_tip is not None:
        update_args.append(old_tip)
    completed = git(*update_args)
    if completed.returncode:
        message = completed.stderr.decode(errors="replace").strip()
        raise RuntimeError(message or "could not update " + ref)

    checkout = git("checkout", "--quiet", branch)
    if checkout.returncode:
        message = checkout.stderr.decode(errors="replace").strip()
        return {
            "checked_out": False,
            "checkout_changed": False,
            "checkout_error": message,
        }
    return {"checked_out": True, "checkout_changed": True, "checkout_error": None}


def ssh_call(remote: str, function, *args, verbose: bool):
    if verbose:
        print(f"ssh_sync: {remote}: call {function.__name__}()")
    return ssh_sync.call_remote(remote, function, *args)


def ssh_process(remote: str, argv: list[str], *, cwd: str, verbose: bool):
    if verbose:
        print(f"ssh_sync: {remote}: run {shlex.join(argv)} (cwd {cwd})")
    return ssh_sync.open_process(remote, argv, cwd=cwd)


def first_remote(verbose: bool) -> str:
    if verbose:
        print("ssh_sync: list_hosts()")
    hosts = ssh_sync.list_hosts()
    if not hosts:
        raise SyncError("no running ssh_sync remote; pass --remote or start one")
    return hosts[0]


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode == 0


def find_common(
    repo: Path, remote: str, remote_path: str, branch: str, verbose: bool
) -> str:
    commits = run_git(repo, "rev-list", "--first-parent", branch).decode().splitlines()
    batch_size = 512
    for offset in range(0, len(commits), batch_size):
        common = ssh_call(
            remote,
            remote_find_common,
            remote_path,
            branch,
            commits[offset : offset + batch_size],
            verbose=verbose,
        )
        if common is not None:
            return common
    raise SyncError("the two branch histories have no common commit")


def receive_bundle(
    repo: Path,
    remote: str,
    remote_path: str,
    branch: str,
    base: str | None,
    verbose: bool,
) -> None:
    ref = "refs/heads/" + branch
    argv = ["git", "bundle", "create", "-", ref]
    if base is not None:
        argv.append("^" + base)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        local = subprocess.Popen(
            ["git", "-C", str(repo), "bundle", "unbundle", "-"],
            stdin=subprocess.PIPE,
            stdout=output,
            stderr=errors,
        )
        assert local.stdin is not None
        remote_errors = bytearray()
        try:
            with ssh_process(remote, argv, cwd=remote_path, verbose=verbose) as process:
                process.close_stdin()
                for event in process:
                    if event.stream == "stdout":
                        local.stdin.write(event.data)
                    else:
                        remote_errors.extend(event.data)
                local.stdin.close()
                local.stdin = None
                local.wait()
                if process.returncode:
                    raise SyncError(
                        remote_errors.decode(errors="replace").strip()
                        or "remote git bundle create failed"
                    )
        except BaseException:
            if local.stdin is not None:
                local.stdin.close()
            local.wait()
            raise
        if local.returncode:
            errors.seek(0)
            raise SyncError(
                errors.read().decode(errors="replace").strip()
                or "local git bundle unbundle failed"
            )


def send_bundle(
    repo: Path,
    remote: str,
    remote_path: str,
    branch: str,
    base: str | None,
    verbose: bool,
) -> None:
    ref = "refs/heads/" + branch
    argv = ["git", "-C", str(repo), "bundle", "create", "-", ref]
    if base is not None:
        argv.append("^" + base)
    with tempfile.TemporaryFile() as local_errors:
        local = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=local_errors)
        assert local.stdout is not None
        remote_errors = bytearray()
        with ssh_process(
            remote,
            ["git", "bundle", "unbundle", "-"],
            cwd=remote_path,
            verbose=verbose,
        ) as process:
            with local.stdout:
                while data := local.stdout.read(64 * 1024):
                    process.send(data)
            process.close_stdin()
            for event in process:
                if event.stream == "stderr":
                    remote_errors.extend(event.data)
        local.wait()
        if local.returncode:
            local_errors.seek(0)
            raise SyncError(
                local_errors.read().decode(errors="replace").strip()
                or "local git bundle create failed"
            )
        if process.returncode:
            raise SyncError(
                remote_errors.decode(errors="replace").strip()
                or "remote git bundle unbundle failed"
            )


def update_remote(
    repo: Path,
    remote: str,
    remote_path: str,
    branch: str,
    old_tip: str | None,
    new_tip: str,
    verbose: bool,
) -> None:
    send_bundle(repo, remote, remote_path, branch, old_tip, verbose)
    result = ssh_call(
        remote,
        remote_update_branch,
        remote_path,
        branch,
        old_tip,
        new_tip,
        verbose=verbose,
    )
    old = old_tip[:12] if old_tip is not None else "new branch"
    print(f"remote: updated {branch} ({old} -> {new_tip[:12]})")
    if result["checkout_changed"]:
        print(f"remote: checked out {branch}")
    elif not result["checked_out"]:
        detail = result["checkout_error"] or "working tree would be overwritten"
        print(f"remote: kept the existing checkout: {detail}")


def sync(
    local_path: str, remote_path: str, remote: str | None, verbose: bool = False
) -> None:
    repo, branch, local_tip = local_repo(local_path)
    remote = remote or first_remote(verbose)
    info = ssh_call(remote, remote_repo_info, remote_path, branch, verbose=verbose)
    remote_path = str(info["path"])
    remote_tip = info["tip"]
    print(f"sync: {repo} <-> {remote}:{remote_path} ({branch})")

    if remote_tip == local_tip:
        return
    if remote_tip is None:
        update_remote(repo, remote, remote_path, branch, None, local_tip, verbose)
        return

    if is_ancestor(repo, remote_tip, local_tip):
        update_remote(repo, remote, remote_path, branch, remote_tip, local_tip, verbose)
        return

    if ssh_call(
        remote,
        remote_has_ancestor,
        remote_path,
        local_tip,
        branch,
        verbose=verbose,
    ):
        receive_bundle(repo, remote, remote_path, branch, local_tip, verbose)
        run_git(repo, "merge", "--ff-only", "--quiet", remote_tip)
        print(f"local: fast-forwarded {branch} ({local_tip[:12]} -> {remote_tip[:12]})")
        return

    common = find_common(repo, remote, remote_path, branch, verbose)
    receive_bundle(repo, remote, remote_path, branch, common, verbose)
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "rebase",
            "--onto",
            remote_tip,
            common,
            branch,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = completed.stderr.decode(errors="replace").strip()
        print(
            f"local: rebase of {branch} stopped; remote was not changed",
            file=sys.stderr,
        )
        raise SyncError(
            detail or "resolve the conflicts, then continue or abort the rebase"
        )
    rebased_tip = run_git(repo, "rev-parse", "--verify", branch).decode().strip()
    print(
        f"local: rebased {branch} onto remote "
        f"({local_tip[:12]} -> {rebased_tip[:12]})"
    )
    update_remote(repo, remote, remote_path, branch, remote_tip, rebased_tip, verbose)


def main() -> int:
    args = parse_args()
    local_path = args.local_path if args.local_path is not None else abbreviated_cwd()
    remote_path = args.remote_path if args.remote_path is not None else local_path
    try:
        sync(local_path, remote_path, args.remote, args.verbose)
    except (
        OSError,
        SyncError,
        ssh_sync.RemoteError,
        RuntimeError,
        TimeoutError,
    ) as error:
        print(f"sync_repo.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
