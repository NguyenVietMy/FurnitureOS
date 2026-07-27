/**
 * The preset seam: how a catalogue item becomes something the right size on screen.
 *
 * Every preset is stretched non-uniformly to the item's true dimensions, by decision —
 * drawn size must equal collision size must equal delivered size. That makes the scale
 * factors worth testing even while every preset is still a grey box: when issue 14
 * lands real `.glb` models, the maths that sizes them is already proven.
 */

import { describe, expect, it } from "vitest";

import { BOX_PRESET, presetScale, resolvePreset } from "./presets";

const SOFA = { width_m: 2.1, depth_m: 0.92, height_m: 0.84 };

describe("resolvePreset", () => {
  it("falls back to the box rather than throwing on a ref it has never heard of", () => {
    // Issue 13 may add a ref before issue 14 has a model for it. A missing model is a
    // plain-looking sofa, not a blank planner.
    expect(resolvePreset("chaise-longue-de-luxe")).toBe(BOX_PRESET);
  });

  it("has no models yet, so every catalogue ref resolves to the box", () => {
    expect(resolvePreset("sofa-3")).toBe(BOX_PRESET);
    expect(resolvePreset("wardrobe")).toBe(BOX_PRESET);
  });

  it("describes the box as a unit cube with no source file", () => {
    expect(BOX_PRESET.source).toBeNull();
    expect(BOX_PRESET.natural).toEqual({ width_m: 1, depth_m: 1, height_m: 1 });
  });
});

describe("presetScale", () => {
  it("stretches a unit box to the item's true size", () => {
    const [x, y, z] = presetScale(BOX_PRESET, SOFA);

    expect(x).toBeCloseTo(2.1, 9);
    expect(y).toBeCloseTo(0.84, 9);
    expect(z).toBeCloseTo(0.92, 9);
  });

  it("puts height on world Y and depth on world Z, matching the plan mapping", () => {
    const [, y, z] = presetScale(BOX_PRESET, { width_m: 1, depth_m: 2, height_m: 3 });

    expect(y).toBe(3);
    expect(z).toBe(2);
  });

  it("divides through a preset's own size, so a 2m model at 2m is left alone", () => {
    const preset = {
      ref: "sofa-3",
      source: "/models/sofa-3.glb",
      natural: { width_m: 2, depth_m: 1, height_m: 0.8 },
    };

    expect(presetScale(preset, { width_m: 2, depth_m: 1, height_m: 0.8 })).toEqual([1, 1, 1]);
  });

  it("stretches each axis independently — that is the whole decision", () => {
    const preset = {
      ref: "sofa-3",
      source: "/models/sofa-3.glb",
      natural: { width_m: 2, depth_m: 1, height_m: 0.8 },
    };

    const [x, y, z] = presetScale(preset, { width_m: 3, depth_m: 1, height_m: 0.4 });

    expect(x).toBeCloseTo(1.5, 9);
    expect(y).toBeCloseTo(0.5, 9);
    expect(z).toBeCloseTo(1, 9);
  });

  it("refuses to divide by a zero-sized preset", () => {
    const broken = {
      ref: "broken",
      source: "/models/broken.glb",
      natural: { width_m: 0, depth_m: 1, height_m: 1 },
    };

    // An Infinity scale is a model that vanishes on screen with no error anywhere.
    expect(presetScale(broken, SOFA).every(Number.isFinite)).toBe(true);
  });
});
