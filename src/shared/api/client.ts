import { readVariantStream } from './variant-stream';
import type { VariantStreamEvent } from './types';
import type {
  CatalogueGallery,
  DesignFixtures,
  DesignResult,
  LiveBedroomConfig,
  LiveDesignConfig,
  LiveGenerationResult,
  NudgeMutationResult,
  NudgeRegionResult,
  NudgeRequest,
  PreviewDesign,
  SwapCandidateResult,
  SwapCurrentResult,
  SwapMutationResult,
  SwapRequest,
} from './types';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
let captureAuthorization: (() => Promise<string>) | null = null;
export function setCaptureAuthorization(provider: (() => Promise<string>) | null) { captureAuthorization = provider; }
export class CaptureApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
async function privateHeaders(): Promise<Record<string, string>> {
  const provider = captureAuthorization;
  return provider ? { Authorization: `Bearer ${await provider()}` } : {};
}
export async function captureRequest<T>(path: string, method: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const binary = body instanceof Blob;
  const response = await fetch(`${API_BASE}${path}`, { method, signal, headers: {
    ...(await privateHeaders()), accept: 'application/json', ...(body===undefined?{}:{'Content-Type':binary?body.type:'application/json'}),
  }, body: body===undefined?undefined:binary?body:JSON.stringify(body) });
  const value = await response.json();
  if (!response.ok) throw new CaptureApiError(value?.detail?.detail ?? (typeof value?.detail==='string'?value.detail:`Capture request returned ${response.status}`),response.status);
  return value as T;
}
export async function capturePhotoUrl(captureId: string, photoId: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`${API_BASE}/api/captures/${captureId}/photos/${photoId}/content`, {signal,headers:await privateHeaders()});
  if (!response.ok) throw new Error('Private photo is unavailable.');
  return URL.createObjectURL(await response.blob());
}
const mutationReadSignal = (signal?: AbortSignal) => signal
  ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000);
export async function fetchPreviewDesign(signal?: AbortSignal): Promise<PreviewDesign> {
  const response = await fetch(`${API_BASE}/api/preview-design`, { signal, headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`Preview API returned ${response.status}`);
  return response.json() as Promise<PreviewDesign>;
}

export async function fetchCatalogueGallery(signal?: AbortSignal): Promise<CatalogueGallery> {
  const response = await fetch(`${API_BASE}/api/catalogue-gallery`, {
    signal,
    headers: { accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`Catalogue gallery API returned ${response.status}`);
  return response.json() as Promise<CatalogueGallery>;
}

export async function fetchDesignFixtures(signal?: AbortSignal): Promise<DesignFixtures> {
  const response = await fetch(`${API_BASE}/api/design-fixtures`, {
    signal,
    headers: { accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`Design fixtures API returned ${response.status}`);
  return response.json() as Promise<DesignFixtures>;
}

export async function resolveDesignFixture(
  fixtureId: string,
  signal?: AbortSignal,
): Promise<DesignResult> {
  const response = await fetch(`${API_BASE}/api/design-resolution`, {
    method: 'POST',
    signal,
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify({ fixtureId, maxCandidates: 128 }),
  });
  if (!response.ok) throw new Error(`Design resolution API returned ${response.status}`);
  return response.json() as Promise<DesignResult>;
}

export async function fetchLiveBedroomConfig(signal?: AbortSignal): Promise<LiveBedroomConfig> {
  const response = await fetch(`${API_BASE}/api/live-bedroom/config`, {
    signal,
    headers: { accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`Live bedroom configuration returned ${response.status}`);
  return response.json() as Promise<LiveBedroomConfig>;
}

export async function generateLiveBedroom(
  referenceId: string,
  signal?: AbortSignal,
): Promise<{ result: LiveGenerationResult; receivedAtMs: number }> {
  const response = await fetch(`${API_BASE}/api/live-bedroom/generate`, {
    method: 'POST',
    signal,
    headers: { accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify({ roomType: 'bedroom', referenceId }),
  });
  if (!response.ok) throw new Error(`Live bedroom generation returned ${response.status}`);
  const result = await response.json() as LiveGenerationResult;
  return { result, receivedAtMs: performance.now() };
}

export async function fetchLiveDesignConfig(roomType: 'bedroom' | 'living-room', signal?: AbortSignal): Promise<LiveDesignConfig> {
  const response = await fetch(`${API_BASE}/api/live-design/config?${new URLSearchParams({ roomType })}`, { signal, headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`Live Design configuration returned ${response.status}`);
  return response.json() as Promise<LiveDesignConfig>;
}

export async function generateLiveDesign(roomType: 'bedroom' | 'living-room', referenceId: string, signal?: AbortSignal): Promise<{ result: LiveGenerationResult; receivedAtMs: number }> {
  const response = await fetch(`${API_BASE}/api/live-design/generate`, { method: 'POST', signal, headers: { accept: 'application/json', 'content-type': 'application/json' }, body: JSON.stringify({ roomType, referenceId }) });
  if (!response.ok) throw new Error(`Live Design generation returned ${response.status}`);
  return { result: await response.json() as LiveGenerationResult, receivedAtMs: performance.now() };
}

export async function fetchSwapCandidates(
  sessionId: string,
  expectedVersion: number,
  instanceId: string,
  signal?: AbortSignal,
): Promise<SwapCandidateResult> {
  const query = new URLSearchParams({
    expectedVersion: String(expectedVersion),
    instanceId,
  });
  const response = await fetch(`${API_BASE}/api/swaps/${encodeURIComponent(sessionId)}/candidates?${query}`, {
    signal,
    headers: { ...(await privateHeaders()), accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`Swap candidates API returned ${response.status}`);
  return response.json() as Promise<SwapCandidateResult>;
}

export async function submitSwap(request: SwapRequest): Promise<SwapMutationResult> {
  const response = await fetch(`${API_BASE}/api/swaps`, {
    method: 'POST',
    signal: mutationReadSignal(),
    headers: { ...(await privateHeaders()), accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(`Swap API returned ${response.status}`);
  return response.json() as Promise<SwapMutationResult>;
}

export async function fetchCurrentSwapSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SwapCurrentResult> {
  const response = await fetch(`${API_BASE}/api/swaps/${encodeURIComponent(sessionId)}`, {
    signal: mutationReadSignal(signal),
    headers: { ...(await privateHeaders()), accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`Current Swap session API returned ${response.status}`);
  return response.json() as Promise<SwapCurrentResult>;
}

export async function fetchNudgeRegion(
  sessionId: string,
  expectedVersion: number,
  instanceId: string,
  signal?: AbortSignal,
): Promise<NudgeRegionResult> {
  const query = new URLSearchParams({ expectedVersion: String(expectedVersion), instanceId });
  const response = await fetch(`${API_BASE}/api/nudges/${encodeURIComponent(sessionId)}/region?${query}`, {
    signal: mutationReadSignal(signal), headers: { ...(await privateHeaders()), accept: 'application/json' },
  });
  if (!response.ok) throw new Error(`Nudge region API returned ${response.status}`);
  return response.json() as Promise<NudgeRegionResult>;
}

export async function submitNudge(request: NudgeRequest): Promise<NudgeMutationResult> {
  const response = await fetch(`${API_BASE}/api/nudges`, {
    method: 'POST',
    signal: mutationReadSignal(),
    headers: { ...(await privateHeaders()), accept: 'application/json', 'content-type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(`Nudge API returned ${response.status}`);
  return response.json() as Promise<NudgeMutationResult>;
}

export async function streamVariants(path: string, body: unknown, receive: (event: VariantStreamEvent) => void, signal: AbortSignal, privateRoom = false): Promise<void> {
  const headers = privateRoom ? await privateHeaders() : {};
  if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
  const response = await fetch(`${API_BASE}${path}`, { method: 'POST', signal,
    headers: { ...headers, accept: 'application/x-ndjson', 'content-type': 'application/json' }, body: JSON.stringify(body) });
  return readVariantStream(response, receive, signal);
}
