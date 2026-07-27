---
name: red-green-refactor
description: How to implement with TDD in this repo. Use for any implementation task.
---

# Red-Green-Refactor (TDD)

Feedback loops are the ceiling on quality. Do not code blind.

1. RED — write ONE failing test that describes the next small behavior. Run it.
   Confirm it fails for the right reason.
2. GREEN — write the minimum implementation to make it pass. Run the test. Confirm green.
3. REFACTOR — clean up while keeping tests green.

Rules:
- Test at the DEEP-MODULE boundary (one big boundary per module), not every tiny function.
- Never weaken, skip, or delete a test to make it pass.
- Use the in-memory / SQLite test DB for locally-substitutable dependencies.
- Before finishing: run the full test suite AND the type-checker; fix anything they surface.
