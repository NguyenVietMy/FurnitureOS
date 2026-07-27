import { getJson } from "@/core/http";

import type { Item } from "./types";

/**
 * The whole catalogue, in the order the server groups it: category, then name.
 *
 * Fetched once and filtered in the browser. Twenty items today, a hundred at the
 * ceiling the panel is built for — small enough that paging or a search endpoint would
 * be latency bought with nothing.
 */
export async function fetchItems(): Promise<Item[]> {
  // An unseeded catalogue is `[]`, not a 404.
  return (await getJson<Item[]>("/api/items")) ?? [];
}
