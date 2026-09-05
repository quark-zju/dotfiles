## Automatic commit
After changing a repo, commit by default:
`git commit -m 'topic: title' -m 'User request: ...' -m 'Decision: ...'`

Prefer small, single-logic commits (e.g. move and modify = 2 commits).
Add `-m 'Result: ...'` for meaningful data not tracked in the repo (e.g. benchmark changes).
Note: under the codex sandbox `git add` can't write `.git/index.lock` - ask for permission.

## Missing tools
Don't search broad dirs like `~` or `/` for tools not on `PATH`; ask the user to install missing tools.

## Use sub-agents (offload)
If you are GPT-6 Astra, offload boring execution to `gpt-5.6-luna` and keep the reasoning to yourself. Luna's context is ~3x smaller, so every task you hand off spares a big round-trip.

Hand off whole, self-contained jobs (goal + scope + acceptance) — avoid steering via repeated follow-ups. Typical Luna fodder: batch `cargo build`/`test`/`fmt`, repo-wide `rg` sweeps, `git log` archaeology, benchmark runs + result parsing.
Keep in your loop only what needs your judgment: read the relevant lines, then decide and edit. Don't ask Luna for a step you're about to edit.
Keep it async — keep working while it runs; block only on a true dependency. For tasks touching shared files, give Luna its own worktree/file set so you don't collide.

## Format code
Rust: `cargo fmt && cargo test -q`. Python: `black` - one file per run (multi-file can stall under the sandbox).

## Avoid shortcuts
For algorithmic optimization, don't take shortcuts that only fit the visible tests or narrow special cases.

## Code investigation
To understand a 3rd-party project, `git clone` to `~/src/3p/` and read locally.
For large repos (>2GB or >10 min), use `--filter=blob:none`, never `--depth`.

## Linux (external sandbox)
`leash` may hide/deny file access by process+path; notably `.git` is only fully visible/writable by the `git` process.
