# FurnitureOS

FurnitureOS is building a way to turn a real Room into a furnished 3D Design made from real Products. One Vite frontend serves the product landing and illustrative concept at `/`, and the accepted real-world-scale bed in a 4×3 metre Room at `/design`. The sample does not generate Designs; the Room preview renders an authoritative FastAPI response. Domain vocabulary lives in [`CONTEXT.md`](CONTEXT.md); durable architecture decisions live in [`docs/adr/`](docs/adr).

FastAPI/Pydantic is authoritative for the Catalogue, preview Design and all placement/fit validation. React/TypeScript/Vite fetches that Design and renders it with React Three Fiber/drei. The browser has rendering geometry only; it is not a second placement solver.

Accepted fixture and live Designs can expose versioned Product Swaps. Swap sessions are intentionally bounded, process-local, in-memory demo state: they expire, do not survive a restart, and are not shared across workers. An unknown, expired, or Catalogue-stale session fails closed and must be refreshed from a newly selected or generated Design.

## Running it

```
npm ci
uv sync --all-groups

# terminal 1 — FastAPI at http://127.0.0.1:8000
npm run start:api

# terminal 2 — Vite at http://127.0.0.1:5173 (proxies /api to FastAPI)
npm run dev

# or build the SPA and serve the complete app from FastAPI on :8000
npm run start:full
```

`predev`/`prebuild` copy the BasisU transcoder from `three` to `public/decoders/`, so every decoder is delivered from this origin.

## Proofs

```
npm run typecheck
npm run test -- --run       # frontend and asset checks
uv run pytest               # FastAPI domain, contract, static and regression cases
npm run build               # Vite production build
npm run assets:report       # published Product budget and format validation
npm run test:e2e            # built SPA and API from one full FastAPI server
```

The browser proof covers landing interactions, keyboard focus, responsive frames, route navigation, local fonts, metadata and the lazy 3D/API boundary. Room checks cover FastAPI provenance, Product bounds and north-wall contact, orbiting, three LODs, same-origin decoders, texture fallback, attribution, Retry and four viewport sizes. It needs Chromium once: `npx playwright install chromium`. On Windows, `npm run test:e2e` builds and starts its own production-mode FastAPI server on port 3101; leave that port free. For another running full-app server, set `E2E_BASE_URL` explicitly.

## Layout

Start with the [frontend guide](docs/frontend.md) for the route flow, feature boundaries and migration details. UI changes follow [DESIGN.md](DESIGN.md).

| Path | Role |
| --- | --- |
| `api/` | FastAPI API, full Pydantic contracts, provider adapter, Catalogue and authoritative solver |
| `backend_tests/` | Independent Catalogue, geometry, HTTP, OpenAPI and static-delivery behavior matrix |
| `src/app/` | Bootstrap, router, route metadata, error boundary and font setup |
| `src/features/landing/` | Marketing composition, schematic sample interactions and scoped styles |
| `src/features/design/` | API-driven Room UI and lazy React Three Fiber rendering |
| `src/shared/api/` | OpenAPI-generated contract and typed fetch boundary |
| `public/products/` | Published Meshes, manifests, textures and provenance |
| `scripts/` | Asset pipeline, decoder copy, budget report and browser runner |

The Product must publish a +Z-front, metre-normalized Mesh. The asset manifest supplies dimensions and normalization to the provider adapter. FastAPI validates arbitrary convex Room Shell floor polygons and stable wall segments, floor-centre vertical placement, placed-top ceiling clearance, wall contact and face-oriented access regions. The API preserves purchase disclosure and attribution fields; the UI renders them without inventing a purchase link.

## Deployment

The existing Vercel project is configured for a Vite static build plus the recognized FastAPI entrypoint at `api/index.py`. With the existing authenticated project scope, validate a protected preview with:

```powershell
vercel deploy --yes
npx -y vercel@latest curl https://<preview-url>/api/health
$env:E2E_BASE_URL='https://<preview-url>'
npx -y vercel@latest env run -- npm.cmd run test:e2e
```

`vercel curl` and the development OIDC token injected by `vercel env run` retain Deployment Protection while allowing API and browser checks. Verify `/api/health`, `/api/preview-design`, `/api/placement-validation`, SPA history routes, built assets and Product assets. Only promote or update the demo alias after those checks pass.
