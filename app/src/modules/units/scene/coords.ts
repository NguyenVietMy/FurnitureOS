/**
 * The one place the plan's 2D coordinates meet three.js.
 *
 * The plan is a right-handed XY plane with +Y forward. three.js is Y-up, so the plan
 * lies in XZ with plan +Y mapping to world -Z. Getting this backwards mirrors the whole
 * apartment — which looks plausible until a buyer notices their kitchen is on the wrong
 * side — so the mapping lives here and nowhere else.
 */

import type { Point } from "../types";

/** Plan (x, y) -> world (x, height, z). */
export function toWorld(point: Point, heightM = 0): [number, number, number] {
  return [point[0], heightM, -point[1]];
}

/** World (x, _, z) -> plan (x, y). The inverse of `toWorld`, for the camera. */
export function toPlan(x: number, z: number): Point {
  return [x, -z];
}

/**
 * Rotation about the world Y axis that points a box's local +X along the wall.
 *
 * Equal to the plan angle: rotating +X by θ about Y gives (cos θ, 0, -sin θ), which is
 * exactly `toWorld` applied to the plan direction (cos θ, sin θ).
 */
export function toWorldRotation(angleRad: number): [number, number, number] {
  return [0, angleRad, 0];
}
