/**
 * Wall geometry: turning walls and openings into solid pieces.
 *
 * Pure functions over plain numbers — no three.js, no rendering. A doorway that is
 * drawn open but not actually cut, or a lintel a centimetre too low, is a bug that is
 * miserable to spot by eye and trivial to catch here.
 */

import { describe, expect, it } from "vitest";

import { deriveWallPieces, type WallPiece } from "./geometry";
import type { Opening, Unit, Wall } from "./types";

const CEILING_M = 2.7;

function wall(overrides: Partial<Wall> = {}): Wall {
  const start = overrides.start ?? ([0, 0] as const);
  const end = overrides.end ?? ([4, 0] as const);
  return {
    id: "outline:0",
    start,
    end,
    thickness_m: 0.2,
    length_m: Math.hypot(end[0] - start[0], end[1] - start[1]),
    ...overrides,
  };
}

function door(overrides: Partial<Opening> = {}): Opening {
  return {
    wall: "outline:0",
    kind: "door",
    offset_m: 1.5,
    width_m: 0.9,
    sill_m: 0,
    head_m: 2.1,
    ...overrides,
  };
}

function unit(walls: Wall[], openings: Opening[] = []): Unit {
  return {
    slug: "test",
    name: "Test",
    building: "Test",
    ceiling_height_m: CEILING_M,
    area_m2: 0,
    bedrooms: 0,
    outline: [],
    walls,
    rooms: [],
    openings,
  };
}

/**
 * Piece lengths, ascending and rounded to the millimetre.
 *
 * Numerically sorted — the default `.sort()` is lexicographic, which puts 1.6 before
 * 1.5999999999 — and rounded, because these come out of floating-point subtraction and
 * no wall is specified to sub-millimetre precision anyway.
 */
function lengths(pieces: readonly WallPiece[]): number[] {
  return pieces
    .map((piece) => Math.round(piece.length_m * 1000) / 1000)
    .sort((a, b) => a - b);
}

/** Solid volume of the pieces, for conservation checks. */
function totalVolume(unitPlan: Unit): number {
  return deriveWallPieces(unitPlan).reduce(
    (sum, piece) =>
      sum + piece.length_m * piece.thickness_m * (piece.top_m - piece.base_m),
    0,
  );
}

describe("a wall with no openings", () => {
  it("becomes a single piece spanning floor to ceiling", () => {
    const pieces = deriveWallPieces(unit([wall()]));

    expect(pieces).toHaveLength(1);
    expect(pieces[0]).toMatchObject({
      wallId: "outline:0",
      length_m: 4,
      thickness_m: 0.2,
      base_m: 0,
      top_m: CEILING_M,
    });
  });

  it("is centred on the wall's midpoint", () => {
    const [piece] = deriveWallPieces(unit([wall({ start: [1, 2], end: [5, 2] })]));

    expect(piece.center[0]).toBeCloseTo(3);
    expect(piece.center[1]).toBeCloseTo(2);
  });

  it("carries the wall's angle, measured from +X", () => {
    const [horizontal] = deriveWallPieces(unit([wall({ start: [0, 0], end: [4, 0] })]));
    const [vertical] = deriveWallPieces(unit([wall({ start: [0, 0], end: [0, 4] })]));
    const [diagonal] = deriveWallPieces(unit([wall({ start: [0, 0], end: [3, 3] })]));

    expect(horizontal.angle_rad).toBeCloseTo(0);
    expect(vertical.angle_rad).toBeCloseTo(Math.PI / 2);
    expect(diagonal.angle_rad).toBeCloseTo(Math.PI / 4);
  });
});

describe("a door", () => {
  it("splits the wall into two jambs and a lintel", () => {
    const pieces = deriveWallPieces(unit([wall()], [door()]));

    expect(pieces).toHaveLength(3);

    const jambs = pieces.filter((piece) => piece.top_m === CEILING_M && piece.base_m === 0);
    expect(lengths(jambs)).toEqual([1.5, 1.6]);

    const lintel = pieces.find((piece) => piece.base_m > 0);
    expect(lintel).toMatchObject({ base_m: 2.1, top_m: CEILING_M });
    expect(lintel?.length_m).toBeCloseTo(0.9);
  });

  it("leaves nothing solid across the doorway below its head", () => {
    const pieces = deriveWallPieces(unit([wall()], [door()]));
    const doorwayMidpoint = 1.5 + 0.9 / 2;

    for (const piece of pieces) {
      const startsAt = pieceStart(piece.center, piece.length_m, piece.angle_rad);
      const spansDoorway =
        startsAt < doorwayMidpoint && startsAt + piece.length_m > doorwayMidpoint;
      if (spansDoorway) expect(piece.base_m).toBeGreaterThanOrEqual(2.1);
    }
  });

  it("produces no lintel when it reaches the ceiling", () => {
    const pieces = deriveWallPieces(unit([wall()], [door({ head_m: CEILING_M })]));

    expect(pieces).toHaveLength(2);
    expect(pieces.every((piece) => piece.top_m === CEILING_M)).toBe(true);
  });

  it("produces no jamb when it starts flush with the wall", () => {
    const pieces = deriveWallPieces(unit([wall()], [door({ offset_m: 0 })]));

    expect(pieces).toHaveLength(2);
    expect(lengths(pieces)).toEqual([0.9, 3.1]);
  });

  it("produces no jamb when it ends flush with the wall", () => {
    const pieces = deriveWallPieces(unit([wall()], [door({ offset_m: 3.1, width_m: 0.9 })]));

    expect(pieces).toHaveLength(2);
  });
});

describe("a window", () => {
  it("adds a sill below it as well as a lintel above", () => {
    const pieces = deriveWallPieces(
      unit([wall()], [door({ kind: "window", sill_m: 0.9, head_m: 2.1 })]),
    );

    expect(pieces).toHaveLength(4);

    const sill = pieces.find((piece) => piece.top_m === 0.9);
    expect(sill).toMatchObject({ base_m: 0, top_m: 0.9 });
    expect(sill?.length_m).toBeCloseTo(0.9);

    const lintel = pieces.find((piece) => piece.base_m === 2.1);
    expect(lintel).toMatchObject({ base_m: 2.1, top_m: CEILING_M });
    expect(lintel?.length_m).toBeCloseTo(0.9);
  });
});

describe("several openings on one wall", () => {
  it("splits it into the segments between them", () => {
    const plan = unit(
      [wall({ end: [6, 0], length_m: 6 })],
      [
        door({ offset_m: 1, width_m: 0.9 }),
        door({ offset_m: 3.5, width_m: 0.9 }),
      ],
    );

    const pieces = deriveWallPieces(plan);
    const fullHeight = pieces.filter((piece) => piece.base_m === 0);

    expect(lengths(fullHeight)).toEqual([1, 1.6, 1.6]);
    expect(pieces.filter((piece) => piece.base_m === 2.1)).toHaveLength(2);
  });

  it("handles them given out of order", () => {
    const ascending = unit(
      [wall({ end: [6, 0], length_m: 6 })],
      [door({ offset_m: 1 }), door({ offset_m: 3.5 })],
    );
    const descending = unit(
      [wall({ end: [6, 0], length_m: 6 })],
      [door({ offset_m: 3.5 }), door({ offset_m: 1 })],
    );

    expect(totalVolume(ascending)).toBeCloseTo(totalVolume(descending));
  });
});

describe("invariants", () => {
  it("conserves volume: wall solid minus the holes cut in it", () => {
    const opening = door({ offset_m: 1.5, width_m: 0.9, sill_m: 0, head_m: 2.1 });
    const plan = unit([wall()], [opening]);

    const solid = 4 * 0.2 * CEILING_M;
    const hole = opening.width_m * 0.2 * (opening.head_m - opening.sill_m);

    expect(totalVolume(plan)).toBeCloseTo(solid - hole);
  });

  it("never emits a piece with zero or negative extent", () => {
    const plan = unit(
      [wall(), wall({ id: "outline:1", start: [4, 0], end: [4, 3], length_m: 3 })],
      [
        door({ offset_m: 0, width_m: 0.9, head_m: CEILING_M }),
        door({ wall: "outline:1", offset_m: 2.1, width_m: 0.9 }),
      ],
    );

    for (const piece of deriveWallPieces(plan)) {
      expect(piece.length_m).toBeGreaterThan(0);
      expect(piece.top_m - piece.base_m).toBeGreaterThan(0);
    }
  });

  it("ignores openings that reference a wall that is not there", () => {
    const pieces = deriveWallPieces(unit([wall()], [door({ wall: "partition:9" })]));

    expect(pieces).toHaveLength(1);
  });
});

/** Distance along the wall at which a piece begins, recovered from its centre. */
function pieceStart(center: readonly [number, number], length: number, angle: number): number {
  const alongX = Math.cos(angle);
  const alongY = Math.sin(angle);
  return center[0] * alongX + center[1] * alongY - length / 2;
}
