import type { PreviewDesign } from './types';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
export async function fetchPreviewDesign(signal?: AbortSignal): Promise<PreviewDesign> {
  const response = await fetch(`${API_BASE}/api/preview-design`, { signal, headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`Preview API returned ${response.status}`);
  return response.json() as Promise<PreviewDesign>;
}
