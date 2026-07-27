/**
 * The unit payload as the API serves it.
 *
 * Wall ids come from the server — openings reference them, so the server owns wall
 * *identity* and this module owns wall *geometry*. Deriving ids on both sides would let
 * the two drift apart silently.
 *
 * Coordinates are metres in a right-handed XY plane with Y forward. Mapping that to
 * three.js XZ is the scene's job, not this module's.
 */

export type Point = readonly [number, number];

export interface Wall {
  readonly id: string;
  readonly start: Point;
  readonly end: Point;
  readonly thickness_m: number;
  readonly length_m: number;
}

export interface Opening {
  readonly wall: string;
  readonly kind: "door" | "window";
  readonly offset_m: number;
  readonly width_m: number;
  readonly sill_m: number;
  readonly head_m: number;
}

export interface Room {
  readonly key: string;
  readonly name: string;
  readonly type: string;
  readonly polygon: readonly Point[];
}

/**
 * A unit as the gallery lists it: what a card shows, plus the polygons it draws.
 *
 * Area and bedroom count are derived server-side from the same plan the detail endpoint
 * reads, never stored beside it — so a card cannot contradict the page it opens.
 */
export interface UnitSummary {
  readonly slug: string;
  readonly name: string;
  readonly building: string;
  readonly area_m2: number;
  readonly bedrooms: number;
  readonly outline: readonly Point[];
  readonly rooms: readonly Room[];
}

/** A unit as the renderer needs it: the summary, plus the geometry to extrude. */
export interface Unit extends UnitSummary {
  readonly ceiling_height_m: number;
  readonly walls: readonly Wall[];
  readonly openings: readonly Opening[];
}
