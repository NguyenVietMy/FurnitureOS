/**
 * Turning an item with the mouse.
 *
 * The handle sits in front of the item — along its local +Y, the direction its depth
 * runs — and dragging that handle points the front of the item at the pointer. Direct
 * manipulation: the thing under the mouse is the thing that moves.
 *
 * Pure arithmetic, kept out of the scene so it can be tested without a canvas.
 */

import type { Point } from "@/modules/units";

/**
 * How coarsely a turn lands: 24 positions round the circle.
 *
 * Furniture in a real room is square-on to a wall or at a deliberate angle to it, never
 * at 37.4°. Snapping is what lets a hand hit "square to that wall" and "half a turn"
 * exactly, and it is why an item nudged during a drag does not end up 2° off true.
 */
export const ROTATION_STEP_RAD = Math.PI / 12;

const FULL_TURN_RAD = Math.PI * 2;

/** Below this the pointer is on top of the centre and the drag has no direction in it. */
const DEAD_ZONE_M = 0.05;

/**
 * The rotation that points the item's front at `pointer`, snapped to the step.
 *
 * Returns `current` unchanged when the pointer is on the item's centre, where the angle
 * is meaningless — dragging the handle across the middle of a sofa must not spin it.
 */
export function rotationToward(centre: Point, pointer: Point, current: number): number {
  const dx = pointer[0] - centre[0];
  const dy = pointer[1] - centre[1];
  if (Math.hypot(dx, dy) < DEAD_ZONE_M) return current;

  // Less a quarter turn: the handle points along the item's +Y, and `rotation_rad` is
  // measured from +X.
  const facing = Math.atan2(dy, dx) - Math.PI / 2;
  const snapped = Math.round(facing / ROTATION_STEP_RAD) * ROTATION_STEP_RAD;

  // Snap first, wrap second. The other order lets a rotation that snaps up to a full
  // turn come back as 2π rather than 0.
  return ((snapped % FULL_TURN_RAD) + FULL_TURN_RAD) % FULL_TURN_RAD;
}
