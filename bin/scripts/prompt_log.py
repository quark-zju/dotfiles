#!/usr/bin/env python3
"""Log and search Claude Code prompts in a sqlite database.

Hook mode (stdin is not a tty, no args):
    Reads UserPromptSubmit JSON from stdin, stores prompt in
    ~/.local/state/prompts/claude.sqlite3

Standalone mode:
    prompt_log.py [PATTERN] [--cwd CWD] [--session SESSION_ID]
    Searches prompts. Prints matched prompt text to stdout,
    metadata (cwd, timestamp, session_id) to stderr.
    If multiple matches on a tty, shows the latest 10 and asks
    which one to use.

Hook configuration (~/.claude/settings.json):
    {
      "hooks": {
        "UserPromptSubmit": [
          {
            "hooks": [
              {
                "type": "command",
                "command": "~/bin/scripts/prompt_log.py"
              }
            ]
          }
        ]
      }
    }
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path.home() / ".local" / "state" / "prompts" / "claude.sqlite3"

SCHEMA = """\
CREATE TABLE IF NOT EXISTS prompts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    cwd        TEXT    NOT NULL,
    prompt     TEXT    NOT NULL,
    timestamp  TEXT    NOT NULL
);
"""


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def hook_mode():
    """Read UserPromptSubmit JSON from stdin, store in db."""
    data = json.load(sys.stdin)
    conn = get_db()
    conn.execute(
        "INSERT INTO prompts (session_id, cwd, prompt, timestamp) VALUES (?, ?, ?, ?)",
        (
            data.get("session_id", ""),
            data.get("cwd", ""),
            data.get("prompt", ""),
            datetime.now().astimezone().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def search(pattern=None, cwd=None, session_id=None):
    """Search prompts, return list of Row objects."""
    conn = get_db()
    clauses = []
    params = []
    if pattern:
        clauses.append("prompt LIKE ?")
        params.append(f"%{pattern}%")
    if cwd:
        clauses.append("cwd LIKE ?")
        params.append(f"%{cwd}%")
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM prompts{where} ORDER BY timestamp DESC", params
    ).fetchall()
    conn.close()
    return rows


def print_row(row):
    """Print prompt to stdout, metadata to stderr."""
    sys.stderr.flush()
    print(row["prompt"], end="")
    sys.stdout.flush()
    print(
        f"\n\nsession_id: {row['session_id']}  cwd: {row['cwd']}  timestamp: {row['timestamp']}",
        file=sys.stderr,
    )


def interactive_pick(rows, limit=20):
    """Show latest `limit` matches, let user pick one."""
    rows = rows[:limit]
    for i, row in enumerate(rows):
        preview = row["prompt"].replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        print(
            f"[{i}] {preview}\n"
            f"    session={row['session_id']}  cwd={row['cwd']}  ts={row['timestamp']}",
            file=sys.stderr,
        )
    print(file=sys.stderr)
    try:
        choice = input("Pick a number [0]: ")
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    idx = int(choice) if choice.strip() else 0
    if not 0 <= idx < len(rows):
        print("Invalid choice.", file=sys.stderr)
        sys.exit(1)
    print_row(rows[idx])


def main():
    if not sys.stdin.isatty() and len(sys.argv) == 1:
        # Hook mode: no args and stdin is piped
        hook_mode()
        return

    parser = argparse.ArgumentParser(description="Search logged Claude prompts.")
    parser.add_argument("pattern", nargs="?", help="Substring to match in prompt text")
    parser.add_argument("--cwd", help="Filter by working directory")
    parser.add_argument("--session", help="Filter by session ID")
    args = parser.parse_args()

    rows = search(pattern=args.pattern, cwd=args.cwd, session_id=args.session)

    if not rows:
        print("No matches.", file=sys.stderr)
        sys.exit(1)

    if len(rows) == 1:
        print_row(rows[0])
    elif sys.stdout.isatty():
        interactive_pick(rows)
    else:
        # Not a tty, just print the latest match
        print_row(rows[0])


if __name__ == "__main__":
    main()
