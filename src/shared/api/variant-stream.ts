import type { VariantStreamEvent } from './types';

const MAX_LINE = 524_288;
const MAX_BODY = 4_194_304;
const labels = ['A', 'B', 'C'];
const object = (value: unknown): value is Record<string, any> => !!value && typeof value === 'object' && !Array.isArray(value);

/** No reconnect: a truncated response must never silently repeat provider work. */
export async function readVariantStream(response: Response, receive: (event: VariantStreamEvent) => void, signal?: AbortSignal): Promise<void> {
  if (!response.ok) throw new Error(`Variant generation returned ${response.status}. Review the current Room and retry explicitly.`);
  if (!response.headers.get('content-type')?.includes('application/x-ndjson') || !response.body) throw new Error('The Variant stream is unavailable.');
  const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', { fatal: true });
  const encoder = new TextEncoder();
  let buffer = '', bytes = 0, events = 0, generationId = '', terminal = false, count = 0;
  const signatures = new Set<string>();
  const line = (raw: string) => {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    if (!raw || encoder.encode(raw).byteLength > MAX_LINE || ++events > 32 || terminal) throw new Error('Malformed Variant stream.');
    const value: unknown = JSON.parse(raw);
    if (!object(value) || typeof value.generationId !== 'string' || !value.generationId || value.generationId.length > 128) throw new Error('Malformed Variant event.');
    if (!generationId) {
      if (value.type !== 'shell' && value.type !== 'error') throw new Error('The Room Shell was missing.');
      generationId = value.generationId;
    }
    if (value.generationId !== generationId) throw new Error('The generation identity changed.');
    switch (value.type) {
      case 'shell':
        if (events !== 1 || !object(value.room) || !Array.isArray(value.room.floorPolygon) || !Array.isArray(value.room.walls)) throw new Error('Malformed Room Shell.');
        break;
      case 'progress':
        if (value.variant !== labels[count] || !['selecting', 'duplicate-retry'].includes(value.stage)) throw new Error('Unexpected Variant progress.');
        break;
      case 'variant': {
        const r = value.result, d = r?.design;
        if (value.variant !== labels[count] || typeof value.signature !== 'string' || !/^[a-f0-9]{64}$/.test(value.signature) || signatures.has(value.signature)
          || r?.status !== 'solved' || !object(d) || d.status !== 'solved' || !object(d.room) || !Array.isArray(d.placements) || !d.placements.length
          || !Array.isArray(d.products) || !Array.isArray(d.intents) || d.products.length !== d.placements.length || d.intents.length !== d.placements.length) throw new Error('Malformed furnished Variant.');
        signatures.add(value.signature); count++;
        break;
      }
      case 'error':
        if (value.invalidated === true) { count = 0; signatures.clear(); }
        if (typeof value.code !== 'string' || typeof value.detail !== 'string' || value.detail.length > 16_384 || typeof value.invalidated !== 'boolean') throw new Error('Malformed generation failure.');
        break;
      case 'complete':
        if (!['complete', 'partial', 'failed'].includes(value.status) || !['complete', 'duplicate-exhausted', 'generation-failed', 'timeout', 'cancelled'].includes(value.reason)
          || !Array.isArray(value.available) || value.available.join() !== labels.slice(0, count).join()
          || (value.status === 'complete') !== (count === 3)) throw new Error('Malformed generation completion.');
        terminal = true;
        break;
      default: throw new Error('Unknown Variant event.');
    }
    receive(value as unknown as VariantStreamEvent);
  };
  try {
    while (true) {
      const chunk = await reader.read();
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (chunk.done) break;
      bytes += chunk.value.byteLength;
      if (bytes > MAX_BODY) throw new Error('The Variant stream exceeded its byte limit.');
      buffer += decoder.decode(chunk.value, { stream: true });
      let end;
      while ((end = buffer.indexOf('\n')) >= 0) { line(buffer.slice(0, end)); buffer = buffer.slice(end + 1); }
      if (encoder.encode(buffer).byteLength > MAX_LINE) throw new Error('The Variant event exceeded its byte limit.');
    }
    buffer += decoder.decode();
    if (buffer || !terminal) throw new Error('Generation was interrupted before completion. Available Variants are retained.');
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
