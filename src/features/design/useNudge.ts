import { useEffect, useRef, useState } from 'react';
import { fetchCurrentSwapSession, fetchNudgeRegion, submitNudge } from '@/shared/api/client';
import type { NudgeRegionAvailable, SolvedDesign, Vec2 } from '@/shared/api/types';
import { clipNudgeSegment, validNudgeRegion } from './nudge-geometry';
import type { MutationLock } from './useMutationLock';

export type NudgeStatus = 'idle' | 'pending' | 'ready' | 'dragging' | 'clamped' | 'committing' | 'reconciling' | 'unavailable' | 'error' | 'blocked';
interface NudgeState {
  status: NudgeStatus;
  instanceId: string;
  region: NudgeRegionAvailable | null;
  preview: Vec2 | null;
  message: string;
}
export interface NudgeController extends NudgeState {
  enabled: boolean;
  choose: (instanceId: string) => void;
  prepare: () => void;
  begin: (instanceId: string) => boolean;
  move: (desired: Vec2) => void;
  end: () => void;
  cancel: () => void;
  retryCurrent: () => void;
}

export function useNudge(design: SolvedDesign | null, onDesignChange: (design: SolvedDesign) => void, lock: MutationLock): NudgeController {
  const session = design?.swap?.status === 'available' ? design.swap : null;
  const identity = session ? `${session.sessionId}:${session.version}` : '';
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const sequence = useRef(0);
  const requestAbort = useRef<AbortController | null>(null);
  const expiresAt = useRef(0);
  const initial: NudgeState = { status: 'idle', instanceId: design?.placements[0]?.instanceId ?? '', region: null, preview: null, message: '' };
  const [state, setState] = useState<NudgeState>(initial);
  const stateRef = useRef(state);
  const publish = (next: NudgeState) => { stateRef.current = next; setState(next); };

  useEffect(() => {
    sequence.current += 1;
    requestAbort.current?.abort();
    expiresAt.current = 0;
    publish({ ...initial, instanceId: design?.placements.some((placement) => placement.instanceId === stateRef.current.instanceId)
      ? stateRef.current.instanceId : initial.instanceId });
    lock.release('nudge');
    return () => { sequence.current += 1; requestAbort.current?.abort(); lock.release('nudge'); };
  }, [identity]);

  const cancel = () => {
    if (stateRef.current.status === 'committing' || stateRef.current.status === 'reconciling' || stateRef.current.status === 'blocked') return;
    sequence.current += 1;
    requestAbort.current?.abort();
    expiresAt.current = 0;
    publish({ ...stateRef.current, status: 'idle', region: null, preview: null, message: 'Nudge cancelled. The confirmed Design is restored.' });
    lock.release('nudge');
  };

  useEffect(() => {
    if (!state.region || !['ready', 'dragging', 'clamped'].includes(state.status)) return;
    const timer = window.setTimeout(() => {
      if (identityRef.current !== identity) return;
      publish({ ...stateRef.current, status: 'error', region: null, preview: null, message: 'Safe movement expired. Prepare Nudge again.' });
      lock.release('nudge');
    }, Math.max(0, expiresAt.current - performance.now()));
    return () => window.clearTimeout(timer);
  }, [state.region, state.status, identity]);

  const reconcile = async () => {
    if (!session) return;
    const ownedIdentity = identity;
    publish({ ...stateRef.current, status: 'reconciling', region: null, preview: null, message: 'Recovering the confirmed Design…' });
    try {
      const result = await fetchCurrentSwapSession(session.sessionId);
      if (identityRef.current !== ownedIdentity) return;
      if (result.status === 'current') {
        onDesignChange(result.design);
        publish({ ...stateRef.current, status: 'idle', region: null, preview: null, message: `Confirmed Design version ${result.version} restored.` });
        lock.release('nudge');
      } else {
        publish({ ...stateRef.current, status: 'blocked', message: 'detail' in result ? result.detail : 'The current Design response is incomplete. Retry.' });
      }
    } catch {
      if (identityRef.current !== ownedIdentity) return;
      publish({ ...stateRef.current, status: 'blocked', message: 'Current Design could not be recovered. Retry before making another change.' });
    }
  };

  const prepare = async () => {
    const instanceId = stateRef.current.instanceId;
    if (!session || !instanceId || !lock.acquire('nudge')) return;
    const ownedIdentity = identity;
    const requestSequence = ++sequence.current;
    requestAbort.current?.abort();
    const abort = new AbortController();
    requestAbort.current = abort;
    // TTL begins conservatively at request start, including network latency.
    const requestedAt = performance.now();
    publish({ ...stateRef.current, status: 'pending', region: null, preview: null, message: 'Preparing safe movement…' });
    try {
      const result = await fetchNudgeRegion(session.sessionId, session.version, instanceId, abort.signal);
      if (abort.signal.aborted || identityRef.current !== ownedIdentity || sequence.current !== requestSequence) return;
      if (result.status === 'available' && result.sessionId === session.sessionId && result.version === session.version
        && result.instanceId === instanceId && validNudgeRegion(result)) {
        const placement = design?.placements.find((value) => value.instanceId === instanceId);
        if (!placement || result.origin[0] !== placement.position[0] || result.origin[1] !== placement.position[2]
          || result.fixedY !== placement.position[1] || result.fixedYaw !== placement.yaw) throw new Error('Safe movement does not match the confirmed Placement.');
        expiresAt.current = requestedAt + result.expiresInMs;
        if (expiresAt.current <= performance.now()) throw new Error('Safe movement expired in transit. Prepare Nudge again.');
        publish({ status: 'ready', instanceId, region: result, preview: null, message: 'Drag this Product in the Room. Release to save, or cancel.' });
      } else if (result.status === 'stale-version') {
        await reconcile();
      } else {
        publish({ ...stateRef.current, status: 'unavailable', region: null, preview: null,
          message: result.status === 'available' ? 'The safe movement response is malformed. Retry.' : result.detail });
        lock.release('nudge');
      }
    } catch (cause) {
      if (abort.signal.aborted || identityRef.current !== ownedIdentity || sequence.current !== requestSequence) return;
      publish({ ...stateRef.current, status: 'error', region: null, preview: null, message: cause instanceof Error ? cause.message : 'Safe movement could not be prepared. Retry.' });
      lock.release('nudge');
    }
  };

  const begin = (instanceId: string) => {
    const current = stateRef.current;
    if (current.status !== 'ready' || !current.region || current.instanceId !== instanceId || performance.now() >= expiresAt.current) return false;
    publish({ ...current, status: 'dragging', preview: current.region.origin, message: 'Safe preview. Release to save.' });
    return true;
  };
  const move = (desired: Vec2) => {
    const current = stateRef.current;
    if (!current.region || !current.preview || !['dragging', 'clamped'].includes(current.status)) return;
    if (performance.now() >= expiresAt.current) {
      publish({ ...current, status: 'error', region: null, preview: null, message: 'Safe movement expired. Prepare Nudge again.' });
      lock.release('nudge');
      return;
    }
    const result = clipNudgeSegment(current.region, current.preview, desired);
    publish({ ...current, preview: result.point, status: result.clamped ? 'clamped' : 'dragging',
      message: result.clamped ? 'Safe limit reached. Release to save this position.' : 'Safe preview. Release to save.' });
  };
  const end = async () => {
    const current = stateRef.current;
    if (!session || !current.region || !current.preview || !['dragging', 'clamped'].includes(current.status)) return;
    const target = current.preview;
    const region = current.region;
    if (performance.now() >= expiresAt.current) {
      publish({ ...current, status: 'error', region: null, preview: null, message: 'Safe movement expired. The confirmed Design is restored.' });
      lock.release('nudge');
      return;
    }
    if (Math.hypot(target[0] - region.origin[0], target[1] - region.origin[1]) < 1e-6) { cancel(); return; }
    const ownedIdentity = identity;
    publish({ ...current, status: 'committing', region: null, preview: null, message: 'Saving Nudge… The confirmed Design stays visible.' });
    try {
      const result = await submitNudge({ sessionId: session.sessionId, expectedVersion: session.version,
        instanceId: current.instanceId, regionId: region.regionId, target });
      if (identityRef.current !== ownedIdentity) return;
      if (result.status === 'accepted') {
        onDesignChange(result.design);
        publish({ ...stateRef.current, status: 'idle', message: result.detail });
        lock.release('nudge');
      } else if (result.status === 'stale-version') {
        await reconcile();
      } else {
        publish({ ...stateRef.current, status: 'error', message: result.detail });
        lock.release('nudge');
      }
    } catch {
      if (identityRef.current !== ownedIdentity) return;
      await reconcile();
    }
  };
  return { ...state, enabled: ['ready', 'dragging', 'clamped'].includes(state.status),
    choose: (instanceId) => { if (lock.heldBy('swap')) return; cancel(); publish({ ...stateRef.current, instanceId, message: '' }); },
    prepare, begin, move, end, cancel, retryCurrent: reconcile };
}
