"use client";

import type { ThreeEvent } from "@react-three/fiber";

import { toWorld } from "@/modules/units";

/** The ring's colour, matching the selection outline it belongs to. */
const HANDLE_COLOUR = "#6b7f9e";

/** How far in front of the item the ring floats, and how big it is. */
const GAP_M = 0.25;
const RING_RADIUS_M = 0.11;
const RING_TUBE_M = 0.025;
/** The pointer target under the ring. A 2.5cm tube is a hard thing to hit with a mouse. */
const GRAB_RADIUS_M = 0.24;
/** Just off the floor, so it is not fighting the floor plane for the same pixels. */
const LIFT_M = 0.02;

/**
 * The ring that turns the selected item.
 *
 * It sits in front of the item — inside the item's own rotated group, so it stays at the
 * front as the item turns — and dragging it points the front at the pointer. Direct
 * manipulation: the buyer turns the sofa by taking hold of it, not by nudging a number.
 *
 * Flat on the floor rather than upright, because the whole gesture happens in the floor
 * plane and a ring standing up would read as a wheel to be spun the other way.
 */
export function RotateHandle({
  depthM,
  onGrab,
}: {
  depthM: number;
  onGrab: () => void;
}) {
  const grab = (event: ThreeEvent<PointerEvent>) => {
    if (event.button !== 0) return;
    // Otherwise the item under it starts a move, and the buyer drags what they meant to
    // turn clean across the room.
    event.stopPropagation();
    onGrab();
  };

  return (
    <group position={toWorld([0, depthM / 2 + GAP_M], LIFT_M)} onPointerDown={grab}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <torusGeometry args={[RING_RADIUS_M, RING_TUBE_M, 8, 24]} />
        <meshBasicMaterial color={HANDLE_COLOUR} />
      </mesh>

      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[GRAB_RADIUS_M, 24]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
    </group>
  );
}
