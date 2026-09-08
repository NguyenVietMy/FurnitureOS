# Room geometry comes from the Capture, not a floor-plan editor

A Room Shell is built from the user's Capture rather than drawn by hand, but the work is split by what each party is actually good at: a vision model reads **semantics** from the photos (which wall has the window, where the door is and which way it swings, whether Detected Furniture is present), the user picks the **topology** from a small set of shapes, and **scale** comes from typed dimensions confirmed in a numeric step. The model is never the tape measure.

## Considered options

- **A floor-plan editor.** The obvious, reliable answer, and the reason this ADR exists — a future reader will see a vision pipeline and ask why we didn't just let people draw a rectangle. Drawing produces correct geometry every time, but it discards the photo, and the photo is both the product's hook and the only available source of Opening semantics and Style context. An editor also asks the user to do the tedious half of the job while the model does the easy half.
- **Full photo-to-geometry inference.** Where this design started, and rejected on physics rather than model quality. Photographs are scale-ambiguous: a dollhouse and a bedroom produce identical images, so absolute size cannot be recovered from pixels without a reference. A single photo also cannot see the whole room — shot from a doorway you get the far wall, slices of two side walls, and nothing of the wall behind you, so a headboard would be placed against a wall the camera never observed. Wrong metric geometry is the one error class that poisons a spatial planner, where correctness is the entire differentiator.

## Consequences

Wrong *scale* is recoverable — the numeric confirm step exists precisely to catch it, and scale is what silently corrupts every downstream fit decision. Wrong *topology* is not: if inference and the shape picker between them produce the wrong room outline, there is no repair path in v1, because the geometry editor is deferred rather than rejected. Multi-photo capture (roughly one per wall) is required, not optional, since single-photo coverage cannot see a whole room.
