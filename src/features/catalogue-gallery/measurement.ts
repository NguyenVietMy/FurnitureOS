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
}

export interface CatalogueMeasurement {
  protocolVersion: 'catalogue-phone-v1';
  buildId: string;
  catalogueVersion: string;
  navigationStartMs: number;
  allVisibleMs: number | null;
  products: Record<string, ProductMeasurement>;
}

declare global {
  // eslint-disable-next-line no-var
  var __catalogueMeasurement: CatalogueMeasurement | undefined;
}

export function startMeasurement(
  buildId: string,
  catalogueVersion: string,
  productIds: readonly string[],
): CatalogueMeasurement {
  const measurement: CatalogueMeasurement = {
    protocolVersion: 'catalogue-phone-v1',
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
  };
  window.__catalogueMeasurement = measurement;
  return measurement;
}

export function markRendered(productId: string, lod: number): void {
  const measurement = window.__catalogueMeasurement;
  const product = measurement?.products[productId];
  if (!measurement || !product) return;
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
