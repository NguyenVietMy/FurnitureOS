---
name: improve-codebase-architecture
description: Scan the repo and find shallow modules to consolidate into deep, testable ones. Run periodically as the codebase grows.
---

# Improve Codebase Architecture

Scan the codebase for architectural improvement candidates. Reference: John
Ousterhout, "A Philosophy of Software Design" — prefer DEEP modules with small
interfaces over shallow modules with tangled cross-dependencies.

For each candidate, report:
- The cluster of related files/modules that could be tested as ONE unit.
- Why they are coupled.
- A dependency category (e.g. locally substitutable via an in-memory/SQLite test DB).
- Current test coverage and the biggest gaps.

Prioritize modules with meaningful logic and zero/low tests. Propose ONE big test
boundary per deep module rather than wrapping every tiny function individually.
Do not refactor yet — produce a prioritized list of candidates for me to approve.
