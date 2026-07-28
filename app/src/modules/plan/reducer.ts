/**
 * The buyer's plan: what is in the apartment and where it stands.
 *
 * A pure reducer, deliberately. Every change to a plan goes through here, which is what
 * lets issue 05 hang debounced autosave off a single state value and issue 10 hang a
 * delete-undo buffer off a single action — neither of them needing to know that a pose
 * came from a mouse drag.
 *
 * It holds no prices. Prices are resolved from the catalogue whenever they are shown,
 * so a plan reopened next month reflects next month's prices (issue 05), and a
 * submitted quote is recomputed server-side and frozen (issue 08).
 *
 * Selection is not in here. It is a property of one screen, not of the plan, and it is
 * never saved.
 */

import type { Pose } from "@/modules/geometry";

/** One catalogue item standing somewhere. `key` identifies this copy, not the product. */
export interface PlacedItem {
  readonly key: string;
  readonly itemId: string;
  readonly pose: Pose;
}

export interface PlanState {
  /** In insertion order, which is the order the scene draws them. */
  readonly items: readonly PlacedItem[];
}

export type PlanAction =
  | { readonly type: "add"; readonly item: PlacedItem }
  | { readonly type: "move"; readonly key: string; readonly pose: Pose }
  | { readonly type: "rotate"; readonly key: string; readonly rotation_rad: number }
  | { readonly type: "remove"; readonly key: string };

export const emptyPlan: PlanState = { items: [] };

/**
 * Apply one action. Returns the same state object when nothing changed, so a caller
 * comparing by reference — an autosave effect, say — is not woken by a no-op.
 */
export function planReducer(state: PlanState, action: PlanAction): PlanState {
  switch (action.type) {
    case "add": {
      if (state.items.some((item) => item.key === action.item.key)) return state;
      return { items: [...state.items, action.item] };
    }

    case "move": {
      if (!state.items.some((item) => item.key === action.key)) return state;
      return {
        items: state.items.map((item) =>
          item.key === action.key ? { ...item, pose: action.pose } : item,
        ),
      };
    }

    // Rotation is its own action rather than a `move` carrying a new angle. The scene
    // turns an item about its own centre and never moves it in the same gesture, and
    // saying so here is what keeps a rotate from quietly nudging a pose.
    case "rotate": {
      const turning = state.items.find((item) => item.key === action.key);
      if (!turning || turning.pose.rotation_rad === action.rotation_rad) return state;

      return {
        items: state.items.map((item) =>
          item.key === action.key
            ? { ...item, pose: { ...item.pose, rotation_rad: action.rotation_rad } }
            : item,
        ),
      };
    }

    case "remove": {
      if (!state.items.some((item) => item.key === action.key)) return state;
      return { items: state.items.filter((item) => item.key !== action.key) };
    }
  }
}
