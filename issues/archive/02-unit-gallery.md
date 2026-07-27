# 02 — Unit gallery: browse layouts and open yours

Type: AFK
Blocked by: 01

## Stories delivered
- As a buyer, I can browse a public gallery of unit layouts and open mine, so that I
  never have to measure or draw my own apartment.

## Reviewable end state
Land on the site root with no login. See a grid of layout cards — name, bedroom count,
floor area, a top-down thumbnail of the outline. Click one and the 3D unit from issue
01 loads. Back button returns to the gallery.

## Notes
This is the front door of the funnel and it is deliberately public: no code, no unit
number lookup, no verification.

Vertical slice: `GET /api/units` list endpoint returning display metadata (slug, name,
bedrooms, area m²) + gallery route in `app/(buyer)/` + navigation into the plan route.

Area and bedroom count are derived from the unit JSON rather than stored separately —
one source of truth. Thumbnails render from the outline polygon (a small 2D SVG of the
room regions is enough; do not screenshot the 3D scene).

With one seeded unit the gallery is a grid of one. That is fine and expected — it still
proves the route, the list endpoint and the navigation. It becomes real when issue 12
lands and again when the tracer tool exists post-v1.

Test boundary: list-endpoint shape in pytest; derived metadata (area from polygon) as a
pure function in Vitest.
