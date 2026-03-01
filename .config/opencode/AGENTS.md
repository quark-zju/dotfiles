# AGENTS

## 1. Commit Often

Always create a `git commit` after completing any atomic action, unless the change is completely unrelated to the project or the user explicitly forbids it.

If a user prompt contains multiple distinct tasks, break them down into multiple isolated commits.

* **Examples of atomic commits:**
    * Refactoring, code cleanup, or dependency updates made in preparation for a new feature.
    * Modifying a single file (provided the code is runnable and does not break existing tests).

**Commit Message Convention:**
* **Title:** `<type|area>: <summary>`
* **Body:** You MUST include:
    1. A brief overview of the original requirement.
    2. The core decision-making logic (focus on the *Why* rather than the *What*).

## 2. Avoid Complex Bash

If bash/shell logic becomes complex, write a Python script instead.

## 3. Pause if Stuck

If you make little to no progress after 20 consecutive attempts, halt execution and prompt the user for guidance.
