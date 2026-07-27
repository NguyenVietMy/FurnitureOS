# PRD: FurnitureOS v1 — Unit Planner & Quote Capture

## Problem statement

We own a furniture store sited directly in front of an apartment cluster. Everyone
who walks past lives in — or is buying into — a known, finite set of unit layouts.

A buyer moving into one of those units cannot answer the only question that matters
before spending money: *what will actually fit, and what will the whole apartment
cost?* Today they guess from a tape measure and a showroom floor, or they use a
generic room planner that (a) makes them draw their own apartment, which is the step
everyone abandons, and (b) sells them nothing we stock.

We have the two things no generic planner has: the real floorplans and the real
inventory. Nothing currently connects them, so buying signal is invisible to us —
someone can spend an evening planning their home and we never learn they exist.

The existing `index.html` prototype proves the interaction is enjoyable, but it is a
toy: a single rectangular box room, sixteen hardcoded primitive-mesh items with
invented dimensions, no prices, no server, and `localStorage` as its only memory.

## Solution

A desktop web app where a buyer picks their real unit layout from a public gallery,
furnishes it with our actual catalogue, watches a running total in VND, and submits
the finished plan as a quote request that lands as a row in our admin.

It is not a design tool. It is a showroom conversion instrument — the plan is a
shopping cart wearing a 3D costume.

Shape:

```
app/    Next.js + TypeScript + react-three-fiber   buyer app + admin UI
api/    FastAPI + Postgres                         catalogue, units, plans, leads
```

The buyer flow, end to end:

```
gallery  →  pick layout  →  empty rooms  →  add room bundles  →  rearrange
                                                                    ↓
     admin leads row  ←  submit  ←  itemised quote + shareable link
```

No signup, no login, no payment, no email, no phone call. A plan autosaves to a
private unguessable URL the buyer can bookmark or send to their partner. Identity is
the price of the quote, not the price of entry.

v1 ships **one hand-seeded unit type and ~20 seeded items**. The tools for authoring
more (floorplan tracer, catalogue admin) are deliberately deferred — we prove the
funnel converts before building authoring tools for a funnel nobody has used.

## User stories (definition of done)

**Buyer**

- As a buyer, I can browse a public gallery of unit layouts and open mine, so that I
  never have to measure or draw my own apartment.
- As a buyer, I can see my unit rendered as its true polygon outline with its real
  walls, doors and windows, so that it reads as *my* home rather than a generic box.
- As a buyer, I can move between the rooms of my unit and see one running total
  across the whole apartment, so that I'm budgeting for a home and not for a sofa.
- As a buyer, I can drop a room bundle ("Living Essentials") and have it place itself
  sensibly, so that I get from an empty room to a furnished one in seconds.
- As a buyer, I can browse the catalogue by category or search, and drag an item into
  the room, so that I can furnish it exactly how I want.
- As a buyer, I can move, rotate and delete any item with the mouse, so that editing
  feels direct.
- As a buyer, I am prevented from overlapping two items or pushing one through a
  wall, so that every plan I make is physically real.
- As a buyer, I can see each item drawn at its true size, so that "it fits" in the app
  means "it fits" on delivery day.
- As a buyer, I can undo an accidental delete, so that one misclick doesn't cost me my
  evening's work.
- As a buyer, I can reset a room to empty, so that I can start over deliberately.
- As a buyer, my plan saves itself to a private link I can bookmark or send to my
  partner, so that I don't lose it and don't have to sign up.
- As a buyer, I can submit my plan with my name and phone number and immediately see
  an itemised quote broken down by room, so that I get the number I just spent twenty
  minutes building.
- As a buyer on a phone, I see a clear "open this on a computer" page rather than a
  broken 3D canvas, so that I know what to do next.

**Store (admin)**

- As the store owner, I can log into an admin area and see every submitted plan as a
  row — unit type, item count, total, name, phone, timestamp — so that no lead is
  lost.
- As the store owner, I can open a lead and see its full itemised breakdown and the
  buyer's plan, so that I can pick up the phone already knowing what they want.

## Modules to create / modify

### `app/` — Next.js + TypeScript

- **`lib/geometry/`** — *the deep module of this project.* Pure TypeScript, no
  three.js, no React. Interface is roughly four functions:
  `createRoomModel(unit)`, `roomModel.canPlace(footprint, pose)`,
  `roomModel.resolveDrag(footprint, desiredPose)`, `roomModel.findFreeSpot(footprint)`.
  Hides: polygon containment, oriented-bounding-box overlap (SAT), wall-segment
  distance, clamping and sliding behaviour, and whatever spatial index we need to keep
  drags smooth. Everything the prototype did with `rectsOverlap`, `clampToRoom`,
  `corners`, `halfExtents` and `collidesAt` is replaced by and hidden behind this.
- **`lib/plan/`** — plan state and mutations as a pure reducer:
  `add`, `move`, `rotate`, `remove`, `addBundle`, `resetRoom`, `undoLastRemove`, plus
  `planTotals(plan, catalogue)`. Hides item id generation, per-room grouping, and the
  single-step delete-undo buffer.
- **`scene/`** — react-three-fiber rendering: `<RoomScene>`. Hides three.js setup,
  `OrbitControls`, camera framing, selection markers, blocked-placement flash, and the
  pointer→ground-plane maths behind the drag loop. Carries over the prototype's
  `buildRoom`, `makeSelectionMarker`, `flashBlocked`, `setMarkerBlocked` concepts.
- **`scene/models/`** — `loadPresetScaled(presetRef, dims)`. Hides the glTF cache,
  up-axis and origin normalisation, and the non-uniform stretch to real dimensions.
  This is the seam where a custom per-item `.glb` will later slot in unchanged.
- **`lib/money.ts`** — VND integer handling and formatting (`12.500.000 ₫`).
- **`lib/api/`** — typed client for the FastAPI endpoints; hides fetch, serialisation
  and the debounced autosave.
- **`app/(buyer)/`** — gallery route, plan route (`/plan/<token>`), quote result view,
  and the small-viewport interstitial.
- **`app/(admin)/`** — leads list and lead detail, behind admin auth.

### `api/` — FastAPI + Postgres

- **`api/catalog/`** — `list_items()`, `get_items(ids)`, `list_bundles(room_type)`.
  Hides the ORM and the stock columns that exist but are never exposed in v1.
- **`api/units/`** — `list_units()`, `get_unit(slug)`. Hides polygon/opening JSON
  storage and its validation on load.
- **`api/plans/`** — `create_plan()`, `get_plan(token)`, `save_plan(token, payload)`.
  Hides token generation and upsert semantics.
- **`api/quotes/`** — `submit_quote(token, contact)`. **Recomputes every price
  server-side** from item ids and quantities and snapshots the itemisation onto the
  lead. Hides lead creation.
- **`api/admin/`** — leads list/detail endpoints plus the admin auth dependency.
- **`api/db/`** — SQLAlchemy models and Alembic migrations.
- **`api/seeds/`** — `unit_sunrise_b.json` (hand-traced polygon, rooms, openings) and
  `items.json` (~20 items with real dimensions, VND prices, preset refs).

### Modify

- **`index.html`** — retired as the app entry point once `app/` renders a room. Kept in
  the repo as a reference prototype until the geometry module reaches parity.
- **`CLAUDE.md`** — the feedback-loop commands currently cover only the TypeScript
  half. Add the Python loop (pytest, ruff, mypy); "run the feedback loops before
  finishing" must mean both halves. Fill in the module map.
- **`docs/architecture.md`** — currently an empty template; fill in from this PRD.

## Implementation decisions

- **Money is integer VND.** Dong has no fractional unit, so prices are `BIGINT` and
  there is no float money anywhere in either language. A `numeric(10,2)` price column
  would be wrong from the first migration.
- **Prices are recomputed server-side at submit.** The client total is display-only;
  the lead's itemisation is built from item ids against the server's own catalogue.
- **Geometry runs client-side.** Collision must resolve at interactive framerate
  during a drag, so `lib/geometry` is TypeScript in the browser. The server validates
  referential integrity (unit exists, item ids exist) but does **not** re-validate
  geometry in v1 — a geometrically odd stored plan is harmless when there are no
  payments.
- **Preset models stretch non-uniformly** to each item's true W×D×H. Drawn size equals
  collision size equals delivered size. Mild proportion distortion is the correct price
  for never lying about fit.
- **Model source is a tagged union from day one** —
  `{kind:'preset', ref} | {kind:'custom', url}` — so designer-supplied `.glb` files slot
  in later with no schema change.
- **Stock columns exist and are never rendered.** Swapping stock into the UI later is a
  UI change, not a migration.
- **No colour or finish variants.** One item, one look. The prototype's `setColor` and
  `insSwatch` are deleted rather than ported.
- **Doors and windows are stored and rendered, but enforce nothing.** Clearance rules
  (door swing, walkway width, blocked sliders) are a v2 upgrade that will need no
  re-tracing.
- **Bundles are item lists, not fixed layouts.** They auto-place through
  `findFreeSpot` so the same bundle works in differently shaped rooms.
- **No buyer auth.** A plan lives at `/plan/<token>` where the token is unguessable
  (`secrets.token_urlsafe`). Knowing the URL is the authorisation.
- **Server is the source of truth**; the prototype's `localStorage` persistence is
  dropped. The client autosaves on a debounce.
- **Admin auth is a single shared login** with an httpOnly session cookie. No user
  management, no roles.
- **Desktop only.** Small or coarse-pointer viewports get an interstitial rather than a
  degraded canvas. Mouse bindings: left-drag moves furniture, right-drag orbits, scroll
  zooms — which is close to what the prototype already does.
- **Reset over history.** A per-room "Reset room" with a confirm, plus a single-step
  undo-on-delete toast. No undo stack.
- **No analytics or instrumentation in v1.** Success is judged qualitatively.

## Testing decisions

Per `CLAUDE.md`, TDD throughout — failing test first, in both languages.

- **`lib/geometry` is the heart of the test suite.** Pure functions, so tested with
  plain polygon fixtures and zero rendering: a rectangular room, an L-shaped
  living/dining, a room with a doorway notch, and a near-degenerate thin room.
  Cases: containment at and just past the boundary; rotated-item overlap that
  axis-aligned maths would miss; drag clamping and sliding along a wall; and the
  invariant that any pose returned by `findFreeSpot` reports `canPlace === true`.
- **`lib/plan` reducer** — unit tested as pure state transitions, including bundle
  insertion, per-room totals, reset, and that undo-on-delete restores exact pose.
- **`lib/money`** — VND formatting and the absence of any float path.
- **API service layer (pytest)** — tested at the service boundary against a real
  Postgres test database, not by mocking the ORM. Fixtures: the seeded unit and a small
  item set.
- **Server-side price authority** — an explicit test that a client-submitted total is
  ignored and the lead's total is recomputed from item ids.
- **Plan tokens** — unguessable, and a wrong token 404s rather than leaking existence.
- **One Playwright happy path** — gallery → open unit → add a bundle → drag an item →
  submit quote → the lead appears in admin with the right total.
- **No pixel or 3D-rendering tests.** The scene is verified indirectly through the
  geometry and plan layers; `scene/` stays thin enough to not need its own suite.

## Out of scope

Deferred to after v1, by explicit decision:

- **Floorplan tracer tool** (upload plan → set scale → click corners → drop openings).
  v1's single unit is hand-authored JSON.
- **Catalogue admin UI.** v1's ~20 items are seeded.
- **More than one unit type.** The cluster's unit-type count is still unknown; it only
  becomes urgent when the tracer is prioritised.
- **Custom `.glb` import UI.** The data model supports it; the upload path isn't built.
- **Clearance and design-quality warnings.** Door swing, walkway width, blocked
  windows, unfurnished-room nudges, readiness scores.

Rejected outright, not merely postponed:

- **Payments, checkout, deposits, stock holds, delivery scheduling, refunds.** The
  conversion event is a lead, not an order.
- **Email, SMS, WhatsApp, Zalo, PDF quotes, or any notification.** A submitted plan is
  a row in the admin and nothing else.
- **Buyer accounts, magic links, sign-up.** Rejected in favour of the private plan URL.
- **Colour and fabric variants, and the free colour picker** the prototype ships with.
- **Mobile and tablet support; any native app.** Desktop browser only.
- **A drawing tool for buyers to trace their own space.** It would widen the market
  past the apartment cluster, but it is the step users hate and it discards the entire
  moat.
- **Auto-furnish by budget.**
- **Whole-apartment pre-designed packages** ("Scandi", "Warm Minimal"). Room-level
  bundles were chosen instead — less authoring, reusable across unit types.
- **Integration with Shopify, WooCommerce, a POS or an ERP.** FurnitureOS owns the
  catalogue outright.
- **Analytics, funnel instrumentation, and success metrics.**
- **Undo/redo history.** Reset plus single-step delete-undo only.
