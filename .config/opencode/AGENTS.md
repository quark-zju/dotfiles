## ALWAYS COMMIT

**Always create a `git commit`** after code changes, even if the user didn't ask.

## Commit small

Avoid big commit. Think ahead. Break work down into multiple small atomic commits.

If the commit title includes the word "and", it's an indication that the commit needs split.

Examples of atomic commits:
* Refactoring, code cleanup, or dependency updates made in preparation for a new feature.
* Modifying a single file (provided the code is runnable and does not break existing tests).

## Commit message = Title + Body

**Always use `git commit -m 'TITLE' -m 'User request: TEXT' -m 'Decision: TEXT'`**.
* Title: `<type|area>: <summary>`
* Body: You MUST include BOTH: 1. A brief overview of the USER REQUEST. 2. The core decision-making logic (focus on *Why* than *What*).
* Caution: Avoid backticks (`` ` ``) - they trigger shell command substitution! Use `"` or `'` instead.

## PAUSE if Stuck

If you make little to no progress after 15 consecutive attempts, halt execution and prompt the user for guidance.
