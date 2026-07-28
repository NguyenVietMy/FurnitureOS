/**
 * Plane geometry primitives. Internal to the geometry module on purpose.
 *
 * Everything here is metres in the plan's XY, and nothing here knows what a sofa is.
 * The room model is the only caller; keeping these private is what stops polygon maths
 * from leaking into the scene layer one convenient import at a time.
 */

import type { Point } from "@/modules/units";

/** Below this, two numbers came out of the same measurement and differ by rounding. */
export const EPSILON_M = 1e-9;

/**
 * Ray casting, counting the boundary as inside.
 *
 * Boundary-inclusive matters: room polygons share edges with the outline, and an item
 * flush against a wall lands its corners exactly on a derived line often enough that
 * the exclusive version would flicker.
 */
export function pointInPolygon(point: Point, polygon: readonly Point[]): boolean {
  if (pointOnBoundary(point, polygon)) return true;

  const [x, y] = point;
  let inside = false;

  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index];
    const [x2, y2] = polygon[(index + 1) % polygon.length];
    if (y1 > y !== y2 > y) {
      const crossingX = x1 + ((y - y1) / (y2 - y1)) * (x2 - x1);
      if (crossingX > x) inside = !inside;
    }
  }

  return inside;
}

function pointOnBoundary(point: Point, polygon: readonly Point[]): boolean {
  for (let index = 0; index < polygon.length; index += 1) {
    const start = polygon[index];
    const end = polygon[(index + 1) % polygon.length];
    if (pointToSegment(point, start, end) <= EPSILON_M) return true;
  }
  return false;
}

/** Shortest distance from a point to a segment. */
export function pointToSegment(point: Point, start: Point, end: Point): number {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const lengthSquared = dx * dx + dy * dy;

  if (lengthSquared === 0) return Math.hypot(point[0] - start[0], point[1] - start[1]);

  const t = Math.max(
    0,
    Math.min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / lengthSquared),
  );

  return Math.hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy));
}

/** Shortest distance between two segments. Zero when they cross. */
export function segmentToSegment(a1: Point, a2: Point, b1: Point, b2: Point): number {
  if (segmentsIntersect(a1, a2, b1, b2)) return 0;

  return Math.min(
    pointToSegment(a1, b1, b2),
    pointToSegment(a2, b1, b2),
    pointToSegment(b1, a1, a2),
    pointToSegment(b2, a1, a2),
  );
}

function segmentsIntersect(a1: Point, a2: Point, b1: Point, b2: Point): boolean {
  const d1 = cross(b1, b2, a1);
  const d2 = cross(b1, b2, a2);
  const d3 = cross(a1, a2, b1);
  const d4 = cross(a1, a2, b2);

  // Strict straddle on both sides. Touching without crossing is left to the distance
  // check above, which reports the (zero) separation just as accurately.
  return d1 * d2 < 0 && d3 * d4 < 0;
}

function cross(from: Point, to: Point, point: Point): number {
  return (to[0] - from[0]) * (point[1] - from[1]) - (to[1] - from[1]) * (point[0] - from[0]);
}

/**
 * Shortest distance from a convex polygon's *solid area* to a segment.
 *
 * Zero when the segment touches or passes through the polygon — including the case
 * where the segment lies wholly inside it, which an edges-only comparison would report
 * as a comfortable clearance.
 */
/** Do two convex polygons share any area? Touching along an edge does not count. */
export function convexOverlap(a: readonly Point[], b: readonly Point[]): boolean {
  return !separated(a, b) && !separated(b, a);
}

/**
 * Is there a line perpendicular to one of `polygon`'s edges with `other` wholly clear
 * of it on one side?
 *
 * Half of the separating axis test. For convex shapes, no such line existing on either
 * shape's edges is exactly the same statement as the two shapes overlapping — which is
 * why this handles a rotated sofa correctly with no special case for the angle, where
 * comparing bounding boxes is wrong in both directions at once: it invents collisions
 * between two items turned away from each other and misses real ones between two turned
 * towards each other.
 *
 * Contact counts as clear. Items pushed flush against each other are what a furnished
 * room looks like, and a buyer sliding a nightstand up to a bed must be able to land it.
 */
function separated(polygon: readonly Point[], other: readonly Point[]): boolean {
  for (let index = 0; index < polygon.length; index += 1) {
    const [x1, y1] = polygon[index];
    const [x2, y2] = polygon[(index + 1) % polygon.length];

    // The edge's outward normal, unit length, so the gap below is measured in metres.
    const length = Math.hypot(x2 - x1, y2 - y1);
    if (length === 0) continue;
    const axis: Point = [-(y2 - y1) / length, (x2 - x1) / length];

    const [minSelf, maxSelf] = project(polygon, axis);
    const [minOther, maxOther] = project(other, axis);

    if (maxSelf <= minOther + EPSILON_M || maxOther <= minSelf + EPSILON_M) return true;
  }

  return false;
}

/** The shadow a polygon casts on an axis: how far along it the polygon reaches. */
function project(polygon: readonly Point[], axis: Point): [number, number] {
  let min = Infinity;
  let max = -Infinity;

  for (const [x, y] of polygon) {
    const along = x * axis[0] + y * axis[1];
    min = Math.min(min, along);
    max = Math.max(max, along);
  }

  return [min, max];
}

export function polygonToSegment(
  polygon: readonly Point[],
  start: Point,
  end: Point,
): number {
  if (pointInPolygon(start, polygon) || pointInPolygon(end, polygon)) return 0;

  let closest = Infinity;
  for (let index = 0; index < polygon.length; index += 1) {
    const edgeStart = polygon[index];
    const edgeEnd = polygon[(index + 1) % polygon.length];
    closest = Math.min(closest, segmentToSegment(edgeStart, edgeEnd, start, end));
    if (closest === 0) return 0;
  }

  return closest;
}
