## Automatic commit
After changing a repo, commit by default:
`git commit -m 'topic: title' -m 'User request: ...' -m 'Decision: ...'`

Prefer small, single-logic commits (e.g. move and modify = 2 commits).
Add `-m 'Result: ...'` for meaningful data not tracked in the repo (e.g. benchmark changes).

Note: under the codex sandbox `git add` can't write `.git/index.lock` - ask for permission.

## Missing tools
Don't search broad dirs like `~` or `/` for tools not on `PATH`; ask the user to install missing tools.

## Use sub-agents
Do not start sub-agents unless you have confirmed that you are the `gpt-6-astra` model.

If you are `gpt-6-astra`, offload tasks to `gpt-5.6-luna` and keep the difficult reasoning to yourself. Luna is 50x cheaper and reasonably capable. Context resend ≈ 85% of cost. So try aggressively offloading your round-trips to Luna.
For example, Luna can batch `cargo build`/`test`/`fmt`, `rg` reads, `git log` archaeology, benchmark runs + result parsing, and edit/commit based on high-level ideas.
When sub-agents are running, do useful independent work or call `wait_agent` with a long timeout; don't poll, emit filler updates, or invent work.

## Format code
Rust: `cargo fmt`. Python: `black` - one file per run (multi-file can stall under the sandbox).
Only format before committing. Consider chaining `cargo fmt && git commit ...` to reduce round-trip.

## Avoid shortcuts
For algorithmic optimization, don't take shortcuts that only fit the visible tests or narrow special cases.

## Code investigation
To understand a 3rd-party project, `git clone` to `~/src/3p/` and read locally.
For large repos (>2GB or >10 min), use `--filter=blob:none`, never `--depth`.

## Linux (external sandbox)
`leash` may hide/deny file access by process+path; notably `.git` is only fully visible/writable by the `git` process.
