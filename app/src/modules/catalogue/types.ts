/**
 * A catalogue item as the API serves it.
 *
 * Dimensions are true metres and they are load-bearing: the same three numbers set the
 * size the scene draws and the footprint the geometry collides with. Drawn size equals
 * collision size equals delivered size, which is the only reason "it fits" means
 * anything.
 *
 * `price_vnd` is a whole number of dong. Vietnamese dong has no fractional unit, so
 * nothing on this path — schema, wire, or arithmetic — is allowed to become a float.
 *
 * Stock exists on the server and is deliberately absent here.
 */
export interface Item {
  readonly id: string;
  readonly name: string;
  readonly category: string;
  readonly width_m: number;
  readonly depth_m: number;
  readonly height_m: number;
  readonly price_vnd: number;
  /** Which 3D archetype draws this item. Issue 14 supplies the models behind the refs. */
  readonly preset_ref: string;
  readonly photo_url: string | null;
}
