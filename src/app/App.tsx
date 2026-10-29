import { lazy, Suspense, useLayoutEffect } from 'react';
import { Link, matchPath, Route, Routes, useLocation } from 'react-router';
import { LandingPage } from '../features/landing/LandingPage';
import { RouteErrorBoundary } from './RouteErrorBoundary';
const OwnerIdentity = lazy(() => import('@/shared/auth/OwnerIdentity').then(module => ({ default: module.OwnerIdentity })));

const DesignPage = lazy(() => import('../features/design/DesignPage'));
const LiveBedroomPage = lazy(() => import('../features/design/LiveBedroomPage'));
const CapturePage = lazy(() => import('../features/capture/CapturePage'));
const SavedDesignsPage = lazy(() => import('../features/saved/SavedDesignsPage'));
const catalogueGalleryEnabled = import.meta.env.VITE_ENABLE_CATALOGUE_GALLERY === '1';
const CatalogueGalleryPage = catalogueGalleryEnabled
  ? lazy(() => import('../features/catalogue-gallery/CatalogueGalleryPage'))
  : null;

export function App() {
  const { pathname } = useLocation();
  const privateFeatures = pathname === '/capture' || pathname === '/saved' || pathname.startsWith('/saved/') || pathname.startsWith('/design');
  return privateFeatures ? <Suspense fallback={<main className="route-message" role="status">Loading Room preview…</main>}><OwnerIdentity><AppRoutes /></OwnerIdentity></Suspense> : <AppRoutes />;
}

function AppRoutes() {
  const { pathname } = useLocation();
  const feature = matchPath({ path: '/capture', caseSensitive: true, end: true }, pathname) ? 'capture' : pathname === '/' ? 'landing'
    : matchPath({ path: '/design', caseSensitive: true, end: true }, pathname)
      || matchPath({ path: '/design/live', caseSensitive: true, end: true }, pathname)
      || matchPath({ path: '/design/live-bedroom', caseSensitive: true, end: true }, pathname)
      || pathname === '/saved' || pathname.startsWith('/saved/') ? 'design'
      : CatalogueGalleryPage
        && matchPath({ path: '/catalogue-gallery', caseSensitive: true, end: true }, pathname)
        ? 'catalogue-gallery'
        : 'not-found';

  useLayoutEffect(() => {
    document.documentElement.dataset.feature = feature;
    document.title = catalogueGalleryEnabled && feature === 'catalogue-gallery'
      ? 'FurnitureOS — controlled Catalogue measurement'
      : feature === 'landing' ? 'FurnitureOS — AI powered room design'
        : feature === 'capture' ? 'FurnitureOS — Room Capture' : feature === 'design' ? 'FurnitureOS — Room preview' : 'Page not found — FurnitureOS';
    document.querySelector('meta[name="description"]')?.setAttribute(
      'content',
      catalogueGalleryEnabled && feature === 'catalogue-gallery'
        ? 'Controlled physical-device measurement build.'
        : feature === 'landing'
          ? 'Turn a real Room Capture into a furnished Design assembled from real Products.'
          : feature === 'capture' ? 'Private Room Capture, corrected Openings and explicitly confirmed scale.' : feature === 'design'
            ? 'A real, real-scale Product placed in a Room Shell.'
            : 'This FurnitureOS page could not be found.',
    );
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      'content',
      feature === 'design' || (catalogueGalleryEnabled && feature === 'catalogue-gallery')
        ? '#f6f4ef' : '#fdfef6',
    );
    window.scrollTo({ top: 0, behavior: 'instant' });
    document.getElementById('root')?.focus({ preventScroll: true });
  }, [feature, pathname]);

  return (
    <RouteErrorBoundary key={pathname}>
      <Suspense fallback={<main className="route-message" role="status">Loading Room preview…</main>}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/design" caseSensitive element={<DesignPage />} />
          <Route path="/design/live-bedroom" caseSensitive element={<LiveBedroomPage bedroomOnly />} />
          <Route path="/design/live" caseSensitive element={<LiveBedroomPage />} />
          <Route path="/capture" caseSensitive element={<CapturePage />} />
          <Route path="/saved" caseSensitive element={<SavedDesignsPage />} />
          <Route path="/saved/:savedId" caseSensitive element={<SavedDesignsPage />} />
          {CatalogueGalleryPage ? (
            <Route path="/catalogue-gallery" caseSensitive element={<CatalogueGalleryPage />} />
          ) : null}
          <Route path="*" element={<main className="route-message"><h1>Page not found</h1><p>This address does not match a FurnitureOS page.</p><Link to="/">FurnitureOS home</Link></main>} />
        </Routes>
      </Suspense>
    </RouteErrorBoundary>
  );
}
