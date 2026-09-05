## Automatic commit
After changing a repo, commit by default:
`git commit -m 'topic: title' -m 'User request: ...' -m 'Decision: ...'`

Prefer small, single-logic commits (e.g. move and modify = 2 commits).
Add `-m 'Result: ...'` for meaningful data not tracked in the repo (e.g. benchmark changes).
Note: under the codex sandbox `git add` can't write `.git/index.lock` - ask for permission.

## Missing tools
Don't search broad dirs like `~` or `/` for tools not on `PATH`; ask the user to install missing tools.

## Use sub-agents (offload aggressively)
If you are GPT-6 Astra, offload execution to `gpt-5.6-luna` subagents and keep the hard reasoning to yourself. Luna carries a much smaller context (~40-50K vs your ~120-140K), so pushing mechanical work onto it cuts your expensive large-context round-trips.

To make offload actually pay off:
- Delegate in one self-contained shot: goal, scope, file list, acceptance check. Avoid dribbling instructions via repeated follow-ups — every steering round-trip still bills your full context.
- Offload heavy/boring shell to Luna: batch `cargo build/test/fmt`, multi-file `rg`, `git log` sweeps, benchmark runs, and result parsing/aggregation.
- Keep in your own loop only read-then-edit steps that need your reasoning (skim a file, then decide and edit). Don't split off a step that is tightly coupled to an edit you are about to make.
- Give subagents that touch shared mutable state their own worktree (or a disjoint file partition). Don't edit the same file a running subagent is editing — concurrent writes get lost or conflict.
- Keep subagents async and keep doing your own work while they run (that is the whole point). Only block/serialize when a step genuinely depends on a subagent's result.

## Format code
Rust: `cargo fmt && cargo test -q`. Python: `black` - one file per run (multi-file can stall under the sandbox).

## Avoid shortcuts
For algorithmic optimization, don't take shortcuts that only fit the visible tests or narrow special cases.

## Code investigation
To understand a 3rd-party project, `git clone` to `~/src/3p/` and read locally.
For large repos (>2GB or >10 min), use `--filter=blob:none`, never `--depth`.

## Linux (external sandbox)
`leash` may hide/deny file access by process+path; notably `.git` is only fully visible/writable by the `git` process.
