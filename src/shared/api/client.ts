import type { CatalogueGallery, DesignFixtures, DesignResult, PreviewDesign } from './types';
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
