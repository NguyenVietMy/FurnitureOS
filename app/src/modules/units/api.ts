import { getJson } from "@/core/http";

import type { Unit } from "./types";

/** Fetch a unit by slug. Null when no unit has that slug. */
export function fetchUnit(slug: string): Promise<Unit | null> {
  return getJson<Unit>(`/api/units/${encodeURIComponent(slug)}`);
}
