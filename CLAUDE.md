# CLAUDE.md

## Commands

- Install: `<npm install>`
- Dev: `<npm run dev>`
- Test: `<npm test>`
- Type-check: `<npm run type-check>`
- Lint/format: `<npm run lint>`

## Hard rules

- Always use TDD (red-green-refactor). Write the failing test first. Never weaken a test to make it pass.
- Prefer DEEP modules: small, simple interfaces hiding lots of functionality. Avoid shallow-module sprawl.
- Work in vertical slices (schema + service + minimal UI), never horizontal layers.
- Run the feedback loops (test + type-check) before finishing any task.
- Keep this file small. Process lives in skills; durable knowledge lives in docs/.

## Module map

<!-- One line per top-level module: name — responsibility. Keep current. -->

- `src/...` — ...

## Where things live

- Process/how-to: `.claude/skills/`
- Durable knowledge: `docs/` (architecture, module map, standards)
- Active work: `issues/` • Shipped work: `issues/archive/` (do not scan by default)
