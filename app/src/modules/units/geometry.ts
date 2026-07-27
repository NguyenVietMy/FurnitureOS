/**
 * Wall geometry: walls + openings + ceiling height -> solid boxes.
 *
 * Pure numbers. No three.js, no React. The scene turns a WallPiece into a mesh and does
 * nothing else clever, which is what makes both halves testable.
 *
 * Coordinates are metres in the plan's XY plane, matching the API. Height is a separate
 * axis (`base_m`/`top_m`) because walls are extrusions of a 2D plan, not free solids.
 */

import type { Opening, Point, Unit, Wall } from "./types";

/** A solid rectangular box: a whole wall, or what remains of one around its openings. */
export interface WallPiece {
  readonly wallId: string;
  /** Centre of the box in plan coordinates. */
  readonly center: Point;
  /** Extent along the wall. */
  readonly length_m: number;
  /** Extent across the wall. */
  readonly thickness_m: number;
  /** Metres above the floor. */
  readonly base_m: number;
  readonly top_m: number;
  /** The wall's direction in the plan, radians anticlockwise from +X. */
  readonly angle_rad: number;
}

/** Lengths below this are rounding noise, not geometry worth drawing. */
const EPSILON_M = 1e-9;

/**
 * Cut every wall into the solid pieces left over once its openings are removed.
 *
 * An opening leaves up to four pieces around it: a segment either side, a lintel above,
 * and — for a window — a sill below. Anything that would come out at zero size is
 * dropped rather than emitted degenerate.
 */
export function deriveWallPieces(unit: Unit): WallPiece[] {
  const openingsByWall = groupOpeningsByWall(unit.openings);

  return unit.walls.flatMap((wall) =>
    cutWall(wall, openingsByWall.get(wall.id) ?? [], unit.ceiling_height_m),
  );
}

function groupOpeningsByWall(openings: readonly Opening[]): Map<string, Opening[]> {
  const grouped = new Map<string, Opening[]>();

  for (const opening of openings) {
    const existing = grouped.get(opening.wall);
    if (existing) existing.push(opening);
    else grouped.set(opening.wall, [opening]);
  }

  // Openings arrive in whatever order the plan lists them; the cut walks left to right.
  for (const wallOpenings of grouped.values()) {
    wallOpenings.sort((a, b) => a.offset_m - b.offset_m);
  }

  return grouped;
}

function cutWall(wall: Wall, openings: Opening[], ceilingHeightM: number): WallPiece[] {
  const angleRad = Math.atan2(wall.end[1] - wall.start[1], wall.end[0] - wall.start[0]);
  const pieces: WallPiece[] = [];

  const emit = (fromM: number, toM: number, baseM: number, topM: number): void => {
    if (toM - fromM <= EPSILON_M || topM - baseM <= EPSILON_M) return;
    pieces.push({
      wallId: wall.id,
      center: pointAlong(wall, (fromM + toM) / 2),
      length_m: toM - fromM,
      thickness_m: wall.thickness_m,
      base_m: baseM,
      top_m: topM,
      angle_rad: angleRad,
    });
  };

  let cursorM = 0;

  for (const opening of openings) {
    // The full-height run leading up to this opening.
    emit(cursorM, opening.offset_m, 0, ceilingHeightM);

    const openingEndM = opening.offset_m + opening.width_m;
    emit(opening.offset_m, openingEndM, 0, opening.sill_m); // sill, windows only
    emit(opening.offset_m, openingEndM, opening.head_m, ceilingHeightM); // lintel

    cursorM = Math.max(cursorM, openingEndM);
  }

  emit(cursorM, wall.length_m, 0, ceilingHeightM);

  return pieces;
}

/**
 * Area-weighted centroid of a polygon — the point the camera is trying to look at.
 *
 * Not the bounding-box centre: for an L-shaped unit that can land outside the floor
 * entirely, which would flip the hiding test for a whole wing.
 */
export function outlineCentroid(outline: readonly Point[]): Point {
  let twiceArea = 0;
  let x = 0;
  let y = 0;

  for (let index = 0; index < outline.length; index += 1) {
    const [x1, y1] = outline[index];
    const [x2, y2] = outline[(index + 1) % outline.length];
    const cross = x1 * y2 - x2 * y1;
    twiceArea += cross;
    x += (x1 + x2) * cross;
    y += (y1 + y2) * cross;
  }

  // Degenerate outline (zero area, or fewer than 3 points): fall back to the mean.
  if (Math.abs(twiceArea) < EPSILON_M) {
    const count = outline.length || 1;
    return [
      outline.reduce((sum, point) => sum + point[0], 0) / count,
      outline.reduce((sum, point) => sum + point[1], 0) / count,
    ];
  }

  return [x / (3 * twiceArea), y / (3 * twiceArea)];
}

/**
 * Does this piece stand between the camera and the interior?
 *
 * The buyer orbits a closed box, so the near walls have to get out of the way or they
 * see nothing but a roofless crate. A piece occludes when the camera is on its outward
 * side — the side facing away from `interior`.
 *
 * Ties (a wall passing through the interior point) resolve to visible: better a wall in
 * the way for a frame than one flickering as the camera crosses it.
 */
export function occludesInterior(
  piece: WallPiece,
  camera: Point,
  interior: Point,
): boolean {
  const normal: Point = [-Math.sin(piece.angle_rad), Math.cos(piece.angle_rad)];

  const towardInterior =
    normal[0] * (interior[0] - piece.center[0]) + normal[1] * (interior[1] - piece.center[1]);
  if (Math.abs(towardInterior) < EPSILON_M) return false;

  const outward: Point =
    towardInterior > 0 ? [-normal[0], -normal[1]] : [normal[0], normal[1]];

  const towardCamera =
    outward[0] * (camera[0] - piece.center[0]) + outward[1] * (camera[1] - piece.center[1]);

  return towardCamera > 0;
}

/** The point `distanceM` along the wall from its start. */
function pointAlong(wall: Wall, distanceM: number): Point {
  const fraction = wall.length_m === 0 ? 0 : distanceM / wall.length_m;
  return [
    wall.start[0] + (wall.end[0] - wall.start[0]) * fraction,
    wall.start[1] + (wall.end[1] - wall.start[1]) * fraction,
  ];
}
