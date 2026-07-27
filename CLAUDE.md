# CLAUDE.md

## Commands

Two feedback loops — run BOTH before finishing anything that touches both sides.

Services (from repo root):
- Postgres: `docker compose up -d` (host port **5433**, not 5432)

Backend, from `api/`:
- Install: `uv sync`
- Migrate: `uv run alembic upgrade head` • Seed: `uv run python -m furnitureos.seed`
- Dev: `uv run uvicorn furnitureos.main:app --reload --port 8000`
- Test: `uv run pytest` • Type-check: `uv run mypy src tests`
- Lint/format: `uv run ruff check .` and `uv run ruff format .`

Frontend, from `app/`:
- Install: `npm install` • Dev: `npm run dev`
- Test: `npm test` • Type-check: `npm run type-check` • Lint: `npm run lint`

## Hard rules

- Always use TDD (red-green-refactor). Write the failing test first. Never weaken a test to make it pass.
- Prefer DEEP modules: small, simple interfaces hiding lots of functionality. Avoid shallow-module sprawl.
- Work in vertical slices (schema + service + minimal UI), never horizontal layers.
- Run the feedback loops (test + type-check) before finishing any task.
- Keep this file small. Process lives in skills; durable knowledge lives in docs/.
- Modular Monolith style

## Module map

<!-- One line per top-level module: name — responsibility. Keep current. -->

Modular monolith, same shape on both sides: `core/` is the shared kernel, each
`modules/<name>/` is a bounded slice, and its `__init__.py` / `index.ts` is the ONLY
way in. `core/` may not import `modules/`. Enforced by
`api/tests/test_module_boundaries.py` and `no-restricted-imports` in `app/eslint.config.mjs`.

- `api/src/furnitureos/core` — settings, engine, session, `Base`
- `api/src/furnitureos/modules/units` — apartment geometry: parse, store as JSONB, serve
- `app/src/core` — API base URL, `getJson`
- `app/src/modules/units` — fetch a unit, derive wall boxes, render it in 3D
- `app/src/app` — routes only, no domain logic

Detail: `docs/module-map.md`. Shape and rationale: `docs/architecture.md`.

## Where things live

- Process/how-to: `.claude/skills/`
- Durable knowledge: `docs/` (architecture, module map, standards)
- Active work: `issues/` • Shipped work: `issues/archive/` (do not scan by default)
