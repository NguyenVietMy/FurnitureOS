/**
 * Camera-aware wall hiding.
 *
 * The buyer orbits a closed box. Without this the near walls hide everything, and with
 * it slightly wrong they flicker or hide the wrong side — both are obvious in motion
 * and invisible in a screenshot, so they get pinned here instead.
 */

import { describe, expect, it } from "vitest";

import { occludesInterior, outlineCentroid, type WallPiece } from "./geometry";
import type { Point } from "./types";

/** A 10x8 room, walls running along its edges. */
const ROOM_CENTRE: Point = [5, 4];

function piece(center: Point, angleRad: number): WallPiece {
  return {
    wallId: "outline:0",
    center,
    length_m: 10,
    thickness_m: 0.2,
    base_m: 0,
    top_m: 2.7,
    angle_rad: angleRad,
  };
}

describe("outlineCentroid", () => {
  it("is the middle of a rectangle", () => {
    const [x, y] = outlineCentroid([
      [0, 0],
      [10, 0],
      [10, 8],
      [0, 8],
    ]);

    expect(x).toBeCloseTo(5);
    expect(y).toBeCloseTo(4);
  });

  it("does not depend on winding order", () => {
    const clockwise = outlineCentroid([
      [0, 0],
      [0, 8],
      [10, 8],
      [10, 0],
    ]);

    expect(clockwise[0]).toBeCloseTo(5);
    expect(clockwise[1]).toBeCloseTo(4);
  });

  it("stays inside an L-shape, where the bounding-box centre would not", () => {
    // The seeded unit's shape. Its bounding box is 10x9, centred at (5, 4.5) — which is
    // outside the floor, in the notch.
    const outline: Point[] = [
      [0, 0],
      [10, 0],
      [10, 5],
      [6, 5],
      [6, 9],
      [0, 9],
    ];

    const [x, y] = outlineCentroid(outline);

    expect(x).toBeLessThan(5);
    expect(y).toBeLessThan(4.5);
  });
});

describe("occludesInterior", () => {
  const southWall = piece([5, 0], 0); // runs along +X at y = 0
  const northWall = piece([5, 8], 0);
  const westWall = piece([0, 4], Math.PI / 2); // runs along +Y at x = 0

  it("hides the wall the camera is looking through", () => {
    expect(occludesInterior(southWall, [5, -12], ROOM_CENTRE)).toBe(true);
    expect(occludesInterior(northWall, [5, 20], ROOM_CENTRE)).toBe(true);
    expect(occludesInterior(westWall, [-12, 4], ROOM_CENTRE)).toBe(true);
  });

  it("keeps the far wall, which the buyer is looking at", () => {
    expect(occludesInterior(northWall, [5, -12], ROOM_CENTRE)).toBe(false);
    expect(occludesInterior(southWall, [5, 20], ROOM_CENTRE)).toBe(false);
    expect(occludesInterior(westWall, [20, 4], ROOM_CENTRE)).toBe(false);
  });

  it("does not care which way the wall was drawn", () => {
    const reversed = piece([5, 0], Math.PI); // same wall, start and end swapped

    expect(occludesInterior(reversed, [5, -12], ROOM_CENTRE)).toBe(
      occludesInterior(southWall, [5, -12], ROOM_CENTRE),
    );
  });

  it("hides a wall from a camera off to the diagonal", () => {
    expect(occludesInterior(southWall, [-8, -8], ROOM_CENTRE)).toBe(true);
    expect(occludesInterior(westWall, [-8, -8], ROOM_CENTRE)).toBe(true);
    expect(occludesInterior(northWall, [-8, -8], ROOM_CENTRE)).toBe(false);
  });

  it("keeps a wall running through the interior point rather than flickering", () => {
    const throughCentre = piece(ROOM_CENTRE, 0);

    expect(occludesInterior(throughCentre, [5, -12], ROOM_CENTRE)).toBe(false);
    expect(occludesInterior(throughCentre, [5, 20], ROOM_CENTRE)).toBe(false);
  });

  it("hides an interior partition only from the side the camera is on", () => {
    const partition = piece([5, 6], 0); // between the centre and the north wall

    expect(occludesInterior(partition, [5, 20], ROOM_CENTRE)).toBe(true);
    expect(occludesInterior(partition, [5, -12], ROOM_CENTRE)).toBe(false);
  });
});
