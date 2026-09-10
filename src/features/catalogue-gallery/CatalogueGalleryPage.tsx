import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { fetchCatalogueGallery } from '@/shared/api/client';
import type { CatalogueGallery } from '@/shared/api/types';
import { startMeasurement } from './measurement';
import './catalogue-gallery.css';

const CatalogueGalleryCanvas = lazy(() => import('./CatalogueGalleryCanvas'));
const BUILD_ID = import.meta.env.VITE_MEASUREMENT_BUILD_ID ?? 'unfrozen-local';

export default function CatalogueGalleryPage() {
  const [gallery, setGallery] = useState<CatalogueGallery | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [loadErrors, setLoadErrors] = useState<Record<string, string>>({});
  const recordLoadError = useCallback((productId: string, cause: unknown) => {
    setLoadErrors((current) => ({
      ...current,
      [productId]: cause instanceof Error ? cause.message : String(cause),
    }));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalogueGallery(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      startMeasurement(BUILD_ID, result.catalogueVersion, result.products.map((product) => product.id));
      setGallery(result);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : String(cause));
    });
    return () => controller.abort();
  }, []);

  function restartMeasurement() {
    if (!gallery) return;
    setLoadErrors({});
    startMeasurement(BUILD_ID, gallery.catalogueVersion, gallery.products.map((product) => product.id));
    setAttempt((value) => value + 1);
  }

  function exportMeasurement() {
    if (!window.__catalogueMeasurement) return;
    const blob = new Blob(
      [`${JSON.stringify(window.__catalogueMeasurement, null, 2)}\n`],
      { type: 'application/json' },
    );
    const anchor = document.createElement('a');
    anchor.href = URL.createObjectURL(blob);
    anchor.download = `${BUILD_ID}-run.json`;
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  }

  if (error) return (
    <main className="gallery-message" data-testid="gallery-error">
      <h1>Catalogue measurement failed.</h1>
      <p role="alert">{error}</p>
      <button onClick={() => window.location.reload()}>Retry cold load</button>
    </main>
  );
  if (!gallery) return <main className="gallery-message" role="status">Loading the controlled Catalogue…</main>;

  return (
    <main className="catalogue-gallery" data-testid="catalogue-gallery">
      <header>
        <p className="gallery-kicker">Controlled measurement build</p>
        <h1>20 real-scale Products</h1>
        <p>This route is compiled only for approved device testing. No private Style names are exposed.</p>
        <dl>
          <div><dt>Build</dt><dd data-testid="measurement-build-id">{BUILD_ID}</dd></div>
          <div><dt>Catalogue</dt><dd data-testid="catalogue-version">{gallery.catalogueVersion}</dd></div>
          <div><dt>Products</dt><dd data-testid="product-count">{gallery.products.length}</dd></div>
        </dl>
        <div className="gallery-actions" aria-label="Measurement controls">
          <button type="button" onClick={restartMeasurement}>Restart measurement</button>
          <button type="button" onClick={exportMeasurement}>Export run JSON</button>
        </div>
        <p className="gallery-cold-note">Restarting instrumentation does not clear HTTP caches. Follow the frozen phone protocol before each recorded cold-load run.</p>
        {Object.keys(loadErrors).length ? (
          <p className="gallery-load-error" role="alert" data-testid="gallery-load-error">
            {Object.keys(loadErrors).length} Product load failed. Fix the network condition, then restart the measurement.
          </p>
        ) : null}
      </header>
      <section className="gallery-stage" aria-label="Real-scale Catalogue scene">
        <Suspense fallback={<div className="gallery-message" role="status">Preparing the 3D scene…</div>}>
          <CatalogueGalleryCanvas key={attempt} products={gallery.products} onLoadError={recordLoadError} />
        </Suspense>
      </section>
      <ol className="gallery-products" aria-label="Catalogue Product facts">
        {gallery.products.map((product) => (
          <li key={product.id} data-product-id={product.id}>
            <span>{product.category}</span>
            <strong>{product.displayName}</strong>
            <small>{product.dimensionsM.widthM.toFixed(2)} × {product.dimensionsM.heightM.toFixed(2)} × {product.dimensionsM.depthM.toFixed(2)} m</small>
          </li>
        ))}
      </ol>
    </main>
  );
}
