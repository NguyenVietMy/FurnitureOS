import { useEffect, useRef } from 'react';
import { Link } from 'react-router';
import type { DesignFixture, DesignResult } from '@/shared/api/types';
import { DesignPanel } from './DesignPanel';
import { FixtureSelector } from './FixtureSelector';

function ArrangementFeedback({ result, fixture }: { result: DesignResult; fixture: DesignFixture }) {
  const history = result.arrangementHistory;
  if (!history) return null;
  const clearance = result.status === 'solved'
    ? result.circulation?.clearanceWidthM
    : result.limitingConstraint?.clearanceWidthM;
  return (
    <section className="arrangement-feedback" data-testid="arrangement-feedback">
      <p className="eyebrow">Arrangement check</p>
      <p className="selected-arrangement">{fixture.label}</p>
      <h2>{result.status === 'solved' ? 'A connected walking route is clear' : 'No traversable arrangement was found'}</h2>
      <p>
        {result.status === 'solved'
          ? `The final Design connects all required door and Product access at ${clearance?.toFixed(2)} m clearance.`
          : `Furniture could not connect every required access point${clearance ? ` at ${clearance.toFixed(2)} m clearance` : ''}.`}
      </p>
      <p className="subtle">
        {result.zones?.length ?? 0} Placement {(result.zones?.length ?? 0) === 1 ? 'Zone' : 'Zones'} · {history.attempts.length} tried {history.attempts.length === 1 ? 'arrangement' : 'arrangements'}
      </p>
      <ol className="attempt-list" data-testid="arrangement-attempts">
        {history.attempts.map((attempt) => (
          <li key={attempt.id} data-outcome={attempt.outcome}>
            <strong>{attempt.stage === 'initial' ? 'Initial selection' : attempt.stage === 'repair' ? 'Repair selection' : attempt.stage === 'drop' ? 'Optional furniture removed' : 'Unsafe removal skipped'}:</strong>{' '}
            {attempt.outcome === 'solved' ? 'walking route clear.' : attempt.outcome === 'circulation-blocked' ? 'the walking route remained blocked.' : attempt.detail}
            {attempt.changedRequestIds?.length || attempt.droppedRequestIds?.length || attempt.limitingConstraint?.disconnectedAccessIds?.length ? (
              <details className="technical-details">
                <summary>Technical details</summary>
                {attempt.changedRequestIds?.length ? <p>Changed requests: {attempt.changedRequestIds.join(', ')}.</p> : null}
                {attempt.droppedRequestIds?.length ? <p>Removed requests: {attempt.droppedRequestIds.join(', ')}.</p> : null}
                {attempt.limitingConstraint?.disconnectedAccessIds?.length ? (
                  <p data-testid="blocked-access">Blocked access: {attempt.limitingConstraint.disconnectedAccessIds.join(', ')}.</p>
                ) : null}
              </details>
            ) : null}
          </li>
        ))}
      </ol>
      {result.status === 'failed' && result.limitingConstraint?.attributionLimited ? (
        <p className="attribution-note" data-testid="attribution-limitation">
          The blocked edge could not be attributed to one Product, so all movable, non-anchor furniture is listed conservatively.
        </p>
      ) : null}
      {result.status === 'failed' && (result.limitingConstraint?.implicatedRequestIds?.length || result.limitingConstraint?.attributionLimitation) ? (
        <details className="technical-details">
          <summary>Constraint details</summary>
          {result.limitingConstraint.implicatedRequestIds?.length ? (
            <p data-testid="implicated-requests">Implicated requests: {result.limitingConstraint.implicatedRequestIds.join(', ')}.</p>
          ) : null}
          {result.limitingConstraint.attributionLimitation ? <p>{result.limitingConstraint.attributionLimitation}</p> : null}
        </details>
      ) : null}
    </section>
  );
}

export function DesignRail({
  fixtures,
  selectedId,
  result,
  onSelect,
}: {
  fixtures: ReadonlyArray<DesignFixture>;
  selectedId: string;
  result: DesignResult;
  onSelect: (fixtureId: string) => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const selectedFixture = fixtures.find((fixture) => fixture.id === selectedId)!;
  const isArrangement = Boolean(result.arrangementHistory);

  useEffect(() => {
    if (isArrangement) panelRef.current?.scrollTo({ top: 0 });
  }, [isArrangement, selectedId]);

  return (
    <aside className="panel" data-testid="design-panel" ref={panelRef}>
      <Link className="home-link" to="/">← FurnitureOS home</Link>
      {isArrangement ? <ArrangementFeedback result={result} fixture={selectedFixture} /> : null}
      <FixtureSelector fixtures={fixtures} selectedId={selectedId} onSelect={onSelect} />
      {!isArrangement ? <ArrangementFeedback result={result} fixture={selectedFixture} /> : null}
      {result.status === 'failed' ? (
        <section
          className="solver-failure"
          data-testid="design-failure"
          data-reason={result.reason}
        >
          <p className="eyebrow">Design unavailable</p>
          <h2>{result.reason === 'NO_VALID_DESIGN' ? 'No valid Design' : <>Reason: <code>{result.reason}</code></>}</h2>
          <p role="alert">{result.detail}</p>
        </section>
      ) : (
        result.products.map((product, index) => (
          <DesignPanel
            key={result.intents[index]?.id ?? product.id}
            room={result.room}
            product={product}
            fit={result.fits[index]!}
            intentKind={result.intents[index]?.kind}
          />
        ))
      )}
    </aside>
  );
}
