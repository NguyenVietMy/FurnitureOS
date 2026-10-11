import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchCurrentSwapSession, fetchSwapCandidates, submitSwap } from '@/shared/api/client';
import type { Product, SolvedDesign, SwapCandidateResult } from '@/shared/api/types';

type MutationState =
  | { status: 'idle'; message?: string }
  | { status: 'pending' }
  | { status: 'reconciling' }
  | { status: 'stale'; message: string }
  | { status: 'blocked'; message: string };

interface CandidateRequest {
  instanceId: string;
  requestId: number;
  sessionId: string;
  version: number;
}

function dimensions(product: Product): string {
  const value = product.dimensionsM;
  return `${value.widthM.toFixed(2)} × ${value.depthM.toFixed(2)} × ${value.heightM.toFixed(2)} m`;
}

export function SwapControls({
  design,
  onDesignChange,
}: {
  design: SolvedDesign;
  onDesignChange: (design: SolvedDesign) => void;
}) {
  const session = design.swap?.status === 'available' ? design.swap : null;
  const [instanceId, setInstanceId] = useState('');
  const [candidateId, setCandidateId] = useState('');
  const [candidateResult, setCandidateResult] = useState<SwapCandidateResult | null>(null);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateRequest, setCandidateRequest] = useState<CandidateRequest | null>(null);
  const [mutation, setMutation] = useState<MutationState>({ status: 'idle' });
  const candidateRequestSequence = useRef(0);
  const sessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    const ownedSessionId = session?.sessionId ?? null;
    sessionIdRef.current = ownedSessionId;
    return () => {
      if (sessionIdRef.current === ownedSessionId) sessionIdRef.current = null;
    };
  }, [session?.sessionId]);

  useEffect(() => {
    setInstanceId(design.placements[0]?.instanceId ?? '');
  }, [session?.sessionId]);

  useEffect(() => {
    setCandidateRequest(null);
    setCandidateLoading(false);
    setCandidateId('');
    setCandidateResult(null);
    setCandidateError(null);
  }, [session?.sessionId, session?.version]);

  useEffect(() => {
    setMutation({ status: 'idle' });
  }, [session?.sessionId]);

  useEffect(() => {
    if (!session || !candidateRequest
      || candidateRequest.sessionId !== session.sessionId
      || candidateRequest.version !== session.version
      || candidateRequest.instanceId !== instanceId) return;
    const controller = new AbortController();
    setCandidateLoading(true);
    setCandidateError(null);
    setCandidateResult(null);
    setCandidateId('');
    fetchSwapCandidates(
      candidateRequest.sessionId,
      candidateRequest.version,
      candidateRequest.instanceId,
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted || sessionIdRef.current !== session.sessionId) return;
        setCandidateResult(result);
        if (result.status === 'candidates') {
          setCandidateId(result.candidates[0]?.product.id ?? '');
        } else if (result.status === 'stale-version') {
          setMutation({ status: 'stale', message: result.detail });
        } else if (result.status === 'catalogue-changed' || result.status === 'expired-session' || result.status === 'unknown-session') {
          setMutation({ status: 'blocked', message: result.detail });
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted && sessionIdRef.current === session.sessionId) {
          setCandidateError(cause instanceof Error ? cause.message : 'Compatible Products could not be checked.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && sessionIdRef.current === session.sessionId) setCandidateLoading(false);
      });
    return () => controller.abort();
  }, [candidateRequest, instanceId, session?.sessionId, session?.version]);

  const selectedProduct = useMemo(() => {
    if (candidateResult?.status !== 'candidates') return null;
    return candidateResult.candidates.find((candidate) => candidate.product.id === candidateId)?.product ?? null;
  }, [candidateId, candidateResult]);

  if (!design.swap) return null;
  if (design.swap.status === 'unavailable') return (
    <section className="swap-controls" data-testid="swap-unavailable">
      <p className="eyebrow">Swap Product</p>
      <h2>Swap unavailable</h2>
      <p role="status">{design.swap.detail}</p>
    </section>
  );
  if (!session) return null;

  const locked = mutation.status === 'pending' || mutation.status === 'reconciling'
    || mutation.status === 'stale' || mutation.status === 'blocked';

  const reconcile = async (ownedSessionId: string) => {
    if (sessionIdRef.current !== ownedSessionId) return;
    setMutation({ status: 'reconciling' });
    try {
      const current = await fetchCurrentSwapSession(ownedSessionId);
      if (sessionIdRef.current !== ownedSessionId) return;
      if (current.status === 'current') {
        onDesignChange(current.design);
        setMutation({ status: 'idle', message: `Current Design version ${current.version} restored.` });
      } else {
        setMutation({ status: 'blocked', message: 'detail' in current ? current.detail : 'The current Design could not be recovered.' });
      }
    } catch (cause: unknown) {
      if (sessionIdRef.current !== ownedSessionId) return;
      setMutation({
        status: 'blocked',
        message: cause instanceof Error ? cause.message : 'The current Design could not be recovered.',
      });
    }
  };

  const swap = async () => {
    if (!session || !instanceId || !candidateId || locked) return;
    const ownedSessionId = session.sessionId;
    setMutation({ status: 'pending' });
    try {
      const result = await submitSwap({
        sessionId: ownedSessionId,
        expectedVersion: session.version,
        instanceId,
        replacementProductId: candidateId,
      });
      if (sessionIdRef.current !== ownedSessionId) return;
      if (result.status === 'accepted') {
        onDesignChange(result.design);
        setMutation({ status: 'idle', message: result.detail });
      } else if (result.status === 'stale-version') {
        setMutation({ status: 'stale', message: result.detail });
      } else if (result.status === 'catalogue-changed' || result.status === 'expired-session' || result.status === 'unknown-session') {
        setMutation({ status: 'blocked', message: result.detail });
      } else {
        setMutation({ status: 'idle', message: result.detail });
      }
    } catch {
      if (sessionIdRef.current !== ownedSessionId) return;
      // The server may have committed before the response was lost. A current
      // read is mandatory before another mutation is enabled.
      await reconcile(ownedSessionId);
    }
  };

  const placementOptions = design.placements.map((placement, index) => ({
    instanceId: placement.instanceId ?? design.intents[index]?.id ?? `placement-${index + 1}`,
    product: design.products[index]!,
  }));
  const rejected = candidateResult && 'rejected' in candidateResult ? candidateResult.rejected ?? [] : [];
  const changeInstance = (nextInstanceId: string) => {
    setInstanceId(nextInstanceId);
    setCandidateRequest(null);
    setCandidateLoading(false);
    setCandidateId('');
    setCandidateResult(null);
    setCandidateError(null);
  };
  const requestCandidates = () => {
    if (!session || !instanceId || locked || candidateLoading) return;
    candidateRequestSequence.current += 1;
    setCandidateError(null);
    setCandidateRequest({
      instanceId,
      requestId: candidateRequestSequence.current,
      sessionId: session.sessionId,
      version: session.version,
    });
  };
  return (
    <section className="swap-controls" data-testid="swap-controls" data-session-id={session.sessionId} data-version={session.version}>
      <p className="eyebrow">Swap Product</p>
      <h2>Keep the pose, change the Product</h2>
      <p className="subtle">Every choice is checked against the complete Design before it is accepted.</p>

      <label className="swap-field">
        <span>Placement</span>
        <select
          aria-label="Placement to Swap"
          value={instanceId}
          disabled={locked}
          onChange={(event) => changeInstance(event.target.value)}
        >
          {placementOptions.map((option) => (
            <option key={option.instanceId} value={option.instanceId}>
              {option.product.displayName} — {option.instanceId}
            </option>
          ))}
        </select>
      </label>

      {!candidateResult ? (
        <button
          className="swap-check-button"
          type="button"
          disabled={locked || candidateLoading || !instanceId}
          onClick={requestCandidates}
        >
          {candidateLoading ? 'Checking compatible Products…' : candidateError ? 'Retry compatible Products' : 'Check compatible Products'}
        </button>
      ) : null}
      {candidateLoading ? <p role="status">Checking compatible Products…</p> : null}
      {candidateError ? <p className="warning" role="alert">{candidateError}</p> : null}
      {candidateResult?.status === 'candidates' ? (
        <label className="swap-field">
          <span>Compatible Product</span>
          <select
            aria-label="Compatible Product"
            value={candidateId}
            disabled={locked}
            onChange={(event) => setCandidateId(event.target.value)}
          >
            {candidateResult.candidates.map((candidate) => (
              <option key={candidate.product.id} value={candidate.product.id}>
                {candidate.product.displayName} — {dimensions(candidate.product)}
              </option>
            ))}
          </select>
        </label>
      ) : candidateResult?.status === 'no-compatible-candidates' ? (
        <p role="status" data-testid="swap-empty">{candidateResult.detail}</p>
      ) : candidateResult && candidateResult.status !== 'stale-version' ? (
        <p className="warning" role="alert">{candidateResult.detail}</p>
      ) : null}

      {selectedProduct ? (
        <p className="swap-choice" data-testid="swap-choice">
          <strong>{selectedProduct.displayName}</strong><br />{dimensions(selectedProduct)}
        </p>
      ) : null}
      {rejected.length ? (
        <details className="technical-details swap-rejections">
          <summary>Why other same-role Products do not fit</summary>
          <ul>{rejected.map((item) => <li key={item.product.id}><strong>{item.product.displayName}:</strong> {item.detail}</li>)}</ul>
        </details>
      ) : null}

      <button
        className="swap-button"
        type="button"
        disabled={!candidateId || candidateResult?.status !== 'candidates' || locked}
        onClick={swap}
      >
        {mutation.status === 'pending' ? 'Validating Swap…' : mutation.status === 'reconciling' ? 'Recovering current Design…' : 'Swap Product'}
      </button>
      {mutation.status === 'stale' ? (
        <p className="swap-feedback" role="alert">
          {mutation.message}{' '}
          <button type="button" onClick={() => reconcile(session.sessionId)}>Refresh current Design</button>
        </p>
      ) : mutation.status === 'blocked' ? (
        <p className="swap-feedback" role="alert">
          {mutation.message}{' '}
          <button type="button" onClick={() => reconcile(session.sessionId)}>Retry current Design</button>
        </p>
      ) : mutation.status === 'pending' || mutation.status === 'reconciling' ? (
        <p className="swap-feedback" role="status">{mutation.status === 'pending' ? 'The current Design stays visible while validation runs.' : 'Confirming the server’s current Design before another Swap.'}</p>
      ) : mutation.message ? <p className="swap-feedback" role="status">{mutation.message}</p> : null}
    </section>
  );
}
