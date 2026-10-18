import type { CaptureDraft } from '@/shared/api/types';
import { draftWalls, wallLabel } from './capture-topology';
export function RoomReviewPreview({ draft, confirmed }: { draft: CaptureDraft; confirmed: boolean }) {
  const walls = draftWalls(draft);
  if (!walls) return <section className="room-review"><h2>Room review preview</h2><p>Enter consistent dimensions for Rectangle or L-shaped to inspect the Room. Invalid drafts remain editable.</p></section>;
  const scale = Math.min(340 / draft.widthM!, 280 / draft.depthM!);
  const left = (500 - draft.widthM! * scale) / 2, top = (430 - draft.depthM! * scale) / 2;
  const xy = (point: readonly [number, number]) => [left + point[0] * scale, top + point[1] * scale] as const;
  return <section className="room-review"><h2>{confirmed ? 'Confirmed Room' : 'Room review preview'}</h2>
    <p>{draft.widthM} × {draft.depthM} m · ceiling {draft.heightM ?? 'unknown'} m · {draft.roomType || 'Room Type unknown'}</p>
    {draft.topology === 'L-shaped' ? <p>The top-right notch is absent floor. Align your six physical walls to this convention; these labels do not infer compass directions.</p> : null}
    <svg viewBox="0 0 500 430" role="img" aria-label="Room plan with stable wall labels, start and end directions, Openings and door swings" data-testid="capture-room-diagram">
      <defs><marker id="wall-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0 L6 3 L0 6" fill="#446bce" /></marker></defs>
      <polygon points={walls.map(wall => xy(wall.start).join(',')).join(' ')} fill="#fdfef6" stroke="#23211d" strokeWidth="3" />
      {walls.map(wall => {
        const a = xy(wall.start), b = xy(wall.end), dx = (b[0] - a[0]) / (wall.length * scale), dy = (b[1] - a[1]) / (wall.length * scale);
        const offset = 12, trim = Math.min(16, wall.length * scale / 4);
        return <g key={wall.id}><path d={`M${a[0] + dy * offset + dx * trim} ${a[1] - dx * offset + dy * trim} L${b[0] + dy * offset - dx * trim} ${b[1] - dx * offset - dy * trim}`} stroke="#446bce" fill="none" markerEnd="url(#wall-arrow)" />
          <text x={(a[0] + b[0]) / 2 + dy * 31} y={(a[1] + b[1]) / 2 - dx * 31 + 4} textAnchor="middle" fontSize="14">{wallLabel(draft.topology, wall.id)}</text></g>;
      })}
      {draft.openings?.map((opening, index) => {
        const wall = walls.find(w => w.id === opening.wallId);
        if (!wall || !opening.widthM || opening.widthM <= 0 || opening.distanceFromStartM == null) return null;
        const a = xy(wall.start), b = xy(wall.end), ux = (b[0] - a[0]) / (wall.length * scale), uy = (b[1] - a[1]) / (wall.length * scale);
        const x = a[0] + ux * opening.distanceFromStartM * scale, y = a[1] + uy * opening.distanceFromStartM * scale;
        const dx = ux * opening.widthM * scale, dy = uy * opening.widthM * scale, end = opening.hingeSide === 'end';
        const hx = end ? x + dx : x, hy = end ? y + dy : y, cx = end ? x : x + dx, cy = end ? y : y + dy, r = opening.widthM * scale;
        const ox = hx - uy * r, oy = hy + ux * r, sweep = (cx - hx) * ux + (cy - hy) * uy > 0 ? 1 : 0;
        return <g key={opening.id}>{opening.kind === 'door' && opening.direction === 'inward' && opening.angle === '90' && opening.hingeSide !== 'unknown' ? <path d={`M${hx} ${hy} L${cx} ${cy} A${r} ${r} 0 0 ${sweep} ${ox} ${oy} Z`} fill="#ff7b5520" stroke="#ff7b55" strokeDasharray="4 4" /> : null}
          <line x1={x} y1={y} x2={x + dx} y2={y + dy} stroke={opening.kind === 'door' ? '#ff7b55' : '#46d7d4'} strokeWidth="9" /><text x={x - uy * 18} y={y + ux * 18} fontSize="12">O{index + 1}</text></g>;
      })}
    </svg>
    <ol aria-label="Derived wall lengths">{walls.map(wall => <li key={wall.id}>{wallLabel(draft.topology, wall.id)}: {Number(wall.length.toFixed(6))} m · start → end</li>)}</ol>
    {draft.topology === 'L-shaped' ? <p>Closure: A + C = E ({draft.widthM} m); B + D = F ({draft.depthM} m). Ceiling: {draft.heightM ?? '?'} m.</p> : null}
    <ol>{draft.openings?.map((opening, i) => <li key={opening.id}>Opening {i + 1}: {opening.kind}, {wallLabel(draft.topology, opening.wallId)} · start offset {opening.distanceFromStartM ?? '?'} m · width {opening.widthM ?? '?'} m · bottom {opening.bottomM ?? '?'} m · height {opening.heightM ?? '?'} m · clearance {opening.clearanceDepthM ?? '?'} m{opening.kind === 'door' ? ` · ${opening.direction}/${opening.angle}° · hinge ${opening.hingeSide}` : ''}</li>)}</ol>
  </section>;
}
