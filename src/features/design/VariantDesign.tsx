import type { SolvedDesign } from '@/shared/api/types';
import type { ReactNode } from 'react';
import { useEffect } from 'react';
import { fetchCurrentSwapSession } from '@/shared/api/client';
import { RoomStage } from './RoomStage';
import { useMutationLock } from './useMutationLock';
import { useNudge } from './useNudge';
import { NudgeControls } from './NudgeControls';
import { SwapControls } from './SwapControls';
import { ProductDisclosures } from './ProductDisclosures';
import { SaveDesign } from '@/features/saved/SaveDesign';

/** A keyed selected workspace resets transient operations on every visit. */
export function VariantDesign({ design, receivedAtMs, generationId, installDesign, controls }: { design: SolvedDesign; receivedAtMs: number; generationId: string; installDesign: (design: SolvedDesign) => void; controls: ReactNode }) {
  const sessionId = design.swap?.status === 'available' ? design.swap.sessionId : null;
  const lock = useMutationLock(sessionId);
  useEffect(() => {
    if (!sessionId) return;
    const abort = new AbortController();
    // A prior visit may have committed before its response reached the browser.
    void fetchCurrentSwapSession(sessionId, abort.signal).then(result => {
      if (!abort.signal.aborted && result.status === 'current') installDesign(result.design);
    }).catch(() => { /* Mutation controls retain their existing explicit recovery. */ });
    return () => abort.abort();
  }, [sessionId, installDesign]);
  const nudge = useNudge(design, installDesign, lock);
  return <><RoomStage result={design} receivedAtMs={receivedAtMs} generationId={generationId} nudge={nudge} />
    {controls}
    <div className="variant-mutations"><NudgeControls design={design} nudge={nudge} lock={lock} />
      <SwapControls design={design} onDesignChange={installDesign} mutationLock={lock} /><SaveDesign design={design} lock={lock} installDesign={installDesign} /><ProductDisclosures products={design.products} /></div></>;
}
