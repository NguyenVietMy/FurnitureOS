# Supported L-shaped Rooms

Capture supports Rectangle and an orthogonal L. FastAPI remains authoritative: vision supplies semantics, the user chooses topology and confirms scale, and the provider selects Products and coordinate-free Placement Intents.

## Capture contract

The five L dimensions are overall width W, overall depth D, notch width NW, notch depth ND and ceiling height H, in metres. Each is finite, positive and at most 1000. NW < W and ND < D. The absent corner is the diagram's top-right corner. This is an association convention, without inferred compass directions.

With x right and z down, the canonical perimeter is (-W/2,-D/2), (W/2-NW,-D/2), (W/2-NW,-D/2+ND), (W/2,-D/2+ND), (W/2,D/2), (-W/2,D/2).

| Label | Stable ID | Directed length |
| --- | --- | --- |
| A | wall-north | W − NW |
| B | wall-notch-vertical | ND |
| C | wall-notch-horizontal | NW |
| D | wall-east | D − ND |
| E | wall-south | W |
| F | wall-west | D |

Closure is A + C = E and B + D = F. Opening distances and hinge start/end refer to each actual directed wall. Rectangle retains its four original IDs and A/B/C/D ordering.

Every active wall requires a distinct accepted primary photo and explicit Opening inventory review. Observed secondary walls do not replace primary coverage. Limits remain eight photos and 32 MB lifetime input reservation. Invalid dimensions and inactive primary associations remain editable blockers; they never become a bounding rectangle.

## Save and review transitions

Save Room details before confirming changed measurements. The server installs its normalized saved draft; the user then explicitly confirms the saved dimensions and reviews the Opening inventory. The checkbox and final confirmation stay unavailable while active metric/topology edits are unsaved. Final confirmation can save ordinary Opening/review edits whose metric truth is unchanged.

Changing any active dimension, including ceiling height, forces dimensionsConfirmed=false, clears every wall review and clears every Opening reviewed flag. Typed Opening metrics and wall IDs survive metric changes. Every dimension deliberately maps to all active walls.

Changing topology additionally clears Opening wall IDs, calibration records, dimension evidence and unchanged applied provisional values without manual override. Photo bytes, quotas, primary IDs and analysis attempt counters survive. Stored semantics and observed associations clear, and analysis becomes unknown. Inactive primary IDs require reassociation or removal. Inactive notch fields normalize away on rectangles.

HTTP normalization and the SQL transaction independently enforce these rules. Stale flags in the same mutation cannot bypass invalidation. Existing owner, expiry, revision, lease and confirmed-Room-hash authority remains. Notch reference targets are floor-plane lengths; height remains a wall-plane length. Estimates remain provisional, photo/hash bound and editable.

## Shared geometry authority

General Room Shells retain valid convex polygons and add simple six-edge orthogonal L polygons, including rotations and reversed winding. Arbitrary concavity, duplicate/collinear vertices, self-intersection and mismatched walls remain invalid.

Wall inward orientation follows boundary winding and actual wall direction. Declared Product contact must fit the finite directed wall interval as well as the plane, alignment and gap tolerances. Contact beyond or partially overhanging a notch-wall endpoint is rejected. Nudge drops contacts that cease to be physically true.

A supported L equals its convex hull minus the open triangle formed by its reflex vertex and its neighbours. Hull containment plus SAT separation from that triangle proves complete convex-subject containment for Product/access footprints, atomic/merged Zone rectangles and every circulation target, connector and edge sweep. Corner/centre samples are insufficient. Concave point depth uses finite boundary distances and actual inside/outside.

The optimized convex path, 0.25 m Zone subdivision, stable IDs, 0.05 m circulation lattice, 0.60 m walking width, existing tolerances and finite budgets remain. Bounded failure does not claim continuous impossibility.

Nudge certificates remain convex conservative translation regions. Outer-hull half-planes and a stable notch separator constrain each mover. Tethers require one common separator for both endpoints against the notch, proving their complete swept hull. Insufficient numeric margin/work returns unavailable. The browser clips returned constraints without solving placement geometry.

The floor is triangulated as a concave polygon. Decorative grid segments are clipped to the floor boundary, and wall faces use winding-correct normals.

## Migration and proof boundary

20261018180615_capture_l_shaped_rooms.sql is additive; all four earlier migrations remain byte-for-byte unchanged. It extends wall IDs/observed cardinality and existing transaction functions while preserving security-definer search paths, owner locks, grants and lifecycle invariants. It changes no Storage read policy or readiness flag and contains no empty-state cutover.

Local proof applies the old migrations to an empty fixture, adds the new migration and runs all SQL contracts. A separate populated rectangle upgrade applies only the additive migration after population, checking unchanged rows/revision and owner access. This is simulated Auth/Storage SQL proof, not hosted RLS/CDN proof.

Controlled browser fixtures use six distinct synthetic JPEG byte hashes, controlled Auth/Storage/provider transport, actual Python normalization/confirmation/calibration and the real HTTP arrangement solver. They inspect actual Product Mesh rendering on desktop/mobile viewports. They do not establish actual-photo AI accuracy.

Hosted activation remains a separately authorized, unrun action. Physical-phone and physical manual-calibration testing are waived. Actual-photo AI accuracy and paid provider integration remain UNRUN and deferred to the end of the project.

