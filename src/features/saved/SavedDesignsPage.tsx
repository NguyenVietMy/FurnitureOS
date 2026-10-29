import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import type { SavedList, SavedReceipt, SavedRestore, SolvedDesign } from '@/shared/api/types';
import { captureRequest, CaptureApiError } from '@/shared/api/client';
import { useOwnerIdentity } from '@/shared/auth/OwnerIdentity';
import { VariantDesign } from '@/features/design/VariantDesign';
import { ownsNewerDesign } from '@/features/design/useMutationLock';
import { IdentityControls } from './IdentityControls';
import { clearPendingSave, readPendingSave } from './SaveDesign';
import '@/features/design/design.css';
import './saved.css';

export default function SavedDesignsPage() {
  const identity = useOwnerIdentity();
  const owner = identity.session?.user.id;
  const { savedId } = useParams();
  const navigate = useNavigate();
  const [listing, setListing] = useState<SavedList>({ items: [] });
  const [restored, setRestored] = useState<SavedRestore | null>(null);
  const [message, setMessage] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [pending, setPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const sequence = useRef(0);
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (message) statusRef.current?.focus(); }, [message]);
  // Clear the previous private scene before an identity transition can paint.
  useLayoutEffect(() => {
    const abort = new AbortController(); active.current?.abort(); active.current = abort;
    const ticket = ++sequence.current;
    setRestored(null); setListing({ items: [] }); setMessage(''); setBusy(false);
    setPending(owner ? Boolean(readPendingSave(owner)) : false);
    if (owner && identity.config?.ready) {
      void captureRequest<SavedList>('/api/saved-designs', 'GET', undefined, abort.signal).then(value => {
        if (!abort.signal.aborted && sequence.current === ticket) setListing(value);
      }).catch(() => { if (!abort.signal.aborted && sequence.current === ticket) setMessage('Saved Designs could not be listed. Retry after refreshing your account.'); });
      if (savedId) void captureRequest<SavedRestore>(`/api/saved-designs/${encodeURIComponent(savedId)}`, 'GET', undefined, abort.signal).then(value => {
        if (!abort.signal.aborted && sequence.current === ticket) setRestored(value);
      }).catch(error => {
        if (!abort.signal.aborted && sequence.current === ticket) setMessage(error instanceof Error ? error.message : 'This saved Design is unavailable.');
      });
    }
    return () => { sequence.current++; abort.abort(); };
  }, [owner, identity.epoch, identity.config?.ready, savedId, attempt]);
  const installDesign = useCallback((design: SolvedDesign) => setRestored(current => current && ownsNewerDesign(current.design, design) ? { ...current, design } : current), []);

  const remove = async (id: string, idempotencyKey: string) => {
    if (!owner) return;
    active.current?.abort(); const abort = new AbortController(); active.current = abort;
    const ticket = ++sequence.current; setBusy(true); setRestored(null);
    if (readPendingSave(owner)?.body.idempotencyKey === idempotencyKey) {
      clearPendingSave(owner, idempotencyKey); setPending(false);
    }
    try {
      await captureRequest(`/api/saved-designs/${id}`, 'DELETE', undefined, abort.signal, owner);
      if (ticket !== sequence.current || abort.signal.aborted) return;
      if (savedId === id) navigate('/saved'); else setAttempt(value => value + 1);
    } catch (error) { if (!abort.signal.aborted && ticket === sequence.current) setMessage(error instanceof Error ? error.message : 'Deletion did not finish. Retry.'); }
    finally { if (ticket === sequence.current) setBusy(false); }
  };
  const retry = async () => {
    if (!owner) return;
    const hint = readPendingSave(owner);
    if (!hint) { setPending(false); setMessage('The pending save expired. Review your saved list. No new save was created.'); return; }
    const abort = new AbortController(); active.current?.abort(); active.current = abort;
    const ticket = ++sequence.current; setBusy(true);
    try {
      const receipt = await captureRequest<SavedReceipt>('/api/saved-designs', 'POST', hint.body, abort.signal, owner);
      if (ticket !== sequence.current || abort.signal.aborted) return;
      clearPendingSave(owner, hint.body.idempotencyKey); setPending(Boolean(readPendingSave(owner))); navigate(`/saved/${receipt.id}`); setAttempt(value => value + 1);
    } catch (error) {
      if (ticket !== sequence.current || abort.signal.aborted) return;
      if (error instanceof CaptureApiError && [410,422].includes(error.status)) { clearPendingSave(owner, hint.body.idempotencyKey); setPending(Boolean(readPendingSave(owner))); }
      setMessage(error instanceof Error ? error.message : 'Save recovery did not finish. Retry.');
    } finally { if (ticket === sequence.current) setBusy(false); }
  };
  const more = async () => {
    if (!listing.nextCursor) return;
    const cursor = listing.nextCursor;
    const ticket = sequence.current;
    try {
      const next = await captureRequest<SavedList>(`/api/saved-designs?cursor=${encodeURIComponent(cursor)}`, 'GET', undefined, active.current?.signal);
      if (sequence.current === ticket) setListing(current => {
        if (current.nextCursor !== cursor) return current;
        const ids = new Set(current.items.map(item => item.id));
        return { items: [...current.items, ...next.items.filter(item => !ids.has(item.id))], nextCursor: next.nextCursor };
      });
    } catch { if (sequence.current === ticket) setMessage('The next page could not be loaded. Retry.'); }
  };
  return <main className="saved-page"><header><Link to="/design">Room preview</Link> · <Link to="/capture">Room Capture</Link><h1>Saved Designs</h1>
    <p>Saved Room and Design metadata remain until you delete each save. Photos keep their original 24-hour expiry. Deleting a Capture leaves its saved copies here.</p>
    <p>Deleting a save erases its content immediately. A minimal retry marker stays for at least 25 hours and cannot reopen the Design. A later new save removes eligible markers, so they may remain longer if you do not save again.</p></header>
    {!identity.config?.ready ? <p role="status">Saving and saved recovery are unavailable right now.</p> : !owner ? <p role="status">Restore your existing account below to see its saved Designs.</p> : <>
      <button disabled={busy} onClick={() => setAttempt(value => value + 1)}>Refresh saved Designs</button>
      {pending ? <div className="saved-pending"><p>A previous save may have committed. Retry the same request or review your list.</p><button disabled={busy} onClick={() => void retry()}>Recover pending save</button><button disabled={busy} onClick={() => { localStorage.removeItem(`furnitureos.saved.pending.${owner}`); setPending(false); }}>Dismiss retry hint</button></div> : null}
      <ul className="saved-list">{listing.items.map(item => <li key={item.id}><Link to={`/saved/${item.id}`}>{item.roomType === 'living-room' ? 'Living room' : 'Bedroom'} · {new Date(item.createdAt).toLocaleString()}</Link>
        {item.captureId ? <span>Confirmed Capture {item.captureId}</span> : null}<button disabled={busy} onClick={() => void remove(item.id, item.idempotencyKey)}>Delete saved Design</button></li>)}</ul>
      {listing.nextCursor ? <button onClick={() => void more()}>Load more saved Designs</button> : null}
      {restored ? <section className="saved-workspace"><h2>Reopened Design</h2>{restored.capture ? <p>Archived confirmed Capture {restored.capture.id}, revision {restored.capture.confirmedRevision}. Original photos are separate.</p> : null}
        <VariantDesign key={`${restored.design.swap?.status === 'available' ? restored.design.swap.sessionId : restored.id}:${identity.epoch}`} design={restored.design} installDesign={installDesign} receivedAtMs={0} generationId={restored.id} controls={null} />
      </section> : null}
    </>}
    {message ? <p role="alert" ref={statusRef} tabIndex={-1}>{message}</p> : null}
    <IdentityControls />
  </main>;
}
