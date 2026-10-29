import type { AuthChangeEvent, Session } from '@supabase/supabase-js';

type Operation = { abort: AbortController; owner?: string; notificationToken?: string };
type Admission = { epoch: number; operation: Operation | null; owner: string; previousOwner: string | null; previousToken: string | null };
const obsolete = () => new DOMException('The account changed or this account action was cancelled.', 'AbortError');

/** Guards the supported SDK fetch/storage boundaries, using only its existing store. */
export class AuthAuthority {
  readonly storageKey: string;
  private authPrefix: string;
  private epoch = 0;
  private operation: Operation | null = null;
  private owner: string | null;
  private requests = new Set<AbortController>();
  // Bounded, transient network-response admissions; never persisted or used
  // to authorize application requests. Entries are consumed by SDK writes.
  private admissions = new Map<string, Admission>();
  private storageChanged = (event: StorageEvent) => { if (event.key === this.storageKey || event.key === null) this.cancel(); };

  constructor(url: string) {
    this.storageKey = `sb-${new URL(url).hostname.split('.')[0]}-auth-token`;
    this.authPrefix = `${url.replace(/\/$/, '')}/auth/v1/`;
    this.owner = this.current()?.user.id ?? null;
    globalThis.addEventListener?.('storage', this.storageChanged);
  }
  private current(): Session | null {
    try {
      const value = JSON.parse(globalThis.localStorage?.getItem(this.storageKey) ?? 'null') as Session | null;
      return value?.user && typeof value.user.id === 'string' && typeof value.access_token === 'string' ? value : null;
    }
    catch { return null; }
  }
  matches(session: Session | null) {
    const stored = this.current();
    return session === null ? stored === null : stored?.user.id === session.user.id
      && stored.user.is_anonymous === session.user.is_anonymous && stored.access_token === session.access_token;
  }
  cancel() {
    this.epoch++;
    this.operation?.abort.abort();
    for (const request of this.requests) request.abort();
  }
  dispose() { this.cancel(); globalThis.removeEventListener?.('storage', this.storageChanged); }
  observe(event: AuthChangeEvent, session: Session | null) {
    if (!this.matches(session)) return;
    const owner = session?.user.id ?? null;
    const ownTransition = session && !this.operation?.abort.signal.aborted && this.operation?.notificationToken === session.access_token;
    if (event === 'SIGNED_OUT' || (owner !== this.owner && !ownTransition)) this.cancel();
    this.owner = owner;
  }
  async run<T>(work: () => Promise<T>, signal?: AbortSignal, owner?: string): Promise<T> {
    this.operation?.abort.abort();
    const operation: Operation = { abort: new AbortController(), owner };
    const cancel = () => operation.abort.abort();
    if (signal?.aborted) cancel();
    signal?.addEventListener('abort', cancel, { once: true });
    this.operation = operation;
    try {
      operation.abort.signal.throwIfAborted();
      const result = await work();
      operation.abort.signal.throwIfAborted();
      return result;
    } catch (error) {
      if (operation.abort.signal.aborted) throw obsolete();
      throw error;
    } finally {
      signal?.removeEventListener('abort', cancel);
      if (this.operation === operation) this.operation = null;
    }
  }
  readonly storage = {
    getItem: (key: string) => globalThis.localStorage.getItem(key),
    removeItem: (key: string) => { if (key === this.storageKey) this.cancel(); globalThis.localStorage.removeItem(key); },
    setItem: (key: string, value: string) => {
      if (key === this.storageKey) {
        const session = JSON.parse(value) as Session;
        const admission = this.admissions.get(session.access_token);
        const current = this.current();
        if (admission) {
          if (admission.epoch !== this.epoch || admission.operation?.abort.signal.aborted
              || admission.owner !== session.user.id || (current?.user.id ?? null) !== admission.previousOwner
              || (current?.access_token ?? null) !== admission.previousToken) throw obsolete();
          if (admission.operation) admission.operation.notificationToken = session.access_token;
          this.admissions.delete(session.access_token);
        } else if (!current || current.access_token !== session.access_token || current.user.id !== session.user.id) throw obsolete();
      }
      // The SDK's one normal session key remains the only persisted token store.
      globalThis.localStorage.setItem(key, value);
    },
  };
  readonly fetch: typeof fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    if (!url.startsWith(this.authPrefix)) return globalThis.fetch(input, init);
    const operation = this.operation, epoch = this.epoch, previousOwner = this.current()?.user.id ?? null;
    const previousToken = this.current()?.access_token ?? null;
    const abort = new AbortController(); this.requests.add(abort);
    const signal = AbortSignal.any([abort.signal, ...(operation ? [operation.abort.signal] : []), ...(init?.signal ? [init.signal] : [])]);
    const check = () => { signal.throwIfAborted(); if (epoch !== this.epoch || previousOwner !== (this.current()?.user.id ?? null) || previousToken !== (this.current()?.access_token ?? null)) throw obsolete(); };
    try {
      check();
      const response = await globalThis.fetch(input, { ...init, signal });
      // Inspect the complete response before the SDK can parse or persist it.
      const value = await response.clone().json().catch(() => null) as { access_token?: string; user?: { id?: string }; id?: string } | null;
      check();
      const owner = value?.user?.id ?? value?.id;
      const token = value?.access_token ?? new Headers(init?.headers).get('Authorization')?.replace(/^Bearer /, '');
      const path = new URL(url).pathname;
      if (response.ok && owner && token) {
        if ((operation?.owner && owner !== operation.owner) || (path.endsWith('/token') && previousOwner && owner !== previousOwner)) throw obsolete();
        this.admissions.set(token, { epoch, operation, owner, previousOwner, previousToken });
        if (this.admissions.size > 32) this.admissions.delete(this.admissions.keys().next().value!);
      }
      return response;
    } finally { this.requests.delete(abort); }
  };
}
