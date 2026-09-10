export const NORMALIZATION_TOLERANCE_M = 0.002;
export const MANIFEST_BOUNDS_TOLERANCE_M = 0.000001;

export function normalizationMetrics(measure) {
  return {
    floorGapM: Math.abs(measure.min[1]),
    doubledCentreXM: Math.abs(measure.min[0] + measure.max[0]),
    doubledCentreZM: Math.abs(measure.min[2] + measure.max[2]),
  };
}

export function normalizationTranslation(measure) {
  return [
    -(measure.min[0] + measure.max[0]) / 2,
    -measure.min[1],
    -(measure.min[2] + measure.max[2]) / 2,
  ];
}

export function assertNormalizedBounds(label, measure) {
  const metrics = normalizationMetrics(measure);
  if (Object.values(metrics).some((value) => value > NORMALIZATION_TOLERANCE_M)) {
    throw new Error(
      `${label} violates floor-centre normalization: ` +
        `floor gap ${metrics.floorGapM}, doubled X centre ${metrics.doubledCentreXM}, ` +
        `doubled Z centre ${metrics.doubledCentreZM}`,
    );
  }
  return metrics;
}

function assertMeasuredArray(label, field, actual, declared) {
  if (!Array.isArray(declared) || actual.length !== declared.length) {
    throw new Error(`${label} manifest ${field} is not comparable with measured geometry`);
  }
  actual.forEach((value, index) => {
    if (Math.abs(value - declared[index]) > MANIFEST_BOUNDS_TOLERANCE_M) {
      throw new Error(
        `${label} measured ${field}[${index}] ${value} does not match manifest ${declared[index]}`,
      );
    }
  });
}

export function assertManifestMeasurement(label, manifestLod, measured) {
  if (measured.triangles !== manifestLod.triangles) {
    throw new Error(
      `${label} measured ${measured.triangles} triangles, manifest says ${manifestLod.triangles}`,
    );
  }
  assertMeasuredArray(label, 'bounds.min', measured.min, manifestLod.bounds?.min);
  assertMeasuredArray(label, 'bounds.max', measured.max, manifestLod.bounds?.max);
  assertMeasuredArray(label, 'bounds.size', measured.size, manifestLod.bounds?.size);
}

export function maxBoundsDelta(first, second) {
  return Math.max(
    ...first.min.map((value, index) => Math.abs(value - second.min[index])),
    ...first.max.map((value, index) => Math.abs(value - second.max[index])),
  );
}
