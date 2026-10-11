import { describe, expect, it } from 'vitest';
import type { NudgeRegionAvailable, SolvedDesign, Vec2 } from '../src/shared/api/types';
import { clipNudgeSegment, nudgeContains, validNudgeRegion } from '../src/features/design/nudge-geometry';
import { ownsNewerDesign } from '../src/features/design/useMutationLock';

function region(origin: Vec2 = [0, 0], bound = 1): NudgeRegionAvailable {
  return { status: 'available', conservative: true, regionId: 'r', sessionId: 's', version: 1,
    instanceId: 'bed', origin, fixedY: 0, fixedYaw: 0, expiresInMs: 120000, detail: 'Conservative',
    constraintCount: 4, witnessPolygonCount: 0, attachmentCount: 0, computationMs: 1,
    constraints: [
      { normal: [1, 0], maxDisplacementM: bound }, { normal: [-1, 0], maxDisplacementM: bound },
      { normal: [0, 1], maxDisplacementM: bound }, { normal: [0, -1], maxDisplacementM: bound },
    ], polygon: [[-bound, -bound], [bound, -bound], [bound, bound], [-bound, bound]] };
}

describe('certified segment clipping', () => {
  it('takes a sparse jump only to the first boundary, never through a thin excluded strip', () => {
    const r = region();
    const hit = clipNudgeSegment(r, [0, 0], [3, 0.6]);
    expect(hit.clamped).toBe(true);
    expect(hit.point[0]).toBeCloseTo(1 - 1e-8, 6);
    expect(hit.point[1]).toBeCloseTo(0.2, 6);
    expect(nudgeContains(r, hit.point)).toBe(true);
    // Even if another safe component existed beyond the strip, it cannot be
    // reached by projecting the desired endpoint into that component.
    expect(hit.point[0]).toBeLessThan(1);
  });

  it('preserves every interpolated point between successive clipped samples', () => {
    const r = region();
    let last: Vec2 = [0, 0];
    for (const desired of [[4, 5], [-5, 3], [0.2, -6], [-0.1, 0.4]] as Vec2[]) {
      const next = clipNudgeSegment(r, last, desired).point;
      for (let step = 0; step <= 100; step += 1) {
        const t = step / 100;
        expect(nudgeContains(r, [last[0] * (1 - t) + next[0] * t, last[1] * (1 - t) + next[1] * t])).toBe(true);
      }
      last = next;
    }
  });

  it('moves freely within a permitted rug region', () => {
    const r = region();
    expect(clipNudgeSegment(r, [0, 0], [0.8, 0.4])).toEqual({ point: [0.8, 0.4], clamped: false });
  });

  it('uses the strict inward margin immediately inside, on and outside a bound', () => {
    const r = region([0, 0], 0.001 - 1e-7);
    expect(nudgeContains(r, [0.001 - 1e-7 - 1e-8 - 1e-12, 0])).toBe(true);
    expect(nudgeContains(r, [0.001 - 1e-7, 0])).toBe(false);
    expect(nudgeContains(r, [0.001 + 1e-12, 0])).toBe(false);
    const witness = region([0, 0], 0.1 + 1e-9 - 1e-7);
    expect(nudgeContains(witness, [0.1 + 1e-9 - 1e-7 - 1e-8 - 1e-12, 0])).toBe(true);
    expect(nudgeContains(witness, [0.1 + 1e-9, 0])).toBe(false);
  });

  it('rechecks clipping after large-coordinate cancellation and JSON round trip', () => {
    const r = JSON.parse(JSON.stringify(region([999, -999], 0.01))) as NudgeRegionAvailable;
    expect(validNudgeRegion(r)).toBe(true);
    const hit = clipNudgeSegment(r, r.origin, [999.7, -998.6]);
    expect(hit.clamped).toBe(true);
    expect(nudgeContains(r, hit.point)).toBe(true);
  });

  it('rejects malformed certificates and keeps the last safe pose on invalid desired input', () => {
    const r = region();
    for (const malformed of [
      { ...r, constraints: [] }, { ...r, origin: [NaN, 0] },
      { ...r, constraints: [{ normal: [2, 0], maxDisplacementM: 1 }, ...r.constraints] },
      { ...r, expiresInMs: Infinity }, { ...r, fixedYaw: NaN },
      { ...r, constraints: [{ normal: [1, 0], maxDisplacementM: -1 }, ...r.constraints] },
    ]) expect(validNudgeRegion(malformed as NudgeRegionAvailable)).toBe(false);
    expect(clipNudgeSegment(r, [0.2, 0.2], [NaN, 0]).point).toEqual([0.2, 0.2]);
  });

  it('cannot special-case an uncertified origin as safe', () => {
    const r = region();
    const bad = { ...r, constraints: [{ normal: [1, 0] as Vec2, maxDisplacementM: -0.1 }, ...r.constraints] };
    expect(validNudgeRegion(bad)).toBe(false);
  });
});

it('both page owners reject foreign sessions and version regressions', () => {
  const design = (id: string, version: number) => ({ swap: { status: 'available', sessionId: id, version } }) as SolvedDesign;
  expect(ownsNewerDesign(design('owned', 2), design('foreign', 3))).toBe(false);
  expect(ownsNewerDesign(design('owned', 2), design('owned', 1))).toBe(false);
  expect(ownsNewerDesign(design('owned', 2), design('owned', 2))).toBe(true);
  expect(ownsNewerDesign(design('owned', 2), design('owned', 3))).toBe(true);
});
