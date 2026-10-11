# FurnitureOS

A web app that turns photos of a real room into a furnished 3D scene, where every piece of furniture shown is a real product that exists and can be bought.

## Language

### The space

**Room**:
The real physical space a user wants furnished. Always modelled at real-world scale.
_Avoid_: Space, scene, area

**Room Shell**:
A Room's structure: floor polygon, wall segments, and ceiling height. Carries no furniture.
_Avoid_: Geometry, walls, box

**Opening**:
A window or door in a wall segment. A door Opening carries its swing arc, because the swing constrains what can be placed near it.
_Avoid_: Hole, aperture, gap

**Room Type**:
The function a Room serves — bedroom or living room. Declared by the user, never inferred. Determines which Products are eligible and which Placement Intents apply.
_Avoid_: Category, room kind, space type, purpose

**Capture**:
The set of photos a user takes of their Room, from which the Room Shell and its Openings are inferred.
_Avoid_: Upload, scan, photoshoot

**Detected Furniture**:
Furniture recognised in a Capture. It is never reconstructed or placed — it exists only so the user can be told that their Design assumes an empty Room.
_Avoid_: Existing furniture, current furniture

### The output

**Design**:
A Room Shell furnished with Placements. The thing a user comes to FurnitureOS to get.
_Avoid_: Layout, render, mockup, plan, result

**Placement**:
One Product positioned and rotated within a Room, constrained by the Room Shell and its Openings.
_Avoid_: Position, arrangement, spot

**Zone**:
A named region of a Room — seating, sleeping, storage, circulation — derived from the Room Shell and its Openings before generation begins. Zones are computed from geometry and offered to the generator; they are never invented by it.
_Avoid_: Area, region, section, spot

**Variant**:
One of the alternative Designs produced by a single generation, between which the user chooses.
_Avoid_: Option, version, alternative, candidate

**Placement Intent**:
A desired spatial relationship between a Product and the Room Shell, expressed without coordinates. Intent is what taste produces; a Placement is what geometry resolves it into.
_Avoid_: Hint, suggestion, constraint, rule

The current wall-relative slice accepts ordered `against`, `centred_on`, and right-angle `in_corner` intents. An `against` intent is explored on a deterministic 0.1 m lattice in centre, positive, negative order; reaching the lattice or request budget is not proof that continuous space has no fit. The resolver therefore reports such failure as non-exhaustive. Fixed centred and supported corner requests can be exhaustive. Search is globally bounded to 256 attempted Placements across at most 20 intents and revisits earlier choices when a later Product cannot fit.

Every resolved Placement carries the Placement Intent ID as its stable instance identity. Several Placements may reference the same Catalogue Product, while intent IDs remain unique. A corner Placement publishes both physical wall contacts: the primary face and a perpendicular allowed side face, each checked for wall distance and alignment.

Object-relative Placement Intents use `referenceId` to name another unique Placement Intent request. `adjacent_to` also requires a local `side` (`left`, `right`, `front` or `back`); `facing` uses the referenced Placement's front; `flanking` is exactly two requests with the same `referenceId` and `gapM`, one `left` and one `right`. `gapM` is the finite signed face-to-face distance in metres: zero touches and positive values separate. A negative value is accepted only for an intentional `floor-covering`/`floor-standing` overlap through `adjacent_to`. Its target-local signed centre separation is the target half-span plus source half-span plus `gapM`; a separation below zero by more than the 1e-9 m numeric-noise scale fails before search, while floating-point-scale rounding within that boundary is clamped to zero. Object-relative Placements inherit the target yaw except `facing`, whose +Z front points back at the target. Flanking Placements align their rear edges with the target rear.

Reference dependencies are validated and resolved topologically with stable request-ID tie-breaking, while public Design arrays retain request input order. Missing, self and cyclic references, malformed flanking pairs, unsupported shapes and class-invalid negative gaps fail before search. Serialized neutral defaults are reusable: wall-relative intents may carry `gapM=0`, and object-relative intents may carry `face=back`; non-neutral fields for the wrong intent shape remain unsupported. The same 20-request and 256-attempt bounds cover graph work and candidate resolution.

`floor-covering` is an explicit provider-neutral Placement class. Each floor-covering/floor-standing pair may overlap, so several floor-standing Products can independently share one covering; a covering may also occupy those Products' walkable required-access footprints. Two floor coverings still collide, ordinary floor-standing pairs still collide, and a floor covering's own declared required access remains protected from floor-standing obstacles. Room containment, floor anchoring, door operation and required-access containment always remain enforced. Class metadata, never Product name, category or thinness, grants this exception.

`in_zone` is the supported Zone-relative Placement Intent. It names a Zone ID derived by FastAPI from the Room Shell and Openings; callers can select an offered Zone but cannot provide Zone geometry. The authority tries the four cardinal yaws and a centre-out 0.1 m lattice inside that Zone, while preserving the same containment, collision, Opening and access rules as every other Placement. Zone derivation uses documented 0.25 m subdivisions, stable content-derived IDs and strict pre-allocation bounds; unsupported Room scale returns a typed failure rather than partial Zones.

An Arrangement is a bounded sequence of complete Design requests. After each Placement solve, FastAPI validates a connected 0.60 m-wide route among every required door and Product access region on a documented 0.05 m grid. Door approach width follows the actual Opening width, floor coverings remain walkable, and ordinary furniture remains an obstacle. The authority may try at most two explicit repairs and then remove optional requests in deterministic decoration-before-secondary order without removing required requests, protected anchors or their dependants. Public Arrangements keep required and anchor Intents immovable by default. The live-bedroom authority narrowly opts its required bed into spatial repair while preserving its request and Product identities; every repaired pose is solved and physically validated again, and the bed remains protected from drops. Every attempt is retained as typed history. Exhaustion returns `NO_VALID_DESIGN` with the limiting constraint. A non-exhaustive search also retains the most recent observed physical candidate rejection when one exists, without presenting that observation as a unique cause or proof of continuous impossibility. The conservative reachable-frontier method never claims unique Product causality: blocker attribution is explicitly limited, includes movable non-anchors, and distinguishes an unusable access connector whose Room or access geometry may itself be limiting.

Live-bedroom correction prompts may include a private, server-authored composition guide after a graph-valid failed Design. At most 32 additional diagnostic solves share one budget across dependency-closed pair checks and complete-Design checks; each keeps the ordinary 256-candidate, geometry, access, Opening and circulation authority. A changed request, including the protected anchor's spatial pose, is checked with every transitive dependent, the complete affected atomic flanking group and the ancestor chain needed to solve it; an anchor included only as context does not sweep in unrelated optional children. Repair prompts repeat bed options only for the identity-locked selected anchor Product. The guide preserves the full request/Product identity contract and contains only coordinate-free replacement Intents. A pair witness is not a Design witness. Only a successful validation of the complete selected identity set is labelled complete-Design witnessed-valid. These diagnostic solves never enter public Arrangement history, add provider calls, unlock optional drops or publish a Design; the provider must return a full repair that passes normal validation again.

Public Room input is bounded before topology checks: metre coordinates and dimensions are finite and no greater than 1000 m in magnitude, wall segments are at most 1000 m long, and a Room Shell accepts at most 64 floor vertices, 64 walls, and 128 Openings. These are practical service limits rather than a claim about the size of real rooms.

**Swap**:
Replacing the Product in an existing Placement at exactly the same pose after FastAPI validates the complete Design. Compatibility includes semantic role, Placement class, footprint, height, Opening and required-access clearance, wall contact, and whole-Design circulation. A rejected Swap leaves the prior Design unchanged; an accepted Swap cannot invalidate the Design.
_Avoid_: Replace, substitute, change

**Nudge**:
A user-initiated move of an existing Placement. A Nudge must be validated by the FastAPI authority before it is accepted. A future browser preview must have an explicit parity contract; it is not an authority.
_Avoid_: Drag, move, reposition

### The furniture

**Product**:
A real furniture item that exists in the world: real-world dimensions, a Mesh, descriptive metadata, and a link to where it can be bought.
_Avoid_: Item, furniture, SKU, model, piece

**Mesh**:
The 3D geometry and materials used to draw a Product. A Mesh represents a Product; it is not a photograph of one.
_Avoid_: Model, asset, object, 3D

**Catalogue**:
The finite set of Products a Design can be assembled from. Designs are built by selecting from the Catalogue, never by inventing furniture.
_Avoid_: Inventory, database, library, feed

**Style**:
The visual direction a user picks for a Design. Chosen by pointing at images, not by naming a style.
_Avoid_: Theme, aesthetic, vibe, taste
