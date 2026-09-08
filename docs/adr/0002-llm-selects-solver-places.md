# The LLM selects furniture; a deterministic solver places it

Generating a Design is split in two: an LLM chooses Products from the Catalogue and emits Placement Intent — spatial relationships expressed without coordinates — and a deterministic solver resolves that intent into actual Placements, enforcing collisions, clearances, and door swings. The LLM never emits coordinates.

## Considered options

- **Ask the LLM for coordinates directly.** The obvious 2026 instinct and the reason this ADR exists. Language models place objects in continuous 3D space poorly; the failure modes are overlapping furniture and beds intersecting walls, which are exactly the errors that destroy trust in a spatial planner.
- **Templates or pure optimisation, with no LLM.** Both produce valid geometry, and both produce visibly repetitive or soulless rooms. Taste is the half a language model is actually good at.

## Consequences

Placement Intent is a bounded vocabulary: anything the LLM can express, the solver must implement. Widening it is a change to both halves. When intent is unsatisfiable the solver reports back and the LLM re-selects, up to two rounds, after which the Product is dropped from the Design.
