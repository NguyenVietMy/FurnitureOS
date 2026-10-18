import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import type { CaptureConfig } from '@/shared/api/types';
let client: SupabaseClient | null = null;
let binding = '';
export function captureAuth(config: CaptureConfig) {
  const url = config.authUrl ?? import.meta.env.VITE_SUPABASE_URL;
  const key = config.publishableKey ?? import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key || !config.storageReady) throw new Error('Private Capture activation is not verified.');
  if (!client || binding !== url + key) {
    client = createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } });
    binding = url + key;
  }
  return client.auth;
}
export function isAnonymousSession(session: Session|null): session is Session {
  return session?.user?.is_anonymous===true;
}
export function requireAnonymousSession(session: Session|null): Session {
  if(!isAnonymousSession(session))throw new Error('Capture requires an anonymous account. Your existing account has not been changed.');
  return session;
}
export async function ensureAnonymous(config: CaptureConfig) {
  const auth = captureAuth(config);
  const restored = await auth.getSession();
  if (restored.error) throw restored.error;
  if (restored.data.session) return requireAnonymousSession(restored.data.session);
  const created = await auth.signInAnonymously();
  if (created.error || !created.data.session) throw new Error('Anonymous sign-in is unavailable. Retry before adding photos.');
  return requireAnonymousSession(created.data.session);
}
