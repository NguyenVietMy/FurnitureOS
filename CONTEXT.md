# FurnitureOS

A web app that turns photos of a real room into a furnished 3D scene, where every piece of furniture shown is a real product that exists and can be bought.

## Language

### The space

**Room**:
The real physical space a user wants furnished. Always modelled at real-world scale.
_Avoid_: Space, scene, area

**Room Shell**:
A Room's structure: floor polygon, wall segments, and ceiling height. Carries no furniture.
_Avoid_: Geometry, walls, box

**Opening**:
A window or door in a wall segment. A door Opening carries its swing arc, because the swing constrains what can be placed near it.
_Avoid_: Hole, aperture, gap

**Room Type**:
The function a Room serves — bedroom or living room. Declared by the user, never inferred. Determines which Products are eligible and which Placement Intents apply.
_Avoid_: Category, room kind, space type, purpose

**Capture**:
The set of photos a user takes of their Room, from which the Room Shell and its Openings are inferred.
_Avoid_: Upload, scan, photoshoot

**Detected Furniture**:
Furniture recognised in a Capture. It is never reconstructed or placed — it exists only so the user can be told that their Design assumes an empty Room.
_Avoid_: Existing furniture, current furniture

### The output

**Design**:
A Room Shell furnished with Placements. The thing a user comes to FurnitureOS to get.
_Avoid_: Layout, render, mockup, plan, result

**Placement**:
One Product positioned and rotated within a Room, constrained by the Room Shell and its Openings.
_Avoid_: Position, arrangement, spot

**Zone**:
A named region of a Room — seating, sleeping, storage, circulation — derived from the Room Shell and its Openings before generation begins. Zones are computed from geometry and offered to the generator; they are never invented by it.
_Avoid_: Area, region, section, spot

**Variant**:
One of the alternative Designs produced by a single generation, between which the user chooses.
_Avoid_: Option, version, alternative, candidate

**Placement Intent**:
A desired spatial relationship between a Product and the Room Shell, expressed without coordinates. Intent is what taste produces; a Placement is what geometry resolves it into.
_Avoid_: Hint, suggestion, constraint, rule

**Swap**:
Replacing the Product in an existing Placement with another whose footprint fits the same slot. A Swap never moves anything, so it can never invalidate a Design.
_Avoid_: Replace, substitute, change

**Nudge**:
A user-initiated move of an existing Placement. Unlike a Swap, a Nudge must be validated by the FastAPI authority before it is accepted. A future browser preview must have an explicit parity contract; it is not an authority.
_Avoid_: Drag, move, reposition

### The furniture

**Product**:
A real furniture item that exists in the world: real-world dimensions, a Mesh, descriptive metadata, and a link to where it can be bought.
_Avoid_: Item, furniture, SKU, model, piece

**Mesh**:
The 3D geometry and materials used to draw a Product. A Mesh represents a Product; it is not a photograph of one.
_Avoid_: Model, asset, object, 3D

**Catalogue**:
The finite set of Products a Design can be assembled from. Designs are built by selecting from the Catalogue, never by inventing furniture.
_Avoid_: Inventory, database, library, feed

**Style**:
The visual direction a user picks for a Design. Chosen by pointing at images, not by naming a style.
_Avoid_: Theme, aesthetic, vibe, taste
