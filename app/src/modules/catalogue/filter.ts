/**
 * Category chips and the search box, as a pure function.
 *
 * Filtering is client-side: twenty items today, a hundred at the ceiling the panel is
 * built for, and a round trip per keystroke would buy latency and nothing else. The
 * server sorts the catalogue by category then name and this preserves that order, so
 * the list narrows in place instead of reshuffling as the buyer types.
 */

import type { Item } from "./types";

/** The "everything" chip. A sentinel rather than null, so the chip row is one list. */
export const ALL_CATEGORIES = "all";

export interface CatalogueFilter {
  readonly category: string;
  readonly query: string;
}

/** Every category present, once each, in catalogue order. */
export function categoriesOf(items: readonly Item[]): string[] {
  return [...new Set(items.map((item) => item.category))];
}

export function filterItems(items: readonly Item[], filter: CatalogueFilter): Item[] {
  // Substring, not prefix: a buyer types "sofa", and the product is called "Linen
  // 3-seat sofa". Category is searchable too, so typing "decor" works before anyone
  // notices the chips.
  const query = filter.query.trim().toLowerCase();

  return items.filter((item) => {
    if (filter.category !== ALL_CATEGORIES && item.category !== filter.category) return false;
    if (query === "") return true;

    return (
      item.name.toLowerCase().includes(query) || item.category.toLowerCase().includes(query)
    );
  });
}
