import { StrictMode, useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MeshPreview } from './MeshPreview';
import type { Candidate, Mutation, State } from './types';
import './style.css';

function App() {
  const [state, setState] = useState<State | null>(null), [error, setError] = useState('');
  const [pending, setPending] = useState(false), [remaining, setRemaining] = useState('');
  const remainingDirty = useRef(false);
  const stateRef = useRef(state), pendingRef = useRef(false);
  const read = useCallback(async () => {
    const response = await fetch('/api/state');
    const value = await response.json();
    if (!response.ok) throw new Error(value.error);
    if (stateRef.current && value.revision < stateRef.current.revision) return;
    stateRef.current = value; setState(value);
  }, []);
  useEffect(() => {
    read().catch((e: Error) => setError(e.message));
    const timer = setInterval(() => { if (!pendingRef.current) read().catch((e: Error) => setError(e.message)); }, 800);
    return () => clearInterval(timer);
  }, [read]);
  useEffect(() => {
    if (!remainingDirty.current) setRemaining(state?.sample.remainingCandidates?.toString() ?? '');
  }, [state?.sample.remainingCandidates]);
  const mutate = useCallback(async (operation: Mutation) => {
    const current = stateRef.current;
    if (!current || pendingRef.current) return;
    pendingRef.current = true; setPending(true); setError('');
    try {
      const response = await fetch('/api/mutate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Curator-Token': current.token }, body: JSON.stringify({ ...operation, revision: current.revision, opId: crypto.randomUUID() }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      stateRef.current = { ...result.state, token: current.token }; setState(stateRef.current);
    } catch (e) { setError((e as Error).message); await read().catch(() => {}); }
    finally { pendingRef.current = false; setPending(false); }
  }, [read]);
  const tags = useCallback((candidate: Candidate, kind: 'styles' | 'rooms', value: string) => {
    const values = candidate[kind].includes(value) ? candidate[kind].filter((s) => s !== value) : [...candidate[kind], value];
    void mutate({ type: 'tags', productId: candidate.productId, styles: candidate.styles, rooms: candidate.rooms, [kind]: values });
  }, [mutate]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target;
      if (!(target instanceof HTMLElement) || event.repeat || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || target.closest('input,select,textarea,button,a,[contenteditable]:not([contenteditable="false"]),[role="button"]')) return;
      const s = stateRef.current, candidate = s?.candidates?.[s.cursor ?? 0];
      if (!s || !candidate || pendingRef.current) return;
      const key = event.key.toLowerCase();
      if (key === '[' || key === ']') { event.preventDefault(); void mutate({ type: 'navigate', cursor: ((s.cursor ?? 0) + (key === '[' ? s.freeze.count - 1 : 1)) % s.freeze.count }); return; }
      if (s.busy || (s.actor !== 'automated' && s.sample.status !== 'ACTIVE')) return;
      if (key === 'u') { event.preventDefault(); void mutate({ type: 'undo' }); }
      if (key === 'a' || key === 'r') { event.preventDefault(); void mutate({ type: key === 'a' ? 'accept' : 'reject', productId: candidate.productId }); }
      if (candidate.decision) return;
      if (/^[1-5]$/.test(key)) { const style = s.styles?.[Number(key) - 1]; if (style) { event.preventDefault(); tags(candidate, 'styles', style.id); } }
      if (key === 'b' || key === 'l') { if (key === 'b' && s.freeze.purpose) return; event.preventDefault(); tags(candidate, 'rooms', key === 'b' ? 'bedroom' : 'living-room'); }
    };
    window.addEventListener('keydown', handler); return () => window.removeEventListener('keydown', handler);
  }, [mutate, tags]);
  const exportReport = async () => {
    try {
      const response = await fetch('/api/report'); if (!response.ok) throw new Error('Report export failed');
      const blob = await response.blob(), url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = `product-curation-${state?.actor}-${state?.sample.status}.json`; link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError((e as Error).message); }
  };
  const skipLink = <a className="skip-link" href="#curator-main">Skip to curator content</a>;
  if (!state) return <>{skipLink}<main id="curator-main" tabIndex={-1}><h1>Product curator</h1><p role="status">{error || 'Opening local workspace…'}</p></main></>;
  const candidate = state.candidates?.[state.cursor ?? 0];
  const owner = state.actor === 'owner', reviewer = state.actor !== 'automated', review = !reviewer || state.sample.status === 'ACTIVE';
  const blocked = pending || state.busy || !review;
  const accepted = state.candidates?.filter((c) => c.decision === 'accepted').length ?? 0;
  const rejected = state.candidates?.filter((c) => c.decision === 'rejected').length ?? 0;
  return <>
    {skipLink}
    <header><a href="/" className="wordmark">FurnitureOS <span>Local workbench</span></a><span className="actor">{state.actor === 'agent' ? state.evidenceKind === 'genuine-agent-curation' ? 'Genuine agent seed review' : 'Controlled agent simulation' : owner ? state.freeze.purpose ? 'Owner living seed review' : 'Owner sample' : 'Controlled automated workspace'}</span></header>
    <main id="curator-main" tabIndex={-1}>
      <div className="title-row"><div><h1>Product curator</h1><p>Review the Mesh. Keep the source. Make a deliberate selection.</p></div><button onClick={() => void exportReport()}>Export {state.sample.status === 'NOT_STARTED' ? 'UNRUN protocol' : 'report'}</button></div>
      <section className="sample" aria-label="Sample protocol">
        <div><strong>{reviewer ? state.sample.status.replaceAll('_', ' ') : 'Automated evidence only'}</strong>{!state.freeze.purpose && <span className="clock">{(state.sample.elapsedMs / 1000).toFixed(1)} active seconds</span>}<p>{state.protocol}</p>{(state.freeze.reviewerIdentity || state.freeze.ownerIdentity) && <p>Reviewer: {state.freeze.reviewerIdentity ?? state.freeze.ownerIdentity}. Actor: {state.actor}. This seed review is separate from the historical timed20 sample.</p>}<small>Seed SHA256 {state.freeze.seedSha256} · {state.freeze.count} frozen candidates</small></div>
        {reviewer && <div className="sample-controls">
          {state.sample.status === 'NOT_STARTED' && <button className="primary" disabled={pending} onClick={() => void mutate({ type: 'start' })}>{state.freeze.purpose ? 'Start seed review' : 'Start owner sample'}</button>}
          {state.sample.status === 'ACTIVE' && <><button disabled={pending} onClick={() => void mutate({ type: 'pause' })}>{state.freeze.purpose ? 'Pause seed review' : 'Pause sample'}</button><button disabled={pending || state.busy} onClick={() => void mutate({ type: 'finish' })}>{state.freeze.purpose ? 'Finish seed review' : 'Finish sample'}</button></>}
          {state.sample.status === 'PAUSED' && <button className="primary" disabled={pending} onClick={() => void mutate({ type: 'resume' })}>{state.freeze.purpose ? 'Resume seed review' : 'Resume sample'}</button>}
          {!state.freeze.purpose && !['FINISHED', 'INVALID'].includes(state.sample.status) && <label>Remaining candidates (optional)<input type="number" min="0" max="1000000" disabled={pending || state.busy} value={remaining} onChange={(e) => { remainingDirty.current = true; setRemaining(e.target.value); }} onBlur={() => { if (!remainingDirty.current) return; remainingDirty.current = false; const count = remaining === '' ? null : Number(remaining); if (count !== state.sample.remainingCandidates) void mutate({ type: 'estimate', remainingCandidates: count }); }} /></label>}
        </div>}
      </section>
      {error && <p role="alert" className="error">{error}</p>}
      {state.sample.invalidReason && <p role="alert" className="error">{state.sample.invalidReason}</p>}
      {!candidate ? <section className="covered" aria-label="Review covered"><h2>{state.sample.status === 'PAUSED' ? 'Review is paused' : `Ready for ${state.freeze.count} deliberate decisions`}</h2><p>{state.sample.status === 'PAUSED' ? state.freeze.purpose ? 'The Mesh and candidate details are covered. Resume the seed review to continue with retained decisions.' : 'The Mesh and candidate details are covered. Resume to continue; only explicit pauses are excluded from active time.' : state.freeze.purpose ? 'Start the living seed review to reveal actual Meshes. Choose Style and Living room tags and record your judgments. Activity timing does not determine acceptance.' : 'Start explicitly to reveal candidate details and begin timing. Fresh Style and Room Type choices begin empty. These are existing source identities being re-reviewed.'}</p></section> : <>
        <nav aria-label="Candidate navigation" className="queue-nav"><button disabled={pending} onClick={() => void mutate({ type: 'navigate', cursor: ((state.cursor ?? 0) + state.freeze.count - 1) % state.freeze.count })}>[ Previous</button><span><b>{String((state.cursor ?? 0) + 1).padStart(2, '0')}</b> / {state.freeze.count} · {candidate.decision ?? 'Awaiting decision'}</span><button disabled={pending} onClick={() => void mutate({ type: 'navigate', cursor: ((state.cursor ?? 0) + 1) % state.freeze.count })}>Next ]</button></nav>
        <div className="workbench">
          <MeshPreview key={candidate.productId} url={candidate.previewUrl} />
          <aside aria-label="Candidate details and decisions">
            <h2>{candidate.record.displayName}</h2><p>{candidate.record.brand} · {candidate.record.colour}</p>
            {state.freeze.purpose && <label>Suitability, Mesh limitations and Style judgment<textarea key={`${candidate.productId}-${candidate.note ?? ''}`} defaultValue={candidate.note ?? ''} maxLength={2000} disabled={blocked || !!candidate.decision} onBlur={(e) => { if (e.target.value !== (candidate.note ?? '')) void mutate({ type: 'note', productId: candidate.productId, note: e.target.value }); }} /></label>}
            <dl className="dimensions">{(['widthM', 'heightM', 'depthM'] as const).map((key) => <div key={key}><dt>{key.replace('M', '')}</dt><dd>{candidate.dimensions[key].toFixed(3)} m</dd></div>)}</dl>
            <fieldset disabled={blocked || !!candidate.decision}><legend>Private Styles <small>choose at least one</small></legend>{state.styles?.map((style, i) => <label key={style.id}><input type="checkbox" checked={candidate.styles.includes(style.id)} onChange={() => tags(candidate, 'styles', style.id)} /><span>{style.privateName}{state.reviewImages?.filter(image => image.privateStyleId === style.id).map(image => <img className="review-reference" key={image.id} src={image.imageUrl} alt={`${image.label}; Style inspiration`} />)}</span><kbd>{i + 1}</kbd></label>)}</fieldset>
            <fieldset disabled={blocked || !!candidate.decision}><legend>Room Types <small>choose at least one</small></legend>{(state.freeze.purpose ? [['living-room', 'Living room', 'L']] : [['bedroom', 'Bedroom', 'B'], ['living-room', 'Living room', 'L']]).map(([id, name, key]) => <label key={id}><input type="checkbox" checked={candidate.rooms.includes(id!)} onChange={() => tags(candidate, 'rooms', id!)} /><span>{name}</span><kbd>{key}</kbd></label>)}</fieldset>
            <p className="hint">Historical Style suggestions: {candidate.record.privateStyleIds.map((id) => state.styles?.find((s) => s.id === id)?.privateName).join(', ')}. Reference only; never preselected.</p>
            <div className="decisions"><button className="primary" disabled={blocked || !!candidate.decision} onClick={() => void mutate({ type: 'accept', productId: candidate.productId })}>Accept <kbd>A</kbd></button><button disabled={blocked || !!candidate.decision} onClick={() => void mutate({ type: 'reject', productId: candidate.productId })}>Reject <kbd>R</kbd></button><button disabled={blocked || !state.canUndo} onClick={() => void mutate({ type: 'undo' })}>Undo <kbd>U</kbd></button></div>
            {candidate.error && <div className="error" role="alert"><p>{candidate.error}</p><button disabled={blocked} onClick={() => void mutate({ type: 'retry', productId: candidate.productId })}>Retry acceptance</button></div>}
            <p className="disclosure">Purchase availability unknown. ABO license records conflict; commercial rights remain unresolved.</p>
            <details><summary>Source and purchase disclosure</summary><p>Purchase availability unknown. No purchase link has been verified. ABO license records conflict (CC BY 4.0 / CC BY-NC 4.0); commercial rights remain unresolved.</p><p className="mono">Source {candidate.record.itemId}<br />SHA256 {candidate.record.sourceSha256}</p><p>Actual dimensions come from the measured Mesh. Acceptance rebuilds the pinned source and independently validates its bytes.</p></details>
          </aside>
        </div>
        <section className="progress" aria-label="Progress and history"><div><h2>{accepted + rejected === state.freeze.count ? `All ${state.freeze.count} have final decisions` : `${accepted + rejected} / ${state.freeze.count} reviewed`}</h2><p>{accepted} accepted · {rejected} rejected · {state.freeze.count - accepted - rejected} unresolved</p><p>Each tag update is one undo step; each decision is one step. Navigation persists and is never an undo target. Undo returns to the affected candidate. Accepted tags stay locked until undo.</p><p>Sources, previous outputs and failed attempts are retained. Undo removes the logical selection; it never deletes files. Navigation is available during conversion; tag, decision and undo actions wait. Shutdown interrupts acceptance; retry creates a new attempt.</p></div><div className="history"><h3>Attempt progress</h3>{!state.attempts?.length && <p>No attempts yet.</p>}{state.attempts?.slice(-6).reverse().map((a) => <p key={a.id}><strong>{a.productId}</strong><br />{a.status} · {a.stage}{a.durationMs !== undefined ? ` · ${(a.durationMs / 1000).toFixed(1)} s` : ''}</p>)}<details><summary>Event history ({state.history?.length})</summary><ol>{state.history?.slice(-30).reverse().map((e) => <li key={e.revision}>#{e.revision} {e.type} {e.productId ?? e.stage}</li>)}</ol></details></div></section>
      </>}
      <footer>Shortcuts: A accept · R reject · U undo · [ / ] navigate · 1–5 Styles · {state.freeze.purpose ? 'L Room Type' : 'B / L Room Types'}. Native controls keep Space/Enter; shortcuts ignore editing, repeats and modifiers. {state.actor === 'automated' && 'Real owner sample UNRUN.'}</footer>
    </main>
  </>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
