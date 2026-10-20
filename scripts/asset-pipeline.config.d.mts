export interface SourceRecord {
  productId: string;
  sourceUrl: string;
  sourceFile: string;
  sourceSha256: string;
  sourceBytes: number;
  sourceFrontAxis: string;
}
export const PRODUCT_ASSET_SOURCES: SourceRecord[];
export const PUBLISHED_PRODUCT_ASSET_SOURCES: SourceRecord[];
export const ASSET_BUDGET_BYTES: number;
export const MAX_TEXTURE_PX: number;
export function validateReviewedLiving(metadata: unknown): SourceRecord[];
