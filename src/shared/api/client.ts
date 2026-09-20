import type {
  CatalogueGallery,
  DesignFixtures,
  DesignResult,
  LiveBedroomConfig,
  LiveGenerationResult,
  PreviewDesign,
} from './types';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
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
