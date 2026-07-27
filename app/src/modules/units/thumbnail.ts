/**
 * Gallery thumbnails: a unit's polygons projected into a small SVG box.
 *
 * Pure numbers in, path strings out. No React, no DOM, no three.js — the card that
 * renders this owns colour and size, and knows nothing about coordinates.
 *
 * Drawn from the outline and room regions rather than a screenshot of the 3D scene: a
 * grid of cards must not each boot a renderer, and a floorplan read from above is what
 * a buyer recognises as "mine" anyway.
 */

import type { Point, Room, UnitSummary } from "./types";

/** One room region, ready to fill. `type` is what the card colours by. */
export interface ThumbnailShape {
  readonly key: string;
  readonly type: string;
  /** An SVG path `d`, closed. */
  readonly d: string;
}

export interface Thumbnail {
  readonly width: number;
  readonly height: number;
  /** `0 0 width height`, so the card can drop it straight onto an `<svg>`. */
  readonly viewBox: string;
  readonly outline: string;
  readonly rooms: readonly ThumbnailShape[];
}

/** Extent of the plan's longest side, in viewBox units. */
const SIZE = 100;

/** Inset on every side, so a stroked outline is not clipped by the viewBox. */
const PADDING = 4;

/** Coordinates are rounded to this many decimals: sub-pixel precision nobody can see. */
const DECIMALS = 2;

/**
 * Project a unit into a padded box that preserves its aspect ratio.
 *
 * Plan Y is forward and SVG Y is down, so the projection flips Y — without it every
 * unit renders mirrored, which is subtle enough on a rectangle to ship unnoticed and
 * obvious the moment the buyer opens the 3D scene.
 */
export function deriveThumbnail(unit: UnitSummary): Thumbnail {
  const bounds = boundsOf(unit.outline);

  // A zero-extent plan (empty, or a single repeated vertex) has no scale to fit to.
  // Drawing it dull beats propagating NaN into the DOM.
  const span = Math.max(bounds.width, bounds.height);
  const scale = span > 0 ? SIZE / span : 1;

  const project = ([x, y]: Point): Point => [
    round(PADDING + (x - bounds.minX) * scale),
    round(PADDING + (bounds.maxY - y) * scale),
  ];

  const width = round(bounds.width * scale + PADDING * 2);
  const height = round(bounds.height * scale + PADDING * 2);

  return {
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    outline: toPath(unit.outline, project),
    rooms: unit.rooms.map((room: Room) => ({
      key: room.key,
      type: room.type,
      d: toPath(room.polygon, project),
    })),
  };
}

interface Bounds {
  readonly minX: number;
  readonly maxY: number;
  readonly width: number;
  readonly height: number;
}

function boundsOf(polygon: readonly Point[]): Bounds {
  if (polygon.length === 0) return { minX: 0, maxY: 0, width: 0, height: 0 };

  const xs = polygon.map(([x]) => x);
  const ys = polygon.map(([, y]) => y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);

  return {
    minX,
    maxY: Math.max(...ys),
    width: Math.max(...xs) - minX,
    height: Math.max(...ys) - minY,
  };
}

function toPath(polygon: readonly Point[], project: (point: Point) => Point): string {
  if (polygon.length === 0) return "";

  return `${polygon
    .map((point, index) => {
      const [x, y] = project(point);
      return `${index === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ")} Z`;
}

function round(value: number): number {
  const factor = 10 ** DECIMALS;
  return Math.round(value * factor) / factor;
}
