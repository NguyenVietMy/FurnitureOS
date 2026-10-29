import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import type { Session } from '@supabase/supabase-js';
import type { CaptureConfig, SavedConfig } from '@/shared/api/types';
import { setCaptureAuthorization } from '@/shared/api/client';
import { captureAuth, ensureAnonymous, requireOwnerSession, observeOwnerAuth } from './supabase';

type Identity = { config: SavedConfig | null; session: Session | null; epoch: number; authReady: boolean; ensure: (signal?: AbortSignal) => Promise<Session> };
const OwnerContext = createContext<Identity | null>(null);

/** One SDK store and one authorization provider for all private features. */
export function OwnerIdentity({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<SavedConfig | null>(null);
  const [authConfig, setAuthConfig] = useState<CaptureConfig | SavedConfig | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [epoch, setEpoch] = useState(0);
  const signature = useRef('');
  const revision = useRef(0);
  useEffect(() => {
    const abort = new AbortController();
    void Promise.all([
      fetch('/api/saved-designs/config', { signal: abort.signal }).then(r => r.ok ? r.json() as Promise<SavedConfig> : null),
      fetch('/api/captures/config', { signal: abort.signal }).then(r => r.ok ? r.json() as Promise<CaptureConfig> : null),
    ]).then(([saved, capture]) => {
      if (abort.signal.aborted) return;
      setConfig(saved);
      setAuthConfig(saved?.ready ? saved : capture?.storageReady ? capture : null);
    }).catch(() => { if (!abort.signal.aborted) setConfig({ ready: false, detail: 'Account access is unavailable. Retry later.' }); });
    return () => abort.abort();
  }, []);
  useLayoutEffect(() => {
    if (!authConfig) return;
    const auth = captureAuth(authConfig);
    const subscription = observeOwnerAuth(authConfig, (_event, next) => {
      const valid = next && typeof next.user.is_anonymous === 'boolean' ? next : null;
      const nextSignature = valid ? `${valid.user.id}:${valid.user.is_anonymous}:${valid.access_token}` : '';
      if (nextSignature === signature.current) return;
      const previousOwner = signature.current.split(':')[0];
      if (previousOwner && previousOwner !== valid?.user.id) {
        try {
          localStorage.removeItem(`furnitureos.capture.${previousOwner}`);
          localStorage.removeItem(`furnitureos.saved.pending.${previousOwner}`);
        } catch { /* Restricted browser storage must never prevent private UI invalidation. */ }
      }
      signature.current = nextSignature;
      revision.current++;
      setSession(valid);
      setEpoch(value => value + 1);
    }).data.subscription;
    setCaptureAuthorization(async expectedOwner => {
      const restored = await auth.getSession();
      if (restored.error) throw new Error('Refresh your account before continuing.');
      if (!restored.data.session) return null;
      const current = requireOwnerSession(restored.data.session);
      if (expectedOwner && current.user.id !== expectedOwner) throw new Error('The account changed. Reopen Saved Designs before continuing.');
      return current.access_token;
    });
    return () => { subscription.unsubscribe(); setCaptureAuthorization(null); };
  }, [authConfig]);
  const ensure = useCallback(async (signal?: AbortSignal) => {
    if (!authConfig) throw new Error('Account access is unavailable right now.');
    const previousOwner = signature.current.split(':')[0];
    const before = revision.current;
    const restored = await ensureAnonymous(authConfig, signal);
    if ((previousOwner && previousOwner !== restored.user.id)
        || revision.current - before > (previousOwner ? 0 : 1)
        || (signature.current && signature.current.split(':')[0] !== restored.user.id)) {
      throw new Error('The account changed or refreshed. Review the current Design before trying again.');
    }
    return restored;
  }, [authConfig]);
  return <OwnerContext value={{ config, session, epoch, authReady: authConfig !== null, ensure }}>{children}</OwnerContext>;
}

export function useOwnerIdentity() {
  const value = useContext(OwnerContext);
  if (!value) throw new Error('Owner identity context is required.');
  return value;
}
