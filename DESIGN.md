# FurnitureOS design system

This is the UI source of truth for FurnitureOS. Read it before adding, changing, or reviewing UI. Domain meaning remains authoritative in `CONTEXT.md`; asset credits live in `docs/landing/assets.md`.

## Direction and provenance

The landing system adapts the visual grammar of the September 8, 2026 light-theme `superwall.com` captures in `docs/landing/reference/`: an ivory framed canvas, editorial scale, visible construction grid, thin borders, split feature rows, and pixel-textured accents. FurnitureOS owns the copy, diagrams, interaction model, and imagery. Reference captures are comparison evidence, never page assets.

Aim for precise structure rather than ornamental approximation: square marketing sections, continuous frame lines, large unembellished type, dense internal product UI, and patterned color bands. Rounded corners belong to calls to action and internal preview UI, not floating marketing cards.

## Tokens

Define landing tokens on `html[data-feature="landing"]` in `src/features/landing/landing.css`; components consume these names rather than introducing parallel aliases. `src/app/App.tsx` selects the route scope so these tokens and resets remain isolated from the Room preview.

| Token | Value | Role |
| --- | --- | --- |
| `--color-paper` | `#fdfef6` | Page and framed-grid ground |
| `--color-ink` | `#0c0b0a` | Primary text, dark controls, hard edges |
| `--color-muted` | `#66665e` | Supporting copy |
| `--color-border` | `#e2e4d0` | Structural rules and grid lines |
| `--color-cyan` | `#67edec` | Primary accent and CTA fill |
| `--color-cyan-deep` | `#46d7d4` | Selected rules and CTA edge |
| `--color-teal-ink` | `#143e3d` | Text and diagrams on cyan |
| `--color-navy` | `#29407c` | Blue feature-band ground |
| `--color-periwinkle` | `#446bce` | Blue-band depth and focus outline |
| `--color-orange` | `#ff7b55` | Sparse numeric emphasis |
| `--content-max` | `1280px` | Content cap; `1440px` at `96rem` (1536px with default browser settings) |
| `--frame-width` | `min(90%, var(--content-max))` | Main framed canvas; `100%` at viewport widths up to `639px` |
| `--grid-x` | `10px` | Construction-grid column |
| `--grid-y` | `55px` | Construction-grid row |
| `--section-gap` | `64px` | Desktop section rhythm; `48px` at `640px` |
| `--line` | `1px solid var(--color-border)` | Shared structural border |

Manrope Variable is the display/body face through `--font-manrope`; Roboto Mono is the label/data face through `--font-roboto-mono`. Both are self-hosted from the same licensed Fontsource Latin WOFF2 files through `@font-face` in `src/app/global.css`, emitted locally by Vite, with system fallbacks.

Type is deliberately tight: the desktop hero is `88px / 83.6px`, weight `500`, tracking `-4.4px`; large section headings are `80px / 80px`, tracking `-4px`; feature headings are `28px / 30.8px`. At the `900px` intermediate breakpoint the hero becomes `72px / 68.4px`. At `640px`, use a `48px / .95` hero and `46px / .98` section headings. Mono labels remain small and functional, normally `9–11px`.

## Layout grammar

- **Frame:** center primary sections on `--frame-width`, matching Superwall's live `.site-frame` width rule verified September 9, 2026. At a 1440px viewport the frame is 1280px wide at x=80; at 1920px it is 1440px at x=240. At 640px it is 576px at x=32; below 640px it is full width. Side borders begin at the hero below navigation and remain continuous through content. The user rejected the intermediate 1600px cap/32px-gutter experiment; retain the reference's responsive caps and borderless navigation.
- **Grid:** `.framed-grid` uses 10px columns, 55px rows, and one-pixel border-colored lines. Hero corners use four 20px black brackets. Grid and pattern remain visible behind content without reducing legibility.
- **Rhythm:** separate major framed compositions by `--section-gap`. Use borders, spacing, and background changes to group content rather than generic shadows or cards.
- **Split:** desktop feature and FAQ rows use `5fr 7fr`. Feature copy has 32px horizontal padding and the visual panel 48px; feature rows and section intros stack to one column at `900px`.
- **Responsive:** `900px` stacks split content and adjusts type/navigation. `640px` is the compact control breakpoint: two-by-two tabs and stats, tighter section padding, and compact controls. Frame width becomes full bleed at `639px`, independently of those control styles; its large-screen cap changes at `96rem`. The page remains scrollable while its visual scrollbar is hidden to match the reference. Validate widths on both sides of each frame breakpoint as well as 390px, 768px, 1440px, and 1920px.

## Component recipes

- **Announcement and navigation:** pair the 33px cyan announcement with a sticky 65px desktop header. The header spans the viewport with only a bottom divider; its inner row aligns to `--frame-width`. The wordmark belongs to this unframed navigation area, outside the content's side borders. Mobile uses a sticky 93px two-row header. The principal navigation CTA is a square-cornered, black, 40px-high mono control.
- **Hero:** use a fixed 532px desktop grid field, centered two-line heading, 18px supporting copy, and a 672px by 74px pill control. On mobile the field is 557px and the pill is 62px high. Preserve the four corner brackets.
- **Dither CTA:** combine cyan fill, deep-cyan edge, fully rounded shape, fine six-pixel dot texture, and dark teal text. Prefer this CSS pattern to raster effects or shaders.
- **Tabs and preview:** four equal 62px tabs use dividers and a deep-cyan selected rule; mobile forms a two-by-two grid. The preview keeps a 56px desktop grid surround. Rounded internal windows are appropriate because they depict product UI.
- **Marketing sections:** use bordered grids, editorial columns, and six repeated split feature rows. Dark and navy patterned bands interrupt the ivory canvas; the footer ends with an oversized wordmark motif.
- **Sample dialog:** keep the native dialog square and information-dense, with an obvious close control, disclosure, Room Type and Variant controls, schematic, and Swap control. All repeated sample CTAs open this same flow.

## Domain and content integrity

Use the terms in `CONTEXT.md`. A Design furnishes one Room Shell with Placements; a Variant changes the arrangement within that same Room Shell. A Swap preserves its Placement and accepts only a fitting footprint. A Product means a real, dimensioned, purchasable Catalogue entry.

The current landing page presents product direction and an interactive concept, not an operational generator or Catalogue. Keep this disclosure visible wherever the preview can be understood as output:

> Interactive concept preview. Illustrative furnishings; no live Catalogue or room generation.

Schematic fixtures are “illustrative furnishings” or “sample concepts,” not Products. The demonstration chairs both use a `0.8 × 0.8m` footprint and retain `x:412; y:184; rotation:0` through Swap. Variants keep one Room Shell. Room photographs communicate Style inspiration only; credit them and never present them as generated Designs. Claims about live generation, availability, purchasing, customers, traction, pricing, or endorsements require real supporting evidence before publication.

## Accessibility and motion

Keep one `h1`, labelled landmarks, meaningful image alternatives, a visible skip link, and the existing three-pixel periwinkle `:focus-visible` outline. Inactive tab panels stay hidden and outside keyboard order; tabs support arrows, Home, and End. The dialog closes with its control or Escape and restores focus to its opener. Mobile navigation closes after selection and on Escape. Prefer native controls and `details`/`summary` semantics.

Motion supports orientation and yields to `prefers-reduced-motion`: disable smooth scrolling and collapse animation/transition durations for reduced-motion users. Color, borders, and text must carry every state without relying on motion alone.

## Validation gate

Compare Playwright captures at 1440x1000, 390x844, 768px, and full-page height with the references described in `docs/landing/reference/README.md`. Record measurements and evidence links. Score 20 binary checks at five points each; release requires at least 90/100.

| Category | Checks |
| --- | --- |
| Frame and geometry | At 1440px, 1280±2px frame at x=80±2; at 1920px, 1440±2px frame at x=240±2; viewport-wide header with zero side borders; 33±3px announcement and 65±4px header; 532±32px hero with computed heading `max-width: 1024px` (shorter FurnitureOS text may occupy less); 64±4px section rhythm and 5:7 split within two percentage points. |
| Typography | Loaded Manrope 500 hero; 88±1px / 83.6±2px / -4.4±.2px desktop hero; 80±2px section and 28±1px feature headings; 48±1px / .95±.03 mobile hero with 16–18px body. |
| Palette and patterns | Exact paper/ink/border tokens; exact cyan/deep-cyan/navy accents; 10x55±1px hero grid; 20±2px corner brackets and visible dither texture. |
| Components | 672±8px by 74±8px hero pill; four equal 62±4px tabs with dividers and selected rule; square black nav CTA, thin section borders, and no floating rounded marketing cards. |
| Composition | Preview with 56±8px surround; dark CTA, navy patterned band, and four-column comparison; six split features, editorial gallery/FAQ, spacious footer, and wordmark. |
| Responsive | At 900px and below, feature/intro columns stack; at 390px, navigation uses two rows and tabs use a two-by-two grid; at all three widths, no horizontal overflow and controls remain readable with hierarchy intact. |

Treat the score as design conformance, not pixel similarity. Explain intentional differences caused by FurnitureOS copy, imagery, truthful proof replacements, and open-source fonts. A CSS or component change is complete only when affected checks are remeasured and accessibility interactions still pass.
