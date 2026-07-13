## Always commit

When inside a git repo, **always create a `git commit`** after code changes, even if the user didn't ask.

### Commit small

Break work down into multiple small atomic commits. One small step one commit.

If the user uses bullet points, then probably each bullet point is at least one commit.

Even one line change, as long as a single logical unit, is a commit.

Do: "reformat code", "move my_function from a.py to b.py", "modify my_function" as 3 commits.
Do not: "reformat and move my_function and modify it".

### Commit message = Title + Body

Use `git commit -m 'TITLE' -m 'User request: TEXT' -m 'Decision: TEXT'`.

* Title: `<type|area>: <summary>`
* Body: You MUST include BOTH: 1. A brief overview of the USER REQUEST. 2. The core decision-making logic (focus on *Why* than *What*).
* Caution: Avoid backticks (`` ` ``) - they trigger shell command substitution! Use `"` or `'` instead.

## Ask for missing tools

When certain tools are missing, ask the user to install, or provide the path. Do not search through broad directories like `~` or `/` just to find tools not in `PATH`.

## Pause if stuck

If you make little to no progress after 15 consecutive attempts, halt execution and prompt the user for guidance.

## Save context

Avoid large outputs. Prefer `git diff --stat` to `git diff`. Prefer `cargo test -q` to `cargo test`. Use `| head -n 30` to bound output length.

## Format code

Run commands like `cargo fmt && cargo test -q`. Ensure code format before each commit.
Use `black` to format Python code.

## No cheating or shortcut solutions

For algorithmic optimization tasks, do not implement shortcuts that only work for the visible tests, known inputs, or narrow special cases unless explicitly requested.

If a general optimization is not clear, say so instead of submitting a shortcut patch.

## Environment instructions

On Linux, the current process might be under `leash` sandbox, it can deny access based on process and path. Namely, `.git` is only fully visible and writable by the `git` process.
