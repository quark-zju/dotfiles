## ALWAYS COMMIT

**Always create a `git commit`**, even if the user didn't ask.

## Commit small

Avoid big commit. Think ahead. Break work down into multiple small atomic commits.

Examples of atomic commits:
* Refactoring, code cleanup, or dependency updates made in preparation for a new feature.
* Modifying a single file (provided the code is runnable and does not break existing tests).

## Commit message = Title + Body

**Always use `git commit -m TITLE -m BODY`**.
* Title: `<type|area>: <summary>`
* Body: You MUST include BOTH: 1. A brief overview of the USER REQUEST. 2. The core decision-making logic (focus on *Why* than *What*).

## PAUSE if Stuck

If you make little to no progress after 15 consecutive attempts, halt execution and prompt the user for guidance.
