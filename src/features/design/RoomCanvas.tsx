import { OrbitControls } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import { Component, type ErrorInfo, type ReactNode, Suspense, useEffect, useId, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import { Vector3 } from 'three';
import type { Placement, Product, RoomShell, Vec3 } from '@/shared/api/types';
import { AccessRegions, ProductPlacement } from './ProductPlacement';
import { RoomShellMesh } from './RoomShellMesh';
import { clearSceneDebug, currentSceneDebug, resetSceneDebug } from './scene-debug';

/** What the ordinary fixture camera orbits: roughly standing eye level. */
const ORBIT_TARGET: Vec3 = [0, 0.7, 0];
/** A higher, wider view used only for the multi-Product zoned fixture. */
const OVERVIEW_TARGET: Vec3 = [0, 0.55, -0.35];

/**
 * Publishes a handle for driving the camera from outside React. Used by the
 * browser proof to step the camera back and watch the level of detail change;
 * it does nothing to what a person sees.
 */
function CameraBridge({ target, sceneRevision }: { target: Vec3; sceneRevision: number }) {
  const camera = useThree((state) => state.camera);
  useEffect(() => {
    const debug = currentSceneDebug(sceneRevision);
    if (!debug) return;
    debug.setCameraDistanceM = (distance: number) => {
      const focus = new Vector3(target[0], target[1], target[2]);
      const direction = camera.position.clone().sub(focus).normalize();
      camera.position.copy(focus.clone().add(direction.multiplyScalar(distance)));
      camera.lookAt(focus);
      camera.updateMatrixWorld();
    };
    return () => {
      const current = currentSceneDebug(sceneRevision);
      if (current) current.setCameraDistanceM = null;
    };
  }, [camera, sceneRevision, target]);
  return null;
}

/** Stand-in drawn while the Mesh is still downloading: the Product's own bounds. */
function LoadingBounds({ product, placement }: { product: Product; placement: Placement }) {
  const { widthM, heightM, depthM } = product.dimensionsM;
  return (
    <mesh
      position={[placement.position[0], heightM / 2, placement.position[2]]}
      rotation={[0, placement.yaw, 0]}
    >
      <boxGeometry args={[widthM, heightM, depthM]} />
      <meshBasicMaterial color="#b9b2a5" wireframe />
    </mesh>
  );
}

class MeshErrorBoundary extends Component<{
  instanceId: string;
  sceneRevision: number;
  fallback: ReactNode;
  children: ReactNode;
}, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    const debug = currentSceneDebug(this.props.sceneRevision);
    if (!debug) return;
    debug.errors.push(`Mesh load failed for ${this.props.instanceId}.`);
    debug.ready = false;
  }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function UsefulViewReporter({ sceneRevision }: { sceneRevision: number }) {
  useFrame(() => {
    const debug = currentSceneDebug(sceneRevision);
    if (!debug) return;
    if (debug.usefulView.status !== 'pending') return;
    const instances = Object.values(debug.instances);
    debug.usefulView.renderedPlacements = instances.filter((entry) => entry.actualFrameRendered).length;
    debug.usefulView.materialsReady = instances.length > 0 && instances.every((entry) => entry.materialsReady);
    debug.usefulView.texturesReady = debug.textures.fallback === 0
      && debug.textures.requested === debug.textures.decoded;
    const complete = instances.length === debug.usefulView.expectedPlacements
      && instances.every((entry) => entry.ready
        && entry.actualFrameRendered
        && entry.screenVisible
        && entry.activeMeshCount > 0
        && entry.mainCameraMeshCount === entry.activeMeshCount)
      && debug.usefulView.materialsReady
      && debug.usefulView.texturesReady
      && debug.errors.length === 0;
    if (complete && debug.usefulView.receivedAtMs !== null) {
      const completedAtMs = performance.now();
      debug.usefulView.status = 'complete';
      debug.usefulView.completedAtMs = completedAtMs;
      debug.usefulView.durationMs = completedAtMs - debug.usefulView.receivedAtMs;
    }
  });
  return null;
}

export default function RoomCanvas({
  room,
  products,
  placements,
  overview = false,
  receivedAtMs,
  generationId,
}: {
  room: RoomShell;
  products: ReadonlyArray<Product>;
  placements: ReadonlyArray<Placement>;
  overview?: boolean;
  receivedAtMs?: number;
  generationId?: string;
}) {
  // Reset during the first render, before any child effect can report into it.
  const sceneOwnerToken = useId();
  const [sceneRevision] = useState(() => resetSceneDebug(products.map((product, index) => ({
    instanceId: placements[index]?.instanceId ?? `${product.id}-${index}`,
    productId: product.id,
  })), receivedAtMs, generationId, sceneOwnerToken).revision);
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      queueMicrotask(() => {
        if (!mountedRef.current) clearSceneDebug(sceneRevision);
      });
    };
  }, [sceneRevision]);
  const primaryPlacement = placements[0];
  const orbitTarget = overview ? OVERVIEW_TARGET : ORBIT_TARGET;
  const cameraPosition: Vec3 = overview ? [6.5, 8.5, -9] : [3.1, 2.3, 3.7];

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
      camera={{ position: cameraPosition, fov: 45, near: 0.1, far: 60 }}
      data-testid="room-canvas"
    >
      <color attach="background" args={['#e9e6e0']} />
      <hemisphereLight args={['#fefdfa', '#c4bcae', 0.7]} />
      <ambientLight intensity={0.25} />
      <directionalLight
        position={[2.6, 4.2, 2.4]}
        intensity={1.7}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-camera-left={-4}
        shadow-camera-right={4}
        shadow-camera-top={4}
        shadow-camera-bottom={-4}
        shadow-camera-near={0.5}
        shadow-camera-far={16}
      />

      <RoomShellMesh room={room} contactWallId={primaryPlacement?.wallContact?.wallId ?? null} />
      {products.map((product, index) => {
        const placement = placements[index];
        const instanceId = placement?.instanceId ?? `${product.id}-${index}`;
        return placement ? <AccessRegions key={`access-${instanceId}`} product={product} placement={placement} /> : null;
      })}

      {products.map((product, index) => {
        const placement = placements[index];
        if (!placement) return null;
        const instanceId = placement.instanceId ?? `${product.id}-${index}`;
        return (
          <MeshErrorBoundary
            key={instanceId}
            instanceId={instanceId}
            sceneRevision={sceneRevision}
            fallback={<LoadingBounds product={product} placement={placement} />}
          >
            <Suspense fallback={<LoadingBounds product={product} placement={placement} />}>
              <ProductPlacement
                product={product}
                placement={placement}
                primary={index === 0}
                sceneRevision={sceneRevision}
              />
            </Suspense>
          </MeshErrorBoundary>
        );
      })}

      <CameraBridge target={orbitTarget} sceneRevision={sceneRevision} />
      <UsefulViewReporter sceneRevision={sceneRevision} />
      <OrbitControls
        makeDefault
        target={[orbitTarget[0], orbitTarget[1], orbitTarget[2]]}
        enablePan={false}
        enableDamping
        dampingFactor={0.08}
        minDistance={1.6}
        maxDistance={overview ? 18 : 14}
        // Stay above the floor: looking up from underneath the Room is never useful.
        maxPolarAngle={Math.PI / 2 - 0.03}
        minPolarAngle={0.15}
      />
    </Canvas>
  );
}
