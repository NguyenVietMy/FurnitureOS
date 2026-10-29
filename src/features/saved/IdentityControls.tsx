import { useEffect, useRef, useState } from 'react';
import { useOwnerIdentity } from '@/shared/auth/OwnerIdentity';
import { beginEmailLink, finishEmailLink, beginReturningSignIn, finishReturningSignIn, signOutOwner } from '@/shared/auth/supabase';

export function IdentityControls() {
  const { config, session } = useOwnerIdentity();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [switching, setSwitching] = useState(false);
  const [step, setStep] = useState<'link' | 'return' | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const linkingOwner = useRef('');
  const sequence = useRef(0);
  const active = useRef<AbortController | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => { if (message) statusRef.current?.focus(); }, [message]);
  useEffect(() => () => { sequence.current++; active.current?.abort(); }, []);
  useEffect(() => { sequence.current++; setEmail(''); setCode(''); setStep(null); setMessage(''); setBusy(false); }, [session?.user.id]);
  const run = async (action: (current: () => boolean, signal: AbortSignal) => Promise<void>) => {
    active.current?.abort(); const abort = new AbortController(); active.current = abort;
    const ticket = ++sequence.current;
    const current = () => ticket === sequence.current && !abort.signal.aborted;
    setBusy(true); setMessage('');
    try { await action(current, abort.signal); }
    catch (error) { if (current()) setMessage(error instanceof Error ? error.message : 'Account access did not finish. Retry.'); }
    finally { if (current()) { setBusy(false); setCode(''); } }
  };
  if (!config?.ready) return null;
  return <section className="identity-controls" aria-label="Keep or recover your account"><h2>Keep or recover your account</h2>
    <p>{session ? session.user.is_anonymous ? 'You are using a private anonymous account. Clearing browser data can lose access. Link an email to keep this same account.' : 'Your current account can reopen its saved Designs.' : 'Return with your existing email account to reopen saved Designs.'}</p>
    <form onSubmit={event => { event.preventDefault(); void run(async (current, signal) => {
      if (!step) {
        if (session?.user.is_anonymous && !switching) {
          linkingOwner.current = session.user.id;
          await beginEmailLink(config, email, session.user.id, signal); if (current()) setStep('link');
        } else { await beginReturningSignIn(config, email, switching, signal); if (current()) setStep('return'); }
        if (current()) setMessage('Check your email for a code. Delivery and email configuration must be available.');
      } else {
        if (step === 'link') { await finishEmailLink(config, email, code, linkingOwner.current, signal); if (current()) setMessage('Email linked and refreshed. Your account and saved Designs keep the same ownership.'); }
        else { await finishReturningSignIn(config, email, code, signal); if (current()) setMessage('Returning account verified. Its saved Designs are ready to reopen.'); }
        if (current()) { setStep(null); setEmail(''); setSwitching(false); }
      }
    }); }}>
      <label>Email<input type="email" autoComplete="email" required value={email} disabled={busy || step !== null} onChange={event => setEmail(event.target.value)} /></label>
      {!step ? <label><input type="checkbox" checked={switching} disabled={busy} onChange={event => setSwitching(event.target.checked)} />I choose to switch to an existing email account. This does not merge accounts or transfer anonymous saves; keep access to the current account first.</label> : null}
      {step ? <label>Email verification code<input inputMode="numeric" autoComplete="one-time-code" required minLength={6} maxLength={12} value={code} disabled={busy} onChange={event => setCode(event.target.value)} /></label> : null}
      <button disabled={busy || (!step && !session?.user.is_anonymous && !switching)}>{busy ? 'Checking…' : step ? 'Verify email code' : session?.user.is_anonymous && !switching ? 'Link email to this account' : 'Send returning sign-in code'}</button>
      {step ? <button type="button" disabled={busy} onClick={() => { setStep(null); setCode(''); setMessage('Verification cancelled. Your current account remains available.'); }}>Cancel verification</button> : null}
    </form>
    {session ? <button disabled={busy} onClick={() => void run(async () => { const result = await signOutOwner(config); if (result.error) throw new Error('Sign out did not finish. Retry.'); setStep(null); setMessage('Signed out. Private previews and recovery pointers were cleared.'); })}>Sign out of this account</button> : null}
    {message ? <p role="status" tabIndex={-1} ref={statusRef}>{message}</p> : null}
  </section>;
}
