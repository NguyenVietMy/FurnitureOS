/**
 * Units module — apartment geometry: what shape the buyer is furnishing.
 *
 * PUBLIC SURFACE. Everything outside this module goes through here; lint enforces it.
 *
 * Internals:
 *   types.ts       the API's wire format
 *   api.ts         fetching
 *   geometry.ts    walls + openings -> solid boxes (pure, no three.js)
 *   scene/         the react-three-fiber rendering of those boxes
 */

export { fetchUnit } from "./api";
export { deriveWallPieces, type WallPiece } from "./geometry";
export { UnitScene } from "./scene/UnitScene";
export type { Opening, Point, Room, Unit, Wall } from "./types";
