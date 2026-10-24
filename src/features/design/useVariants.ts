import { useCallback, useEffect, useRef, useState } from 'react';
import { streamVariants } from '@/shared/api/client';
import type { SolvedDesign } from '@/shared/api/types';
import { acceptVariantEvent, emptyVariants, installVariantDesign, type Label } from './variant-state';
import { clearSceneDebug } from './scene-debug';

export function useVariants() {
  const [state, setState] = useState(emptyVariants);
  const sequence = useRef(0), active = useRef<AbortController | null>(null);
  const clear = useCallback(() => {
    active.current?.abort(); const key = ++sequence.current;
    clearSceneDebug(); setState(emptyVariants(key));
  }, []);
  useEffect(() => () => { ++sequence.current; active.current?.abort(); clearSceneDebug(); }, []);
  const start = async (path: string, body: unknown, privateRoom = false) => {
    active.current?.abort(); const key = ++sequence.current, abort = new AbortController(); active.current = abort;
    clearSceneDebug(); setState({ ...emptyVariants(key), status: 'running', message: 'Preparing the confirmed Room Shell…' });
    try {
      await streamVariants(path, body, event => {
        if (!abort.signal.aborted && key === sequence.current) setState(current => acceptVariantEvent(current, key, event, performance.now()));
      }, abort.signal, privateRoom);
    } catch (error) {
      if (!abort.signal.aborted && key === sequence.current) setState(current => ({ ...current, status: 'interrupted', message: error instanceof Error ? error.message : 'Generation was interrupted. Available Variants are retained.' }));
    }
  };
  const stop = () => {
    active.current?.abort(); ++sequence.current;
    setState(current => ({ ...current, status: 'stopped', message: 'Generation stopped. Available Variants are retained.' }));
  };
  const select = (label: Label) => setState(current => current.variants[label] && label !== current.selected ? { ...current, selected: label, visit: current.visit + 1 } : current);
  const ownedSession = state.variants[state.selected]?.result.design.swap;
  const sessionId = ownedSession?.status === 'available' ? ownedSession.sessionId : null;
  const installDesign = useCallback((design: SolvedDesign) => {
    if (sessionId && design.swap?.status === 'available' && design.swap.sessionId === sessionId)
      setState(current => installVariantDesign(current, state.key, design));
  }, [state.key, sessionId]);
  return { state, start, clear, stop, select, installDesign, selected: state.variants[state.selected], running: state.status === 'running' };
}
