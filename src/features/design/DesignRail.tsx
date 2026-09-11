import { Link } from 'react-router';
import type { DesignFixture, DesignResult } from '@/shared/api/types';
import { DesignPanel } from './DesignPanel';
import { FixtureSelector } from './FixtureSelector';

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
  return (
    <aside className="panel" data-testid="design-panel">
      <Link className="home-link" to="/">← FurnitureOS home</Link>
      <FixtureSelector fixtures={fixtures} selectedId={selectedId} onSelect={onSelect} />
      {result.status === 'failed' ? (
        <section
          className="solver-failure"
          data-testid="design-failure"
          data-reason={result.reason}
        >
          <p className="eyebrow">Placement unavailable</p>
          <h2>Reason: <code>{result.reason}</code></h2>
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
