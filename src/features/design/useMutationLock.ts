import { useCallback, useMemo, useRef, useState } from 'react';
import type { SolvedDesign } from '@/shared/api/types';

type Owner = 'swap' | 'nudge' | 'save';
export interface MutationLock {
  owner: Owner | null;
  acquire: (owner: Owner) => boolean;
  release: (owner: Owner) => void;
  heldBy: (owner: Owner) => boolean;
}

/** One immediate lease prevents sibling controls racing between React frames. */
export function useMutationLock(sessionId: string | null): MutationLock {
  const lease = useRef<{ sessionId: string | null; owner: Owner | null }>({ sessionId, owner: null });
  const [state, setState] = useState(lease.current);
  if (lease.current.sessionId !== sessionId) lease.current = { sessionId, owner: null };
  const acquire = useCallback((owner: Owner) => {
    if (!sessionId || lease.current.sessionId !== sessionId || lease.current.owner !== null) return false;
    lease.current = { sessionId, owner };
    setState(lease.current);
    return true;
  }, [sessionId]);
  const release = useCallback((owner: Owner) => {
    if (lease.current.sessionId !== sessionId || lease.current.owner !== owner) return;
    lease.current = { sessionId, owner: null };
    setState(lease.current);
  }, [sessionId]);
  const heldBy = useCallback((owner: Owner) => lease.current.sessionId === sessionId && lease.current.owner === owner, [sessionId]);
  return useMemo(() => ({ owner: state.sessionId === sessionId ? state.owner : null, acquire, release, heldBy }), [state, sessionId, acquire, release, heldBy]);
}

/** Both pages accept mutations/reconciliation only from their current session. */
export function ownsNewerDesign(current: SolvedDesign, next: SolvedDesign): boolean {
  return current.swap?.status === 'available' && next.swap?.status === 'available'
    && current.swap.sessionId === next.swap.sessionId && next.swap.version >= current.swap.version;
}
