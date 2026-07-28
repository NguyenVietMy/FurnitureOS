"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { CataloguePanel, CATALOGUE_ITEM_MIME, type Item } from "@/modules/catalogue";
import { createRoomModel } from "@/modules/geometry";
import { UnitScene, type Point, type Unit } from "@/modules/units";

import { footprintOf, occupantsOf } from "./occupancy";
import { emptyPlan, planReducer } from "./reducer";
import { PlanItems, type FloorProjector } from "./scene/PlanItems";
import styles from "./Planner.module.css";

/** How long a refusal stays on screen. Long enough to read, short enough to forgive. */
const NOTICE_MS = 3500;

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
  const [notice, setNotice] = useState<Notice | null>(null);

  const byId = useMemo(
    () => new Map(catalogue.map((item) => [item.id, item] as const)),
    [catalogue],
  );

  // The room is the apartment plus what is already standing in it, so it is rebuilt
  // whenever anything moves. Cheap by design: the model holds no state of its own.
  const occupants = useMemo(() => occupantsOf(plan.items, byId), [plan.items, byId]);
  const roomModel = useMemo(() => createRoomModel(unit, occupants), [unit, occupants]);

  const projectorRef = useRef<FloorProjector | null>(null);

  const place = useCallback(
    (item: Item, near?: Point) => {
      // Aim for where they dropped it and settle for the nearest floor that fits, clear
      // of the walls and of everything already in the room.
      const pose = roomModel.findFreeSpot(footprintOf(item), near);
      if (pose === null) {
        setNotice({ text: `No room left for the ${item.name}.`, at: Date.now() });
        return;
      }

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

  // A refusal is a moment, not a state. It says its piece and goes.
  useEffect(() => {
    if (notice === null) return;

    const timer = setTimeout(() => setNotice(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice]);

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
            onRotate={(key, rotation_rad) => dispatch({ type: "rotate", key, rotation_rad })}
            projectorRef={projectorRef}
          />
        </UnitScene>

        {plan.items.length === 0 && (
          <p className={styles.empty}>Drag something in from the catalogue.</p>
        )}

        {notice && (
          <p className={styles.notice} role="status">
            {notice.text}
          </p>
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
 * Something the planner could not do, and when it was said.
 *
 * The timestamp is what makes two identical refusals two refusals: without it the second
 * "no room left" would inherit the first one's dismissal timer and vanish immediately.
 */
interface Notice {
  readonly text: string;
  readonly at: number;
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
