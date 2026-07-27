/**
 * The room model: can this thing go here, and where does it end up if you shove it.
 *
 * This is the heart of the suite. Everything a buyer believes about "it fits" is
 * decided by `canPlace`, and everything that makes dragging feel solid is decided by
 * `resolveDrag`. Both are pure functions over polygons, so they are tested here against
 * awkward fixtures rather than by eye against a render.
 *
 * Containment only. Item-to-item overlap is issue 04.
 */

import { describe, expect, it } from "vitest";

import {
  OUTER_WALL_THICKNESS_M,
  PARTITION_THICKNESS_M,
  lShapedUnit,
  notchedUnit,
  rectangleUnit,
  unitFrom,
} from "./fixtures";
import { createRoomModel, type Footprint, type Pose } from "./roomModel";

const SOFA: Footprint = { width_m: 2.1, depth_m: 0.9 };

function pose(xM: number, yM: number, rotationRad = 0): Pose {
  return { x_m: xM, y_m: yM, rotation_rad: rotationRad };
}

/** Half the outer wall's thickness: how far the wall's solid face is from its centreline. */
const WALL_FACE_M = OUTER_WALL_THICKNESS_M / 2;

describe("canPlace — containment", () => {
  const model = createRoomModel(rectangleUnit(6, 4));

  it("accepts an item in open floor", () => {
    expect(model.canPlace(SOFA, pose(3, 2))).toBe(true);
  });

  it("rejects an item outside the apartment altogether", () => {
    expect(model.canPlace(SOFA, pose(20, 20))).toBe(false);
  });

  it("rejects an item whose centre is inside but whose corner is not", () => {
    // Centre 5cm from the east wall: the item is mostly in the room and still wrong.
    expect(model.canPlace(SOFA, pose(5.95, 2))).toBe(false);
  });

  it("accepts an item flush against a wall's inner face", () => {
    const flushM = WALL_FACE_M + SOFA.depth_m / 2;

    expect(model.canPlace(SOFA, pose(3, flushM))).toBe(true);
  });

  it("rejects an item one centimetre inside the wall", () => {
    const flushM = WALL_FACE_M + SOFA.depth_m / 2;

    expect(model.canPlace(SOFA, pose(3, flushM - 0.01))).toBe(false);
  });

  it("measures the wall from its face, not its centreline", () => {
    // Standing on the centreline would be legal if thickness were ignored.
    expect(model.canPlace(SOFA, pose(3, SOFA.depth_m / 2))).toBe(false);
  });
});

describe("canPlace — rotation", () => {
  // 4.0 across, 2.0 deep inside the walls. A 3m plank fits east-west and cannot fit
  // north-south, which is only true if rotation is honoured.
  const model = createRoomModel(rectangleUnit(4 + OUTER_WALL_THICKNESS_M, 2 + OUTER_WALL_THICKNESS_M));
  const plank: Footprint = { width_m: 3, depth_m: 0.5 };
  const centre = pose((4 + OUTER_WALL_THICKNESS_M) / 2, (2 + OUTER_WALL_THICKNESS_M) / 2);

  it("fits along the long axis", () => {
    expect(model.canPlace(plank, centre)).toBe(true);
  });

  it("does not fit turned a quarter turn", () => {
    expect(model.canPlace(plank, { ...centre, rotation_rad: Math.PI / 2 })).toBe(false);
  });

  it("is blocked at 45° where its true corners reach further than its width", () => {
    // The diagonal half-extent at 45° is (3 + 0.5) / (2√2) ≈ 1.237m, past the 1m
    // half-depth of the room. An axis-aligned approximation would let this through.
    expect(model.canPlace(plank, { ...centre, rotation_rad: Math.PI / 4 })).toBe(false);
  });
});

describe("canPlace — non-convex outlines", () => {
  it("rejects a spot in the L's missing corner", () => {
    const model = createRoomModel(lShapedUnit());

    // Inside the bounding box, outside the apartment.
    expect(model.canPlace(SOFA, pose(8, 7))).toBe(false);
    expect(model.canPlace(SOFA, pose(3, 7))).toBe(true);
  });

  it("rejects an item spanning the L's inner corner", () => {
    const model = createRoomModel(lShapedUnit());
    const rug: Footprint = { width_m: 3, depth_m: 3 };

    // Centred on the reflex vertex at (6, 5): half of it hangs over open air.
    expect(model.canPlace(rug, pose(6, 5))).toBe(false);
  });

  it("lets a small item sit inside a doorway recess", () => {
    const model = createRoomModel(notchedUnit());
    const plant: Footprint = { width_m: 0.5, depth_m: 0.5 };

    expect(model.canPlace(plant, pose(3, 4.45))).toBe(true);
    // The recess is 1.2m wide between wall centrelines, so 1.0m of clear floor.
    const bench: Footprint = { width_m: 1.1, depth_m: 0.5 };
    expect(model.canPlace(bench, pose(3, 4.45))).toBe(false);
  });
});

describe("canPlace — partitions", () => {
  // 10 × 4, split down the middle at x = 5.
  const model = createRoomModel(
    unitFrom(
      [
        [0, 0],
        [10, 0],
        [10, 4],
        [0, 4],
      ],
      [{ start: [5, 0], end: [5, 4] }],
    ),
  );

  it("refuses to push an item through a partition", () => {
    expect(model.canPlace(SOFA, pose(5, 2))).toBe(false);
  });

  it("accepts an item flush against the partition's face", () => {
    const flushM = 5 - PARTITION_THICKNESS_M / 2 - SOFA.depth_m / 2;

    expect(model.canPlace(SOFA, { ...pose(flushM, 2), rotation_rad: Math.PI / 2 })).toBe(true);
  });

  it("still refuses one centimetre further in", () => {
    const flushM = 5 - PARTITION_THICKNESS_M / 2 - SOFA.depth_m / 2;

    expect(model.canPlace(SOFA, { ...pose(flushM + 0.01, 2), rotation_rad: Math.PI / 2 })).toBe(
      false,
    );
  });
});

describe("canPlace — a room too thin to furnish", () => {
  it("accepts nothing and admits it", () => {
    // 0.6m of clear floor north to south. Nothing in the catalogue is that shallow.
    const model = createRoomModel(rectangleUnit(6, 0.8));

    expect(model.canPlace(SOFA, pose(3, 0.4))).toBe(false);
    expect(model.findFreeSpot(SOFA)).toBeNull();
  });
});

describe("resolveDrag", () => {
  const model = createRoomModel(rectangleUnit(6, 4));
  const start = pose(3, 2);

  it("returns the desired pose when it is legal", () => {
    const desired = pose(2, 1.5);

    expect(model.resolveDrag(SOFA, desired, start)).toEqual(desired);
  });

  it("never returns a pose that canPlace rejects", () => {
    const desired = pose(50, -50);

    const resolved = model.resolveDrag(SOFA, desired, start);

    expect(model.canPlace(SOFA, resolved)).toBe(true);
  });

  it("clamps to the wall face rather than stopping where the drag began", () => {
    const flushM = WALL_FACE_M + SOFA.depth_m / 2;

    const resolved = model.resolveDrag(SOFA, pose(3, -5), start);

    expect(resolved.y_m).toBeCloseTo(flushM, 3);
    expect(resolved.x_m).toBeCloseTo(3, 6);
  });

  it("slides along a wall instead of sticking to it", () => {
    // Drag hard into the south wall and well to the east at the same time. The wall
    // stops the southward half; the eastward half must still happen.
    const resolved = model.resolveDrag(SOFA, pose(4.5, -5), start);

    expect(resolved.x_m).toBeCloseTo(4.5, 6);
    expect(resolved.y_m).toBeCloseTo(WALL_FACE_M + SOFA.depth_m / 2, 3);
  });

  it("slides into a corner from a diagonal drag", () => {
    const resolved = model.resolveDrag(SOFA, pose(-5, -5), start);

    expect(model.canPlace(SOFA, resolved)).toBe(true);
    expect(resolved.x_m).toBeCloseTo(WALL_FACE_M + SOFA.width_m / 2, 3);
    expect(resolved.y_m).toBeCloseTo(WALL_FACE_M + SOFA.depth_m / 2, 3);
  });

  it("keeps the item where it was when nothing at all is reachable", () => {
    const rotated = { ...start, rotation_rad: Math.PI / 2 };
    const tiny = createRoomModel(rectangleUnit(6, 4));

    // A rotation that cannot be honoured anywhere near the start pose leaves the pose
    // alone rather than teleporting the item somewhere legal.
    const resolved = tiny.resolveDrag({ width_m: 5, depth_m: 3.5 }, rotated, start);

    expect(resolved).toEqual(start);
  });
});

describe("findFreeSpot", () => {
  it("returns a pose the model itself accepts", () => {
    const model = createRoomModel(lShapedUnit());

    const spot = model.findFreeSpot(SOFA);

    expect(spot).not.toBeNull();
    expect(model.canPlace(SOFA, spot!)).toBe(true);
  });

  it("returns null rather than an illegal pose when nothing fits", () => {
    const model = createRoomModel(rectangleUnit(6, 4));

    expect(model.findFreeSpot({ width_m: 9, depth_m: 9 })).toBeNull();
  });

  it("is deterministic, so a repeated insert does not wander", () => {
    const model = createRoomModel(lShapedUnit());

    expect(model.findFreeSpot(SOFA)).toEqual(model.findFreeSpot(SOFA));
  });

  it("returns the asked-for point when the item already fits there", () => {
    const model = createRoomModel(rectangleUnit(6, 4));

    const spot = model.findFreeSpot(SOFA, [3, 2]);

    expect(spot).toEqual({ x_m: 3, y_m: 2, rotation_rad: 0 });
  });

  it("nudges to the nearest floor when the asked-for point is inside a wall", () => {
    // A buyer dropping a sofa aims at the wall they want it against and overshoots.
    const model = createRoomModel(rectangleUnit(6, 4));

    const spot = model.findFreeSpot(SOFA, [3, -0.2]);

    expect(spot).not.toBeNull();
    expect(model.canPlace(SOFA, spot!)).toBe(true);
    expect(spot!.y_m).toBeLessThan(1);
    expect(spot!.x_m).toBeCloseTo(3, 1);
  });

  it("still gives up when the item fits nowhere at all", () => {
    const model = createRoomModel(rectangleUnit(6, 0.8));

    expect(model.findFreeSpot(SOFA, [3, 0.4])).toBeNull();
  });
});
