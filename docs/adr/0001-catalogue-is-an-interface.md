# The Catalogue is an interface, not a dataset

The demo is built on Amazon Berkeley Objects, which is licensed CC BY-NC 4.0 and therefore cannot survive the app becoming commercial. Rather than treat that as a future migration, we define `Catalogue` as an interface from day one — a Product is a mesh, real-world dimensions, metadata, Style tags, and a purchase URL — and ABO is merely the first implementation of it.

## Considered options

- **Build directly against ABO's schema.** Faster now, but every downstream component would encode a schema we already know we must abandon, and the migration would touch the generator, the solver, and the renderer at once.
- **Start on a commercially licensed catalogue.** No retailer offers commercially licensable 3D models of purchasable furniture. The only documented external 3D API is Wayfair's, which requires a negotiated licence and exposes ~200 models publicly. Not available on a demo timeline.

## Consequences

The purchase URL is part of the Product shape even though affiliate linking is deferred, so the slot exists unused rather than being added later. Nothing outside the Catalogue implementation may read ABO-specific fields.
