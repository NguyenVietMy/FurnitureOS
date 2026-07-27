/**
 * Presets: the seam between a catalogue item and something the right size on screen.
 *
 * An item names an archetype (`preset_ref`), not a file. The archetype resolves to a
 * model here, and the model is stretched non-uniformly to the item's true width, depth
 * and height. That stretch is a decision, not a shortcut: drawn size equals collision
 * size equals delivered size, so a sofa that looks like it fits does fit.
 *
 * Until issue 14 supplies `.glb` files, every ref resolves to `BOX_PRESET` and renders
 * as a correctly sized box. That is a seam, not a stopgap — a real model slots into
 * `PRESETS` with a source and a natural size and nothing else changes. The same seam is
 * how a hero item gets its own bespoke model post-v1.
 */

export interface PresetSize {
  readonly width_m: number;
  readonly depth_m: number;
  readonly height_m: number;
}

export interface Preset {
  readonly ref: string;
  /** The `.glb` to load, or null while the archetype is still a box. */
  readonly source: string | null;
  /**
   * The model's own size in metres, divided out before the item's size is applied.
   *
   * Issue 14's models are authored Y-up, origin at the centre of the footprint, facing
   * +Z — so this is the only per-model number the scene needs to know.
   */
  readonly natural: PresetSize;
}

/** The fallback every ref resolves to today: a unit cube, scaled to the item verbatim. */
export const BOX_PRESET: Preset = {
  ref: "box",
  source: null,
  natural: { width_m: 1, depth_m: 1, height_m: 1 },
};

/**
 * Archetype -> model. Empty until issue 14, and adding an entry is the whole of the
 * work needed to switch an archetype from a box to a sofa.
 */
const PRESETS: Readonly<Record<string, Preset>> = {};

export function resolvePreset(presetRef: string): Preset {
  // A ref with no model is a plain-looking item, never a blank planner: issue 13 may
  // well add a product before issue 14 has anything to draw it with.
  return PRESETS[presetRef] ?? BOX_PRESET;
}

/**
 * Scale factors that take a preset to the item's true size, as three.js axes.
 *
 * Note the swap: the plan is XY with Y forward, three.js is Y-up, so the item's *depth*
 * lands on world Z and its *height* on world Y. Same mapping as `toWorld`.
 */
export function presetScale(preset: Preset, size: PresetSize): [number, number, number] {
  return [
    ratio(size.width_m, preset.natural.width_m),
    ratio(size.height_m, preset.natural.height_m),
    ratio(size.depth_m, preset.natural.depth_m),
  ];
}

/** A zero-sized preset would scale to Infinity and vanish with no error anywhere. */
function ratio(wanted: number, natural: number): number {
  return natural > 0 ? wanted / natural : 1;
}
