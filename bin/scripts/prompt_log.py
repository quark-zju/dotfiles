#!/usr/bin/env python3
"""Log and search Claude Code prompts in a sqlite database.

Hook mode (stdin is not a tty, no args):
    Reads UserPromptSubmit JSON from stdin, stores prompt in
    ~/.local/state/prompts/claude.sqlite3

Standalone mode:
    prompt_log.py [PATTERN] [--cwd CWD] [--session SESSION_ID]
    Searches prompts. Prints matched prompt text to stdout,
    metadata (cwd, timestamp, session_id) to stderr.
    If multiple matches on a tty, shows the latest N and asks
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
import io
import json
import os
import shlex
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def get_terminal_width():
    """Get terminal width, defaulting to 80 if not a tty."""
    return shutil.get_terminal_size().columns or 80


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


def search(pattern=None, cwd=None, session_id=None, limit=None):
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
        clauses.append("session_id LIKE ?")
        params.append(f"{session_id}%")

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM prompts{where} ORDER BY timestamp DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def print_row(row, output_file=None):
    """Print prompt to stdout (and file if specified), metadata to stderr."""
    sys.stderr.flush()
    print(row["prompt"], end="")
    sys.stdout.flush()
    if output_file:
        with open(output_file, "w") as f:
            f.write(row["prompt"])
        sys.stdout.flush()
    meta = f"session_id: {row['session_id']}  cwd: {row['cwd']}  timestamp: {row['timestamp']}"
    if sys.stderr.isatty():
        meta = f"\033[90m{meta}\033[0m"
    print(f"\n{meta}", file=sys.stderr)


def format_preview(row, max_width):
    """Single-line preview of prompt text (truncated, newlines collapsed)."""
    preview = row["prompt"].replace("\n", " ")
    if len(preview) > max_width:
        preview = preview[: max_width - 3] + "..."
    return preview


def format_match_context(row, query, max_width):
    """Return a context snippet around the first match if it's beyond the truncated preview.

    Returns None if the match is already visible in the preview or there's no match.
    """
    if not query:
        return None
    flat = row["prompt"].replace("\n", " ")
    if len(flat) <= max_width:
        return None  # preview isn't truncated, match is visible
    # Check if match is visible in the truncated portion
    visible = flat[: max_width - 3]
    if query.lower() in visible.lower():
        return None
    # Find the match position in the full text
    idx = flat.lower().find(query.lower())
    if idx == -1:
        return None
    # Extract a window around the match
    context_width = max_width - 6  # room for "..." on each side
    start = max(0, idx - context_width // 2)
    end = min(len(flat), start + context_width)
    if start > 0:
        start = min(start, end - context_width)
        start = max(0, start)
    snippet = flat[start:end]
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(flat) else ""
    return f"{prefix}{snippet}{suffix}"


def format_meta(row):
    """Metadata line: session=... cwd=... ts=..."""
    return f"session={row['session_id']}  cwd={row['cwd']}  ts={row['timestamp']}"


def interactive_pick(rows, limit=20, output_file=None, query=None):
    """Show latest `limit` matches, let user pick one."""
    rows = rows[:limit]
    for i, row in enumerate(rows):
        preview = format_preview(row, get_terminal_width())
        meta = format_meta(row)
        ctx = format_match_context(row, query, get_terminal_width())
        ctx_line = f"\n    > {ctx}" if ctx else ""
        print(f"[{i}] {preview}{ctx_line}\n    {meta}", file=sys.stderr)
    print(file=sys.stderr)
    try:
        choice = input("Pick a number [0]: ")
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)
    idx = int(choice) if choice.strip() else 0
    if not 0 <= idx < len(rows):
        print("Invalid choice.", file=sys.stderr)
        sys.exit(1)
    print_row(rows[idx], output_file=output_file)


def highlight_fragments(text, query, style_match="class:match", style_plain=""):
    """Split text into (style, substring) fragments, highlighting query matches."""
    if not query:
        return [(style_plain, text)]
    fragments = []
    lower_text = text.lower()
    lower_query = query.lower()
    pos = 0
    while pos < len(text):
        idx = lower_text.find(lower_query, pos)
        if idx == -1:
            fragments.append((style_plain, text[pos:]))
            break
        if idx > pos:
            fragments.append((style_plain, text[pos:idx]))
        fragments.append((style_match, text[idx : idx + len(query)]))
        pos = idx + len(query)
    return fragments


def interactive_pick_pt(initial_args, rows, limit=20):
    """Interactive picker using prompt_toolkit. Returns a Row or None."""
    from prompt_toolkit import Application
    from prompt_toolkit.buffer import Buffer
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension as D
    from prompt_toolkit.layout.layout import Layout
    from prompt_toolkit.styles import Style
    from prompt_toolkit.widgets import TextArea

    state = {"selected": 0, "rows": rows[:limit], "query": "", "error": False}

    def reparse(text):
        """Parse input text and re-run search."""
        search_parser = argparse.ArgumentParser(add_help=False)
        search_parser.add_argument("pattern", nargs="?", default=None)
        search_parser.add_argument("-d", "--cwd", default=None)
        search_parser.add_argument("-s", "--session", default=None)
        try:
            tokens = shlex.split(text)
        except ValueError:
            state["error"] = True
            return  # unclosed quote, skip
        # Suppress argparse error output to stderr
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            parsed, _ = search_parser.parse_known_intermixed_args(tokens)
        except SystemExit:
            state["error"] = True
            return
        finally:
            sys.stderr = old_stderr
        state["error"] = False
        new_rows = search(
            pattern=parsed.pattern,
            cwd=parsed.cwd,
            session_id=parsed.session,
            limit=limit,
        )
        # Try to keep the same row selected
        old_row = state["rows"][state["selected"]] if state["rows"] else None
        state["rows"] = new_rows
        state["query"] = parsed.pattern or ""
        if old_row and new_rows:
            old_id = old_row["id"]
            for i, r in enumerate(new_rows):
                if r["id"] == old_id:
                    state["selected"] = i
                    return
        state["selected"] = 0

    def get_results_fragments():
        frags = []
        for i, row in enumerate(state["rows"]):
            preview = format_preview(row, get_terminal_width())
            meta = format_meta(row)
            ctx = format_match_context(row, state["query"], get_terminal_width())
            is_selected = i == state["selected"]
            marker = "[*]" if is_selected else "[ ]"
            prefix_style = "class:selected" if is_selected else ""
            frags.append((prefix_style, f" {marker} "))
            # Highlight query matches in preview
            pstyle = "class:selected" if is_selected else ""
            mstyle = "class:selected.match" if is_selected else "class:match"
            frags.extend(highlight_fragments(preview, state["query"], mstyle, pstyle))
            frags.append(("", "\n"))
            if ctx:
                frags.append(("", "     > "))
                frags.extend(highlight_fragments(ctx, state["query"], mstyle, ""))
                frags.append(("", "\n"))
            frags.append(("class:meta", f"     {meta}\n"))
        if not state["rows"]:
            frags.append(("class:meta", " No matches.\n"))
        return frags

    def get_prompt_fragments():
        if state["error"]:
            return [("class:error", " > ")]
        return [("", " > ")]

    text_area = TextArea(
        text=initial_args,
        multiline=False,
        get_line_prefix=lambda line, wrap_count: get_prompt_fragments(),
    )
    text_area.buffer.cursor_position = len(initial_args)

    results_control = FormattedTextControl(text=get_results_fragments)
    results_window = Window(content=results_control, height=D(max=42), wrap_lines=False)

    root = HSplit([text_area, results_window])
    layout = Layout(root, focused_element=text_area)

    style = Style.from_dict(
        {
            "selected": "bg:ansiblue fg:ansiwhite bold",
            "selected.match": "bg:ansiblue fg:ansiyellow bold",
            "match": "fg:ansiyellow bold",
            "meta": "fg:ansibrightblack",
            "error": "fg:ansired bold",
        }
    )

    kb = KeyBindings()

    @kb.add("tab")
    @kb.add("down")
    def _(event):
        if state["rows"]:
            state["selected"] = (state["selected"] + 1) % len(state["rows"])

    @kb.add("s-tab")
    @kb.add("up")
    def _(event):
        if state["rows"]:
            state["selected"] = (state["selected"] - 1) % len(state["rows"])

    @kb.add("enter")
    def _(event):
        if state["rows"]:
            event.app.exit(result=state["rows"][state["selected"]])
        else:
            event.app.exit(result=None)

    @kb.add("c-c")
    @kb.add("c-d")
    def _(event):
        event.app.exit(result=None)

    def on_text_changed(buf):
        reparse(buf.text)

    text_area.buffer.on_text_changed += on_text_changed

    app = Application(
        layout=layout,
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=True,
    )
    return app.run()


def main():
    if not sys.stdin.isatty() and len(sys.argv) == 1:
        # Hook mode: no args and stdin is piped
        hook_mode()
        return

    parser = argparse.ArgumentParser(description="Search logged Claude prompts.")
    parser.add_argument("pattern", nargs="?", help="Substring to match in prompt text")
    parser.add_argument("-d", "--cwd", help="Filter by working directory")
    parser.add_argument("-s", "--session", help="Filter by session ID")
    parser.add_argument("-o", "--output", help="Write selected prompt to file")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results (default: 20)",
    )
    args, _ = parser.parse_known_intermixed_args()

    rows = search(
        pattern=args.pattern, cwd=args.cwd, session_id=args.session, limit=args.limit
    )

    if not rows:
        print("No matches.", file=sys.stderr)
        sys.exit(1)

    if len(rows) == 1:
        print_row(rows[0], output_file=args.output)
    elif sys.stdout.isatty():
        # Build initial args string for the picker
        parts = []
        if args.pattern:
            parts.append(args.pattern)
        if args.cwd:
            parts.extend(["--cwd", args.cwd])
        if args.session:
            parts.extend(["--session", args.session])
        initial_args = shlex.join(parts) if parts else ""

        try:
            from prompt_toolkit import Application  # noqa: F401

            result = interactive_pick_pt(initial_args, rows, limit=args.limit)
            if result is None:
                sys.exit(1)
            print_row(result, output_file=args.output)
        except ImportError:
            interactive_pick(
                rows, limit=args.limit, output_file=args.output, query=args.pattern
            )
    else:
        # Not a tty, just print the latest match
        print_row(rows[0], output_file=args.output)


if __name__ == "__main__":
    main()
