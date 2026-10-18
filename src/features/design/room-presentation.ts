import type { RoomShell, Vec2 } from '@/shared/api/types';

export function wallInwardNormal(room: RoomShell, wall: RoomShell['walls'][number]): Vec2 {
  const points = room.floorPolygon;
  const area = points.reduce((sum, p, i) => { const q = points[(i + 1) % points.length]!; return sum + p[0] * q[1] - q[0] * p[1]; }, 0);
  const same = (a: Vec2, b: Vec2) => a[0] === b[0] && a[1] === b[1];
  const edge = points.findIndex((p, i) => same(p, wall.start) && same(points[(i + 1) % points.length]!, wall.end));
  const sign = (area > 0 ? 1 : -1) * (edge < 0 ? -1 : 1);
  const dx = wall.end[0] - wall.start[0], dz = wall.end[1] - wall.start[1], length = Math.hypot(dx, dz);
  return [-dz / length * sign, dx / length * sign];
}

/** Clip decorative grid lines to the authoritative floor polygon, including its notch. */
export function floorGrid(points: RoomShell['floorPolygon']): Float32Array {
  const positions: number[] = [];
  for (const axis of [0, 1] as const) {
    const other = axis === 0 ? 1 : 0;
    const low = Math.min(...points.map(p => p[axis])), high = Math.max(...points.map(p => p[axis]));
    const step = Math.max(1, Math.ceil((high - low) / 128));
    for (let value = Math.ceil(low / step) * step; value < high; value += step) {
      const cuts: number[] = [];
      points.forEach((a, i) => {
        const b = points[(i + 1) % points.length]!;
        if ((a[axis] <= value && value < b[axis]) || (b[axis] <= value && value < a[axis])) cuts.push(a[other] + (value - a[axis]) / (b[axis] - a[axis]) * (b[other] - a[other]));
      });
      cuts.sort((a, b) => a - b);
      for (let i = 0; i + 1 < cuts.length; i += 2) {
        if (axis === 0) positions.push(value, .002, cuts[i]!, value, .002, cuts[i + 1]!);
        else positions.push(cuts[i]!, .002, value, cuts[i + 1]!, .002, value);
      }
    }
  }
  return new Float32Array(positions);
}
