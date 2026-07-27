"use client";

import { presetScale, resolvePreset, type PresetSize } from "./presets";

/** The one grey every placeholder item is, until issue 14 makes them furniture. */
const ITEM_COLOUR = "#a8a196";
const SELECTED_COLOUR = "#6b7f9e";

/**
 * An item drawn at its true size — the `loadPresetScaled` seam.
 *
 * Resolve the archetype, stretch it non-uniformly to the item's width, depth and
 * height, and sit it on the floor. The caller positions and rotates it; this only ever
 * decides how big it is.
 *
 * Every preset resolves to a box today. When issue 14 supplies `.glb` files, the loaded
 * model renders here in place of `<BoxBody>` and nothing around it moves: resolution,
 * the non-uniform scale, and standing on the floor rather than sunk into it are all
 * already settled. The same seam takes a bespoke per-item model post-v1.
 */
export function PresetModel({
  presetRef,
  size,
  selected = false,
}: {
  presetRef: string;
  size: PresetSize;
  selected?: boolean;
}) {
  const preset = resolvePreset(presetRef);

  return (
    <group scale={presetScale(preset, size)}>
      <BoxBody selected={selected} />
    </group>
  );
}

/**
 * A unit cube resting on the floor plane rather than centred on it.
 *
 * Issue 14's models are authored with their origin at the centre of their footprint,
 * sitting on the floor. Lifting the box by half its height puts the placeholder on the
 * same convention, so swapping one for the other does not move anything.
 */
function BoxBody({ selected }: { selected: boolean }) {
  return (
    <>
      <mesh position={[0, 0.5, 0]} castShadow receiveShadow>
        <boxGeometry args={[1, 1, 1]} />
        <meshStandardMaterial color={selected ? SELECTED_COLOUR : ITEM_COLOUR} />
      </mesh>

      {selected && (
        <mesh position={[0, 0.5, 0]} raycast={() => null}>
          <boxGeometry args={[1.02, 1.02, 1.02]} />
          <meshBasicMaterial color={SELECTED_COLOUR} wireframe />
        </mesh>
      )}
    </>
  );
}
