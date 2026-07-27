# 01 — Walking skeleton: a seeded unit renders in 3D from the database

Type: AFK
Blocked by: none

## Stories delivered
- As a buyer, I can see my unit rendered as its true polygon outline with its real
  walls, doors and windows, so that it reads as my home rather than a generic box.

## Reviewable end state
Start both servers, open the plan page, and orbit around an empty two-bedroom
apartment: real outer outline, interior partition walls, door and window openings cut
into the walls, correct ceiling height. Right-drag orbits, scroll zooms. Walls between
the camera and the interior fade or hide so you can always see inside. Nothing to place
yet — this is the room shell only.

## Notes
This is the tracer bullet. It stands up every layer at once so nothing is theoretical
afterwards: Next.js + TypeScript + react-three-fiber in `app/`, FastAPI + Postgres +
Alembic in `api/`, a `units` table, a seed loader, `GET /api/units/{slug}`, and the
scene that draws it.

Scope decisions this ticket locks:

- **Unit JSON shape** — outer polygon, interior partition wall segments, named room
  regions (each its own polygon), wall openings (door/window with position, width,
  sill/head height), ceiling height. Everything downstream reads this shape, so get it
  right here.
- **Whole apartment renders as one scene.** Not one room at a time.
- **Camera occlusion.** Hide or fade walls facing away from the camera, otherwise
  orbiting puts the buyer inside a sealed box. Solve it now, cheaply.
- **Seed is a placeholder** — an agent-authored L-shaped 2BR that exercises non-
  rectangular geometry. Issue 12 replaces it with the real traced floorplan; treat the
  placeholder as disposable but treat its *schema* as permanent.
- Openings are rendered but enforce nothing (per PRD).

Also in this ticket, since it's the scaffolding pass:

- Update `CLAUDE.md`: the feedback loops currently name only `npm test` /
  `npm run type-check` / `npm run lint`. Add the Python half (pytest, ruff, mypy) and
  make "run the feedback loops" mean both. Fill in the module map.
- Fill in `docs/architecture.md`, which is still an empty template.

Test boundary: unit-JSON parsing and validation in pytest; wall-geometry derivation
(polygon → wall segments → openings) as pure TypeScript functions in Vitest. No
rendering tests.

`index.html` stays in the repo untouched as a reference prototype.
