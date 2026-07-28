/**
 * Geometry module — the one thing that knows whether furniture fits.
 *
 * PUBLIC SURFACE. Pure TypeScript: no three.js, no React, no DOM. Ask it a question,
 * draw the answer somewhere else. Lint enforces the front door; this comment explains
 * why it is worth enforcing — the moment polygon maths lands in the scene layer it
 * stops being testable, and "it fits" is the product's only real promise.
 *
 * Internals:
 *   polygon.ts     point-in-polygon, segment and area distances, convex overlap
 *   roomModel.ts   the apartment as three questions
 *   fixtures.ts    awkward plans for the tests: an L, a recess, a room too thin
 */

export { createRoomModel, footprintCorners } from "./roomModel";
export type { Footprint, Occupant, Pose, RoomModel } from "./roomModel";
