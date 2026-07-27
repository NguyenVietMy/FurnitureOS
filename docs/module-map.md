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
| `modules/catalogue/` | What the store sells: name, category, true W×D×H in metres, price in whole dong, which preset draws it. | `Item` `ItemError` `ItemOut` `parse_item` `load_seed_items` `list_items` `resolve_items` `seed_items` `router` | `tests/test_catalogue_item.py` (pure validation), `tests/test_catalogue_service.py` (DB), `tests/test_catalogue_api.py` (HTTP) |

Internals of `modules/units/`: `plan.py` holds the geometry invariants, `models.py` the
`units` table, `service.py` reads and seeding, `schemas.py` the wire format, `router.py`
the routes, `seeds/*.json` the placeholder layouts (schema permanent, coordinates not).

Internals of `modules/catalogue/`: same shape — `item.py` the domain rules, `models.py`
the `items` table, `service.py` reads and seeding, `schemas.py` the wire format,
`router.py` the routes, `seeds/items.json` the placeholder catalogue (issue 13 replaces
the rows, not the columns).

Two differences from `units`, both deliberate. An item is **columns, not a JSONB
document**: a catalogue is queried by category and searched by name, where a unit plan is
only ever fetched whole. And `price_vnd` is `BIGINT` — dong is an integer currency, and no
float ever touches a price on either side of the wire.

`stock_qty` and `lead_time_days` exist on the table and are absent from `ItemOut`.
Availability is a fact the store keeps; it is not a fact the buyer's browser gets, and
`tests/test_catalogue_api.py::test_stock_is_never_exposed` keeps it that way.

`schemas.py` serves two projections of one plan: `UnitSummaryOut` for a gallery card
(display metadata plus the polygons a thumbnail draws) and `UnitOut` for the renderer
(that, plus walls and openings). Both read the derived values off `UnitPlan`, so a card
cannot contradict the page it opens.

## Frontend — `app/src/`

| Module | Responsibility | Public interface | Test boundary |
|--------|----------------|------------------|---------------|
| `app/` | Routes only. Server components fetch and lay out; no domain logic. | `/`, `/unit/[slug]` — both in the `(buyer)` route group | none yet (no rendering tests) |
| `core/` | API base URL and `getJson<T>()` — returns `null` on 404, throws `ApiError` otherwise. May not import `modules/`. | `config`, `http.getJson`, `http.ApiError` | exercised through modules |
| `modules/units/` | The same slice on the client: list units, fetch one, turn walls + openings into solid boxes, render them in 3D or as a flat thumbnail. | `fetchUnits` `fetchUnit` `deriveWallPieces` `WallPiece` `deriveThumbnail` `Thumbnail` `ThumbnailShape` `UnitThumbnail` `UnitScene` `toPlan` `toWorld` `toWorldRotation` and the wire types `Unit` `UnitSummary` `Wall` `Room` `Opening` `Point` | `geometry.test.ts`, `occlusion.test.ts`, `thumbnail.test.ts` — pure functions in vitest's node env |
| `modules/geometry/` | **The deep module.** What may go where. Given a unit, answers whether a footprint fits at a pose, where a drag actually ends up, and where there is room for something. Pure: no three.js, no React, no DOM. | `createRoomModel` `RoomModel` `Footprint` `Pose` `footprintCorners` | `roomModel.test.ts` — the heart of the suite: polygon fixtures, containment at and just past the boundary, drag clamping and sliding |
| `modules/plan/` | What the buyer has put in the unit, and the screen they do it on. Client-only state: a list of item ids and poses. | `Planner` `planReducer` `emptyPlan` `PlanState` `PlanAction` `PlacedItem` | `reducer.test.ts` — pure state transitions. The scene and the panel have no tests by design |
| `modules/catalogue/` | Browsing what the store sells: fetch it, filter it by category and search, show it as a panel you can drag out of. | `fetchItems` `CataloguePanel` `CATALOGUE_ITEM_MIME` `filterItems` `categoriesOf` `ALL_CATEGORIES` `CatalogueFilter` `Item` | `filter.test.ts` — chips and search as a pure function |

Internals of `modules/units/`: `types.ts` the wire format, `api.ts` fetching,
`geometry.ts` the deep module (openings become sill/lintel/run boxes; volume is
conserved), `thumbnail.ts` the gallery's flat projection (outline + rooms to SVG paths,
Y flipped so a floorplan reads north-up), `UnitThumbnail.tsx` the card's `<svg>`,
`scene/coords.ts` the **only** place plan coordinates meet three.js, and
`scene/UnitScene.tsx` the r3f canvas, which takes `children` so other modules can draw
into it without this one learning what they are.

`toWorld` / `toPlan` / `toWorldRotation` are exported rather than kept internal for one
reason: they are the only place plan coordinates meet three.js, and that stays true only
if every module drawing into the scene uses these instead of its own copy.

Internals of `modules/geometry/`: `polygon.ts` the primitives (boundary-inclusive
point-in-polygon, segment and polygon distances), `roomModel.ts` the interface below,
`fixtures.ts` the test rooms, built the way the server builds walls so a fixture cannot
drift from a real unit.

`createRoomModel(unit)` returns three methods and no data:

- `canPlace(footprint, pose)` — every corner inside the outline, and no wall closer than
  half its thickness. Exact, including rotation: a 45° sofa is tested as a rotated
  rectangle, not its bounding box.
- `resolveDrag(footprint, desired, from)` — the legal pose nearest what the pointer asked
  for. Blocked head-on it clamps; blocked at an angle it slides along the wall and into
  the corner. It never returns an illegal pose, and returns `from` when nothing is
  reachable.
- `findFreeSpot(footprint, near?)` — somewhere it fits, nearest first to `near` if given,
  otherwise a deterministic scan. `null` when the room is full.

This ticket is **containment only**: walls and the outline. Item-to-item overlap is issue
04, and it lands behind this same interface — callers do not change.

Internals of `modules/plan/`: `reducer.ts` (`add`/`move`/`remove`, returning the same
object on a no-op), `Planner.tsx` the composition, and `scene/` the r3f half —
`presets.ts` resolves a preset ref and computes the **non-uniform** scale to true W×D×H,
`PresetModel.tsx` is the `loadPresetScaled` seam (a box today; issue 14's `.glb` renders
in the same place at the same size), `floor.ts` turns a screen point into a spot on the
floor, `PlanItems.tsx` draws the furniture and handles left-drag.

The plan holds no prices — totals are issue 06's `lib/money` — and is not saved anywhere;
issue 05 puts it behind a share token.

Route groups carry no URL segment. `(buyer)` exists to hold the public, unauthenticated
surface apart from the admin screens issue 09 adds under `(admin)`.
