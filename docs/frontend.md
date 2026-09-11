# Frontend guide

Run all npm commands from the repository root. `npm ci` installs the single locked frontend. Start `npm run start:api` and `npm run dev` in separate terminals, then open `http://127.0.0.1:5173`. Vite proxies `/api` to port 8000 (override with `FURNITUREOS_API_ORIGIN`). `npm run start:full` builds once and serves the app and API together at `http://127.0.0.1:8000`.

## Find the code

```text
src/
  app/                 main.tsx bootstrap; App.tsx routes, metadata and route scope
                       RouteErrorBoundary.tsx recovery; global.css local fonts
  features/
    landing/           LandingPage.tsx composition and concept interaction state
                       FeatureVisual.tsx repeated feature illustrations
                       RoomSchematic.tsx illustrative SVG; landing.css
    design/            DesignPage.tsx API lifecycle; DesignPanel.tsx facts and home link
                       RoomStage.tsx lazy canvas; RoomCanvas.tsx and rendering helpers
                       ProductPlacement.tsx, product-loaders.ts; design.css
  shared/api/          client.ts HTTP boundary; types.ts generated contract
```

The landing sample remains an illustrative concept. Its tabs, Room Type, Variants and equal-footprint Swap use local state and SVG. The independent Room preview fetches `/api/preview-design`; FastAPI supplies Catalogue, Product, Room Shell and Placement facts. Rendering helpers never become a second placement authority. See ADR-0004 and `CONTEXT.md` before changing those boundaries.

The `/design` fixture rail also resolves controlled wall-relative and object-relative requests through FastAPI. Its object-relative fixtures cover `adjacent_to`, `facing`, `flanking`, a dependency chain, repeated nightstand instances, intentional rug-under-bed overlap, a floor-standing lamp and typed pre-search failures. The complete-bedroom fixture combines the bed, both flanking nightstands, facing chair, under-bed rug and adjacent floor lamp in one solved Design. The browser draws only returned Placements and exposes per-instance Mesh, world-transform and world-bounds evidence through the existing scene-debug contract.

## Routing and loading

React Router's [declarative router](https://reactrouter.com/start/declarative/routing) owns `/`, `/design` (including a trailing slash), browser history and the not-found screen. Use `Link` for app navigation and normal fragment anchors for landing sections. Titles, descriptions, theme color, focus and top-of-page position update at the route boundary. Unknown extensionless app routes receive the SPA and display an accessible not-found screen; missing file/API URLs remain HTTP 404. Route metadata updates in the browser; the static HTML contains landing metadata. This migration does not add server rendering or crawler-specific HTML.

`DesignPage` is a dynamic import, and its canvas is another lazy boundary. A landing visit—including concept interactions—loads no Room chunk, Three/R3F runtime, Product files, decoder or preview API request. A failed import/renderer leaves a reload button and home link; API failures have Retry. API requests abort on unmount, including retries. Room camera, orbit, LOD and texture fallback remain the approved implementation.

Each feature stylesheet nests beneath `html[data-feature]`. App selects that scope in a layout effect. Both stylesheets may remain cached after navigation, but only the current scope applies. This preserves landing scrollbar hiding, margins and type resets without leaking them into the viewport-contained Room. Room's home link lives inside the existing scrolling panel and does not consume canvas height.

## Assets and fonts

`public/images` and `public/icon.svg` preserve the landing files and [credits](landing/assets.md). Normal image elements retain the previous absolute fill, object fit and aspect ratios; they now deliver the original local JPEGs without an image optimization server. `src/app/global.css` references the exact Fontsource 5.3.0 Latin WOFF2 files previously used by the landing. Vite emits their hashes locally, with the same Manrope 200–800 and Roboto Mono 400 faces and swap behavior.

`public/products` contains the 20 curated, normalized Product publications. Prebuild copies their Catalogue manifests for Python packaging and BasisU decoders for same-origin delivery. `npm run assets:report` remeasures every Product against the strict decimal `< 5,000,000`-byte threshold and counts shared paths once. Generated decoder/build output stays ignored.

## Controlled Catalogue measurement

The ordinary app does not expose `/catalogue-gallery` or `/api/catalogue-gallery`. Run `npm run build:measurement`, then start FastAPI with `FURNITUREOS_ENABLE_CATALOGUE_GALLERY=1` only for the approved physical-device protocol. The controlled page uses one WebGL context and one shared KTX2 decoder pool, loads LOD2 before LOD1 and LOD0, records actual rendered-frame events in `window.__catalogueMeasurement`, reports asset failures, and exports run JSON. `dist/measurement-build.json` freezes the build and Catalogue identities. See `docs/product-assets.md` and the external ticket protocol before recording evidence.

## Change and verify

Edit generated API types by changing the authoritative Pydantic contract and running `npm run api:types`; `npm run typecheck` includes freshness validation. Keep direct imports and feature-local state; shared code needs a real consumer rather than a prospective abstraction.

Run root `npm run typecheck`, `npm run test -- --run`, `uv run pytest`, `npm run build`, `npm run assets:report`, and `npm run test:e2e`. The browser runner owns fresh FastAPI servers on port 3101 and stops them afterward. It runs ordinary regressions against the gallery-free build, then separately runs controlled gallery instrumentation/error tests against a measurement build, and finally restores ordinary `dist`. Install Chromium with `npx playwright install chromium` once. Ticket-specific gallery evidence is written outside the checkout under the artifact directory.

The Vercel config builds this root Vite app, sends `/api/*` to `api/index.py`, and limits SPA fallback to extensionless non-asset app routes. No deployment or project configuration change is implied by this guide. The historical `web/` Next.js app has been retired; old plans and captures under `docs/landing` remain provenance, not startup instructions.

See [integration evidence](landing/verification/integration.md) for measured design conformance, exact test results and inherited limitations. The 901×1000 Room camera framing and the landing's 9px heading content-box overrun at 901px are inherited; neither changes the frame rules or causes page-wide horizontal scrolling.
