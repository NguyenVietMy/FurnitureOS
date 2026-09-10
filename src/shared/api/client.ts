import type { CatalogueGallery, PreviewDesign } from './types';
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
