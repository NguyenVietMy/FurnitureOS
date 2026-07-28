/**
 * Plan module — the furniture a buyer has put in a unit, and the screen they do it on.
 *
 * PUBLIC SURFACE. Everything outside this module goes through here; lint enforces it.
 *
 * The plan is client-only state: a list of item ids and poses. It knows nothing about
 * money (issue 06) and is not saved anywhere (issue 05). Whether a pose is legal is not
 * decided here either — that is `@/modules/geometry`, which this module asks.
 *
 * Internals:
 *   reducer.ts                add / move / rotate / remove, pure
 *   occupancy.ts              the plan as the room model sees it
 *   rotation.ts               pointer angle -> a snapped rotation
 *   Planner.tsx               catalogue + scene + plan state, wired together
 *   scene/presets.ts          preset ref + real dimensions -> a non-uniform scale
 *   scene/PresetModel.tsx     the `loadPresetScaled` seam; a box until issue 14
 *   scene/floor.ts            screen point -> spot on the floor
 *   scene/PlanItems.tsx       the furniture in the canvas, and the dragging of it
 *   scene/RotateHandle.tsx    the ring that turns the selected item
 *   scene/useBlockedFlash.ts  the red flash that says no
 */

export { Planner } from "./Planner";
export { emptyPlan, planReducer } from "./reducer";
export type { PlacedItem, PlanAction, PlanState } from "./reducer";
