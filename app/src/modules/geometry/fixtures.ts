/**
 * Plan fixtures for the geometry tests.
 *
 * Deliberately hand-built rather than fetched: the point of these polygons is that they
 * are awkward on purpose — an L, a notch, a room too thin to furnish — and a seed file
 * that has to stay renderable cannot also be a torture test.
 *
 * Wall ids and default thicknesses mirror the server's derivation (`plan.py`), because
 * a fixture whose walls are shaped differently from the real payload tests nothing.
 */

import type { Point, Unit, Wall } from "@/modules/units";

export const OUTER_WALL_THICKNESS_M = 0.2;
export const PARTITION_THICKNESS_M = 0.1;

export interface PartitionSpec {
  readonly start: Point;
  readonly end: Point;
  readonly thickness_m?: number;
}

/** A unit with the given outline and interior partitions, walls derived as the API does. */
export function unitFrom(
  outline: readonly Point[],
  partitions: readonly PartitionSpec[] = [],
): Unit {
  const walls: Wall[] = outline.map((start, index) =>
    wall(`outline:${index}`, start, outline[(index + 1) % outline.length], OUTER_WALL_THICKNESS_M),
  );

  partitions.forEach((partition, index) => {
    walls.push(
      wall(
        `partition:${index}`,
        partition.start,
        partition.end,
        partition.thickness_m ?? PARTITION_THICKNESS_M,
      ),
    );
  });

  return {
    slug: "fixture",
    name: "Fixture",
    building: "Fixture",
    area_m2: 0,
    bedrooms: 0,
    ceiling_height_m: 2.7,
    outline,
    walls,
    rooms: [],
    openings: [],
  };
}

/** A plain rectangle with its south-west corner at the origin. */
export function rectangleUnit(widthM: number, depthM: number): Unit {
  return unitFrom([
    [0, 0],
    [widthM, 0],
    [widthM, depthM],
    [0, depthM],
  ]);
}

/**
 * An L: 10 × 5 across the bottom, with a 6 × 4 wing running north from the west half.
 *
 * The north-east quadrant is outside the apartment, which is what makes this fixture
 * worth having — every bounding-box shortcut passes a rectangle and fails here.
 */
export function lShapedUnit(): Unit {
  return unitFrom([
    [0, 0],
    [10, 0],
    [10, 5],
    [6, 5],
    [6, 9],
    [0, 9],
  ]);
}

/** A rectangle with a small rectangular bite taken out of one wall — a doorway recess. */
export function notchedUnit(): Unit {
  return unitFrom([
    [0, 0],
    [6, 0],
    [6, 4],
    [3.6, 4],
    [3.6, 4.8],
    [2.4, 4.8],
    [2.4, 4],
    [0, 4],
  ]);
}

function wall(id: string, start: Point, end: Point, thicknessM: number): Wall {
  return {
    id,
    start,
    end,
    thickness_m: thicknessM,
    length_m: Math.hypot(end[0] - start[0], end[1] - start[1]),
  };
}
