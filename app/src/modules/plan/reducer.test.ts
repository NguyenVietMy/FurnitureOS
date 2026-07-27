/**
 * The plan reducer as pure state transitions.
 *
 * The reducer is the only thing that changes a plan, which is what lets issue 05 hang
 * autosave off it and issue 10 hang undo off it without either of them knowing how
 * dragging works. So it is tested as data in, data out — no scene, no React.
 */

import { describe, expect, it } from "vitest";

import { emptyPlan, planReducer, type PlacedItem, type PlanState } from "./reducer";

const SOFA: PlacedItem = {
  key: "a",
  itemId: "sofa-3-linen",
  pose: { x_m: 3, y_m: 2, rotation_rad: 0 },
};

const LAMP: PlacedItem = {
  key: "b",
  itemId: "lamp-floor-arc",
  pose: { x_m: 1, y_m: 1, rotation_rad: 0 },
};

function planWith(...items: PlacedItem[]): PlanState {
  return items.reduce((state, item) => planReducer(state, { type: "add", item }), emptyPlan);
}

describe("add", () => {
  it("puts the item in the plan", () => {
    expect(planWith(SOFA).items).toEqual([SOFA]);
  });

  it("keeps insertion order, because that is the order the scene draws", () => {
    expect(planWith(SOFA, LAMP).items.map((item) => item.key)).toEqual(["a", "b"]);
  });

  it("refuses a key that is already in the plan", () => {
    const state = planWith(SOFA);

    expect(planReducer(state, { type: "add", item: { ...LAMP, key: "a" } })).toBe(state);
  });
});

describe("move", () => {
  it("changes the pose of one item and leaves the rest alone", () => {
    const state = planWith(SOFA, LAMP);

    const moved = planReducer(state, {
      type: "move",
      key: "a",
      pose: { x_m: 4.5, y_m: 0.55, rotation_rad: Math.PI / 2 },
    });

    expect(moved.items[0].pose).toEqual({ x_m: 4.5, y_m: 0.55, rotation_rad: Math.PI / 2 });
    expect(moved.items[1]).toBe(state.items[1]);
  });

  it("is a no-op for a key that is not in the plan", () => {
    const state = planWith(SOFA);

    expect(planReducer(state, { type: "move", key: "gone", pose: SOFA.pose })).toBe(state);
  });
});

describe("remove", () => {
  it("drops only the item named", () => {
    const state = planWith(SOFA, LAMP);

    expect(planReducer(state, { type: "remove", key: "a" }).items).toEqual([LAMP]);
  });

  it("is a no-op for a key that is not in the plan", () => {
    const state = planWith(SOFA);

    expect(planReducer(state, { type: "remove", key: "gone" })).toBe(state);
  });
});

describe("purity", () => {
  it("never mutates the state it is given", () => {
    const state = planWith(SOFA, LAMP);
    const before = JSON.stringify(state);

    planReducer(state, { type: "move", key: "a", pose: { x_m: 9, y_m: 9, rotation_rad: 1 } });
    planReducer(state, { type: "remove", key: "b" });
    planReducer(state, { type: "add", item: { ...SOFA, key: "c" } });

    expect(JSON.stringify(state)).toBe(before);
  });

  it("starts empty", () => {
    expect(emptyPlan.items).toEqual([]);
  });
});
