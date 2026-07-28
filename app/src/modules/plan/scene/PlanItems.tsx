"use client";

import { useThree } from "@react-three/fiber";
import { useEffect, useRef, useState } from "react";

import type { Item } from "@/modules/catalogue";
import type { Pose, RoomModel } from "@/modules/geometry";
import { toWorld, toWorldRotation, type Point } from "@/modules/units";

import { footprintOf } from "../occupancy";
import type { PlacedItem } from "../reducer";
import { rotationToward } from "../rotation";
import { projectToFloor } from "./floor";
import { PresetModel } from "./PresetModel";
import { RotateHandle } from "./RotateHandle";
import { useBlockedFlash } from "./useBlockedFlash";

/** Turns a screen point into a spot on the floor. Published for the HTML5 drop target. */
export type FloorProjector = (clientX: number, clientY: number) => Point | null;

/**
 * The gesture in progress. Moving carries the grab offset so the item does not jump to
 * the pointer; turning carries nothing, because a turn is about the item's own centre.
 */
type Gesture =
  | { readonly kind: "move"; readonly key: string; readonly offset: Point }
  | { readonly kind: "turn"; readonly key: string };

/** Past this much of the drag left unspent, the item is being pushed into something. */
const BLOCKED_M = 0.01;

/**
 * The furniture in the room, and the dragging and turning of it.
 *
 * Renders inside the unit's canvas. Every pose it produces has been through the room
 * model, so nothing here decides what is legal — it asks, draws the answer, and flashes
 * the item red when the answer was no. That split is the point of the geometry module.
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
  onRotate,
  projectorRef,
}: {
  items: readonly PlacedItem[];
  catalogue: ReadonlyMap<string, Item>;
  roomModel: RoomModel;
  selectedKey: string | null;
  onSelect: (key: string | null) => void;
  onMove: (key: string, pose: Pose) => void;
  onRotate: (key: string, rotationRad: number) => void;
  projectorRef: { current: FloorProjector | null };
}) {
  const { camera, gl } = useThree();
  const [gesture, setGesture] = useState<Gesture | null>(null);
  const [blockedKey, flashBlocked] = useBlockedFlash();

  // The drag listeners read the latest plan and room without re-subscribing on every
  // change — which, mid-drag, is every frame, and the room model is rebuilt each time an
  // item moves because the item that moved is part of the room.
  const latestRef = useRef({ items, catalogue, roomModel, onMove, onRotate, flashBlocked });
  useEffect(() => {
    latestRef.current = { items, catalogue, roomModel, onMove, onRotate, flashBlocked };
  });

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
    if (gesture === null) return;

    const move = (event: PointerEvent) => {
      const latest = latestRef.current;
      const placed = latest.items.find((item) => item.key === gesture.key);
      const product = placed && latest.catalogue.get(placed.itemId);
      if (!placed || !product) return;

      const floor = projectToFloor(camera, gl.domElement, event.clientX, event.clientY);
      if (floor === null) return;

      const footprint = footprintOf(product);

      if (gesture.kind === "turn") {
        const centre: Point = [placed.pose.x_m, placed.pose.y_m];
        const turned = rotationToward(centre, floor, placed.pose.rotation_rad);
        if (turned === placed.pose.rotation_rad) return;

        // A turn is refused rather than resolved: an item that shuffled itself across
        // the room to make space for its own corners is not what the buyer asked for.
        const turnedPose = { ...placed.pose, rotation_rad: turned };
        if (latest.roomModel.canPlace(footprint, turnedPose, placed.key)) {
          latest.onRotate(placed.key, turned);
        } else {
          latest.flashBlocked(placed.key);
        }

        return;
      }

      const desired: Pose = {
        x_m: floor[0] + gesture.offset[0],
        y_m: floor[1] + gesture.offset[1],
        rotation_rad: placed.pose.rotation_rad,
      };

      const resolved = latest.roomModel.resolveDrag(
        footprint,
        desired,
        placed.pose,
        placed.key,
      );
      if (Math.hypot(desired.x_m - resolved.x_m, desired.y_m - resolved.y_m) > BLOCKED_M) {
        latest.flashBlocked(placed.key);
      }

      latest.onMove(placed.key, resolved);
    };

    const release = () => setGesture(null);

    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);

    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", release);
      window.removeEventListener("pointercancel", release);
    };
  }, [gesture, camera, gl]);

  return (
    <group onPointerMissed={() => onSelect(null)}>
      {items.map((placed) => {
        const product = catalogue.get(placed.itemId);
        // An item the catalogue has lost is not drawn. Issue 05 validates ids on save;
        // this is the display half of the same fact.
        if (!product) return null;

        const selected = placed.key === selectedKey;

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

              setGesture({
                kind: "move",
                key: placed.key,
                offset: [placed.pose.x_m - floor[0], placed.pose.y_m - floor[1]],
              });
            }}
          >
            <PresetModel
              presetRef={product.preset_ref}
              size={product}
              selected={selected}
              blocked={placed.key === blockedKey}
            />

            {selected && (
              <RotateHandle
                depthM={product.depth_m}
                onGrab={() => setGesture({ kind: "turn", key: placed.key })}
              />
            )}
          </group>
        );
      })}
    </group>
  );
}
