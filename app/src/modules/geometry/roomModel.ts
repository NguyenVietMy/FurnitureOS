/**
 * The room model: the one thing that knows whether furniture fits.
 *
 * `createRoomModel(unit)` turns an apartment into three questions and nothing else:
 *
 *     canPlace(footprint, pose)              may this stand here?
 *     resolveDrag(footprint, desired, from)  where does it end up if you shove it there?
 *     findFreeSpot(footprint)                where would it go on its own?
 *
 * Pure TypeScript. No three.js, no React, no DOM. That is the point of the module: the
 * scene asks these questions and draws the answers, and polygon maths never leaks into
 * the rendering layer where it cannot be tested.
 *
 * This ticket answers containment only — the outline, and the walls inside it. Item to
 * item overlap is issue 04, which extends `canPlace` without changing this interface.
 */

import type { Point, Unit, Wall } from "@/modules/units";

import { EPSILON_M, pointInPolygon, polygonToSegment } from "./polygon";

/** An item's true plan size in metres: width across its front, depth back from it. */
export interface Footprint {
  readonly width_m: number;
  readonly depth_m: number;
}

/** Where an item stands: its centre, and its turn anticlockwise from the plan's +X. */
export interface Pose {
  readonly x_m: number;
  readonly y_m: number;
  readonly rotation_rad: number;
}

export interface RoomModel {
  canPlace(footprint: Footprint, pose: Pose): boolean;
  /**
   * The furthest legal pose towards `desired`, starting from the legal pose `from`.
   *
   * Never returns a pose `canPlace` would reject, so a caller can use the result
   * without re-checking. When nothing between the two is legal — a footprint that fits
   * nowhere near, say — the item stays exactly where it was.
   */
  resolveDrag(footprint: Footprint, desired: Pose, from: Pose): Pose;
  /**
   * Somewhere this footprint fits, or null when the room has no room.
   *
   * Given `near`, it searches outward from there and returns that exact point when the
   * item already fits — which is what turns a drop aimed slightly into a wall into a
   * sofa against the wall rather than a sofa in another room.
   */
  findFreeSpot(footprint: Footprint, near?: Point): Pose | null;
}

/** How finely `findFreeSpot` samples the floor. Small enough to find a gap by a sofa. */
const SEARCH_STEP_M = 0.25;

/** How far a drop is nudged to find floor, and how finely. Beyond this, it is a miss. */
const NUDGE_RADIUS_M = 2;
const NUDGE_STEP_M = 0.05;

/**
 * Bisection steps for a blocked drag. 24 halvings of a room-sized span land inside a
 * micrometre, which is four orders of magnitude finer than anyone can drag a mouse.
 */
const SLIDE_STEPS = 24;

export function createRoomModel(unit: Unit): RoomModel {
  const outline = unit.outline;
  const walls = unit.walls;

  const canPlace = (footprint: Footprint, pose: Pose): boolean => {
    const corners = footprintCorners(footprint, pose);

    // Inside the apartment at all. A non-convex outline makes this a real question:
    // the L-shaped unit's missing quadrant sits happily inside its bounding box.
    if (!corners.every((corner) => pointInPolygon(corner, outline))) return false;

    // Clear of every wall's solid face. Walls are drawn centred on their line, so the
    // face is half a thickness in — measuring to the centreline would let a sofa sink
    // 10cm into the plaster, which is exactly the argument this app exists to prevent.
    return walls.every((wall) => clearsWall(corners, wall));
  };

  const resolveDrag = (footprint: Footprint, desired: Pose, from: Pose): Pose => {
    if (canPlace(footprint, desired)) return desired;

    const at = (xM: number, yM: number): Pose => ({
      x_m: xM,
      y_m: yM,
      rotation_rad: desired.rotation_rad,
    });

    /** The furthest point along `origin -> target` that still stands up. */
    const furthest = (origin: Pose | null, target: Pose): Pose | null => {
      if (origin === null || !canPlace(footprint, origin)) return null;

      let low = 0;
      let high = 1;
      for (let step = 0; step < SLIDE_STEPS; step += 1) {
        const mid = (low + high) / 2;
        if (canPlace(footprint, lerp(origin, target, mid))) low = mid;
        else high = mid;
      }

      return lerp(origin, target, low);
    };

    const start = at(from.x_m, from.y_m);

    /**
     * Spend the drag on one axis, then the other, then whatever diagonal is left.
     *
     * This is what turns "pushed into the south wall while moving east" into an item
     * that travels east *along* the wall instead of stopping where it touched. Both
     * orders are tried because an inside corner blocks whichever axis is taken first.
     */
    const slide = (firstAxis: "x" | "y"): Pose | null => {
      const firstTarget =
        firstAxis === "x" ? at(desired.x_m, from.y_m) : at(from.x_m, desired.y_m);
      const afterFirst = furthest(start, firstTarget);
      if (afterFirst === null) return null;

      const secondTarget =
        firstAxis === "x"
          ? at(afterFirst.x_m, desired.y_m)
          : at(desired.x_m, afterFirst.y_m);
      const afterSecond = furthest(afterFirst, secondTarget) ?? afterFirst;

      return furthest(afterSecond, desired) ?? afterSecond;
    };

    const reachable = [slide("x"), slide("y"), furthest(start, desired)].filter(
      (pose): pose is Pose => pose !== null,
    );
    if (reachable.length === 0) return from;

    return reachable.reduce((best, pose) =>
      distanceTo(pose, desired) < distanceTo(best, desired) ? pose : best,
    );
  };

  const findFreeSpot = (footprint: Footprint, near?: Point): Pose | null => {
    if (near) {
      const nearby = searchOutward(footprint, near, canPlace);
      if (nearby) return nearby;
    }

    const [minX, minY, maxX, maxY] = bounds(outline);

    // Scanned in a fixed order so inserting the same item twice does not wander. It
    // returns the first gap rather than the best one; issue 04 makes this smarter once
    // there are other items to be smart about.
    for (let y = minY; y <= maxY; y += SEARCH_STEP_M) {
      for (let x = minX; x <= maxX; x += SEARCH_STEP_M) {
        const pose = { x_m: x, y_m: y, rotation_rad: 0 };
        if (canPlace(footprint, pose)) return pose;
      }
    }

    return null;
  };

  return { canPlace, resolveDrag, findFreeSpot };
}

/**
 * The nearest point to `near` where the footprint stands up, or null within the radius.
 *
 * Candidates are a grid walked in order of true distance, so "nearest" really is
 * nearest — a drop 20cm into the south wall comes back straight north against it,
 * rather than off to one side as a ring sweep would leave it.
 *
 * Bounded, because past a couple of metres "nearest free floor" is no longer what the
 * buyer meant and the caller should fall back to a full scan.
 */
function searchOutward(
  footprint: Footprint,
  near: Point,
  canPlace: (footprint: Footprint, pose: Pose) => boolean,
): Pose | null {
  for (const [offsetX, offsetY] of NUDGE_OFFSETS) {
    const pose = { x_m: near[0] + offsetX, y_m: near[1] + offsetY, rotation_rad: 0 };
    if (canPlace(footprint, pose)) return pose;
  }

  return null;
}

/** Offsets within the nudge radius, nearest first. Built once; the values are constant. */
const NUDGE_OFFSETS: readonly Point[] = buildNudgeOffsets();

function buildNudgeOffsets(): Point[] {
  const steps = Math.round(NUDGE_RADIUS_M / NUDGE_STEP_M);
  const offsets: Point[] = [];

  for (let stepX = -steps; stepX <= steps; stepX += 1) {
    for (let stepY = -steps; stepY <= steps; stepY += 1) {
      const offset: Point = [stepX * NUDGE_STEP_M, stepY * NUDGE_STEP_M];
      if (Math.hypot(offset[0], offset[1]) <= NUDGE_RADIUS_M) offsets.push(offset);
    }
  }

  return offsets.sort((a, b) => Math.hypot(a[0], a[1]) - Math.hypot(b[0], b[1]));
}

/**
 * The four corners of an item's footprint, in plan coordinates.
 *
 * Width runs along the item's local X and depth along its local Y, both rotated by the
 * pose. Rotating the true rectangle — rather than growing an axis-aligned box around
 * it — is what makes a turned sofa collide where it looks like it should.
 */
export function footprintCorners(footprint: Footprint, pose: Pose): Point[] {
  const halfWidth = footprint.width_m / 2;
  const halfDepth = footprint.depth_m / 2;
  const cos = Math.cos(pose.rotation_rad);
  const sin = Math.sin(pose.rotation_rad);

  return (
    [
      [-halfWidth, -halfDepth],
      [halfWidth, -halfDepth],
      [halfWidth, halfDepth],
      [-halfWidth, halfDepth],
    ] as const
  ).map(([localX, localY]): Point => [
    pose.x_m + localX * cos - localY * sin,
    pose.y_m + localX * sin + localY * cos,
  ]);
}

function clearsWall(corners: readonly Point[], wall: Wall): boolean {
  const faceM = wall.thickness_m / 2;
  return polygonToSegment(corners, wall.start, wall.end) >= faceM - EPSILON_M;
}

function lerp(from: Pose, to: Pose, t: number): Pose {
  return {
    x_m: from.x_m + (to.x_m - from.x_m) * t,
    y_m: from.y_m + (to.y_m - from.y_m) * t,
    rotation_rad: to.rotation_rad,
  };
}

function distanceTo(pose: Pose, target: Pose): number {
  return Math.hypot(pose.x_m - target.x_m, pose.y_m - target.y_m);
}

function bounds(outline: readonly Point[]): [number, number, number, number] {
  const xs = outline.map(([x]) => x);
  const ys = outline.map(([, y]) => y);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}
