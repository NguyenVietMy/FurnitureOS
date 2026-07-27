/**
 * Catalogue module — what the store sells, and the panel a buyer browses it in.
 *
 * PUBLIC SURFACE. Everything outside this module goes through here; lint enforces it.
 *
 * Internals:
 *   types.ts               the API's wire format
 *   api.ts                 fetching
 *   filter.ts              chips and search as a pure function
 *   CataloguePanel.tsx     the panel itself
 */

export { fetchItems } from "./api";
export { CataloguePanel, CATALOGUE_ITEM_MIME } from "./CataloguePanel";
export { ALL_CATEGORIES, categoriesOf, filterItems, type CatalogueFilter } from "./filter";
export type { Item } from "./types";
