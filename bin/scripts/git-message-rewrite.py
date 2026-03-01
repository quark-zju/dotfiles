#!/usr/bin/env python3
"""Rewrite git commit messages using a custom editor script.

Usage:
    git-message-rewrite.py --message-edit /path/to/script

The script reads each commit message, passes it to the --message-edit script
via stdin, and uses the stdout as the new commit message.
"""

import argparse
import subprocess
import sys


def get_commits():
    """Get all commit hashes and messages from current HEAD to the first commit."""
    result = subprocess.run(
        ["git", "log", "--format=%H%n%s%n%b", "--reverse"],
        capture_output=True,
        text=True,
        check=True,
    )
    commits = []
    lines = result.stdout.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i]:
            i += 1
            continue
        commit_hash = lines[i]
        i += 1
        if i >= len(lines):
            break
        subject = lines[i]
        i += 1
        body_lines = []
        while i < len(lines) and lines[i]:
            body_lines.append(lines[i])
            i += 1
        message = subject
        if body_lines:
            message = subject + "\n\n" + "\n".join(body_lines)
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
    message = b"\n".join(message_lines).decode("utf-8", errors="replace")
    parent = None
    tree = None
    author = None
    committer = None
    for hl in header_lines:
        hl_str = hl.decode("utf-8", errors="replace")
        if hl_str.startswith("tree "):
            tree = hl_str[5:]
        elif hl_str.startswith("parent "):
            parent = hl_str[7:]
        elif hl_str.startswith("author "):
            author = hl_str[7:]
        elif hl_str.startswith("committer "):
            committer = hl_str[10:]
    return {
        "tree": tree,
        "parent": parent,
        "author": author,
        "committer": committer,
        "message": message,
    }


def create_commit(tree, parent, author, committer, message):
    """Create a new commit object and return its hash."""
    parent_line = f"parent {parent}\n" if parent else ""
    commit_data = (
        f"tree {tree}\n"
        f"{parent_line}"
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


def call_message_edit(edit_script, message):
    """Call the edit script with message on stdin, return new message or None."""
    try:
        result = subprocess.run(
            [edit_script],
            input=message,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"Warning: {edit_script} exited with code {result.returncode}", file=sys.stderr)
            return None
        new_message = result.stdout.rstrip("\n")
        if not new_message:
            print(f"Warning: {edit_script} returned empty message", file=sys.stderr)
            return None
        return new_message
    except subprocess.TimeoutExpired:
        print(f"Warning: {edit_script} timed out", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: Error calling {edit_script}: {e}", file=sys.stderr)
        return None


def rewrite_commit_message(commit_hash, new_message, new_parent):
    """Rewrite a commit with a new message and new parent, preserving other info."""
    raw = get_commit_raw(commit_hash)
    parsed = parse_commit_raw(raw)
    new_hash = create_commit(
        parsed["tree"],
        new_parent,
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
    args = parser.parse_args()

    commits = get_commits()
    if not commits:
        print("No commits found.", file=sys.stderr)
        sys.exit(1)

    hash_mapping = {}
    for old_hash, old_message in commits:
        raw = get_commit_raw(old_hash)
        parsed = parse_commit_raw(raw)
        old_parent = parsed["parent"]

        new_parent = hash_mapping.get(old_parent, old_parent) if old_parent else None

        new_message = call_message_edit(args.message_edit, old_message)
        if new_message is None:
            new_hash = old_hash
        elif new_message == old_message and new_parent == old_parent:
            new_hash = old_hash
        else:
            new_hash = rewrite_commit_message(old_hash, new_message, new_parent)
            hash_mapping[old_hash] = new_hash

        if old_hash != new_hash:
            hash_mapping[old_hash] = new_hash
        print(f"{old_hash} -> {new_hash}")


if __name__ == "__main__":
    main()
