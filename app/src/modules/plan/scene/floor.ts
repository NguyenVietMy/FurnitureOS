/**
 * Screen point -> the spot on the floor under it.
 *
 * Both ways of putting furniture down need this: an HTML5 drop, which arrives on the
 * wrapping div and knows nothing about the camera, and a drag of something already
 * placed, which has to follow the mouse across the floor rather than across the screen.
 *
 * The result is plan coordinates, via `toPlan`, so no caller here ever holds a three.js
 * position — the mapping stays in the units module where it is documented.
 */

import { Plane, Raycaster, Vector2, Vector3, type Camera } from "three";

import { toPlan, type Point } from "@/modules/units";

/** The floor: y = 0, facing up. Items sit on it, so it is the only plane worth hitting. */
const FLOOR = new Plane(new Vector3(0, 1, 0), 0);

const raycaster = new Raycaster();
const ndc = new Vector2();
const hit = new Vector3();

/**
 * Where a screen point lands on the floor, or null when it misses.
 *
 * A miss is real: with the camera near horizontal, the top of the viewport looks at the
 * horizon, and a drop up there has no floor under it at all.
 */
export function projectToFloor(
  camera: Camera,
  element: HTMLElement,
  clientX: number,
  clientY: number,
): Point | null {
  const rect = element.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) return null;

  ndc.set(
    ((clientX - rect.left) / rect.width) * 2 - 1,
    -((clientY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(ndc, camera);

  return raycaster.ray.intersectPlane(FLOOR, hit) ? toPlan(hit.x, hit.z) : null;
}
