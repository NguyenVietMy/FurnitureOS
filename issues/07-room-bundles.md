# 07 — Room bundles that furnish a room in one click

Type: AFK
Blocked by: 04, 06

## Stories delivered
- As a buyer, I can drop a room bundle ("Living Essentials") and have it place itself
  sensibly, so that I get from an empty room to a furnished one in seconds.

## Reviewable end state
Open an empty unit, select the living room, click "Living Essentials — 3.200.000 ₫".
The room fills with a sensible arrangement of real catalogue items, nothing overlaps,
nothing is inside a wall, and both the room subtotal and the grand total jump. Then drag
those items around freely — a bundle is a starting point, not a locked layout.

## Notes
This is the answer to the blank-page problem: an empty room converts badly.

**Bundles are item lists, not fixed layouts.** They carry no coordinates. On insert,
each item is placed via `findFreeSpot` (issue 04) against the target room region. This
is what lets one authored bundle work across differently shaped rooms and, later, across
different unit types.

Vertical slice: `bundles` table (name, room type, item ids with quantities) + seed data
+ `GET /api/bundles?room_type=` + an `addBundle` action on the `lib/plan` reducer + the
bundle strip in the room panel showing each bundle's headline price.

Blocked by 04 because auto-placement needs real collision, and by 06 because a bundle's
headline price and the total update are the whole point of the interaction.

If a room is too small to fit an entire bundle, place what fits and tell the buyer
plainly which items were skipped. Do not silently drop them and do not overlap them.

Note for later: whole-apartment packages ("Scandi", "Warm Minimal") were explicitly
rejected in favour of room-level bundles. Do not reintroduce them.

Test boundary: Vitest on the reducer — inserting a bundle produces N non-overlapping
placements all reporting `canPlace === true`; a too-small room yields a partial
placement with an explicit skipped list; totals reflect the insert.
