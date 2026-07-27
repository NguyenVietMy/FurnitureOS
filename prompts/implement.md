Local issue files from ./issues are provided at the start of context.

- Work on AFK issues only.
- If all AFK tasks are complete, output exactly: NO MORE TASKS
- Otherwise pick the NEXT task by priority:
  1. critical bug fixes
  2. dev infrastructure
  3. tracer-bullet (vertical-slice) issues
  4. polish / quick wins / refactors

To complete the task:
1. Explore the repo.
2. Use TDD (red-green-refactor): write a FAILING test first, confirm it fails,
   then implement until it passes. Do not weaken tests to make them pass.
3. Run the feedback loops (tests, type-check) and fix anything they surface.
4. Commit with a clear message and a short summary of what was done.
