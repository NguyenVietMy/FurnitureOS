import { lazy, Suspense } from 'react';
import type { DesignResult } from '@/shared/api/types';

const RoomCanvas = lazy(() => import('./RoomCanvas'));

/** The API supplies the Design; the browser only renders it. */
export function RoomStage({ result }: { result: DesignResult }) {
  if (result.status === 'failed') {
    return <div className="stage-placeholder" data-testid="stage-invalid-fit"><strong>This bedroom arrangement does not fit.</strong><span>{result.detail}</span></div>;
  }
  return <div className="stage" data-testid="stage"><Suspense fallback={<div className="stage-placeholder" data-testid="stage-placeholder">Preparing the Room…</div>}><RoomCanvas key={result.intents.map((intent) => intent.id).join(':')} room={result.room} products={result.products} placements={result.placements} /></Suspense></div>;
}
