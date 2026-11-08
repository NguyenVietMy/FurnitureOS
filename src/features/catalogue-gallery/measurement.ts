export interface RefinementEvent {
  lod: number;
  visibleMs: number;
}

export interface ProductMeasurement {
  productId: string;
  requestStartedMs: number;
  firstVisibleMs: number | null;
  initialLod: number | null;
  refinements: RefinementEvent[];
  renderedFrames: number;
  error: string | null;
  lodState?: Record<number, {meshes:number;materials:number;textures:number;loadedTextures:number;drawnMeshes:number}>;
}

export interface CatalogueMeasurement {
  protocolVersion: 'catalogue-phone-v1' | 'catalogue-shards-v1';
  buildId: string;
  catalogueVersion: string;
  navigationStartMs: number;
  allVisibleMs: number | null;
  products: Record<string, ProductMeasurement>;
  shard?: {page:number;pageCount:number;totalProducts:number;productIdsSha256:string};
}

declare global {
  // eslint-disable-next-line no-var
  var __catalogueMeasurement: CatalogueMeasurement | undefined;
}

export function startMeasurement(
  buildId: string,
  catalogueVersion: string,
  productIds: readonly string[],
  shard?: {page:number;pageCount:number;totalProducts:number;productIdsSha256:string},
): CatalogueMeasurement {
  const measurement: CatalogueMeasurement = {
    protocolVersion: shard ? 'catalogue-shards-v1' : 'catalogue-phone-v1',
    buildId,
    catalogueVersion,
    navigationStartMs: 0,
    allVisibleMs: null,
    products: Object.fromEntries(productIds.map((productId) => [productId, {
      productId,
      requestStartedMs: performance.now(),
      firstVisibleMs: null,
      initialLod: null,
      refinements: [],
      renderedFrames: 0,
      error: null,
    }])),
    ...(shard ? {shard:{page:shard.page,pageCount:shard.pageCount,totalProducts:shard.totalProducts,productIdsSha256:shard.productIdsSha256}} : {}),
  };
  window.__catalogueMeasurement = measurement;
  return measurement;
}

export function markRendered(productId: string, lod: number, state?: {meshes:number;materials:number;textures:number;loadedTextures:number;drawnMeshes:number}): void {
  const measurement = window.__catalogueMeasurement;
  const product = measurement?.products[productId];
  if (!measurement || !product) return;
  if (state) { product.lodState ??= {}; product.lodState[lod] = {...state}; }
  product.renderedFrames += 1;
  if (product.firstVisibleMs === null) {
    product.firstVisibleMs = performance.now();
    product.initialLod = lod;
    const products = Object.values(measurement.products);
    if (products.every((candidate) => candidate.firstVisibleMs !== null)) {
      measurement.allVisibleMs = Math.max(...products.map((candidate) => candidate.firstVisibleMs!));
    }
    return;
  }
  if (!product.refinements.some((event) => event.lod === lod)) {
    product.refinements.push({ lod, visibleMs: performance.now() });
  }
}

export function markLoadError(productId: string, cause: unknown): void {
  const product = window.__catalogueMeasurement?.products[productId];
  if (product) product.error = cause instanceof Error ? cause.message : String(cause);
}
