# 12 — HUMAN: replace the placeholder unit with a real traced floorplan

Type: HUMAN
Blocked by: 01

## Stories delivered
- Enables every buyer-facing story to be true of an actual apartment rather than an
  invented one.

## Reviewable end state
The gallery shows a real unit type from the apartment cluster. Open it and the outline,
room sizes, ceiling height, door positions and window positions match the real
apartment. Stand a 2.10m sofa against the living room wall and the proportions look
right to someone who has been inside the flat.

## Notes
Needs a human because it needs the developer's floorplan, real dimensions, and judgement
about what the drawing actually means. An agent cannot obtain or sanity-check any of
that.

What to produce: one seed JSON matching the schema locked in issue 01 — outer polygon,
interior partition walls, named room regions, wall openings with positions and widths,
ceiling height. Coordinates in metres.

Worth knowing while doing it:

- **Developers' drawings lie**, usually by the thickness of the plaster. If anyone can
  get into a finished unit with a laser measure, check the two or three dimensions that
  decide whether a wardrobe or a three-seater fits, and trust the tape over the PDF.
- Get the **ceiling height** explicitly; it is rarely on a floorplan and it decides
  whether tall wardrobes are viable.
- Note which units are **mirrored** across the corridor. v1 does not need to handle it,
  but the tracer tool post-v1 will, and knowing early shapes that design.
- No permission from the developer is required — that risk was struck.

The unit-type count for the whole cluster is still unknown. That is fine: v1 ships one.
It only becomes urgent when the floorplan tracer tool is prioritised post-v1, and the
count is what will decide how much that tool is worth.

This ticket also validates the issue-01 schema against reality. If the real plan cannot
be expressed in it, that is a schema bug worth fixing now rather than after ten units
are traced.
