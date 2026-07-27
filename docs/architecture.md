# Architecture

<!-- The big picture. Update when the shape of the system changes. -->

## Overview

FurnitureOS is a desktop-only web app for a furniture store that sits in front of an
apartment cluster. A buyer picks their real unit layout from a public gallery, walks
around it in 3D, furnishes it with the store's real inventory, watches a running total
in VND, and submits the plan as a quote request — which lands as a row in an admin UI.
No emails, no phone calls, no payments.

It is a **modular monolith** in two deployable pieces: a FastAPI backend (`api/`) and a
Next.js frontend (`app/`), each internally split into `core/` (shared kernel) and
`modules/<name>/` (bounded slices). Postgres stores unit layouts as whole JSONB
documents — read and written as a unit, never queried by their parts.

## Layers / deployable units

- **`api/`** — FastAPI + SQLAlchemy 2.0 + Alembic, Python 3.13, managed by `uv`.
  Serves JSON under `/api`. `main.py` is the composition root: it imports module roots,
  mounts their routers, and owns nothing else.
- **`app/`** — Next.js 16 (App Router) + TypeScript + react-three-fiber. Server
  components fetch from the API; the 3D viewport is the only client component.
- **`db`** — Postgres 17 in Docker (`docker-compose.yml`), host port **5433** because a
  local Postgres install already holds 5432 on the dev machine.

## Module boundaries

Three rules, enforced by tests rather than convention:

1. A module may not import another module's submodules — only the module root
   (`furnitureos.modules.units` / `@/modules/units`), and only what its public surface
   (`__init__.py` / `index.ts`) exports.
2. `core/` may not import from `modules/` at all. Dependencies point inward.
3. The composition root imports module roots only.

Enforced by `api/tests/test_module_boundaries.py` (AST walk over every file) and by
`no-restricted-imports` in `app/eslint.config.mjs`. Both guards were verified
non-vacuous by planting a deliberate violation and confirming each fails.

The one documented exception: `api/src/furnitureos/registry.py` imports
`modules.units.models` directly, because Alembic autogenerate needs every ORM model
registered on `Base.metadata` from a single import point.

## Key decisions

- **Modular monolith over microservices** — one team, one deploy, but boundaries drawn
  and machine-checked from day one so slices can be split later without archaeology. (2026-07)
- **JSONB for unit layouts** — a layout is read and written whole and never filtered by
  its interior. Columns would buy nothing and cost a migration per shape change. (2026-07)
- **Server owns wall identity, client owns wall geometry** — the API returns wall ids,
  endpoints and openings; the browser derives extrusion and cutouts. Keeps the wire
  format small and stable while the renderer evolves freely. (2026-07)
- **Plan coordinates are metres in right-handed XY, +Y forward.** three.js is Y-up, so
  plan `(x, y)` → world `(x, h, -y)` and `rotation.y = +angle_rad`. This conversion
  lives in exactly one file, `app/src/modules/units/scene/coords.ts`. (2026-07)
- **Camera-aware wall hiding mutates `mesh.visible` inside `useFrame`**, deliberately
  outside React state — it changes every frame and must not trigger re-renders. (2026-07)
- **Left-drag is reserved for furniture**, so OrbitControls binds orbit to right-drag
  and dolly to middle. (2026-07)
- **Frontend tests run in vitest's node environment** — no jsdom, no testing-library.
  The logic worth testing (geometry, occlusion) is pure. (2026-07)
