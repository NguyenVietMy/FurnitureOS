import type { DesignFixture } from '@/shared/api/types';

export function FixtureSelector({
  fixtures,
  selectedId,
  onSelect,
}: {
  fixtures: ReadonlyArray<DesignFixture>;
  selectedId: string;
  onSelect: (fixtureId: string) => void;
}) {
  return (
    <section className="fixture-selector" aria-labelledby="fixture-heading">
      <p className="eyebrow">Bedroom preview</p>
      <h1 id="fixture-heading">Preview furniture around the bedroom</h1>
      <p className="subtle">
        Choose an arrangement to see how each piece fits against the walls.
      </p>
      <div className="fixture-options" role="group" aria-label="Bedroom arrangements">
        {fixtures.map((fixture) => (
          <button
            key={fixture.id}
            type="button"
            data-testid={`fixture-${fixture.id}`}
            aria-pressed={fixture.id === selectedId}
            onClick={() => onSelect(fixture.id)}
          >
            <span>{fixture.label}</span>
            <small>{fixture.intentKind.replace('_', ' ')}</small>
          </button>
        ))}
      </div>
      <p className="subtle fixture-description">
        {fixtures.find((fixture) => fixture.id === selectedId)?.description}
      </p>
    </section>
  );
}
