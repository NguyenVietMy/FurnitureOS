import { lazy, Suspense } from 'react';
import type { DesignResult } from '@/shared/api/types';

const RoomCanvas = lazy(() => import('./RoomCanvas'));

/** The API supplies the Design; the browser only renders it. */
export function RoomStage({ result }: { result: DesignResult }) {
  if (result.status === 'failed') {
    if (result.arrangementHistory) {
      const clearance = result.limitingConstraint?.clearanceWidthM;
      return (
        <div className="stage-placeholder arrangement-stage-failure" data-testid="stage-invalid-fit">
          <p className="eyebrow">Arrangement check</p>
          <strong>No connected walking route was found.</strong>
          <span>
            The tried arrangements could not connect every required door and furniture access
            {clearance ? ` with ${clearance.toFixed(2)} m clearance` : ''}.
          </span>
          <details className="technical-details">
            <summary>Solver details</summary>
            <p>{result.detail}</p>
            <p><code>{result.limitingConstraint?.code ?? result.reason}</code></p>
          </details>
        </div>
      );
    }
    return <div className="stage-placeholder" data-testid="stage-invalid-fit"><strong>This bedroom arrangement does not fit.</strong><span>{result.detail}</span></div>;
  }

  const isArrangement = Boolean(result.arrangementHistory);
  return (
    <div className={`stage${isArrangement ? ' stage--overview' : ''}`} data-testid="stage">
      <Suspense fallback={<div className="stage-placeholder" data-testid="stage-placeholder">Preparing the Room…</div>}>
        <RoomCanvas
          key={result.intents.map((intent) => intent.id).join(':')}
          room={result.room}
          products={result.products}
          placements={result.placements}
          overview={isArrangement}
        />
      </Suspense>
      {isArrangement ? (
        <div className="stage-outcome" data-testid="stage-arrangement-outcome">
          <strong>Walking route clear</strong>
          <span>{result.circulation?.clearanceWidthM.toFixed(2)} m clearance after one repair</span>
        </div>
      ) : null}
    </div>
  );
}
