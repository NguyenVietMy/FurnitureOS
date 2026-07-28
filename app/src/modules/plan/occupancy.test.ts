/**
 * The plan as the room model sees it.
 *
 * One join, tested because getting it wrong is invisible: an item quietly missing from
 * the occupants list is an item everything else can be dragged straight through.
 */

import { describe, expect, it } from "vitest";

import type { Item } from "@/modules/catalogue";

import { occupantsOf } from "./occupancy";
import type { PlacedItem } from "./reducer";

const SOFA: Item = {
  id: "sofa-3-linen",
  name: "Linen three-seater",
  category: "sofa",
  width_m: 2.1,
  depth_m: 0.9,
  height_m: 0.8,
  price_vnd: 12_500_000,
  preset_ref: "sofa-3",
  photo_url: null,
};

const placed: PlacedItem = {
  key: "sofa-3-linen#1",
  itemId: SOFA.id,
  pose: { x_m: 3, y_m: 2, rotation_rad: Math.PI / 2 },
};

const catalogue = new Map([[SOFA.id, SOFA]]);

describe("occupantsOf", () => {
  it("gives each placed item its true footprint and its pose", () => {
    expect(occupantsOf([placed], catalogue)).toEqual([
      {
        key: placed.key,
        footprint: { width_m: 2.1, depth_m: 0.9 },
        pose: placed.pose,
      },
    ]);
  });

  it("leaves out an item the catalogue no longer has", () => {
    // The scene does not draw one of these either. An occupant nothing can be seen to
    // collide with is worse than no occupant at all.
    const missing: PlacedItem = { ...placed, key: "gone#1", itemId: "withdrawn" };

    expect(occupantsOf([placed, missing], catalogue).map((one) => one.key)).toEqual([
      placed.key,
    ]);
  });
});
