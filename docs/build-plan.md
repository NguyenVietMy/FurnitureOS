# Build plan

Derived from the grilling session. Domain language is in `CONTEXT.md`; the two standing decisions are in `docs/adr/`.

The ordering principle: **the project's real risk is whether a solver plus an LLM can produce a room that looks good using ABO meshes.** Not the photo pipeline, not auth, not the renderer. So the walking skeleton comes first with a hardcoded Room, and the Capture pipeline — the flashiest part, and the entry point of the actual UX — is deliberately deferred until after the core is proven.

---

## Phase 0 — Skeleton

Next.js App Router + TypeScript. React Three Fiber + drei, canvas mounted with `ssr: false`. Supabase project (Postgres + Auth + Storage). Vercel deploy from day one so the public URL exists before there is anything on it.

**Done when:** an empty deployed page renders a grey box in 3D that you can orbit.

---

## Phase 1 — A seed Catalogue

Do *not* curate 300 items yet. Hand-pick **~20 bedroom items** (bed, two nightstands, wardrobe, dresser, chair, rug, lamp) straight from ABO and run them through the asset pipeline manually.

Asset pipeline (later becomes part of Phase 6's tool): `gltf-transform` → meshopt compression + KTX2 textures, 2048px cap, three LOD levels, output to CDN. Budget < 5MB per model.

Implement `Catalogue` as the interface from ADR-0001 — mesh URL, real-world dimensions, category, Room Type, Style tags, purchase URL (empty for now). ABO is one implementation behind it. Nothing outside that implementation reads ABO-specific fields.

**Done when:** 20 Products load into the 3D scene at correct real-world scale, on a phone, in under three seconds.

---

## Phase 2 — The solver

One shared TypeScript module, no framework dependencies, so it can run on the server and in the browser unchanged (Q25).

- Room Shell representation: floor polygon, wall segments, ceiling height, Openings with door swing arcs.
- Zone derivation from geometry — seating, sleeping, storage, circulation.
- Placement Intent vocabulary: `against(wall)`, `centred_on(wall)`, `in_corner(a,b)`, `adjacent_to(product)`, `facing(product)`, `flanking(product)`, `in_zone(zone)`.
- Resolve intent → Placement. Enforce collisions, clearances, door swings.
- **`validRegionFor(placement)`** — not just `isValid(placement)`. Constrained drag (Q20) needs the region, and retrofitting it later is painful.

Test against hardcoded rooms with hand-written intent. No LLM yet.

**Done when:** hand-written intent for a 4×3m bedroom resolves to placements you'd accept, and every deliberately-bad intent is rejected with a reason.

---

## Phase 3 — Walking skeleton *(the go/no-go gate)*

Hardcoded 4×3m bedroom → 20-item Catalogue → `claude-opus-5` selects Products and emits Placement Intent under structured outputs (`output_config.format`) → solver resolves → R3F renders.

Adaptive thinking, effort `high`. Retry loop per ADR-0002: unsatisfiable intent goes back to the model twice, then the Product is dropped.

**Done when:** you generate ten bedrooms in a row and would show seven of them to a stranger. **If that fails, stop and fix it here** — every later phase assumes this works, and none of them can rescue it.

---

## Phase 4 — Interaction

Swap first (safe: the slot is already validated, so any footprint-compatible Product is guaranteed valid). Then constrained-drag Nudge using `validRegionFor` — the piece glides where it can go and stops where it can't.

**Done when:** you can swap and drag on a phone without ever reaching an invalid state.

---

## Phase 5 — Capture → Room Shell

The riskiest remaining component, now with a working system behind it.

1. Multi-photo upload (~4, one per wall).
2. `claude-opus-5` vision reads **semantics only**: which wall has the window, where the door is and which way it swings, whether there is Detected Furniture.
3. User picks room topology from a small set of shapes (rectangle, L).
4. Numeric confirm step — dimensions detected where possible, typed and corrected by the user (Q8). This is the scale ground truth; the model is never the tape measure.
5. If Detected Furniture is present, tell the user the Design assumes an empty room.

**Done when:** four photos of a real room produce a Room Shell you'd accept, and a bad Capture produces an obviously-correctable form rather than a wrong room.

---

## Phase 6 — Full Catalogue + curation tool

Local-only web tool, never deployed, no auth. One item at a time: mesh preview, keyboard shortcuts for accept/reject, Style and Room Type tagging. Runs the Phase 1 asset pipeline on accept.

Style tagging is by mood-board image (~6 boards), matching how users choose (Q15). Keep the private style names as your own consistency aid; never show them.

Target ~300 items across bedroom and living room. **Add living-room Placement Intent handling here** — this is where `in_zone` earns its place, since a living room needs a floating seating group and wall-relative intent alone gives you the student-flat look.

**Done when:** 300 items tagged, and you didn't abandon it halfway.

---

## Phase 7 — Variants and reveal

Three Variants as one continued conversation (Q29): Variant A shown immediately; B and C generated in the background against message history so each differs from the *actual* prior designs. Stable prefix — system prompt, Catalogue, Room Shell — so B and C are cache reads.

Progressive reveal (Q28): render the empty Room Shell the moment geometry is confirmed, before any LLM call. Furniture appears as each Variant solves. Fall back to labelled stage progress if the choreography fights you.

**Done when:** time-to-first-furnished-room is under 30 seconds and the wait has something worth looking at.

---

## Phase 8 — Persistence

Supabase anonymous sign-in on first visit, so a Design has an owner row from the start without a signup wall. Link an email or OAuth identity when the user chooses to save. A Design is a Room Shell plus Placements — a few KB of JSON. Captures in Supabase Storage.

**Done when:** an anonymous user can generate, save, sign in, and still have their Design.

---

## Phase 9 — Five strangers

The stated bar. Not friends, not you.

Watch where they hesitate rather than asking whether they liked it.

---

## Carried risks

- **A wrong-*shape* Room has no repair path in v1.** The numeric confirm fixes scale, not topology. Phase 5's shape picker shrinks this but does not close it. The geometry editor is the fix when you want it.
- **NC-licensed assets cannot survive a commercial launch.** ADR-0001 is what absorbs that; keep it true — nothing outside the Catalogue implementation may touch ABO-specific fields.
- **Upholstered meshes are ABO's weakest, and sofas are unavoidable in a living room.** Expect Phase 6 to reject a lot of them.

## Still open

- A third ADR — *room geometry is inferred rather than drawn* — remains unwritten. Worth adding before Phase 5, since that phase is where a future reader would ask the question.
