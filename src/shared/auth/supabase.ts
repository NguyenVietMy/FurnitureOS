import { createClient, type Session, type SupabaseClient, type AuthChangeEvent } from '@supabase/supabase-js';
import { AuthAuthority } from './auth-authority';
type AuthConfig = { authUrl?: string | null; publishableKey?: string | null; storageReady?: boolean; ready?: boolean };
let client: SupabaseClient | null = null;
let binding = '';
let authority: AuthAuthority | null = null;
export function captureAuth(config: AuthConfig) {
  const url = config.authUrl ?? import.meta.env.VITE_SUPABASE_URL;
  const key = config.publishableKey ?? import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key || !(config.storageReady || config.ready)) throw new Error('Private account activation is not verified.');
  if (!client || binding !== url + key) {
    authority?.dispose();
    const current = authority = new AuthAuthority(url);
    client = createClient(url, key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false, storageKey: current.storageKey, storage: current.storage }, global: { fetch: current.fetch } });
    client.auth.onAuthStateChange((event, session) => current.observe(event, session));
    binding = url + key;
  }
  return client.auth;
}
export function observeOwnerAuth(config: AuthConfig, receive: (event: AuthChangeEvent, session: Session | null) => void) {
  const auth = captureAuth(config), current = authority!;
  return auth.onAuthStateChange((event, session) => { if (current.matches(session)) receive(event, session); });
}
async function accountAction<T>(config: AuthConfig, work: () => Promise<T>, signal?: AbortSignal, owner?: string) {
  captureAuth(config);
  return authority!.run(work, signal, owner);
}
export async function signOutOwner(config: AuthConfig) { const auth = captureAuth(config); authority!.cancel(); return auth.signOut(); }
export function isAnonymousSession(session: Session|null): session is Session {
  return session?.user?.is_anonymous===true;
}
export function requireAnonymousSession(session: Session|null): Session {
  if(!isAnonymousSession(session))throw new Error('Capture requires an anonymous account. Your existing account has not been changed.');
  return session;
}
export function requireOwnerSession(session: Session|null): Session {
  if (!session?.user?.id || typeof session.user.is_anonymous !== 'boolean' || !session.access_token) throw new Error('Refresh or restore your account to continue.');
  return session;
}
export async function ensureAnonymous(config: AuthConfig, signal?: AbortSignal) {
  return accountAction(config, async () => {
    const auth = captureAuth(config);
    const restored = await auth.getSession();
    if (restored.error) throw restored.error;
    if (restored.data.session) return requireOwnerSession(restored.data.session);
    const created = await auth.signInAnonymously();
    if (created.error || !created.data.session) throw new Error('Anonymous sign-in is unavailable. Retry before adding photos.');
    return requireAnonymousSession(created.data.session);
  }, signal);
}

export async function beginEmailLink(config: AuthConfig, email: string, ownerId: string, signal?: AbortSignal) {
  return accountAction(config, async () => {
    const auth = captureAuth(config);
    const restored = await auth.getSession();
    const session = requireOwnerSession(restored.data.session);
    if (restored.error || session.user.id !== ownerId || !isAnonymousSession(session)) throw new Error('Refresh your current anonymous account before linking.');
    const result = await auth.updateUser({ email });
    if (result.error) {
      if (['email_exists','identity_already_exists','user_already_exists'].includes(result.error.code ?? '')) throw new Error('This email already belongs to an account. Your anonymous account and saved Designs remain here. Automatic merging is unavailable.');
      throw new Error('Email linking is unavailable. Your current account and saved Designs remain here. Check email configuration and retry.');
    }
    if (result.data.user?.id !== ownerId) throw new Error('The account changed. Reopen your saved Designs before continuing.');
  }, signal, ownerId);
}

export async function finishEmailLink(config: AuthConfig, email: string, token: string, ownerId: string, signal?: AbortSignal) {
  return accountAction(config, async () => {
    const auth = captureAuth(config);
    const before = await auth.getSession();
    if (before.error || requireOwnerSession(before.data.session).user.id !== ownerId) throw new Error('The account changed. Reopen your saved Designs before verifying this email.');
    const verified = await auth.verifyOtp({ email, token, type: 'email_change' });
    if (verified.error) throw new Error('Email verification did not finish. Check the code and email configuration, then retry.');
    const refreshed = await auth.refreshSession();
    const session = requireOwnerSession(refreshed.data.session);
    const current = await auth.getUser();
    if (refreshed.error || current.error || session.user.id !== ownerId || current.data.user?.id !== ownerId
        || session.user.is_anonymous !== false || current.data.user.is_anonymous !== false) throw new Error('Linking is not verified. Refresh your account and retry.');
    return session;
  }, signal, ownerId);
}

export async function beginReturningSignIn(config: AuthConfig, email: string, deliberateSwitch: boolean, signal?: AbortSignal) {
  return accountAction(config, async () => {
    if (!deliberateSwitch) throw new Error('Choose to switch accounts before requesting a returning sign-in code.');
    const result = await captureAuth(config).signInWithOtp({ email, options: { shouldCreateUser: false } });
    if (result?.error) throw new Error('Returning sign-in is unavailable. No account was created. Check the email and configuration.');
  }, signal);
}

export async function finishReturningSignIn(config: AuthConfig, email: string, token: string, signal?: AbortSignal) {
  return accountAction(config, async () => {
    const auth = captureAuth(config);
    const result = await auth.verifyOtp({ email, token, type: 'email' });
    if (result.error) throw new Error('Returning sign-in did not finish. Check the code and retry.');
    const refreshed = await auth.refreshSession();
    const session = requireOwnerSession(refreshed.data.session);
    const current = await auth.getUser();
    if (refreshed.error || current.error || current.data.user?.id !== session.user.id || current.data.user.is_anonymous !== false || session.user.is_anonymous !== false) throw new Error('Returning account verification failed.');
    return session;
  }, signal);
}
