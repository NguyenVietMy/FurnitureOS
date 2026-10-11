import type { SolvedDesign } from '@/shared/api/types';
import type { MutationLock } from './useMutationLock';
import type { NudgeController } from './useNudge';

export function NudgeControls({ design, nudge, lock }: { design: SolvedDesign; nudge: NudgeController; lock: MutationLock }) {
  const session = design.swap?.status === 'available' ? design.swap : null;
  if (!session) return null;
  const active = ['pending', 'ready', 'dragging', 'clamped', 'committing', 'reconciling', 'blocked'].includes(nudge.status);
  return <section className="nudge-controls" data-testid="nudge-controls" data-state={nudge.status}
    data-session-id={session.sessionId} data-version={session.version} data-instance-id={nudge.instanceId}>
    <h2>Nudge a Product</h2>
    <p className="subtle">Glide within safe movement limits. The Product keeps its rotation; other furniture stays in place.</p>
    <label className="swap-field"><span>Placement</span>
      <select aria-label="Placement to Nudge" value={nudge.instanceId} disabled={active || lock.owner === 'swap'}
        onChange={(event) => nudge.choose(event.target.value)}>
        {design.placements.map((placement, index) => <option key={placement.instanceId} value={placement.instanceId ?? ''}>
          {design.products[index]?.displayName} — {placement.instanceId}
        </option>)}
      </select>
    </label>
    {!active ? <button type="button" className="swap-check-button" disabled={lock.owner !== null || !nudge.instanceId}
      onClick={nudge.prepare}>{nudge.status === 'error' || nudge.status === 'unavailable' ? 'Retry Nudge' : 'Prepare Nudge'}</button> : null}
    {['pending', 'ready', 'dragging', 'clamped'].includes(nudge.status) ? <button type="button" className="swap-check-button" onClick={nudge.cancel}>Cancel Nudge</button> : null}
    {nudge.message ? <p className="nudge-status" role={nudge.status === 'error' || nudge.status === 'blocked' ? 'alert' : 'status'}>{nudge.message}</p> : null}
    {nudge.status === 'blocked' ? <button type="button" className="swap-check-button" onClick={nudge.retryCurrent}>Retry current Design</button> : null}
    {nudge.region ? <p className="subtle">These conservative limits may stop movement before every possible safe position. Preparing again refreshes them.</p> : null}
  </section>;
}
