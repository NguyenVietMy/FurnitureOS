/**
 * Turning an item with the mouse, as arithmetic.
 *
 * The handle drag is three lines of scene code and one function; this tests the
 * function, because the part that can be wrong — which way is the front, where the
 * snap lands, what a pointer on top of the centre means — is all in here.
 */

import { describe, expect, it } from "vitest";

import { ROTATION_STEP_RAD, rotationToward } from "./rotation";

const CENTRE = [3, 2] as const;

/** A point one metre from the centre at `degrees` anticlockwise from due east. */
function around(degrees: number): readonly [number, number] {
  const radians = (degrees * Math.PI) / 180;
  return [CENTRE[0] + Math.cos(radians), CENTRE[1] + Math.sin(radians)];
}

describe("rotationToward", () => {
  it("leaves an item square-on when the pointer is straight in front of it", () => {
    // The handle sits at the item's front, so pointing it north is rotation zero.
    expect(rotationToward(CENTRE, around(90), 0)).toBe(0);
  });

  it("turns the front to face the pointer", () => {
    expect(rotationToward(CENTRE, around(0), 0)).toBeCloseTo((3 * Math.PI) / 2, 9);
    expect(rotationToward(CENTRE, around(180), 0)).toBeCloseTo(Math.PI / 2, 9);
  });

  it("snaps to the step, so 45° is a thing a hand can hit", () => {
    expect(rotationToward(CENTRE, around(90 + 44), 0)).toBeCloseTo(Math.PI / 4, 9);
    expect(rotationToward(CENTRE, around(90 + 47), 0)).toBeCloseTo(Math.PI / 4, 9);
  });

  it("holds an angle steady against a wobbling hand", () => {
    const steady = rotationToward(CENTRE, around(90 + 45), 0);

    expect(rotationToward(CENTRE, around(90 + 45.4), 0)).toBe(steady);
    expect(rotationToward(CENTRE, around(90 + 44.6), 0)).toBe(steady);
  });

  it("only ever returns a multiple of the step, in [0, 2π)", () => {
    for (let degrees = -360; degrees <= 360; degrees += 7) {
      const rotation = rotationToward(CENTRE, around(degrees), 0);

      expect(rotation).toBeGreaterThanOrEqual(0);
      expect(rotation).toBeLessThan(2 * Math.PI);
      expect(Math.round(rotation / ROTATION_STEP_RAD) * ROTATION_STEP_RAD).toBeCloseTo(
        rotation,
        9,
      );
    }
  });

  it("keeps the angle it had when the pointer is on top of the centre", () => {
    // Dragging the handle through the item itself has no angle in it. Anything other
    // than "unchanged" here makes the item spin wildly as the pointer crosses.
    expect(rotationToward(CENTRE, CENTRE, Math.PI / 3)).toBe(Math.PI / 3);
  });
});
