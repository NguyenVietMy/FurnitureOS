# Zones, circulation and arrangement repair

FastAPI remains the only placement and whole-Design authority. Clients may
refer to a server-offered Zone ID, but cannot submit Zone geometry.

## Zone derivation

Zones use the Room's world `(x, z)` metre frame. Rectangle coordinates are
published as `minX`, `minZ`, `maxX`, `maxZ`; minimum edges are inclusive and
maximum edges are inclusive within the existing 0.001 m containment tolerance.

The bounded derivation is deterministic:

1. Sort Openings by stable ID. Reserve each non-empty Opening-clearance
   rectangle and a conservative bounding rectangle around every door-operation
   sweep. These envelopes constrain furniture and Zone derivation.
2. Subdivide the Room bounding box on a 0.25 m lattice, additionally cutting at
   Room vertices and reserved-envelope bounds. At most 128 intervals per axis
   and 16,384 atomic cells are supported.
3. Retain an atomic axis-aligned rectangle only when all four corners are
   contained by the convex Room Shell and its interior avoids every reserved
   envelope.
4. Group rectangles by identical orthogonal intervals, then coalesce contiguous
   intervals in one stable sorted pass. Apply the grouped horizontal pass and
   grouped vertical pass to a fixed point. This preserves exact full-edge merge
   semantics without repeated pairwise scans. Drop merged rectangles narrower
   or shallower than 0.60 m.
5. Sort the result by the same coordinate order. IDs are SHA-256 prefixes of
   the Room ID and canonical rectangle coordinates, so wall and Opening input
   order cannot change them. Labels are `Placement Zone 1`, `Placement Zone 2`,
   and so on in that order.

The scheme deliberately offers only rectangles proven contained; it never
offers a non-rectangular Room's bounding box. A Room beyond the subdivision
limits returns `ZONE_DERIVATION_UNSUPPORTED`.

`in_zone` evaluates yaw in `0, 90, 180, -90` degree order and centre positions
on a deterministic 0.10 m lattice whose per-axis values and expanding rank
squares are centre-out. Candidate positions are yielded lazily under the
existing 20-request and 256-candidate limits. The entire Product footprint must fit in the offered
rectangle and then pass ordinary Room containment, wall contact, Opening,
door-operation, collision and required-access checks. A full discrete search
does not claim continuous impossibility.

## Whole-Design circulation

Ticket fixtures explicitly use `clearanceWidthM = 0.60`. This is a demo design
choice, not a regulatory claim and not a value inferred from Placement Intent
`gapM`.

Each door Opening contributes a required interior approach region using its
actual width and 0.60 m depth. Its stable access ID is `door:<opening-id>`.
Each required Product access declaration contributes the already-authoritative
access rectangle, with ID `product:<request-id>:<access-index>`.

Walking validation moves an axis-aligned 0.60 m square footprint on a 0.05 m
four-neighbour grid. Access-region centres are explicit graph nodes connected
to nearby grid nodes only when the complete swept square is free. Every grid
edge likewise validates the full swept polygon, not just endpoints. The square
must remain in the convex Room Shell and must avoid every floor-standing
Product footprint. Floor coverings are walkable but do not delete their own
required access. At most 50,000 valid grid nodes are supported; larger Rooms
return `CIRCULATION_UNSUPPORTED`.

Before allocating nodes or scanning any obstacle polygon, validation caps the
raw lattice at 1,000 candidate points per axis and 50,000 candidate points in
total. Obstacle and Room comparisons use only a `1e-9 m` numerical tolerance,
so a 0.600 m aligned throat passes while 0.599 m does not; the 0.05 m grid can
still conservatively reject a continuous path that falls between grid lines.

Door-operation envelopes remain reserved for furniture placement. They are not
permanent walking obstacles: a person may use the approach with the door in a
compatible open/closed state. Furniture can therefore never occupy the sweep,
while circulation must still reach the interior door approach.

The grid is conservative: a reported clear path is validated, while a blocked
result does not claim that every continuous curve was exhausted. A blocked
result publishes stable disconnected access IDs, the 0.60 m width, implicated
request IDs and the 0.05 m resolution. Boundary attribution records obstacles
met by the reachable frontier, but this conservative method does not establish
unique Product causality. Every blocked result therefore marks attribution as
limited and includes all movable non-anchor request IDs conservatively. An
unusable access connector is called out separately because Room or access
geometry may itself be limiting. An anchor may be physically named by the
frontier but is never a drop target.

## Arrangement attempts and drops

An arrangement request carries one initial selection and at most two explicit
repair selections. Request policy is keyed by stable request ID and explicitly
declares required/optional status, anchor status and optional priority
(`decoration` or `secondary-furniture`). Every repair must preserve the exact
identity set and the required anchor Intents byte-for-byte; identity churn
cannot reset budgets.

After repair selections fail, optional requests are considered once in this
order: decoration, secondary furniture, stable request ID. A permitted drop
expands repeatedly to all object-relative dependants and both members of a
flanking pair. A closure containing a required request or anchor is skipped.
Every permitted drop reruns bounded Placement and whole-Design validation.

The complete sequence is capped at three selections plus at most twenty
original optional requests, each solve capped at 256 Placement attempts. A
Design is published as solved only after final circulation passes. Exhaustion
returns `NO_VALID_DESIGN` with the actual final Placement, circulation or
unsupported constraint and the full stable attempt history. Pydantic Room
validation remains a separate HTTP 422 diagnostic.

FurnitureOS does not publish an empty Design. If a permitted drop removes the
last optional request, the attempt records `EMPTY_DESIGN_NOT_SUPPORTED` and the
arrangement returns bounded `NO_VALID_DESIGN` rather than constructing an
invalid empty placement request.
