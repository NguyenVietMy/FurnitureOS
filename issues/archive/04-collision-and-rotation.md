# 04 — Items collide with each other, rotate, and show blocked feedback

Type: AFK
Blocked by: 03

## Stories delivered
- As a buyer, I am prevented from overlapping two items, so that every plan I make is
  physically real.
- As a buyer, I can rotate any item with the mouse, so that editing feels direct.

## Reviewable end state
Place two sofas and try to push one through the other — it refuses and flashes red.
Rotate one 45° and try again: it still collides correctly at that angle, not against
some axis-aligned approximation. Rotate an item near a wall and it is blocked by the
wall at its true rotated footprint.

## Notes
Completes `lib/geometry`. This ticket adds oriented-bounding-box overlap (separating
axis test) on top of issue 03's containment, and makes `findFreeSpot` real.

The rotation case is the whole reason this is its own ticket: the prototype's
`rectsOverlap`/`corners` maths is axis-aligned and silently wrong for any rotated item.
Test that explicitly — two boxes that do not overlap when axis-aligned but do overlap
when one is rotated 45°, and the converse.

Also here:

- Blocked-placement feedback in the scene — the prototype's `flashBlocked` /
  `setMarkerBlocked` concepts, ported.
- `resolveDrag` slides along the blocking edge rather than stopping dead, so dragging
  feels continuous.
- Rotation control on the selected item.

Keep a spatial index or early-out behind the `roomModel` interface if drags get slow —
callers must not know it exists.

Test boundary: Vitest against `lib/geometry` fixtures. Include the invariant that any
pose returned by `findFreeSpot` reports `canPlace === true`, and that a room with no
room left returns null rather than an overlapping pose.
