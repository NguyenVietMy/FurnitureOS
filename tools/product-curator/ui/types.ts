export interface Entry {
  product: { id: string; dimensionsM: { widthM: number; heightM: number; depthM: number }; mesh: { lods: { url: string }[] } };
  privateStyleIds: string[];
}
export interface Candidate {
  productId: string; styles: string[]; rooms: string[]; decision: 'accepted' | 'rejected' | null;
  error: string | null; selection: { attemptId: string; entry: Entry } | null;
  record: { displayName: string; brand: string; colour: string; privateStyleIds: string[]; itemId: string; sourceSha256: string };
  previewUrl: string; dimensions: { widthM: number; heightM: number; depthM: number };
}
export interface State {
  token: string; revision: number; actor: 'owner' | 'automated'; evidenceKind: string; protocol: string;
  sample: { status: 'NOT_STARTED' | 'ACTIVE' | 'PAUSED' | 'FINISHED' | 'INVALID'; elapsedMs: number; remainingCandidates: number | null; invalidReason?: string };
  freeze: { count: number; seedSha256: string }; busy: boolean; cursor?: number; candidates?: Candidate[];
  styles?: { id: string; privateName: string }[];
  attempts?: { id: string; productId: string; stage: string; status: string; error?: string; durationMs?: number }[];
  history?: { revision: number; type: string; productId?: string; stage?: string; at: number }[];
  canUndo?: boolean;
}
export type Mutation = { type: string; productId?: string; styles?: string[]; rooms?: string[]; cursor?: number; remainingCandidates?: number | null };
