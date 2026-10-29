import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router';
import type { SavedReceipt, SaveRequest, SolvedDesign } from '@/shared/api/types';
import { captureRequest, CaptureApiError, fetchCurrentSwapSession } from '@/shared/api/client';
import { useOwnerIdentity } from '@/shared/auth/OwnerIdentity';
import type { MutationLock } from '@/features/design/useMutationLock';
import './saved.css';

type PendingSave = { version: 1; at: number; body: SaveRequest };
const lifetime = 24 * 60 * 60 * 1000;
export function readPendingSave(owner: string): PendingSave | null {
  const key = `furnitureos.saved.pending.${owner}`;
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? 'null') as PendingSave | null;
    if (value?.version === 1 && Number.isFinite(value.at) && value.at <= Date.now() && Date.now() - value.at < lifetime
        && value.body?.consent === true && typeof value.body.sessionId === 'string' && typeof value.body.idempotencyKey === 'string'
        && Number.isInteger(value.body.expectedVersion) && value.body.expectedVersion > 0 && value.body.policyVersion === 'saved-until-deleted-v1') return value;
  } catch { /* Invalid hints carry no authority and are discarded. */ }
  try { localStorage.removeItem(key); } catch { /* No hint authority without readable storage. */ }
  return null;
}

export function clearPendingSave(owner: string, key: string) {
  if (readPendingSave(owner)?.body.idempotencyKey === key) localStorage.removeItem(`furnitureos.saved.pending.${owner}`);
}

export function SaveDesign({ design, lock, installDesign }: { design: SolvedDesign; lock: MutationLock; installDesign: (design: SolvedDesign) => void }) {
  const identity = useOwnerIdentity();
  const [consent, setConsent] = useState(false);
  const [message, setMessage] = useState('');
  const [receipt, setReceipt] = useState<SavedReceipt | null>(null);
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const savedVersion = useRef('');
  const previousIdentity = useRef<{ owner: string | null; session: string | null }>({ owner: null, session: null });
  const session = design.swap?.status === 'available' ? design.swap : null;
  const identityKey = session ? `${session.sessionId}:${session.version}` : '';
  const messageRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const nextOwner = identity.session?.user.id ?? null;
    const firstOwner = previousIdentity.current.owner === null && nextOwner !== null && previousIdentity.current.session === session?.sessionId;
    const sameWorkspace = previousIdentity.current.owner === nextOwner && previousIdentity.current.session === session?.sessionId;
    previousIdentity.current = { owner: nextOwner, session: session?.sessionId ?? null };
    if (!firstOwner) {
      generation.current++; active.current?.abort(); setBusy(false); setMessage('');
      if (!sameWorkspace) { setReceipt(null); savedVersion.current = ''; }
    }
  }, [identity.epoch, session?.sessionId]);
  useEffect(() => () => { generation.current++; active.current?.abort(); }, []);
  useEffect(() => { if (message) messageRef.current?.focus(); }, [message]);

  const save = async () => {
    if (!session || !consent || !lock.acquire('save')) return;
    const startingGeneration = generation.current;
    const intendedOwner = identity.session?.user.id;
    const abort = new AbortController(); active.current = abort;
    setBusy(true); setMessage('');
    try {
      const owner = (await identity.ensure(abort.signal)).user.id;
      if (startingGeneration !== generation.current) return;
      if (intendedOwner && intendedOwner !== owner) throw new Error('The account changed. Review the current Design before saving.');
      const pending = readPendingSave(owner);
      if (pending && (pending.body.sessionId !== session.sessionId || pending.body.expectedVersion !== session.version)) {
        setMessage('A previous save needs recovery. Open Saved Designs to retry it or review your saved list.');
        return;
      }
      const request: PendingSave = pending ?? { version: 1, at: Date.now(), body: { sessionId: session.sessionId, expectedVersion: session.version,
        idempotencyKey: crypto.randomUUID(), consent: true, policyVersion: 'saved-until-deleted-v1' } };
      localStorage.setItem(`furnitureos.saved.pending.${owner}`, JSON.stringify(request));
      const ticket = ++generation.current;
      try {
        const saved = await captureRequest<SavedReceipt>('/api/saved-designs', 'POST', request.body, abort.signal, owner);
        if (ticket !== generation.current || abort.signal.aborted) return;
        clearPendingSave(owner, request.body.idempotencyKey);
        savedVersion.current = identityKey;
        setReceipt(saved); setMessage('Design saved. You can reopen it after reload or keep it through email linking.');
      } catch (error) {
        if (ticket !== generation.current || abort.signal.aborted) return;
        if (error instanceof CaptureApiError && error.code === 'stale-version') {
          clearPendingSave(owner, request.body.idempotencyKey);
          const current = await fetchCurrentSwapSession(session.sessionId, abort.signal);
          if (ticket === generation.current && !abort.signal.aborted && current.status === 'current') installDesign(current.design);
          if (ticket === generation.current && !abort.signal.aborted) setMessage('The Design changed. Review the refreshed Design and save again.');
        } else {
          if (error instanceof CaptureApiError && [410, 422].includes(error.status)) clearPendingSave(owner, request.body.idempotencyKey);
          setMessage(error instanceof Error ? error.message : 'Saving did not finish. Retry with the same request or recover from Saved Designs.');
        }
      }
    } catch (error) { if (!active.current?.signal.aborted) setMessage(error instanceof Error ? error.message : 'Account access is unavailable.'); }
    finally { lock.release('save'); setBusy(false); }
  };
  return <section className="saved-controls" aria-label="Save selected Design">
    <h2>Keep this Design</h2>
    <p>Save the selected Design and confirmed Room until you delete the save. Original photos still expire after 24 hours.</p>
    {identity.config?.ready ? <><label><input type="checkbox" checked={consent} disabled={busy} onChange={e => setConsent(e.target.checked)} />I agree to retain this Design and confirmed Capture metadata until I delete the save.</label>
      <button onClick={() => void save()} disabled={!session || !consent || busy || lock.owner !== null || savedVersion.current === identityKey}>{busy ? 'Saving…' : savedVersion.current === identityKey ? 'Design saved' : 'Save Design'}</button></>
      : <p>Saving is unavailable right now.</p>}
    {message ? <p role="status" ref={messageRef} tabIndex={-1}>{message}</p> : null}
    <Link to={receipt ? `/saved/${receipt.id}` : '/saved'}>{receipt ? 'Open saved Design' : 'Saved Designs and account recovery'}</Link>
  </section>;
}
