# Single-frontend integration evidence

September 9, 2026. Landing `/` and Room `/design` now share one root Vite package. This record supersedes historical `web/` startup instructions while retaining the original reference captures, credits and delivery manifests. Architecture and commands: [frontend guide](../../frontend.md).

## Preservation and measurements

The authoritative inputs were the host's frozen `main-before/source` landing and `refactor-before/source` approved Room. The latest main frame rules, borderless navigation, hidden scrollbar, colors, copy and concept interactions were retained. The 171 main workflow/agent/guide files match their snapshot hashes; all ten Product files match the approved Room snapshot. ADRs 0001–0003 had only line-ending differences between inputs, so main's exact bytes were retained. The refactor's FastAPI ADR, domain glossary and build plan remain authoritative.

Fresh captures were opened and visually checked: [desktop](integration/landing-1440.png), [mobile](integration/landing-390.png), [tablet](integration/landing-768.png), [full page](integration/landing-full.png), [FAQ](integration/landing-faq.png), [footer](integration/landing-footer.png), [Room desktop](integration/room-1440.png), [Room mobile](integration/room-390.png). Compare the desktop with [latest main frame evidence](reference-width-desktop.png), mobile with [approved mobile](mobile.png), and composition with the [original references](../reference/README.md).

[Computed measurements](integration/measurements.json) compare the integrated page with the frozen original stylesheet applied to the same migrated DOM, with added preview links removed. This CSS baseline is supporting evidence, not a newly rebuilt Next.js app. At 390/768/900/901px all recorded geometry/type/token measurements match; at 1440/1920px only navigation width differs because of the added Room link. The 901–1100px desktop navigation omits that extra link to preserve existing spacing; the sample dialog and footer still link to the real preview. Mobile also has the preview link in its menu.

The twenty binary DESIGN.md checks score **100/100** (minimum 90). This is design conformance, not pixel similarity or a substitute for host inspection.

| # | Check | Fresh evidence | Points |
| --- | --- | --- | --- |
| 1 | Frame and header geometry | 1440: 1280px at x80; 1920: 1440px at x240; header viewport-wide with no side borders | 5 |
| 2 | Announcement/header | 33px / 65px desktop; sticky header preserved | 5 |
| 3 | Hero and heading cap | 532px hero; 1024px heading max-width | 5 |
| 4 | Rhythm and split | 64px section token; 532.5/745.5px feature columns, original 32/48px padding | 5 |
| 5 | Typeface | Local Manrope Variable, loaded 500 weight | 5 |
| 6 | Hero typography | 88px / 83.6px / -4.4px desktop | 5 |
| 7 | Section/feature type | 80px / 80px section; 28px / 30.8px feature | 5 |
| 8 | Mobile typography | 48px / 45.6px hero; 16px body | 5 |
| 9 | Base palette | Exact #fdfef6, #0c0b0a, #e2e4d0 | 5 |
| 10 | Accents | Exact #67edec, #46d7d4, #29407c | 5 |
| 11 | Grid | 10px × 55px, visible one-pixel lines | 5 |
| 12 | Corners/pattern | 20px brackets and unchanged visible dither gradients | 5 |
| 13 | Hero control | 672px × 74px | 5 |
| 14 | Tabs | Four 319.5px × 62px tabs, dividers and selected rule | 5 |
| 15 | CTA/structure | Square black 40px nav CTA and unchanged section borders | 5 |
| 16 | Preview surround | 56px desktop padding | 5 |
| 17 | Bands/comparison | Dark CTA, navy patterned band, four-column workflow visible in full capture | 5 |
| 18 | Composition | Six split feature rows, gallery, FAQ, footer and wordmark | 5 |
| 19 | Compact layout | 93px two-row header, 195px two-column tabs, stacked features at 390px | 5 |
| 20 | Responsive readability | Original eight overflow checks pass; frame/page-width checks also cover 900/901px | 5 |

## Verification

All commands run from the integration checkout root. `npm ci` passed (192 packages, zero audit vulnerabilities); `npm run typecheck` passed including OpenAPI freshness; `npm run test -- --run` passed eight asset tests; `uv run pytest` passed 149 tests (the original 140 plus nine static/deep-route cases); `npm run build` passed; `npm run assets:report` passed at exactly 1,298,091 Product bytes. `npm run test:e2e` passes 38 Chromium tests against a fresh production-mode FastAPI server: 24 accepted landing cases, two extra boundary frame cases, three accepted Room cases, eight integration cases and one screenshot case.

Browser coverage proves direct `/design` and `/design/` refresh, app links, back/forward, feature style restoration, route metadata, local WOFF2 delivery, accessible unknown/loading/error states, missing assets/API 404, sample focus restoration and mobile navigation. A fresh landing visit and concept Swap request no Room code, 3D runtime, preview API, Product files or decoders. Room checks prove runtime mesh dimensions, north-wall contact, orbit, all three LODs, texture fallback, API Retry, attribution and accepted four-viewport canvas bounds. An additional live Vite probe on port 5175 compared its proxied API JSON with FastAPI on 3102 and rendered the correct Product with `fits` status.

The initial expanded diagnostic run found a 9px heading content-box overrun at 901px. Applying the frozen stylesheet reproduced exactly the same 277px client width / 286px scroll width. The original eight heading checks remain unchanged; the new 900/901 checks assert frame and page-wide overflow preservation. No approved typography was altered to conceal this inherited limitation.

## Migration differences and limits

Fonts use the exact same Fontsource 5.3.0 Latin WOFF2 filenames, weights and swap behavior, with explicit family names instead of generated next/font names. Images use the same original JPEG bytes and fill/object-fit rules; Next image optimization/resizing and its development indicator are gone. Metadata updates in the browser; the initial static HTML contains landing metadata. The sample remains illustrative, with explicit links to the separate real Room preview.

The inherited Room crop at 901×1000 is unchanged. Browser proof uses Chromium/SwiftShader and CSS viewports; it does not claim physical touch-device or cross-engine coverage. Vite reports the existing large lazy RoomCanvas chunk advisory, and Starlette reports an upstream AnyIO deprecation warning. Neither is suppressed. Very tall SwiftShader landing captures repeated compositor tiles; the dedicated capture test uses `--disable-gpu`, and the clean 9,629px full-page artifact was viewed through the footer. Room tests continue to use SwiftShader.

Vercel routes were updated in source to preserve the API and return 404 for missing asset files; this worker did not deploy, mutate project settings, commit or promote anything. Host inspection and drift-checked transfer into main remain separate delivery steps.
