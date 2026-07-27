---
name: coding-standards
description: Project coding standards the implementer can pull on demand. (Also PUSH these into the review step.)
---

# Coding Standards

- Deep modules: small, simple public interface; hide complexity inside.
- One responsibility per module; avoid shallow files that just re-export.
- Explicit types at module boundaries.
- No dead code, no commented-out code, no TODOs left in shipped work.
- Errors are handled or propagated deliberately — never swallowed.
- Tests live beside the module and test its public behavior.
- Naming: <fill in your conventions>.
- Formatting/lint: enforced by `<lint command>` — code must pass it.

<!-- Keep this in sync with docs/standards.md. The reviewer receives these as PUSH. -->
