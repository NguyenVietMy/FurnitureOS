# 13 — HUMAN: replace placeholder items with the real catalogue

Type: HUMAN
Blocked by: 03

## Stories delivered
- Makes every price, dimension and product name in the app real, which is the whole
  premise of the product.

## Reviewable end state
The catalogue panel lists roughly twenty items you actually sell, with their real names,
real prices in VND and real dimensions. A buyer who furnishes a living room gets a total
they could walk into the shop and pay.

## Notes
Needs a human: only you know what you stock, what it costs and what it measures.

For each item: name, category, true width × depth × height in metres, price as a whole
number of VND, a product photo, and which preset archetype it maps to (issue 14 defines
the preset list).

The two things that matter most:

- **Dimensions must be true.** The entire value proposition is "it fits". A sofa entered
  10cm narrow is a delivery-day argument. Measure the actual furniture rather than
  copying a spec sheet where there is any doubt.
- **Prices are whole VND integers.** No decimals anywhere.

Deliberately excluded, so don't collect them:

- **Colour and finish variants.** One item, one look, by decision. If you sell the same
  sofa in three fabrics, pick the one to show and leave it there.
- **Stock levels.** The columns exist in the schema but nothing renders them in v1, so
  filling them in is optional and changes nothing on screen.

Seed roughly twenty items for v1. The catalogue panel is already built to handle around
a hundred, so growing it later is data entry, not development — but that entry stays
manual until the catalogue admin UI is built post-v1, which means for now every price
change is a seed edit and a deploy. Worth knowing before you decide how many items to
load.
