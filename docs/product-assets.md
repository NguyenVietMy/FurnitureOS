# Product assets: provenance, pipeline and runtime

The published Product is `bed-prudence-tufted-queen-natural`, Prudence Tufted
Queen Bed by Stone & Beam. Its source is the Amazon Berkeley Objects (ABO)
collection at `https://amazon-berkeley-objects.s3.amazonaws.com/3dmodels/original/D/B07B4W5T9D.glb` (SHA-256 `2513916c1a172e6fdd8e43e8f3f0e570955c19ceeaa59ca6bc0cdb52107ff348`).
The API returns full CC BY 4.0 attribution: Amazon.com, Inc., collection and
material links, the CVPR 2022 citation and the recorded modifications. The
marketplace listing was unavailable on 2026-09-08, so the required
`purchaseUrl` is honestly empty and its disclosure is shown in the UI.

The ABO README recorded CC BY 4.0 on that date while ADR-0001 records CC BY-NC
4.0. This unresolved rights question is exposed rather than silently decided.

## Published form

The Mesh is normalized to metres, +Y-up, +Z-front, floor-centre origin. Its
measured bounds are 1.6958 m wide, 1.4259 m high and 2.2330 m deep; the listed
66 × 56 × 92-inch figures are an independent sanity check only.

FastAPI is the authority that consumes those dimensions. It rejects a
non-canonical front axis, derives Product dimensions and normalization from the
manifest, validates floor-centre Placement and placed-top ceiling bounds in metre
coordinates, and checks allowed wall-contact faces plus face-oriented required access regions.
React/Vite only renders the API-approved Product and its access overlays. It
does not ship a second fit solver.

The three meshopt-compressed glTF LODs share three KTX2/BasisU textures. The
accepted budget is exactly **1,298,091 bytes**: LOD 0 354,951, LOD 1 165,452,
LOD 2 61,691, shared textures 715,997. `tests/product-assets.test.ts` reads the
published manifest and files to preserve that budget and +Z invariant.

## Pipeline and delivery

`npm run assets:build` downloads and verifies the source asset, converts it with
gltf-transform and native gltfpack, generates three meshopt/KTX2 levels, shares
texture files by content hash, and writes the manifest. `npm run assets:report`
re-measures the published asset set. `GLTFPACK_PATH` can point to a native
gltfpack binary; the npm gltfpack package cannot produce BasisU output.

`scripts/copy-decoders.mjs` copies the installed Three.js BasisU transcoder to
`public/decoders/basis/` before Vite development/build and browser proofs.
`src/features/design/product-loaders.ts` serves it from that same origin and uses a
neutral fallback texture if a KTX2 request fails, so the real Mesh remains
visible. The build also copies the authoritative manifest beside the Python
provider adapter so Vercel's function bundle validates the same manifest used by
the public asset pipeline; the generated copy is ignored.

## Proof commands

```
npm ci
uv sync --all-groups
npm run typecheck
npm run test -- --run
uv run pytest
npm run build
npm run test:e2e
```

The browser test runs the built Vite SPA and API from the full FastAPI server. It proves API
delivery, visible Product dimensions and north-wall contact, orbiting, LODs,
same-origin decoder and compressed asset requests, missing-texture fallback,
attribution links and API-down Retry recovery. Screenshots are kept
in `test-results/screenshots/`.
