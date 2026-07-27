/**
 * The gallery thumbnail: a unit's polygons projected into a small SVG box.
 *
 * Pure numbers in, path strings out — no React, no DOM. A thumbnail that silently
 * mirrors a plan, or squashes an L-shape into a rectangle, is a bug that looks
 * plausible on a card and only becomes obvious once the buyer opens the 3D scene.
 */

import { describe, expect, it } from "vitest";

import { deriveThumbnail } from "./thumbnail";
import type { Point, Room, UnitSummary } from "./types";

function room(key: string, polygon: Point[], type = "living"): Room {
  return { key, name: key, type, polygon };
}

function summary(outline: Point[], rooms: Room[] = []): UnitSummary {
  return {
    slug: "test",
    name: "Test",
    building: "Test",
    area_m2: 0,
    bedrooms: 0,
    outline,
    rooms,
  };
}

/** A 10m x 5m rectangle, wider than it is deep. */
const WIDE: Point[] = [
  [0, 0],
  [10, 0],
  [10, 5],
  [0, 5],
];

/** The seeded unit's shape: a rectangle with a bite out of its top-right. */
const L_SHAPED: Point[] = [
  [0, 0],
  [10, 0],
  [10, 5],
  [6, 5],
  [6, 9],
  [0, 9],
];

/** The points of an SVG path `d`, so tests assert geometry rather than formatting. */
function pathPoints(d: string): Point[] {
  return [...d.matchAll(/(-?[\d.]+)[ ,]+(-?[\d.]+)/g)].map(
    (match) => [Number(match[1]), Number(match[2])] as Point,
  );
}

describe("shape", () => {
  it("preserves aspect ratio: a plan twice as wide comes out twice as wide", () => {
    const thumbnail = deriveThumbnail(summary(WIDE));

    // Padding adds equally to both axes, so their difference is pure geometry.
    const planAspect = 10 / 5;
    const contentWidth = thumbnail.width - thumbnail.height;
    expect(contentWidth).toBeGreaterThan(0);
    expect(thumbnail.width / thumbnail.height).toBeLessThan(planAspect);
    expect(thumbnail.width).toBeGreaterThan(thumbnail.height);
  });

  it("scales the longest side to the same extent whichever axis it is on", () => {
    const wide = deriveThumbnail(summary(WIDE));
    const tall = deriveThumbnail(
      summary([
        [0, 0],
        [5, 0],
        [5, 10],
        [0, 10],
      ]),
    );

    expect(wide.width).toBeCloseTo(tall.height);
    expect(wide.height).toBeCloseTo(tall.width);
  });

  it("keeps every vertex of an L-shape, notch included", () => {
    const thumbnail = deriveThumbnail(summary(L_SHAPED));

    expect(pathPoints(thumbnail.outline)).toHaveLength(L_SHAPED.length);
  });

  it("closes the outline path", () => {
    expect(deriveThumbnail(summary(WIDE)).outline.trimEnd()).toMatch(/Z$/i);
  });

  it("reports a viewBox matching its own width and height", () => {
    const thumbnail = deriveThumbnail(summary(L_SHAPED));

    expect(thumbnail.viewBox).toBe(`0 0 ${thumbnail.width} ${thumbnail.height}`);
  });
});

describe("orientation", () => {
  it("flips Y, so a floorplan reads with high plan-Y at the top", () => {
    // Plan Y is forward; SVG Y is down. Getting this wrong mirrors every unit.
    const thumbnail = deriveThumbnail(summary(WIDE));
    const points = pathPoints(thumbnail.outline);

    const atFarSide = points.filter((_, index) => WIDE[index][1] === 5);
    const atNearSide = points.filter((_, index) => WIDE[index][1] === 0);

    for (const far of atFarSide) {
      for (const near of atNearSide) {
        expect(far[1]).toBeLessThan(near[1]);
      }
    }
  });

  it("does not mirror X", () => {
    const thumbnail = deriveThumbnail(summary(WIDE));
    const points = pathPoints(thumbnail.outline);

    expect(points[0][0]).toBeLessThan(points[1][0]); // [0,0] -> [10,0]
  });
});

describe("framing", () => {
  it("fits the whole plan inside the box with a margin on every side", () => {
    const thumbnail = deriveThumbnail(summary(L_SHAPED));
    const points = pathPoints(thumbnail.outline);

    const xs = points.map(([x]) => x);
    const ys = points.map(([, y]) => y);

    expect(Math.min(...xs)).toBeGreaterThan(0);
    expect(Math.min(...ys)).toBeGreaterThan(0);
    expect(Math.max(...xs)).toBeLessThan(thumbnail.width);
    expect(Math.max(...ys)).toBeLessThan(thumbnail.height);
  });

  it("frames a plan the same wherever its coordinates sit", () => {
    // A traced floorplan need not start at the origin, and a card must not care.
    const shifted = L_SHAPED.map(([x, y]) => [x + 100, y - 40] as Point);

    expect(deriveThumbnail(summary(shifted))).toEqual(deriveThumbnail(summary(L_SHAPED)));
  });
});

describe("rooms", () => {
  it("draws one closed path per room, carrying key and type", () => {
    const thumbnail = deriveThumbnail(
      summary(WIDE, [
        room("living", [
          [0, 0],
          [6, 0],
          [6, 5],
          [0, 5],
        ]),
        room(
          "bedroom-1",
          [
            [6, 0],
            [10, 0],
            [10, 5],
            [6, 5],
          ],
          "bedroom",
        ),
      ]),
    );

    expect(thumbnail.rooms.map((shape) => shape.key)).toEqual(["living", "bedroom-1"]);
    expect(thumbnail.rooms.map((shape) => shape.type)).toEqual(["living", "bedroom"]);
    expect(thumbnail.rooms.every((shape) => /Z$/i.test(shape.d.trimEnd()))).toBe(true);
  });

  it("places rooms in the same frame as the outline", () => {
    const half: Point[] = [
      [0, 0],
      [10, 0],
      [10, 2.5],
      [0, 2.5],
    ];
    const thumbnail = deriveThumbnail(summary(WIDE, [room("living", half)]));

    const roomPoints = pathPoints(thumbnail.rooms[0].d);
    const outlinePoints = pathPoints(thumbnail.outline);

    // The room spans the full width but only the near half of the depth.
    expect(Math.min(...roomPoints.map(([x]) => x))).toBeCloseTo(
      Math.min(...outlinePoints.map(([x]) => x)),
    );
    expect(Math.max(...roomPoints.map(([, y]) => y))).toBeCloseTo(
      Math.max(...outlinePoints.map(([, y]) => y)),
    );
    expect(Math.min(...roomPoints.map(([, y]) => y))).toBeGreaterThan(
      Math.min(...outlinePoints.map(([, y]) => y)),
    );
  });

  it("survives a unit with no room regions", () => {
    const thumbnail = deriveThumbnail(summary(WIDE));

    expect(thumbnail.rooms).toEqual([]);
    expect(thumbnail.outline).not.toBe("");
  });
});

describe("degenerate input", () => {
  it("emits finite numbers for a zero-extent outline", () => {
    // A malformed or half-traced plan must render a dull card, not NaN in the DOM.
    const thumbnail = deriveThumbnail(
      summary([
        [3, 3],
        [3, 3],
        [3, 3],
      ]),
    );

    expect(Number.isFinite(thumbnail.width)).toBe(true);
    expect(Number.isFinite(thumbnail.height)).toBe(true);
    for (const [x, y] of pathPoints(thumbnail.outline)) {
      expect(Number.isFinite(x)).toBe(true);
      expect(Number.isFinite(y)).toBe(true);
    }
  });

  it("emits an empty path for an empty outline", () => {
    const thumbnail = deriveThumbnail(summary([]));

    expect(thumbnail.outline).toBe("");
    expect(Number.isFinite(thumbnail.width)).toBe(true);
  });
});
