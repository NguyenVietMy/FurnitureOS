import type { LiveGenerationFailure, RoomShell, SolvedDesign, VariantEvent, VariantStreamEvent } from '@/shared/api/types';
import { ownsNewerDesign } from './useMutationLock';
export type Label = 'A' | 'B' | 'C';
export interface VariantState {
  key: number;
  generationId: string | null;
  shell: RoomShell | null;
  variants: Partial<Record<Label, VariantEvent & { receivedAtMs: number }>>;
  selected: Label;
  visit: number;
  status: 'idle' | 'running' | 'complete' | 'partial' | 'failed' | 'interrupted' | 'stopped';
  message: string;
  failure: LiveGenerationFailure | null;
}
export const emptyVariants = (key = 0): VariantState => ({ key, generationId: null, shell: null, variants: {}, selected: 'A', visit: 0, status: 'idle', message: '', failure: null });
export function acceptVariantEvent(state: VariantState, key: number, event: VariantStreamEvent, now: number): VariantState {
  if (key !== state.key || state.status !== 'running' || (state.generationId && state.generationId !== event.generationId)) return state;
  switch (event.type) {
    case 'shell': return { ...state, generationId: event.generationId, shell: event.room, message: 'Room Shell ready. Creating Variant A…' };
    case 'progress': return { ...state, message: event.stage === 'duplicate-retry' ? `Finding a distinct Variant ${event.variant}…` : `Creating Variant ${event.variant}. Checking fit and walking space…` };
    case 'variant': return state.variants[event.variant] ? state : { ...state, variants: { ...state.variants, [event.variant]: { ...event, receivedAtMs: now } } };
    case 'error': return { ...state, generationId: event.generationId, ...(event.invalidated ? { shell: null, variants: {} } : {}), message: event.detail, failure: event.failure ?? null };
    case 'complete': return { ...state, status: event.status, message: event.status === 'complete' ? 'Three distinct Variants are ready.'
      : event.reason === 'duplicate-exhausted' ? 'Fewer distinct Variants were found within the retry limit.'
      : event.reason === 'timeout' ? 'Generation reached its time limit. Available Variants are retained.'
      : state.message || 'Generation ended. Available Variants are retained.' };
  }
  return state;
}
export function installVariantDesign(state: VariantState, key: number, design: SolvedDesign): VariantState {
  if (state.key !== key) return state;
  // A commit can finish after A → B → A. Cache the authoritative version by
  // session, regardless of the current visit, without changing the selection.
  const label = (['A', 'B', 'C'] as const).find(value => {
    const current = state.variants[value];
    return current && ownsNewerDesign(current.result.design, design);
  });
  if (!label) return state;
  const current = state.variants[label]!;
  return { ...state, variants: { ...state.variants, [label]: { ...current, result: { ...current.result, design } } } };
}
