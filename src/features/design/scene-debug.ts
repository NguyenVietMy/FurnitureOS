import type { Vec3 } from '@/shared/api/types';

/**
 * A small, deliberate window handle describing what is actually on screen.
 *
 * A browser test that only asserts "a <canvas> exists" proves nothing about the
 * Product, so the scene publishes measured facts — world bounds of the loaded
 * Mesh, which level of detail is drawn, whether any texture fell back — that a
 * test can check against the Catalogue's own numbers.
 */
export interface SceneDebug {
  ready: boolean;
  productId: string;
  /** Index of the level of detail currently being drawn. */
  activeLod: number;
  framesRendered: number;
  /** Axis-aligned bounds of the placed Product in world (Room) coordinates. */
  worldBounds: { min: Vec3; max: Vec3; size: Vec3 } | null;
  placement: { position: Vec3; yaw: number; wallId: string | null } | null;
  products: Record<string, {
    ready: boolean;
    activeLod: number;
    worldBounds: { min: Vec3; max: Vec3; size: Vec3 } | null;
    placement: { position: Vec3; yaw: number; wallId: string | null };
  }>;
  /** Rendered Product occurrences keyed by stable Placement Intent identity. */
  instances: Record<string, {
    instanceId: string;
    productId: string;
    ready: boolean;
    activeLod: number;
    worldBounds: { min: Vec3; max: Vec3; size: Vec3 } | null;
    publishedPlacement: { position: Vec3; yaw: number; wallId: string | null };
    renderedTransform: { position: Vec3; yaw: number; matrixWorld: number[] } | null;
    meshCount: number;
  }>;
  textures: { requested: number; decoded: number; fallback: number };
  camera: Vec3 | null;
  /** Moves the camera to `distance` metres from the Product, keeping direction. */
  setCameraDistanceM: ((distance: number) => void) | null;
}

const handle: SceneDebug = {
  ready: false,
  productId: '',
  activeLod: -1,
  framesRendered: 0,
  worldBounds: null,
  placement: null,
  products: {},
  instances: {},
  textures: { requested: 0, decoded: 0, fallback: 0 },
  camera: null,
  setCameraDistanceM: null,
};

declare global {
  // eslint-disable-next-line no-var
  var __furnitureos: SceneDebug | undefined;
}

/**
 * The handle itself. It is a single stable object, mutated in place, so a test
 * that captured it early keeps seeing live values.
 */
export function sceneDebug(): SceneDebug {
  if (typeof window !== 'undefined' && window.__furnitureos !== handle) {
    window.__furnitureos = handle;
  }
  return handle;
}

/** Clears the handle when the scene mounts, so counts never accumulate. */
export function resetSceneDebug(
  occurrences: ReadonlyArray<{ instanceId: string; productId: string }>,
): SceneDebug {
  const productIds = [...new Set(occurrences.map(({ productId }) => productId))];
  handle.ready = false;
  handle.productId = productIds[0] ?? '';
  handle.activeLod = -1;
  handle.framesRendered = 0;
  handle.worldBounds = null;
  handle.placement = null;
  handle.products = Object.fromEntries(productIds.map((productId) => [productId, {
    ready: false,
    activeLod: -1,
    worldBounds: null,
    placement: { position: [0, 0, 0], yaw: 0, wallId: null },
  }]));
  handle.instances = Object.fromEntries(occurrences.map(({ instanceId, productId }) => [instanceId, {
    instanceId,
    productId,
    ready: false,
    activeLod: -1,
    worldBounds: null,
    publishedPlacement: { position: [0, 0, 0], yaw: 0, wallId: null },
    renderedTransform: null,
    meshCount: 0,
  }]));
  handle.textures.requested = 0;
  handle.textures.decoded = 0;
  handle.textures.fallback = 0;
  handle.camera = null;
  handle.setCameraDistanceM = null;
  return sceneDebug();
}
