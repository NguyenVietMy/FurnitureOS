import { getJson } from "@/core/http";

import type { Unit, UnitSummary } from "./types";

/** Every unit the gallery lists, in the order the API gives them. */
export async function fetchUnits(): Promise<UnitSummary[]> {
  // The collection always exists; an empty showroom is `[]`, not a 404.
  return (await getJson<UnitSummary[]>("/api/units")) ?? [];
}

/** Fetch a unit by slug. Null when no unit has that slug. */
export function fetchUnit(slug: string): Promise<Unit | null> {
  return getJson<Unit>(`/api/units/${encodeURIComponent(slug)}`);
}
