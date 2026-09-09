# Landing verification

Current Vite integration results: [integration evidence](integration.md). Everything below records earlier landing deliveries; source paths, runtimes and commands are historical.

## September 9, 2026: exact reference width restored

The user rejected the wider experiment below and requested Superwall's exact width behavior, retaining the borderless navbar. Inspected the live [Superwall homepage](https://superwall.com/) CSS and `main.site-frame` bounds: `width: min(90%, var(--content-max))`, cap `1280px`, increasing to `1440px` at `min-width: 96rem`; width becomes `100%` at `max-width: 639px`. FurnitureOS now uses these same width rules. `DESIGN.md` is updated; the navbar still spans the viewport with zero side borders.

Live browser measurements matched exactly for both sites:

| Viewport | Frame width | Left gutter |
| --- | --- | --- |
| 390 | 390 | 0 |
| 639 | 639 | 0 |
| 640 | 576 | 32 |
| 768 | 691.1875 | 38.40625 |
| 1440 | 1280 | 80 |
| 1535 | 1280 | 127.5 |
| 1536 | 1382.390625 | 76.796875 |
| 1920 | 1440 | 240 |

[Updated desktop screenshot](reference-width-desktop.png), captured from the live development preview. Typecheck, production build, and all 24 Chrome E2E tests passed, including frame geometry, borderless navigation, and overflow checks at all eight widths. Original delivery approvals/manifests and the wider experiment below remain historical records, not current measurements.

## September 9, 2026: wider frame and unframed navigation

User-approved adjustment: desktop content now uses `min(1600px, calc(100% - 64px))`; the sticky header spans the viewport with zero side borders, while its inner row aligns with the content. Tablet retains `90vw` and mobile retains full-width content. `DESIGN.md` records the updated rule.

Verified frame width/x: 390px viewport = 390/0; 768px = 691.2/38.4; 1440px = 1376/32; 1920px = 1600/160. All four widths have a viewport-wide header, zero header side borders, and no horizontal overflow. Typecheck, production build, and all 16 Chrome E2E tests passed. Screenshots: [updated desktop](wider-desktop.png), [mobile](wider-mobile.png), captured from the live development preview. Its Next.js development indicator is not part of the production UI.

The original measurements, score, manifests, and independent inspection below are historical evidence for the September 8 snapshot, not approval or byte hashes for this later adjustment.

## Original September 8 delivery

September 8, 2026. Coordinator independently ran `npm run typecheck`, `npm run build`, and `npm run test:e2e` in the isolated build checkout: all passed, including9 production-browser tests on installed Chrome. Build prerenders `/` and `/icon.svg`. Final delivery proof is recorded below after transfer.

## Visual comparison

Evidence: [desktop](desktop.png), [mobile](mobile.png), [tablet](tablet.png), [feature rows](features.png), [full page](full-page.png), [raw computed measurements](measurements.json). Production screenshots use CSS pixels at1440x1000,390x844,768x1024. Fonts were loaded and all local photographs decoded before full-page capture, which avoids the lazy-image gaps in the reference full-page capture. Reference files are in [../reference](../reference/README.md).

The approved20-check worksheet gives5 points for each passing item. This is design-system conformance, not a claim of100% pixel similarity. Text, brand, photographic/schematic content, shortened page length, and replacement of customer/pricing claims with truthful product concepts are intentional differences.

| # | Check | Observed evidence | Points |
| --- | --- | --- | --- |
| 1 | Desktop frame1280px atx80 | 1280px atx80 | 5 |
| 2 | Announcement33px/header65px | 33px/65px; sticky | 5 |
| 3 | Hero532px/heading max1024px | 532px; computed max-width1024px | 5 |
| 4 | Spacer64px,5:7 split,32/48px padding | 64px;532.5/745.5px columns;32/48px horizontal padding | 5 |
| 5 | Manrope500 hero | Loaded Manrope,500 | 5 |
| 6 | Hero88/83.6/-4.4px | Exact computed values | 5 |
| 7 | Large title80/80; feature28/30.8 | Exact computed values | 5 |
| 8 | Mobile48/.95; body16-18 | 48/45.6px; body16px | 5 |
| 9 | Paper/ink/border tokens | #fdfef6/#0c0b0a/#e2e4d0 | 5 |
| 10 | Cyan/deep-cyan/navy | #67edec/#46d7d4/#29407c | 5 |
| 11 |10x55px construction grid | Exact grid tokens and one-pixel rules; visible in fold images | 5 |
| 12 |20px corners and dither texture |20x20px brackets; visible six-pixel dot pattern | 5 |
| 13 |672x74px hero pill |672x74px | 5 |
| 14 | Four equal62px tabs/dividers/teal rule | Four319.5x62px tabs, teal selected rule | 5 |
| 15 | Square black nav CTA/structural rules |40px-high rectangular CTA; thin framed sections; no rounded marketing cards | 5 |
| 16 | Framed preview/grid/56px surround |56px surround; desktop screenshot | 5 |
| 17 | Dark CTA/blue band/four-column comparison | Full-page screenshot; four319.5px workflow columns | 5 |
| 18 | Six split features/gallery/FAQ/footer | Six source and rendered rows; feature/full-page screenshots | 5 |
| 19 |390px two-row nav/2x2 tabs/stacked features |93px header;195px-wide2x2 tabs;390px single feature column | 5 |
| 20 | No overflow and readable hierarchy at three widths | Browser tests and computed measurements pass390/768/1440; screenshots reviewed | 5 |

Total:100/100 measured conformance; required minimum90. Independent code/accessibility inspection remains a separate gate and can require fixes even when this visual checklist passes.

## Inspection and delivery

Initial independent inspection identified a missing hero-select keyboard-focus ring and an overlap between the bed and chair in bedroom Variant B. Both were corrected by Sol in fix round 1. The coordinator independently reran typecheck, production build, and all 11 browser tests successfully. New regressions verify the actual focus outline and transformed SVG bed/chair bounds across all three bedroom Variants, including unchanged chair Placement.

Production evidence: [restored keyboard focus](keyboard-focus.png) and [corrected bedroom Variant B](bedroom-variant-b.png). Computed focused outline is `rgb(68, 107, 206) solid 3px`.

Fresh final inspection round 2: **APPROVED**, no unresolved material findings. Inspector independently ran typecheck, production build and all 11 tests, and verified all 27 source hashes before and after inspection. [Full review log](../PLAN-REVIEW-LOG.md).

Delivery integrity: all 27 files match the approved [source manifest](source-manifest.json), SHA256 `FE329E1C3D63228397F20A01258977C50953739A4D82B6D072A3B2C19A24476C`. The [delivery manifest](delivery-manifest.json) confirms byte equality after the final proof. All 85 protected pre-existing skill/GUIDE files were unchanged.

The coordinator ran these commands from the main FurnitureOS checkout, not the isolated review worktree:

```powershell
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run test:e2e
```

All passed: 34 installed packages, zero reported npm audit vulnerabilities, successful static production build, and 11/11 Chrome tests. The test server used port 3100 with reuse disabled. Production preview was then launched from the main checkout with `npm --prefix web run start` on port 3000 and checked in the browser.

Non-blocking environment warnings: Next ignored a pre-existing home-directory package-lock outside this Git repository; Playwright reported NO_COLOR/FORCE_COLOR precedence. Neither warning affected proof results. No unrelated home files or configuration were changed. Testing was Chrome-only, not an exhaustive accessibility or security audit. No commit, push, or public deployment was made.
