/**
 * Units module — apartment geometry: what shape the buyer is furnishing.
 *
 * PUBLIC SURFACE. Everything outside this module goes through here; lint enforces it.
 *
 * Internals:
 *   types.ts            the API's wire format
 *   api.ts              fetching
 *   geometry.ts         walls + openings -> solid boxes (pure, no three.js)
 *   thumbnail.ts        outline + rooms -> SVG paths (pure, no React)
 *   UnitThumbnail.tsx   the gallery card's floorplan
 *   scene/              the react-three-fiber rendering of those boxes
 */

export { fetchUnit, fetchUnits } from "./api";
export { deriveWallPieces, type WallPiece } from "./geometry";
export { deriveThumbnail, type Thumbnail, type ThumbnailShape } from "./thumbnail";
export { UnitThumbnail } from "./UnitThumbnail";
export { UnitScene } from "./scene/UnitScene";
export type { Opening, Point, Room, Unit, UnitSummary, Wall } from "./types";
