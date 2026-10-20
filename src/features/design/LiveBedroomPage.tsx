import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { fetchLiveBedroomConfig, generateLiveBedroom, fetchLiveDesignConfig, generateLiveDesign } from '@/shared/api/client';
import type { LiveDesignConfig, LiveGenerationFailure, LiveGenerationSuccess, SolvedDesign } from '@/shared/api/types';
import { RoomStage } from './RoomStage';
import { ProductDisclosures } from './ProductDisclosures';
import { clearSceneDebug } from './scene-debug';
import { SwapControls } from './SwapControls';
import { NudgeControls } from './NudgeControls';
import { ownsNewerDesign, useMutationLock } from './useMutationLock';
import { useNudge } from './useNudge';
import './design.css';

type RequestState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'client-error'; message: string }
  | { status: 'failed'; failure: LiveGenerationFailure }
  | { status: 'solved'; success: LiveGenerationSuccess; receivedAtMs: number };

export default function LiveBedroomPage({ bedroomOnly = false }: { bedroomOnly?: boolean }) {
  const [config, setConfig] = useState<LiveDesignConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [referenceId, setReferenceId] = useState('');
  const [roomType, setRoomType] = useState<'' | 'bedroom' | 'living-room'>('');
  const roomLabel = roomType === 'living-room' ? 'living room' : 'bedroom';
  const configRoomType = bedroomOnly ? 'bedroom' : roomType || 'bedroom';
  const [requestState, setRequestState] = useState<RequestState>({ status: 'idle' });
  const controllerRef = useRef<AbortController | null>(null);
  const sequenceRef = useRef(0);
  const solved = requestState.status === 'solved' ? requestState.success.design : null;
  const mutationLock = useMutationLock(solved?.swap?.status === 'available' ? solved.swap.sessionId : null);
  const installDesign = useCallback((design: SolvedDesign) => {
    setRequestState((current) => current.status === 'solved' && ownsNewerDesign(current.success.design, design)
      ? { ...current, success: { ...current.success, design } } : current);
  }, []);
  const nudge = useNudge(solved, installDesign, mutationLock);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setConfigError(null);
    (bedroomOnly ? fetchLiveBedroomConfig(controller.signal) : fetchLiveDesignConfig(configRoomType, controller.signal)).then((value) => {
      if (current && !controller.signal.aborted) setConfig({ ...value, roomType: value.roomType ?? 'bedroom' });
    }).catch((cause: unknown) => {
      if (current && !controller.signal.aborted) {
        setConfigError(cause instanceof Error ? cause.message : 'Unable to load live generation choices.');
      }
    });
    return () => { current = false; controller.abort(); };
  }, [bedroomOnly, configRoomType]);

  useEffect(() => () => {
    controllerRef.current?.abort();
    clearSceneDebug();
  }, []);

  const clearGeneration = () => {
    sequenceRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    clearSceneDebug();
    setRequestState({ status: 'idle' });
  };

  const generate = async () => {
    if (!referenceId || !roomType) return;
    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    controllerRef.current?.abort();
    clearSceneDebug();
    const controller = new AbortController();
    controllerRef.current = controller;
    setRequestState({ status: 'loading' });
    try {
      const { result, receivedAtMs } = await (bedroomOnly ? generateLiveBedroom(referenceId, controller.signal) : generateLiveDesign(roomType, referenceId, controller.signal));
      if (controller.signal.aborted || sequenceRef.current !== sequence) return;
      if (result.status !== 'solved') clearSceneDebug();
      setRequestState(result.status === 'solved'
        ? { status: 'solved', success: result, receivedAtMs }
        : { status: 'failed', failure: result });
    } catch (cause: unknown) {
      if (controller.signal.aborted || sequenceRef.current !== sequence) return;
      clearSceneDebug();
      setRequestState({
        status: 'client-error',
        message: cause instanceof Error ? cause.message : 'The generation response could not be received.',
      });
    }
  };

  if (configError) return (
    <main className="stage-placeholder" data-testid="live-config-error">
      <h1>Live Design choices are unavailable.</h1>
      <p role="alert">{configError}</p>
      <button type="button" onClick={() => window.location.reload()}>Retry choices</button>
      <Link to="/design">Return to fixture preview</Link>
    </main>
  );
  if (!config) return <main className="stage-placeholder" role="status">Loading image choices…</main>;

  const selected = config.references.find((reference) => reference.id === referenceId);
  const failure = requestState.status === 'failed' ? requestState.failure : null;
  const clientError = requestState.status === 'client-error' ? requestState.message : null;
  return (
    <main className="layout live-layout" data-testid="live-bedroom">
      {requestState.status === 'solved' ? (
        <RoomStage
          result={requestState.success.design}
          receivedAtMs={requestState.receivedAtMs}
          generationId={requestState.success.generationId}
          nudge={nudge}
        />
      ) : requestState.status === 'loading' ? (
        <section className="stage-placeholder" role="status" data-testid="live-loading">
          <strong>Creating your {roomLabel} Design…</strong>
          <span>Checking furniture fit and walking space.</span>
        </section>
      ) : failure || clientError ? (
        <section className="stage-placeholder live-failure" data-testid="live-failure">
          <strong>{failure?.code === 'no-valid-design' ? `No ${roomLabel} Design fit this Room.` : 'This Design could not be created.'}</strong>
          <span role="alert">{failure?.detail ?? clientError}</span>
          <button type="button" onClick={generate}>Retry this generation</button>
        </section>
      ) : (
        <section className="stage-placeholder live-empty" data-testid="live-idle">
          <strong>Choose an image and Room Type to begin.</strong>
          <span>Your furnished Design will appear here.</span>
        </section>
      )}

      <aside className="panel live-panel">
        <Link className="home-link" to="/design">← Fixture preview</Link>
        <p className="eyebrow">{bedroomOnly ? "Live bedroom" : "Live Room Design"}</p>
        <h1>Choose the feeling, then generate</h1>
        <p className="subtle">Pick the room image closest to what you like.</p>

        <fieldset className="room-type-fieldset">
          <legend>Room Type</legend>
          <label>
            <input
              type="radio"
              name="room-type"
              value="bedroom"
              checked={roomType === 'bedroom'}
              onChange={() => { setRoomType('bedroom'); clearGeneration(); }}
            />
            Bedroom
          </label>
          {!bedroomOnly && <label><input type="radio" name="room-type" value="living-room" checked={roomType === 'living-room'} onChange={() => { setRoomType('living-room'); clearGeneration(); }} />Living room</label>}
        </fieldset>
        {roomType === 'living-room' && <p className="subtle">One sofa, one coffee table and one chair are required, with an optional second chair, rug and floor lamp. Seating Zones offer places to try; fit and connected walking space are checked for the whole Design. The initial policy requires 0.60 m front access, so tighter familiar arrangements may be unavailable.</p>}

        <fieldset className="reference-fieldset">
          <legend>Style inspiration</legend>
          <div className="reference-grid">
            {config.references.map((reference) => (
              <label key={reference.id} className="reference-choice" data-selected={reference.id === referenceId}>
                <input
                  type="radio"
                  name="reference-image"
                  value={reference.id}
                  checked={reference.id === referenceId}
                  onChange={() => { setReferenceId(reference.id); clearGeneration(); }}
                />
                <img src={reference.imageUrl} alt={reference.label} />
                <span>{reference.label}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {selected ? (
          <p className="reference-credit">
            Photo by <a href={selected.sourceUrl} target="_blank" rel="noreferrer noopener">{selected.creator}</a>{' '}
            under the <a href={selected.licenseUrl} target="_blank" rel="noreferrer noopener">{selected.license}</a>.
          </p>
        ) : null}
        <button
          className="generate-button"
          type="button"
          disabled={!config.realCallsEnabled || (!bedroomOnly && config.roomType !== roomType) || !referenceId || !roomType || requestState.status === 'loading'}
          onClick={generate}
        >
          {requestState.status === 'loading' ? 'Generating…' : !bedroomOnly && !roomType ? 'Generate Design' : `Generate ${roomLabel}`}
        </button>
        {!config.realCallsEnabled ? <p className="warning" role="status">Generation is not available right now.</p> : null}

        {requestState.status === 'solved' && roomType === 'living-room' && <section aria-label="Seating Zones"><h2>Seating Zones</h2><p>Server-offered areas; these offers do not guarantee that a seating group fits.</p><ul>{requestState.success.design.zones?.map(zone => <li key={zone.id}>{zone.label}: {(zone.bounds.maxX-zone.bounds.minX).toFixed(2)} m wide × {(zone.bounds.maxZ-zone.bounds.minZ).toFixed(2)} m deep</li>)}</ul></section>}
        {requestState.status === 'solved' ? (
          <>
            <NudgeControls design={requestState.success.design} nudge={nudge} lock={mutationLock} />
            <SwapControls design={requestState.success.design} onDesignChange={installDesign} mutationLock={mutationLock} />
          </>
        ) : null}

        {requestState.status === 'solved' ? <ProductDisclosures products={requestState.success.design.products} /> : null}

        {requestState.status === 'solved' || failure ? (
          <details className="technical-details generation-details">
            <summary>Generation details</summary>
            <dl className="rows">
              <div><dt>Generation ID</dt><dd className="break">{requestState.status === 'solved' ? requestState.success.generationId : failure?.generationId}</dd></div>
              <div><dt>Model time</dt><dd>{requestState.status === 'solved' ? requestState.success.modelLatencyMs : failure?.modelLatencyMs} ms</dd></div>
              <div><dt>Provider calls</dt><dd>{requestState.status === 'solved' ? requestState.success.providerCalls : failure?.providerCalls}</dd></div>
            </dl>
          </details>
        ) : null}
      </aside>
    </main>
  );
}
