"use client";

import { useThree } from "@react-three/fiber";
import { useEffect, useRef, useState } from "react";

import type { Item } from "@/modules/catalogue";
import type { Pose, RoomModel } from "@/modules/geometry";
import { toWorld, toWorldRotation, type Point } from "@/modules/units";

import type { PlacedItem } from "../reducer";
import { projectToFloor } from "./floor";
import { PresetModel } from "./PresetModel";

/** Turns a screen point into a spot on the floor. Published for the HTML5 drop target. */
export type FloorProjector = (clientX: number, clientY: number) => Point | null;

interface Grab {
  readonly key: string;
  /** Where the item's centre sits relative to the point grabbed, so it does not jump. */
  readonly offset: Point;
}

/**
 * The furniture in the room, and the dragging of it.
 *
 * Renders inside the unit's canvas. Every pose it produces has been through
 * `resolveDrag`, so nothing here decides what is legal — it asks the room model and
 * draws the answer. That split is the point of the geometry module.
 *
 * Left button only: right-drag belongs to the camera.
 */
export function PlanItems({
  items,
  catalogue,
  roomModel,
  selectedKey,
  onSelect,
  onMove,
  projectorRef,
}: {
  items: readonly PlacedItem[];
  catalogue: ReadonlyMap<string, Item>;
  roomModel: RoomModel;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  onMove: (key: string, pose: Pose) => void;
  projectorRef: { current: FloorProjector | null };
}) {
  const { camera, gl } = useThree();
  const [grab, setGrab] = useState<Grab | null>(null);

  // The drag listeners read the latest items without re-subscribing on every pose
  // change — which, mid-drag, is every frame.
  const latestRef = useRef(items);
  useEffect(() => {
    latestRef.current = items;
  }, [items]);

  // Publish the projection so the wrapping div can turn an HTML5 drop into a spot on
  // the floor. It needs the camera, and the camera only exists inside the canvas.
  useEffect(() => {
    const element = gl.domElement;
    projectorRef.current = (clientX, clientY) =>
      projectToFloor(camera, element, clientX, clientY);

    return () => {
      projectorRef.current = null;
    };
  }, [camera, gl, projectorRef]);

  // Listeners on the window, not the mesh: a drag that outruns the pointer must keep
  // following it, including off the edge of the canvas and back.
  useEffect(() => {
    if (grab === null) return;

    const move = (event: PointerEvent) => {
      const placed = latestRef.current.find((item) => item.key === grab.key);
      const product = placed && catalogue.get(placed.itemId);
      if (!placed || !product) return;

      const floor = projectToFloor(camera, gl.domElement, event.clientX, event.clientY);
      if (floor === null) return;

      const desired: Pose = {
        x_m: floor[0] + grab.offset[0],
        y_m: floor[1] + grab.offset[1],
        rotation_rad: placed.pose.rotation_rad,
      };

      onMove(placed.key, roomModel.resolveDrag(footprintOf(product), desired, placed.pose));
    };

    const release = () => setGrab(null);

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);

    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
  }, [grab, camera, gl, catalogue, roomModel, onMove]);

  return (
    <group onPointerMissed={() => onSelect(null)}>
      {items.map((placed) => {
        const product = catalogue.get(placed.itemId);
        // An item the catalogue has lost is not drawn. Issue 05 validates ids on save;
        // this is the display half of the same fact.
        if (!product) return null;

        return (
          <group
            key={placed.key}
            position={toWorld([placed.pose.x_m, placed.pose.y_m])}
            rotation={toWorldRotation(placed.pose.rotation_rad)}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.stopPropagation();
              onSelect(placed.key);

              const floor = projectToFloor(
                camera,
                gl.domElement,
                event.clientX,
                event.clientY,
              );
              if (floor === null) return;

              setGrab({
                key: placed.key,
                offset: [placed.pose.x_m - floor[0], placed.pose.y_m - floor[1]],
              });
            }}
          >
            <PresetModel
              presetRef={product.preset_ref}
              size={product}
              selected={placed.key === selectedKey}
            />
          </group>
        );
      })}
    </group>
  );
}

function footprintOf(item: Item) {
  return { width_m: item.width_m, depth_m: item.depth_m };
}
