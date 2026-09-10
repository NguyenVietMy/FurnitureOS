# Product assets: provenance, pipeline and runtime

The seed Catalogue contains 20 distinct real bedroom Products from Amazon
Berkeley Objects (ABO): 4 beds, 4 nightstands, 4 wardrobes/dressers, 3 chairs,
3 rugs and 2 floor-standing lamps. Provider records live in
`api/catalogue/providers/abo-seed.json`; the public `Product` contract contains
provider-neutral identity, dimensions, placement, mesh, purchase-disclosure and
attribution facts. Product IDs, exact upstream paths, source byte counts and
SHA-256 hashes are pinned in that seed. The featured bed also retains the
independent 66 × 56 × 92-inch listing record as sanity-check evidence; measured
Mesh bounds remain authoritative.

ABO's download page and archive record CC BY 4.0, while the AWS Registry of
Open Data entry and CVPR 2022 paper record CC BY-NC 4.0. The adapter and UI
surface this discrepancy as unresolved. They do not infer commercial rights.
Purchase availability was not verified, so every `purchaseUrl` is empty and
the API returns `unknown` with an explicit note.

The shared attribution contract is provider-neutral. `verified` requires at
least one evidence record, `unknown` permits no evidence, and
`conflicting-source-records` requires at least two records with different
recorded licenses. The ABO adapter deliberately selects the conflict status;
clear-license providers are presented without a generic conflict warning.

## Published form

Every Mesh is normalized to metres, +Y-up, +Z-front, with a measured
floor-centre origin. The pipeline records the source bounds and exact applied
translation; it preserves scale and yaw. FastAPI derives public dimensions and
normalization from each generated manifest. React renders these API-approved
facts and does not become a second placement authority.

`gltfpack` locks border vertices, but sparse simplified geometry can still move
measured extrema. The pipeline therefore remeasures every published LOD and,
only when the unchanged 0.002 m floor-centre tolerance is exceeded, adds a
small root translation. That post-simplification correction does not scale,
rotate, or rewrite the compressed geometry. Each affected LOD records the
translation and its maximum bounds delta from LOD0. `npm run assets:report`
independently remeasures the files and rejects normalization, triangle-count,
or bounds drift from the manifest.

Each Product ships three decreasing meshopt-compressed glTF LODs. Textures use
KTX2/BasisLZ with mip chains and progressive longest-edge caps of 2048, 1024
and 512 px for LOD0, LOD1 and LOD2. Each manifest lists the union of external
texture paths referenced by its LODs. Budget accounting stats every LOD file
and counts each path in that union once, even when multiple LOD documents
reference it.

The orchestrator conservatively interprets the owner's “below 5 MB” requirement
as a strict `< 5,000,000` byte per-Product threshold. Current published totals
range from 122,440 to 2,319,925 bytes. `npm run assets:report` independently
re-reads glTF bounds, KTX2 headers and on-disk sizes rather than trusting totals
written in manifests.

## Pipeline and delivery

`npm run assets:build` verifies all source hashes and byte counts, converts the
20 source GLBs, and publishes only normalized runtime assets and manifests.
Raw downloads, conversion work and native tools default to an external temp
directory; environment variables may point them to another external evidence
directory. They do not belong in the checkout.

Prebuild copies all 20 manifests beside the Python provider adapter for
function packaging and copies the Three.js BasisU decoder for same-origin
delivery. The generated provider-manifest directory and decoder copies are
ignored. Vercel's function configuration includes the provider directory so
runtime manifest validation does not depend on public static-file tracing.

## Controlled phone-measurement build

`npm run build:measurement` is the only build that compiles
`/catalogue-gallery`. It hashes source inputs into a build ID, emits
`dist/measurement-build.json`, and exposes all 20 Products in one WebGL canvas.
LOD2 loads first; LOD1 and LOD0 begin only after the prior real Mesh produces
an `onAfterRender` event. `window.__catalogueMeasurement` records per-Product
request, first-visible, refinement, rendered-frame and error evidence. The page
can export that record and restart after a network failure.

Ordinary `npm run build` omits the controlled route, API endpoint and gallery
chunks. The API endpoint additionally requires
`FURNITUREOS_ENABLE_CATALOGUE_GALLERY=1`. Follow the frozen external phone
protocol before every recorded cold-cache run; a desktop browser or the page's
restart button is not a substitute for clearing the approved physical device's
cache.

## Proof commands

```text
npm ci
uv sync --all-groups
npm run typecheck
npm run test -- --run
uv run pytest
npm run assets:report
npm run build
npm run test:e2e
```
