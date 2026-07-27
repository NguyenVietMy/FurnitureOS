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

export interface Unit {
  readonly slug: string;
  readonly name: string;
  readonly building: string;
  readonly ceiling_height_m: number;
  readonly area_m2: number;
  readonly bedrooms: number;
  readonly outline: readonly Point[];
  readonly walls: readonly Wall[];
  readonly rooms: readonly Room[];
  readonly openings: readonly Opening[];
}
