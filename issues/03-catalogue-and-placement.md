# 03 — Catalogue panel and placing items inside the room outline

Type: AFK
Blocked by: 01

## Stories delivered
- As a buyer, I can browse the catalogue by category or search, and drag an item into
  the room, so that I can furnish it exactly how I want.
- As a buyer, I can move and delete any item with the mouse, so that editing feels
  direct.
- As a buyer, I can see each item drawn at its true size, so that "it fits" in the app
  means "it fits" on delivery day.
- As a buyer, I am prevented from pushing an item through a wall.

## Reviewable end state
Open a unit, filter the catalogue by category or type in the search box, drag a sofa
into the living room. It appears at its real width, depth and height. Drag it around —
it slides along walls and cannot leave the apartment outline or cross a partition wall.
Select it, delete it. Refreshing loses everything (persistence is issue 05).

## Notes
The biggest ticket in the set, because it creates `lib/geometry` — the deep module this
whole project is organised around.

**`lib/geometry`** — pure TypeScript, no three.js, no React. Interface:
`createRoomModel(unit)`, `canPlace(footprint, pose)`, `resolveDrag(footprint,
desiredPose)`, `findFreeSpot(footprint)`. This ticket implements **containment only** —
polygon interior tests and wall clamping/sliding. Item-to-item overlap is issue 04, and
`findFreeSpot` may be stubbed until then. Do not let polygon maths leak into the scene
layer; that separation is the point.

**`lib/plan`** — pure reducer: `add`, `move`, `remove`. State is client-only for now.

**`scene/models/loadPresetScaled(presetRef, dims)`** — resolves the preset model and
stretches it **non-uniformly** to the item's true W×D×H. Drawn size equals collision
size. Until issue 14 supplies real `.glb` files, fall back to a primitive box of the
correct dimensions; make that fallback a clean seam, not a temporary hack, since custom
per-item models slot into the same place later.

**Catalogue** — `items` table (name, category, W/D/H in metres, price as `BIGINT` VND,
preset ref, photo, plus stock columns that exist and are never exposed), seeded with
~20 placeholder items, `GET /api/items`, and a panel with category chips and a search
box. Build the panel for ~100 items even though v1 seeds 20.

Prices are stored and carried but not yet totalled — that is issue 06.

Mouse bindings: left-drag moves furniture, right-drag orbits, scroll zooms.

Test boundary: `lib/geometry` is the heart of the suite — plain polygon fixtures in
Vitest (rectangle, L-shaped living/dining, doorway notch, near-degenerate thin room),
testing containment at and just past the boundary, and drag clamping/sliding. `lib/plan`
reducer tested as pure state transitions. No rendering tests.
