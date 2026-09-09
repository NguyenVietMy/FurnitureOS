import { lazy, Suspense } from 'react';
import type { FitResult, Product, RoomShell } from '@/shared/api/types';

const RoomCanvas = lazy(() => import('./RoomCanvas'));

/** The API supplies the Design; the browser only renders it. */
export function RoomStage({ room, product, fit }: { room: RoomShell; product: Product; fit: FitResult }) {
  if (fit.status !== 'fits') return <div className="stage-placeholder" data-testid="stage-invalid-fit"><strong>{product.displayName} cannot be placed here.</strong><span>{fit.detail}</span></div>;
  return <div className="stage" data-testid="stage"><Suspense fallback={<div className="stage-placeholder" data-testid="stage-placeholder">Preparing the Room…</div>}><RoomCanvas room={room} product={product} placement={fit.placement} /></Suspense></div>;
}
