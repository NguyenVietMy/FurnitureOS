import type { CaptureDraft, PhotoReservation } from '@/shared/api/types';

export const rectangleWalls = ['wall-north', 'wall-east', 'wall-south', 'wall-west'] as const;
export const lWalls = ['wall-north', 'wall-notch-vertical', 'wall-notch-horizontal', 'wall-east', 'wall-south', 'wall-west'] as const;
export const activeWalls = (topology?: string) => topology === 'L-shaped' ? lWalls : rectangleWalls;
export const wallLabel = (topology: string | undefined, wall: string | null | undefined) => {
  const index = (activeWalls(topology) as readonly string[]).indexOf(wall ?? '');
  return index < 0 ? 'Unassociated wall' : `Wall ${'ABCDEF'[index]}`;
};
export const dimensionFields = (topology?: string): ReadonlyArray<'widthM' | 'depthM' | 'heightM' | 'notchWidthM' | 'notchDepthM'> =>
  topology === 'L-shaped' ? ['widthM', 'depthM', 'notchWidthM', 'notchDepthM', 'heightM'] : ['widthM', 'depthM', 'heightM'];
export interface PlanWall { id: PhotoReservation['primaryWallId']; start: readonly [number, number]; end: readonly [number, number]; length: number }
// Presentation only: FastAPI validates the Room and owns every fit decision.
export function draftWalls(draft: CaptureDraft): ReadonlyArray<PlanWall> | null {
  const w = draft.widthM, d = draft.depthM, nw = draft.notchWidthM, nd = draft.notchDepthM;
  if (!w || !d || !Number.isFinite(w) || !Number.isFinite(d) || w <= 0 || d <= 0 || w > 1000 || d > 1000) return null;
  if (draft.topology !== 'rectangle' && draft.topology !== 'L-shaped') return null;
  if (draft.topology === 'L-shaped' && (!nw || !nd || !Number.isFinite(nw) || !Number.isFinite(nd) || nw <= 0 || nd <= 0 || nw >= w || nd >= d)) return null;
  const points: ReadonlyArray<readonly [number, number]> = draft.topology === 'L-shaped'
    ? [[0, 0], [w - nw!, 0], [w - nw!, nd!], [w, nd!], [w, d], [0, d]]
    : [[0, 0], [w, 0], [w, d], [0, d]];
  return activeWalls(draft.topology).map((id, i) => ({ id, start: points[i]!, end: points[(i + 1) % points.length]!, length: Math.hypot(points[(i + 1) % points.length]![0] - points[i]![0], points[(i + 1) % points.length]![1] - points[i]![1]) }));
}

