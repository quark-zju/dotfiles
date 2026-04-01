## ALWAYS COMMIT

**Always create a `git commit`** after code changes, even if the user didn't ask.

### Commit small

Break work down into multiple small atomic commits. One small step one commit.

If the user uses bullet points, then probably each bullet point is at least one commit.

Even one line change, as long as a single logical unit, is a commit.

Do: "reformat code", "move my_function from a.py to b.py", "modify my_function" as 3 commits.
Do not: "reformat and move my_function and modify it".

### Commit message = Title + Body

**Always use `git commit -m 'TITLE' -m 'User request: TEXT' -m 'Decision: TEXT'`**.
* Title: `<type|area>: <summary>`
* Body: You MUST include BOTH: 1. A brief overview of the USER REQUEST. 2. The core decision-making logic (focus on *Why* than *What*).
* Caution: Avoid backticks (`` ` ``) - they trigger shell command substitution! Use `"` or `'` instead.

## PAUSE IF STUCK

If you make little to no progress after 15 consecutive attempts, halt execution and prompt the user for guidance.

## SAVE CONTEXT

Avoid large outputs. Prefer `git diff --stat` to `git diff`. Prefer `cargo test -q` to `cargo test`. Use `| head -n 30` to bound output length.
