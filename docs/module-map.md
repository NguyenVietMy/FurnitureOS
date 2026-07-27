# Module map

<!-- Deep modules and their public interfaces. This is the mental model you keep
even while delegating implementation. Keep it current. -->

Layout is the same on both sides: `core/` is the shared kernel, `modules/<name>/` is a
bounded slice whose public surface is its `__init__.py` (Python) or `index.ts` (TS).
Nothing outside a module may reach past that file. See `docs/architecture.md` for the
three boundary rules and the tests that enforce them.

## Backend — `api/src/furnitureos/`

| Module | Responsibility | Public interface | Test boundary |
|--------|----------------|------------------|---------------|
| `main.py` | Composition root: mounts routers, registers models. Owns no logic. | the ASGI `app` | `tests/test_units_api.py` via `TestClient` |
| `registry.py` | Single import point that puts every ORM model on `Base.metadata`, for Alembic autogenerate. | import for side effects | — |
| `core/` | Settings (`settings.database_url`) and SQLAlchemy engine/session/`Base`. May not import `modules/`. | `config.settings`, `db.Base`, `db.get_session` | exercised through modules |
| `modules/units/` | Apartment geometry: what shape the buyer is furnishing. Parses and validates plans, stores them as whole JSONB documents, serves them over HTTP. | `Opening` `Room` `Wall` `UnitPlan` `UnitPlanError` `UnitOut` `UnitSummaryOut` `parse_unit_plan` `load_seed_unit` `get_unit` `list_units` `seed_units` `router` | `tests/test_unit_plan.py` (pure parsing/invariants), `tests/test_units_service.py` (DB), `tests/test_units_api.py` (HTTP) |

Internals of `modules/units/`: `plan.py` holds the geometry invariants, `models.py` the
`units` table, `service.py` reads and seeding, `schemas.py` the wire format, `router.py`
the routes, `seeds/*.json` the placeholder layouts (schema permanent, coordinates not).

`schemas.py` serves two projections of one plan: `UnitSummaryOut` for a gallery card
(display metadata plus the polygons a thumbnail draws) and `UnitOut` for the renderer
(that, plus walls and openings). Both read the derived values off `UnitPlan`, so a card
cannot contradict the page it opens.

## Frontend — `app/src/`

| Module | Responsibility | Public interface | Test boundary |
|--------|----------------|------------------|---------------|
| `app/` | Routes only. Server components fetch and lay out; no domain logic. | `/`, `/unit/[slug]` — both in the `(buyer)` route group | none yet (no rendering tests) |
| `core/` | API base URL and `getJson<T>()` — returns `null` on 404, throws `ApiError` otherwise. May not import `modules/`. | `config`, `http.getJson`, `http.ApiError` | exercised through modules |
| `modules/units/` | The same slice on the client: list units, fetch one, turn walls + openings into solid boxes, render them in 3D or as a flat thumbnail. | `fetchUnits` `fetchUnit` `deriveWallPieces` `WallPiece` `deriveThumbnail` `Thumbnail` `ThumbnailShape` `UnitThumbnail` `UnitScene` and the wire types `Unit` `UnitSummary` `Wall` `Room` `Opening` `Point` | `geometry.test.ts`, `occlusion.test.ts`, `thumbnail.test.ts` — pure functions in vitest's node env |

Internals of `modules/units/`: `types.ts` the wire format, `api.ts` fetching,
`geometry.ts` the deep module (openings become sill/lintel/run boxes; volume is
conserved), `thumbnail.ts` the gallery's flat projection (outline + rooms to SVG paths,
Y flipped so a floorplan reads north-up), `UnitThumbnail.tsx` the card's `<svg>`,
`scene/coords.ts` the **only** place plan coordinates meet three.js, and
`scene/UnitScene.tsx` the r3f canvas.

Route groups carry no URL segment. `(buyer)` exists to hold the public, unauthenticated
surface apart from the admin screens issue 09 adds under `(admin)`.
