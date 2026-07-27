/**
 * Catalogue filtering, tested away from the panel that draws it.
 *
 * Twenty items today and a hundred at the ceiling this panel is built for, so filtering
 * happens in the browser — no round trip per keystroke. That makes it a pure function
 * over an array, and pure functions get tested.
 */

import { describe, expect, it } from "vitest";

import { ALL_CATEGORIES, categoriesOf, filterItems } from "./filter";
import type { Item } from "./types";

function item(overrides: Partial<Item> & Pick<Item, "id" | "name" | "category">): Item {
  return {
    width_m: 1,
    depth_m: 1,
    height_m: 1,
    price_vnd: 1_000_000,
    preset_ref: "box",
    photo_url: null,
    ...overrides,
  };
}

const CATALOGUE: Item[] = [
  item({ id: "bed-double", name: "Double bed, 1.6m", category: "beds" }),
  item({ id: "rug-wool-large", name: "Wool rug, 2.4 × 1.7m", category: "decor" }),
  item({ id: "sofa-3-linen", name: "Linen 3-seat sofa", category: "seating" }),
  item({ id: "armchair-reading", name: "Reading armchair", category: "seating" }),
];

describe("categoriesOf", () => {
  it("lists each category once, in the order the catalogue arrives", () => {
    expect(categoriesOf(CATALOGUE)).toEqual(["beds", "decor", "seating"]);
  });

  it("is empty for an empty catalogue, rather than inventing a chip", () => {
    expect(categoriesOf([])).toEqual([]);
  });
});

describe("filterItems", () => {
  it("returns everything when nothing is asked for", () => {
    expect(filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "" })).toEqual(CATALOGUE);
  });

  it("narrows to one category", () => {
    const filtered = filterItems(CATALOGUE, { category: "seating", query: "" });

    expect(filtered.map((found) => found.id)).toEqual(["sofa-3-linen", "armchair-reading"]);
  });

  it("matches a name regardless of case", () => {
    const filtered = filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "LINEN" });

    expect(filtered.map((found) => found.id)).toEqual(["sofa-3-linen"]);
  });

  it("matches partway through a word, because buyers type 'sofa' not 'Linen 3-seat'", () => {
    const filtered = filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "sofa" });

    expect(filtered.map((found) => found.id)).toEqual(["sofa-3-linen"]);
  });

  it("searches the category name too, so 'decor' finds the rug", () => {
    const filtered = filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "decor" });

    expect(filtered.map((found) => found.id)).toEqual(["rug-wool-large"]);
  });

  it("ignores surrounding whitespace", () => {
    expect(filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "  rug  " })).toHaveLength(1);
  });

  it("applies the chip and the search box together", () => {
    const filtered = filterItems(CATALOGUE, { category: "seating", query: "arm" });

    expect(filtered.map((found) => found.id)).toEqual(["armchair-reading"]);
  });

  it("returns nothing rather than everything when nothing matches", () => {
    expect(filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "hammock" })).toEqual([]);
  });

  it("keeps the catalogue's order, so the list does not jump as you type", () => {
    const filtered = filterItems(CATALOGUE, { category: ALL_CATEGORIES, query: "e" });

    expect(filtered.map((found) => found.id)).toEqual(
      CATALOGUE.filter((found) => filtered.includes(found)).map((found) => found.id),
    );
  });
});
