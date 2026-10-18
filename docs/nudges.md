# Continuously safe Nudge

`GET /api/nudges/{session_id}/region` requests `validRegionFor` a stable
Placement instance, current shared Design version, fixed yaw and fixed y.
FastAPI returns either a typed unavailable/stale/session outcome or one
conservative 2-D convex region. `POST /api/nudges` requires the server-held
region ID and target x/z; a client cannot supply a polygon or physical geometry.
The region is a useful subset of reachable valid positions, not a maximal free
space or a union of grid cells. Tight and unsupported cases fail closed.

## Analytic certificate

The constraints use baseline-relative displacement
`d = (targetX - originX, targetZ - originZ)` and normalized half-planes
`n dot d <= b`. A convex intersection contains the full straight segment
between any two admitted displacements. The browser advances from its last
safe point to the first half-plane hit, rechecks the candidate, and never shows
the unchecked pointer target. Sparse pointer events therefore cannot cross a
thin obstacle, select another free-space component, or teleport around a bend.

For convex Rooms, each boundary wall constrains all vertices of the selected body and its required access
footprints give an affine containment bound. For each forbidden moving/static
pair, a SAT edge axis and its orientation are chosen at the baseline; preserving
that same inequality preserves separation for every translation in the region.
Pairs include body/body, selected access/static body, fixed access/selected
body, relevant Opening clearance and door swing, and selected access/door
effects. Window clearance uses the ordinary fixed vertical-overlap filter.
Floor-standing/floor-covering body overlap and walkable standing access remain
permitted by class; two floor coverings still collide, and a covering's own
required access remains protected. Other/other pairs, height, y and yaw are
unchanged. The selected body is excluded from static obstacles.

Circulation certification reuses an actual successful internal witness of the
existing 0.05 m grid authority: exact 9-decimal grid coordinates, its clearance
width, axis-aligned walker squares, swept connector hulls, door targets and
required Product targets. The public circulation acceptance arithmetic is
unchanged. A new deterministic connected tree is selected within that already
valid grid using edges checked with the same exact swept predicates and extra
separation from the mover. Fixed access connectors and paths to all selected
attachments span one tree. Obsolete selected-access spokes are omitted. Each
retained fixed swept polygon is a selected-body exclusion. A covering remains
walkable and cannot disrupt the fixed circulation tree.

For each moving required access, try at most 32 deterministically ranked safe
grid attachments `q`, preferring up to 0.25 m additional headroom and then a
short connector. The scan keeps a sorted top-32 list, ejecting its worst entry
before inserting a better one; it never accumulates all eligible grid nodes or
briefly retains a 33rd candidate. Immediate original target squares can pin a
bed between its
opposite side accesses, so farther attachments are necessary. Every baseline
tether is independently checked by the owning swept predicates. It connects
the fixed walker square at `q` to the translated access-target square:

* Convex outer-hull half-planes contain both endpoints, hence their whole convex hull. In an L Room, one common oriented separator also keeps both endpoints on the same side of the excluded notch triangle. Separate opposite endpoint constraints would not prove the tether.
* For each static obstacle, **one common oriented axis** separates both
  endpoints from that obstacle. Only walker x/z axes and fixed obstacle axes
  are used; those remain owning SAT axes after translation. Independently
  choosing opposite sides at the two endpoints would not prove the tether.
* For the moved body, the access-face axis must separate the translated target
  square from the translated body at the baseline. Their relative translation
  cancels, so that endpoint separation stays constant. An additional affine
  bound keeps the fixed `q` square on the same outward side of the moving body.
  The minimum projection of the entire tether hull is the lesser endpoint
  projection, proving separation from the moved body everywhere in the hull.

Thus every selected target stays connected to the fixed tree for every admitted
translation. A lone selected access still gets exact target-square containment
and static-obstacle inequalities; it needs no connecting tree. No fixed anchor
for multiple selected accesses, insufficient useful margin, or excessive work
returns unavailable. Final ordinary whole-Design validation is a backstop and
publication gate, not the proof of the intervening preview.

For supported L Rooms, outer-hull half-planes plus one stable SAT separator against the excluded reflex triangle contain each moving convex footprint. Attachment connectors pass the same complete swept-polygon authority. Tight certificates still return unavailable; L Nudges are not globally disabled. Wall contacts survive only while their finite directed intervals, alignment and gap remain valid. See [L-shaped Rooms](l-shaped-rooms.md).

## Numeric policy and bounds

Local Room/SAT/access/Opening inequalities use their owning placement slack,
`DEFAULT_TOLERANCES.bounds_slack_m = 0.001`. Circulation/body/witness/tether
inequalities use `CIRCULATION_TOLERANCE_M = 1e-9`. A constraint is its baseline
signed separation plus that exact owning slack, **minus 1e-7 m**. Room and SAT
touch can therefore retain a usable origin with placement slack; witness touch
without enough margin needs an alternative tree or returns unavailable.

Normals and constants are JSON round-trip IEEE-754 doubles, with no outward
quantization. Only identical float normals are deduplicated, retaining the
tightest constant. Stored half-planes, not visualization vertices, define the
certificate. Server membership is `n dot d <= b - 1e-9`. Client membership and
clipping use `b - 1e-8`, with no outward epsilon. The client leaves a further
small inward fraction when clipping to a boundary and rechecks the actual
world-coordinate result; rounding failure shrinks along the same safe segment
or retains the last safe point. Malformed/nonfinite certificates fail closed;
the origin must pass the same client test.

Coordinates remain bounded to +/-1000 m, displacement to +/-1 m per coordinate,
and coefficients to unit normals. Coordinate subtraction at 1000 m has double
rounding error below 3e-13 m; the handful of projection/subtraction operations
in these bounds remain below 1e-11 m. The 1e-7 geometry margin and 1e-9/1e-8
membership offsets exceed that error. JSON round trips preserve the same float.
Python/TypeScript tests cover near-boundary placement/circulation arithmetic,
touch, large-coordinate cancellation and sparse clipping. Parity samples
supplement the affine proof; they do not replace it.

Preallocation limits are 20 Placements, 64 Room walls/vertices, 128 Openings,
the existing 50,000-node raw circulation lattice, 256 retained witness polygons,
32 attachment candidates per access and 4096 half-planes. A conservative upper
count is checked before footprint/constraint allocation. Tree polygons are
bounded before allocation. Region work checks a 2-second cooperative deadline
inside expensive loops; the ordinary circulation validation first completes
under its existing finite lattice budget. Responses expose bounded proof counts
and computation duration. Hard cases may be unavailable. Ordinary real fixtures
include a bed with >=0.05 m inward glide and a rug with >=0.20 m glide.

## Ownership and publication

One active random certificate per session is retained for
`min(120 seconds, remaining session lifetime)`; total capacity equals session
capacity. Successful issuance atomically replaces the prior certificate; failed
issuance keeps it. A newer issuance token supersedes in-flight older work.
Acceptance, expiry, session eviction or Catalogue change invalidates it. Region,
Swap candidate and mutation work use immutable snapshots outside the global
store lock. Register checks its Catalogue snapshot before publishing. Mutations
recheck record identity, shared version, expiry, Catalogue and (for Nudge) the
exact certificate before one atomic replacement. Concurrent same-version
Swap/Nudge or Nudge/Nudge requests have at most one accepted winner.

Nudge updates one instance's x/z and retains only existing wall contacts still
physically true under the original alignment/distance tolerance. Fixed y/yaw,
Product and instance identities, other Placements and original Intents remain
unchanged. Intents and Arrangement attempts are historical generation evidence;
current fits and circulation are recomputed for the accepted Design. No solver
or provider call occurs during a Nudge.

Both fixture and live pages use stable instances, session ownership and monotonic
version installation. An immediate shared mutation lease locks conflicting
controls from preparation through drag/commit/recovery. Mesh pointer rays
intersect the fixed-y floor plane with a grab offset, capture one pointer, and
update only transient safe rendering. Second touch, pointercancel, lost capture,
Escape/cancel, source replacement and unmount restore camera controls and the
confirmed pose. Page scrolling outside the active canvas remains available.
Network operations have a 15-second timeout. A lost/uncertain commit response
requires a current-session read before further mutations; failed recovery retains
the confirmed Design and lock with Retry. Late results cannot install a foreign
session or an older version.

## Proof commands

* `uv run pytest -q`
* `npm.cmd exec vitest -- run`
* `npm.cmd run typecheck`
* `npm.cmd run build`
* With the production FastAPI app at `E2E_BASE_URL` and an external
  `FURNITUREOS_EVIDENCE_DIR`:
  `npm.cmd exec playwright -- test e2e/nudges.spec.ts e2e/swaps.spec.ts e2e/room.spec.ts e2e/live-bedroom.spec.ts --workers=1`

Touch tests explicitly use `hasTouch=true`, `isMobile=true`, 390x844 and Chromium
touchStart/move/end input on the real Mesh. Controlled failure/live-generation
responses are labelled separately from real API authority checks. Physical-phone proof is waived by owner decision; deployment behavior remains a separate unrun gate. Sessions remain
process-local, without multi-worker/persistent ownership guarantees.
