import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { fetchDesignFixtures, resolveDesignFixture } from '../../shared/api/client';
import type { DesignFixture, DesignResult } from '../../shared/api/types';
import { DesignRail } from './DesignRail';
import { RoomStage } from './RoomStage';
import './design.css';

const DEFAULT_FIXTURE_ID = 'against-wall';

export default function DesignPage() {
  const [fixtures, setFixtures] = useState<ReadonlyArray<DesignFixture> | null>(null);
  const [selectedId, setSelectedId] = useState(DEFAULT_FIXTURE_ID);
  const [result, setResult] = useState<DesignResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchDesignFixtures(controller.signal).then((fixtureResponse) => {
      if (controller.signal.aborted) return;
      setFixtures(fixtureResponse.fixtures);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Unable to load the Design fixtures.');
      }
    });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    const controller = new AbortController();
    resolveDesignFixture(selectedId, controller.signal).then((resolved) => {
      if (controller.signal.aborted) return;
      setResult(resolved);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : 'Unable to resolve the selected fixture.');
      }
    });
    return () => controller.abort();
  }, [attempt, selectedId]);

  const selectFixture = (fixtureId: string) => {
    setSelectedId(fixtureId);
    setResult(null);
    setError(null);
  };

  if (error) return (
    <main className="stage-placeholder" data-testid="api-error">
      <h1>Design data is unavailable.</h1><span role="alert">{error}</span>
      <button onClick={() => { setError(null); setAttempt((value) => value + 1); }}>Retry</button>
      <Link to="/">FurnitureOS home</Link>
    </main>
  );
  if (!fixtures || !result) {
    return <main className="stage-placeholder" data-testid="api-loading" role="status">Preparing the bedroom preview…</main>;
  }
  return (
    <main className="layout" data-testid="api-preview">
      <RoomStage result={result} />
      <DesignRail
        fixtures={fixtures}
        selectedId={selectedId}
        result={result}
        onSelect={selectFixture}
      />
    </main>
  );
}
