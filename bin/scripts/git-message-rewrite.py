#!/usr/bin/env python3
"""Rewrite git commit messages using a custom editor script.

Usage:
    git-message-rewrite.py --message-edit /path/to/script [--since HASH]

The script reads each commit message, passes it to the --message-edit script
via stdin, and uses the stdout as the new commit message.

Options:
    --since HASH    Stop at the specified commit (will not include it)
"""

import argparse
import subprocess
import sys


def get_commits(since=None):
    """Get all commit hashes and messages from current HEAD to the first commit."""
    cmd = ["git", "rev-list", "--reverse", "--format=%H"]
    if since:
        cmd.append(f"{since}..HEAD")
    else:
        cmd.append("HEAD")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    commits = []
    lines = result.stdout.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].startswith("commit "):
            i += 1
            continue
        commit_hash = lines[i][7:]
        i += 1
        if i >= len(lines):
            break
        raw = get_commit_raw(commit_hash)
        parsed = parse_commit_raw(raw)
        message = parsed["message"]
        commits.append((commit_hash, message))
    return commits


def get_commit_raw(commit_hash):
    """Get raw commit object content."""
    result = subprocess.run(
        ["git", "cat-file", "commit", commit_hash],
        capture_output=True,
        check=True,
    )
    return result.stdout


def parse_commit_raw(raw):
    """Parse raw commit object into components."""
    lines = raw.split(b"\n")
    i = 0
    while i < len(lines) and lines[i]:
        i += 1
    header_lines = lines[:i]
    message_lines = lines[i + 1:] if i < len(lines) else []
    message = b"\n".join(message_lines).decode("utf-8", errors="replace").rstrip("\n")
    parents = []
    tree = None
    author = None
    committer = None
    for hl in header_lines:
        hl_str = hl.decode("utf-8", errors="replace")
        if hl_str.startswith("tree "):
            tree = hl_str[5:]
        elif hl_str.startswith("parent "):
            parents.append(hl_str[7:])
        elif hl_str.startswith("author "):
            author = hl_str[7:]
        elif hl_str.startswith("committer "):
            committer = hl_str[10:]
    return {
        "tree": tree,
        "parents": parents,
        "author": author,
        "committer": committer,
        "message": message,
    }


def create_commit(tree, parents, author, committer, message):
    """Create a new commit object and return its hash."""
    parent_lines = "".join(f"parent {p}\n" for p in parents)
    commit_data = (
        f"tree {tree}\n"
        f"{parent_lines}"
        f"author {author}\n"
        f"committer {committer}\n"
        f"\n{message}"
    ).encode("utf-8")
    result = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
        input=commit_data,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip().decode("utf-8")


def call_message_edit(edit_script, message, orig_commit):
    """Call the edit script with message on stdin, return new message."""
    env = {"ORIG_COMMIT": orig_commit}
    try:
        result = subprocess.run(
            [edit_script],
            input=message,
            capture_output=True,
            text=True,
            timeout=30,
            env={**__import__("os").environ, **env},
        )
        if result.returncode != 0:
            raise RuntimeError(f"{edit_script} exited with code {result.returncode}")
        new_message = result.stdout.rstrip("\n")
        if not new_message:
            raise RuntimeError(f"{edit_script} returned empty message")
        return new_message
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{edit_script} timed out")


def rewrite_commit_message(commit_hash, new_message, new_parents):
    """Rewrite a commit with a new message and new parents, preserving other info."""
    raw = get_commit_raw(commit_hash)
    parsed = parse_commit_raw(raw)
    new_hash = create_commit(
        parsed["tree"],
        new_parents,
        parsed["author"],
        parsed["committer"],
        new_message,
    )
    return new_hash


def main():
    parser = argparse.ArgumentParser(description="Rewrite git commit messages")
    parser.add_argument(
        "--message-edit",
        required=True,
        help="Path to executable script that edits commit messages",
    )
    parser.add_argument(
        "--since",
        help="Stop at the specified commit (will not include it)",
    )
    args = parser.parse_args()

    commits = get_commits(args.since)
    if not commits:
        print("No commits found.", file=sys.stderr)
        sys.exit(1)

    hash_mapping = {}
    for old_hash, old_message in commits:
        raw = get_commit_raw(old_hash)
        parsed = parse_commit_raw(raw)
        old_parents = parsed["parents"]

        new_parents = [hash_mapping.get(p, p) for p in old_parents]

        orig_commit = old_hash.strip().lower()
        new_message = call_message_edit(args.message_edit, old_message, orig_commit)

        if new_message == old_message and new_parents == old_parents:
            new_hash = old_hash
        else:
            new_hash = rewrite_commit_message(old_hash, new_message, new_parents)
            hash_mapping[old_hash] = new_hash

        if old_hash != new_hash:
            hash_mapping[old_hash] = new_hash
        print(f"{old_hash} -> {new_hash}")


if __name__ == "__main__":
    main()
