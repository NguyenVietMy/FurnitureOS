"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { CataloguePanel, CATALOGUE_ITEM_MIME, type Item } from "@/modules/catalogue";
import { createRoomModel, type Footprint } from "@/modules/geometry";
import { UnitScene, type Point, type Unit } from "@/modules/units";

import { emptyPlan, planReducer } from "./reducer";
import { PlanItems, type FloorProjector } from "./scene/PlanItems";
import styles from "./Planner.module.css";

/**
 * The planner: a catalogue on the left, the apartment on the right, furniture in it.
 *
 * Composition, not logic. What may go where is `@/modules/geometry`, what is in the
 * plan is the reducer, what a sofa looks like is the scene — this wires the three
 * together and owns only what a single screen owns: which item is selected, and where
 * the pointer is.
 *
 * Nothing is saved. A refresh loses the plan until issue 05 puts it behind a token.
 */
export function Planner({ unit, catalogue }: { unit: Unit; catalogue: readonly Item[] }) {
  const [plan, dispatch] = useReducer(planReducer, emptyPlan);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const roomModel = useMemo(() => createRoomModel(unit), [unit]);
  const byId = useMemo(
    () => new Map(catalogue.map((item) => [item.id, item] as const)),
    [catalogue],
  );
  const projectorRef = useRef<FloorProjector | null>(null);

  const place = useCallback(
    (item: Item, near?: Point) => {
      const footprint: Footprint = { width_m: item.width_m, depth_m: item.depth_m };

      // Aim for where they dropped it and settle for the nearest floor that fits. A
      // room with nowhere left simply refuses; issue 04 gives that refusal a face.
      const pose = roomModel.findFreeSpot(footprint, near);
      if (pose === null) return;

      const key = nextKey(item.id);
      dispatch({ type: "add", item: { key, itemId: item.id, pose } });
      setSelectedKey(key);
    },
    [roomModel],
  );

  const remove = useCallback((key: string) => {
    dispatch({ type: "remove", key });
    setSelectedKey((selected) => (selected === key ? null : selected));
  }, []);

  // Delete and Backspace remove the selection — unless the buyer is typing in the
  // search box, where Backspace means Backspace.
  useEffect(() => {
    if (selectedKey === null) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Delete" && event.key !== "Backspace") return;
      if (isTyping(event.target)) return;

      event.preventDefault();
      remove(selectedKey);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedKey, remove]);

  const selected = plan.items.find((item) => item.key === selectedKey) ?? null;
  const selectedProduct = selected ? byId.get(selected.itemId) : undefined;

  return (
    <div className={styles.planner}>
      <CataloguePanel items={catalogue} onAdd={(item) => place(item)} />

      <div
        className={styles.viewport}
        onDragOver={(event) => {
          // Without this the browser refuses the drop and animates the card home.
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={(event) => {
          event.preventDefault();
          const item = byId.get(event.dataTransfer.getData(CATALOGUE_ITEM_MIME));
          if (!item) return;

          place(item, projectorRef.current?.(event.clientX, event.clientY) ?? undefined);
        }}
      >
        <UnitScene unit={unit}>
          <PlanItems
            items={plan.items}
            catalogue={byId}
            roomModel={roomModel}
            selectedKey={selectedKey}
            onSelect={setSelectedKey}
            onMove={(key, pose) => dispatch({ type: "move", key, pose })}
            projectorRef={projectorRef}
          />
        </UnitScene>

        {plan.items.length === 0 && (
          <p className={styles.empty}>Drag something in from the catalogue.</p>
        )}

        {selected && selectedProduct && (
          <div className={styles.selection} role="status">
            <span className={styles.selectionName}>{selectedProduct.name}</span>
            <button
              type="button"
              className={styles.delete}
              onClick={() => remove(selected.key)}
            >
              Delete
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * A unique key per placed copy.
 *
 * Identifies this sofa, not sofas. Never leaves the browser: issue 05 stores item ids
 * and poses, and these are minted afresh when a plan is reopened.
 */
let placed = 0;
function nextKey(itemId: string): string {
  placed += 1;
  return `${itemId}#${placed}`;
}

function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.matches("input, textarea, [contenteditable]");
}
