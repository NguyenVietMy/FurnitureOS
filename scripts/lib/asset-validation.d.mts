export interface GltfMeasurement {
  min: number[];
  max: number[];
  size?: number[];
  triangles?: number;
}

export interface ManifestLodMeasurement {
  triangles: number;
  bounds: { min: number[]; max: number[]; size: number[] };
}

export const NORMALIZATION_TOLERANCE_M: number;
export const MANIFEST_BOUNDS_TOLERANCE_M: number;
export function normalizationMetrics(measure: GltfMeasurement): {
  floorGapM: number;
  doubledCentreXM: number;
  doubledCentreZM: number;
};
export function normalizationTranslation(measure: GltfMeasurement): number[];
export function assertNormalizedBounds(label: string, measure: GltfMeasurement): ReturnType<typeof normalizationMetrics>;
export function assertManifestMeasurement(
  label: string,
  manifestLod: ManifestLodMeasurement,
  measured: Required<GltfMeasurement>,
): void;
export function maxBoundsDelta(first: GltfMeasurement, second: GltfMeasurement): number;
