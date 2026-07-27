# 14 — HUMAN: source the preset 3D model set

Type: HUMAN
Blocked by: 03

## Stories delivered
- Turns the placeholder boxes into recognisable furniture, which is what makes the
  planner worth sharing.

## Reviewable end state
Drag a sofa in and it looks like a sofa, not a grey box. Every catalogue item resolves
to a preset that reads correctly at a glance, sitting on the floor at the right size and
facing the right way.

## Notes
Needs a human to source, commission or buy the assets and to judge whether they look
right.

Deliver roughly fifteen to twenty `.glb` presets covering the archetypes the catalogue
uses: sofa (2- and 3-seat), armchair, dining chair, dining table, coffee table, side
table, desk, bed (single and double), nightstand, wardrobe, bookshelf, TV stand, floor
lamp, rug, plant.

Technical requirements, because getting these wrong is where the time goes:

- **Y-up, origin at the centre of the footprint, sitting on the floor plane** — a model
  with its origin at the centre of mass floats or sinks when placed.
- **Facing +Z** consistently, so rotation is predictable across the whole set.
- Modest polygon counts and baked or simple materials. Desktop-only relaxes the budget,
  but the whole apartment renders at once, so a scene can hold thirty of these.

**They will be stretched.** Each preset is scaled non-uniformly to each item's true
dimensions, by decision — drawn size must equal collision size must equal delivered
size. So choose or commission models that survive stretching: avoid ones whose charm
depends on exact proportions, and prefer neutral, well-proportioned shapes at roughly
the median size of the items that will use them, to keep distortion small in both
directions.

If a hero item ever deserves better, the `loadPresetScaled` seam already accepts a
custom per-item `.glb` with no schema change — that is a post-v1 upgrade path, not work
for this ticket.

Until this lands, issue 03's primitive-box fallback keeps everything functional, so
nothing downstream is blocked waiting on assets.
