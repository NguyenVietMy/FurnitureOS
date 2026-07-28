/**
 * The room model: can this thing go here, and where does it end up if you shove it.
 *
 * This is the heart of the suite. Everything a buyer believes about "it fits" is
 * decided by `canPlace`, and everything that makes dragging feel solid is decided by
 * `resolveDrag`. Both are pure functions over polygons, so they are tested here against
 * awkward fixtures rather than by eye against a render.
 *
 * Containment is the walls and the outline; overlap is the furniture already standing
 * there. Both go through the same `canPlace`, because to a buyer they are one question.
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
import { createRoomModel, type Footprint, type Occupant, type Pose } from "./roomModel";

const SOFA: Footprint = { width_m: 2.1, depth_m: 0.9 };
/** A metre square: small enough to leave room to manoeuvre round it in a 10 × 10 hall. */
const BLOCK: Footprint = { width_m: 1, depth_m: 1 };

function pose(xM: number, yM: number, rotationRad = 0): Pose {
  return { x_m: xM, y_m: yM, rotation_rad: rotationRad };
}

function standing(key: string, footprint: Footprint, at: Pose): Occupant {
  return { key, footprint, pose: at };
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

describe("canPlace — item against item", () => {
  const hall = rectangleUnit(10, 10);

  it("accepts a spot clear of everything already standing there", () => {
    const model = createRoomModel(hall, [standing("a", SOFA, pose(2, 2))]);

    expect(model.canPlace(SOFA, pose(6, 6))).toBe(true);
  });

  it("refuses to push one item through another", () => {
    const model = createRoomModel(hall, [standing("a", SOFA, pose(5, 5))]);

    expect(model.canPlace(SOFA, pose(5.5, 5))).toBe(false);
  });

  it("accepts two items flush side by side, because touching is not overlapping", () => {
    const model = createRoomModel(hall, [standing("a", SOFA, pose(5, 5))]);

    expect(model.canPlace(SOFA, pose(5, 5 + SOFA.depth_m))).toBe(true);
    expect(model.canPlace(SOFA, pose(5, 5 + SOFA.depth_m - 0.01))).toBe(false);
  });

  it("does not let an item collide with itself while it is being moved", () => {
    const model = createRoomModel(hall, [standing("sofa", SOFA, pose(5, 5))]);

    expect(model.canPlace(SOFA, pose(5, 5))).toBe(false);
    expect(model.canPlace(SOFA, pose(5, 5), "sofa")).toBe(true);
  });

  it("still refuses a spot that is clear of the furniture but inside a wall", () => {
    const model = createRoomModel(hall, [standing("a", SOFA, pose(5, 5))]);

    expect(model.canPlace(SOFA, pose(5, 0))).toBe(false);
  });
});

describe("canPlace — overlap once an item is turned", () => {
  const hall = rectangleUnit(10, 10);
  const plank: Footprint = { width_m: 2, depth_m: 0.6 };
  const quarterTurn = Math.PI / 4;

  it("catches an overlap that exists only at 45°", () => {
    // Two planks 0.3m apart square-on. Turned, the upper one's corner swings down to
    // (4.51, 3.98) — inside the lower plank. Axis-aligned maths sees no collision here.
    const model = createRoomModel(hall, [standing("a", plank, pose(5, 4))]);

    expect(model.canPlace(plank, pose(5, 4.9))).toBe(true);
    expect(model.canPlace(plank, pose(5, 4.9, quarterTurn))).toBe(false);
  });

  it("clears an overlap that exists only while both are square-on", () => {
    // Two metre squares overlapping corner to corner. Turn one 45° and its nearest edge
    // pulls back past the other's corner — while its *bounding box* grows, so the naive
    // maths reports a collision that is not there and refuses a legal placement.
    const model = createRoomModel(hall, [standing("a", BLOCK, pose(5, 5))]);

    expect(model.canPlace(BLOCK, pose(5.9, 5.9))).toBe(false);
    expect(model.canPlace(BLOCK, pose(5.9, 5.9, quarterTurn))).toBe(true);
  });

  it("collides with a wall at the footprint's true rotated corners", () => {
    // Centre 0.55m from the south wall's face: square-on the plank clears it, turned it
    // reaches 0.92m down and does not.
    const model = createRoomModel(hall);
    const southM = OUTER_WALL_THICKNESS_M / 2 + 0.55;

    expect(model.canPlace(plank, pose(5, southM))).toBe(true);
    expect(model.canPlace(plank, pose(5, southM, quarterTurn))).toBe(false);
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

describe("resolveDrag — past other items", () => {
  const hall = rectangleUnit(10, 10);
  const table: Footprint = { width_m: 2, depth_m: 2 };
  const model = createRoomModel(hall, [
    standing("table", table, pose(5, 5)),
    standing("mover", BLOCK, pose(5, 2)),
  ]);
  const start = pose(5, 2);

  it("stops short of an item dragged straight at it", () => {
    const resolved = model.resolveDrag(BLOCK, pose(5, 8), start, "mover");

    expect(resolved.y_m).toBeCloseTo(5 - table.depth_m / 2 - BLOCK.depth_m / 2, 3);
    expect(resolved.x_m).toBeCloseTo(5, 6);
    expect(model.canPlace(BLOCK, resolved, "mover")).toBe(true);
  });

  it("slides round an item rather than stopping dead against it", () => {
    // Aimed diagonally past the table. The table eats the northward half of the drag
    // only while the mover is behind it; going east first gets the whole drag.
    const resolved = model.resolveDrag(BLOCK, pose(8, 8), start, "mover");

    expect(resolved.x_m).toBeCloseTo(8, 6);
    expect(resolved.y_m).toBeCloseTo(8, 6);
  });

  it("does not treat the moving item's own pose as something to avoid", () => {
    const resolved = model.resolveDrag(BLOCK, pose(5, 2.5), start, "mover");

    expect(resolved).toEqual(pose(5, 2.5));
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

  it("keeps clear of what is already in the room", () => {
    const model = createRoomModel(rectangleUnit(6, 4), [standing("a", SOFA, pose(3, 2))]);

    const spot = model.findFreeSpot(SOFA);

    expect(spot).not.toBeNull();
    expect(model.canPlace(SOFA, spot!)).toBe(true);
  });

  it("moves off a drop point that is already taken", () => {
    const model = createRoomModel(rectangleUnit(6, 4), [standing("a", SOFA, pose(3, 2))]);

    const spot = model.findFreeSpot(SOFA, [3, 2]);

    expect(spot).not.toBeNull();
    expect(model.canPlace(SOFA, spot!)).toBe(true);
  });

  it("returns null rather than an overlapping pose once the room is full", () => {
    // 2.8 × 1.8 of clear floor, all but a 10cm border of it taken.
    const model = createRoomModel(rectangleUnit(3, 2), [
      standing("a", { width_m: 2.6, depth_m: 1.6 }, pose(1.5, 1)),
    ]);

    expect(model.findFreeSpot(SOFA)).toBeNull();
    expect(model.findFreeSpot(SOFA, [1.5, 1])).toBeNull();
  });

  it("fills a room one sofa at a time and never once overlaps", () => {
    // The invariant that matters: every pose it hands back is one the model itself
    // accepts, however full the room has become — and when it stops, it stops with null
    // rather than with a sofa inside another sofa.
    const room = rectangleUnit(6, 4);
    const placed: Occupant[] = [];

    for (let attempt = 0; attempt < 20; attempt += 1) {
      const model = createRoomModel(room, placed);
      const spot = model.findFreeSpot(SOFA);
      if (spot === null) break;

      expect(model.canPlace(SOFA, spot)).toBe(true);
      placed.push(standing(`sofa-${attempt}`, SOFA, spot));
    }

    expect(placed.length).toBeGreaterThan(1);
    expect(createRoomModel(room, placed).findFreeSpot(SOFA)).toBeNull();
  });
});
