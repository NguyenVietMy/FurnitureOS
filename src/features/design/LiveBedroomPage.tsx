import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import { fetchLiveBedroomConfig, fetchLiveDesignConfig } from '@/shared/api/client';
import type { LiveDesignConfig } from '@/shared/api/types';
import { useVariants } from './useVariants';
import { VariantControls } from './VariantControls';
import { VariantDesign } from './VariantDesign';
import { ShellStage } from './RoomStage';
import './design.css';

export default function LiveBedroomPage({ bedroomOnly = false }: { bedroomOnly?: boolean }) {
  const [config, setConfig] = useState<LiveDesignConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [referenceId, setReferenceId] = useState('');
  const [roomType, setRoomType] = useState<'' | 'bedroom' | 'living-room'>('');
  const roomLabel = roomType === 'living-room' ? 'living room' : 'bedroom';
  const configRoomType = bedroomOnly ? 'bedroom' : roomType || 'bedroom';
  const flow = useVariants();
  const roomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (flow.state.status !== 'idle') roomRef.current?.scrollIntoView({ block: 'start', behavior: 'auto' });
  }, [flow.state.key, flow.state.selected, Boolean(flow.state.shell), Boolean(flow.selected)]);
  const clearGeneration = flow.clear;
  const current = flow.selected;
  const generate = () => { if (roomType && referenceId) void flow.start(bedroomOnly ? '/api/live-bedroom/variants' : '/api/live-design/variants', { roomType, referenceId }); };
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
  const failure = flow.state.failure;
  const clientError = !flow.running && !current && flow.state.status !== 'idle' ? flow.state.message : null;
  return (
    <main className="layout live-layout" data-testid="live-bedroom">
      <div className="variant-workspace" ref={roomRef}>
        {current ? <VariantDesign key={`${flow.state.key}:${flow.state.selected}:${flow.state.visit}`} design={current.result.design}
          generationId={`${flow.state.generationId}:${flow.state.selected}`} receivedAtMs={current.receivedAtMs} installDesign={flow.installDesign} controls={<VariantControls flow={flow} />} />
        : failure || clientError ? <section className="stage-placeholder live-failure" data-testid="live-failure">
          <strong>{failure?.code === 'no-valid-design' ? `No ${roomLabel} Design fit this Room.` : 'This Design could not be created.'}</strong>
          <span role="alert">{failure?.detail ?? clientError}</span><button type="button" onClick={generate}>Retry this generation</button></section>
        : flow.state.shell ? <ShellStage room={flow.state.shell} />
        : flow.running ? <section className="stage-placeholder" role="status" data-testid="live-loading"><strong>Creating your {roomLabel} Design…</strong><span>Preparing the Room Shell.</span></section>
        : <section className="stage-placeholder live-empty" data-testid="live-idle"><strong>Choose an image and Room Type to begin.</strong><span>Your furnished Design will appear here.</span></section>}
        {!current && <VariantControls flow={flow} />}
      </div>

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
          disabled={!config.realCallsEnabled || (!bedroomOnly && config.roomType !== roomType) || !referenceId || !roomType || flow.running}
          onClick={generate}
        >
          {flow.running ? 'Generating…' : !bedroomOnly && !roomType ? 'Generate Design' : `Generate ${roomLabel}`}
        </button>
        {!config.realCallsEnabled ? <p className="warning" role="status">Generation is not available right now.</p> : null}

        {current && roomType === 'living-room' ? <section aria-label="Seating Zones"><h2>Seating Zones</h2><p>Server-offered areas; these offers do not guarantee that a seating group fits.</p><ul>{current.result.design.zones?.map(zone => <li key={zone.id}>{zone.label}: {(zone.bounds.maxX-zone.bounds.minX).toFixed(2)} m wide × {(zone.bounds.maxZ-zone.bounds.minZ).toFixed(2)} m deep</li>)}</ul></section> : null}
        {current || failure ? <details className="technical-details generation-details"><summary>Generation details</summary><dl className="rows">
          <div><dt>Generation ID</dt><dd className="break">{flow.state.generationId}</dd></div>
          <div><dt>Provider calls for this Variant</dt><dd>{current?.result.providerCalls ?? failure?.providerCalls}</dd></div>
        </dl></details> : null}
      </aside>
    </main>
  );
}
