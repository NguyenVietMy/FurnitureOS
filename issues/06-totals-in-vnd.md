# 06 — Per-room and whole-apartment totals in VND

Type: AFK
Blocked by: 03

## Stories delivered
- As a buyer, I can move between the rooms of my unit and see one running total across
  the whole apartment, so that I'm budgeting for a home and not for a sofa.

## Reviewable end state
Place items in the living room and a bedroom. A panel shows a subtotal per room and one
grand total for the apartment, formatted as `12.500.000 ₫`. Pick a room from a selector
and the camera flies to it and the catalogue scopes to that room; the totals panel keeps
showing everything. Move an item from one room to the other and watch both subtotals
correct themselves.

## Notes
Two pieces of real work hide behind a simple-looking feature.

**`lib/money`** — VND is an integer currency with no fractional unit. Prices are
`BIGINT` everywhere and there is no float path in either language; a `numeric(10,2)`
column would be wrong. Formatting uses dot thousands separators and a trailing `₫`.
Language is English, currency is VND — the two are independent.

**Room attribution** — which room is an item "in"? Answer by point-in-room-region test
against the named room polygons from the unit JSON, reusing `lib/geometry` rather than
writing a second containment routine. Decide and document the rule for an item
straddling a boundary (recommend: the region containing the item's centre).

**Room selector** — focuses the camera on a room and scopes the catalogue/bundle panel.
It does not swap the scene; the whole apartment stays rendered (settled decision).

`planTotals(plan, catalogue)` lives in `lib/plan` as a pure function so it is testable
without a scene and reusable by issue 08's quote view.

Can be built in parallel with issues 04 and 05.

Test boundary: Vitest — VND formatting and the absence of any float arithmetic; room
attribution including the straddling case and an item outside every named region;
`planTotals` grouping with mixed quantities.
