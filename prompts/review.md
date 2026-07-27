Review the diff for the current issue. You are running in a FRESH context so you
review in the smart zone, not from inside the implementation context.

Compare the code against these PUSHED standards:
- docs/standards.md
- docs/module-map.md (module boundaries)

Check:
- Tests actually test meaningful behavior (not cheated/tautological).
- Vertical slice is complete and reviewable end to end.
- Deep modules with small interfaces; no shallow-module sprawl.
- Type-check and tests pass.

Report issues as a prioritized list. Suggest new tickets for anything out of scope.
