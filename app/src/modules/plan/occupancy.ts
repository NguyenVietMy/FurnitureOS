/**
 * The plan as the room model sees it: what stands where, and how big it is.
 *
 * The plan stores item ids; the geometry needs metres. This is the one place the two
 * meet, so the footprint the room collides with is by construction the same three
 * numbers the scene draws with — no second opinion about how wide a sofa is.
 */

import type { Item } from "@/modules/catalogue";
import type { Footprint, Occupant } from "@/modules/geometry";

import type { PlacedItem } from "./reducer";

/** An item's plan size. Width across its front, depth back from it; height is the scene's. */
export function footprintOf(item: Item): Footprint {
  return { width_m: item.width_m, depth_m: item.depth_m };
}

/**
 * Everything in the plan that the catalogue can still size.
 *
 * An item whose product has gone is left out rather than guessed at, matching the scene,
 * which does not draw one either. Better a gap in the room than an invisible obstacle.
 */
export function occupantsOf(
  items: readonly PlacedItem[],
  catalogue: ReadonlyMap<string, Item>,
): Occupant[] {
  return items.flatMap((placed) => {
    const product = catalogue.get(placed.itemId);
    if (!product) return [];

    return [{ key: placed.key, footprint: footprintOf(product), pose: placed.pose }];
  });
}
