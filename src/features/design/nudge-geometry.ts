import type { NudgeRegionAvailable, Vec2 } from '@/shared/api/types';

export const CLIENT_NUDGE_MARGIN_M = 1e-8;
const finitePoint = (point: unknown): point is Vec2 => Array.isArray(point)
  && point.length === 2 && point.every((value) => typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= 1000);

/** Runtime validation is required even for a generated TypeScript contract. */
export function validNudgeRegion(region: NudgeRegionAvailable): boolean {
  if (!region || typeof region !== 'object') return false;
  return region.status === 'available' && region.conservative === true
    && typeof region.regionId === 'string' && region.regionId.length > 0
    && typeof region.sessionId === 'string' && region.sessionId.length > 0
    && typeof region.instanceId === 'string' && region.instanceId.length > 0
    && Number.isInteger(region.version) && region.version >= 1
    && Number.isFinite(region.fixedY) && Math.abs(region.fixedY) <= 1000
    && Number.isFinite(region.fixedYaw)
    && Number.isInteger(region.expiresInMs) && region.expiresInMs > 0 && region.expiresInMs <= 120000
    && finitePoint(region.origin)
    && Array.isArray(region.constraints) && region.constraints.length >= 3 && region.constraints.length <= 4096
    && region.constraints.every((plane) => plane && typeof plane === 'object' && finitePoint(plane.normal)
      && Math.abs(Math.hypot(...plane.normal) - 1) < 1e-12
      && Number.isFinite(plane.maxDisplacementM) && plane.maxDisplacementM > CLIENT_NUDGE_MARGIN_M)
    && Array.isArray(region.polygon) && region.polygon.length >= 3 && region.polygon.length <= 4096
    && region.polygon.every(finitePoint)
    && nudgeContains(region, region.origin);
}

export function nudgeContains(region: NudgeRegionAvailable, point: Vec2): boolean {
  if (!finitePoint(point)) return false;
  const dx = point[0] - region.origin[0];
  const dz = point[1] - region.origin[1];
  return region.constraints.every((plane) => plane.normal[0] * dx + plane.normal[1] * dz
    <= plane.maxDisplacementM - CLIENT_NUDGE_MARGIN_M);
}

/** Advance along the desired segment only as far as its first half-plane hit. */
export function clipNudgeSegment(region: NudgeRegionAvailable, lastSafe: Vec2, desired: Vec2): { point: Vec2; clamped: boolean } {
  if (!nudgeContains(region, lastSafe) || !finitePoint(desired)) return { point: lastSafe, clamped: true };
  const start: Vec2 = [lastSafe[0] - region.origin[0], lastSafe[1] - region.origin[1]];
  const delta: Vec2 = [desired[0] - lastSafe[0], desired[1] - lastSafe[1]];
  let fraction = 1;
  for (const plane of region.constraints) {
    const speed = plane.normal[0] * delta[0] + plane.normal[1] * delta[1];
    if (speed <= 0) continue;
    const remaining = plane.maxDisplacementM - CLIENT_NUDGE_MARGIN_M
      - plane.normal[0] * start[0] - plane.normal[1] * start[1];
    fraction = Math.min(fraction, Math.max(0, remaining / speed));
  }
  // Leave room for the display interpolation's own double arithmetic too.
  if (fraction < 1) fraction *= 1 - 1e-10;
  // Recheck the world-coordinate result after cancellation/rounding. Shrinking
  // stays on the same certified segment and never expands an inequality.
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const point: Vec2 = [lastSafe[0] + delta[0] * fraction, lastSafe[1] + delta[1] * fraction];
    if (nudgeContains(region, point)) return { point, clamped: fraction < 1 };
    fraction *= 0.999999;
  }
  return { point: lastSafe, clamped: true };
}
