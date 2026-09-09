import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { fetchPreviewDesign } from '../../shared/api/client';
import type { PreviewDesign } from '../../shared/api/types';
import { DesignPanel } from './DesignPanel';
import { RoomStage } from './RoomStage';
import './design.css';

export default function DesignPage() {
  const [design, setDesign] = useState<PreviewDesign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    fetchPreviewDesign(controller.signal).then((preview) => {
      if (!controller.signal.aborted) setDesign(preview);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Unable to load preview.');
    });
    return () => controller.abort();
  }, [attempt]);

  if (error) return (
    <main className="stage-placeholder" data-testid="api-error">
      <h1>Preview data is unavailable.</h1><span role="alert">{error}</span>
      <button onClick={() => { setError(null); setAttempt((value) => value + 1); }}>Retry</button>
      <Link to="/">FurnitureOS home</Link>
    </main>
  );
  if (!design) return <main className="stage-placeholder" data-testid="api-loading" role="status">Loading the authoritative room preview…</main>;
  return <main className="layout" data-testid="api-preview"><RoomStage room={design.room} product={design.product} fit={design.fit} /><DesignPanel room={design.room} product={design.product} fit={design.fit} /></main>;
}
