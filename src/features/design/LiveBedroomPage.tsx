import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { fetchLiveBedroomConfig, generateLiveBedroom } from '@/shared/api/client';
import type { LiveBedroomConfig, LiveGenerationFailure, LiveGenerationSuccess, SolvedDesign } from '@/shared/api/types';
import { RoomStage } from './RoomStage';
import { clearSceneDebug } from './scene-debug';
import { SwapControls } from './SwapControls';
import './design.css';

type RequestState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'client-error'; message: string }
  | { status: 'failed'; failure: LiveGenerationFailure }
  | { status: 'solved'; success: LiveGenerationSuccess; receivedAtMs: number };

export default function LiveBedroomPage() {
  const [config, setConfig] = useState<LiveBedroomConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [referenceId, setReferenceId] = useState('');
  const [roomType, setRoomType] = useState('');
  const [requestState, setRequestState] = useState<RequestState>({ status: 'idle' });
  const controllerRef = useRef<AbortController | null>(null);
  const sequenceRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    fetchLiveBedroomConfig(controller.signal).then((value) => {
      if (current && !controller.signal.aborted) setConfig(value);
    }).catch((cause: unknown) => {
      if (current && !controller.signal.aborted) {
        setConfigError(cause instanceof Error ? cause.message : 'Unable to load live generation choices.');
      }
    });
    return () => { current = false; controller.abort(); };
  }, []);

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
    if (!referenceId || roomType !== 'bedroom') return;
    const sequence = sequenceRef.current + 1;
    sequenceRef.current = sequence;
    controllerRef.current?.abort();
    clearSceneDebug();
    const controller = new AbortController();
    controllerRef.current = controller;
    setRequestState({ status: 'loading' });
    try {
      const { result, receivedAtMs } = await generateLiveBedroom(referenceId, controller.signal);
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
      <h1>Live bedroom choices are unavailable.</h1>
      <p role="alert">{configError}</p>
      <Link to="/design">Return to fixture preview</Link>
    </main>
  );
  if (!config) return <main className="stage-placeholder" role="status">Loading image choices…</main>;

  const selected = config.references.find((reference) => reference.id === referenceId);
  const failure = requestState.status === 'failed' ? requestState.failure : null;
  const clientError = requestState.status === 'client-error' ? requestState.message : null;
  const installSwappedDesign = (design: SolvedDesign) => {
    setRequestState((current) => {
      if (current.status !== 'solved') return current;
      const currentSession = current.success.design.swap;
      const nextSession = design.swap;
      if (currentSession?.status !== 'available' || nextSession?.status !== 'available'
        || currentSession.sessionId !== nextSession.sessionId) return current;
      return { ...current, success: { ...current.success, design } };
    });
  };
  return (
    <main className="layout live-layout" data-testid="live-bedroom">
      {requestState.status === 'solved' ? (
        <RoomStage
          result={requestState.success.design}
          receivedAtMs={requestState.receivedAtMs}
          generationId={requestState.success.generationId}
        />
      ) : requestState.status === 'loading' ? (
        <section className="stage-placeholder" role="status" data-testid="live-loading">
          <strong>Creating your bedroom Design…</strong>
          <span>Checking furniture fit and walking space.</span>
        </section>
      ) : failure || clientError ? (
        <section className="stage-placeholder live-failure" data-testid="live-failure">
          <strong>{failure?.code === 'no-valid-design' ? 'No bedroom Design fit this Room.' : 'This Design could not be created.'}</strong>
          <span role="alert">{failure?.detail ?? clientError}</span>
          <button type="button" onClick={generate}>Retry this generation</button>
        </section>
      ) : (
        <section className="stage-placeholder live-empty" data-testid="live-idle">
          <strong>Choose an image and Bedroom to begin.</strong>
          <span>Your furnished Design will appear here.</span>
        </section>
      )}

      <aside className="panel live-panel">
        <Link className="home-link" to="/design">← Fixture preview</Link>
        <p className="eyebrow">Live bedroom</p>
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
        </fieldset>

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
          disabled={!config.realCallsEnabled || !referenceId || roomType !== 'bedroom' || requestState.status === 'loading'}
          onClick={generate}
        >
          {requestState.status === 'loading' ? 'Generating…' : 'Generate bedroom'}
        </button>
        {!config.realCallsEnabled ? <p className="warning" role="status">Generation is not available right now.</p> : null}

        {requestState.status === 'solved' ? (
          <SwapControls design={requestState.success.design} onDesignChange={installSwappedDesign} />
        ) : null}

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
