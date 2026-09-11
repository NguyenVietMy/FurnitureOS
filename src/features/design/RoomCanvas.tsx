import { OrbitControls } from '@react-three/drei';
import { Canvas, useThree } from '@react-three/fiber';
import { Suspense, useEffect, useState } from 'react';
import { Vector3 } from 'three';
import type { Placement, Product, RoomShell, Vec3 } from '@/shared/api/types';
import { AccessRegions, ProductPlacement } from './ProductPlacement';
import { RoomShellMesh } from './RoomShellMesh';
import { resetSceneDebug, sceneDebug } from './scene-debug';

/** What the camera orbits: roughly the eye level of someone standing in the Room. */
const ORBIT_TARGET: Vec3 = [0, 0.7, 0];

/**
 * Publishes a handle for driving the camera from outside React. Used by the
 * browser proof to step the camera back and watch the level of detail change;
 * it does nothing to what a person sees.
 */
function CameraBridge({ target }: { target: Vec3 }) {
  const camera = useThree((state) => state.camera);
  useEffect(() => {
    const debug = sceneDebug();
    debug.setCameraDistanceM = (distance: number) => {
      const focus = new Vector3(target[0], target[1], target[2]);
      const direction = camera.position.clone().sub(focus).normalize();
      camera.position.copy(focus.clone().add(direction.multiplyScalar(distance)));
      camera.lookAt(focus);
      camera.updateMatrixWorld();
    };
    return () => {
      sceneDebug().setCameraDistanceM = null;
    };
  }, [camera, target]);
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

export default function RoomCanvas({
  room,
  products,
  placements,
}: {
  room: RoomShell;
  products: ReadonlyArray<Product>;
  placements: ReadonlyArray<Placement>;
}) {
  // Reset during the first render, before any child effect can report into it.
  useState(() => resetSceneDebug(products.map((product, index) => ({
    instanceId: placements[index]?.instanceId ?? `${product.id}-${index}`,
    productId: product.id,
  }))));
  const primaryPlacement = placements[0];

  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
      camera={{ position: [3.1, 2.3, 3.7], fov: 45, near: 0.1, far: 60 }}
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
          <Suspense key={instanceId} fallback={<LoadingBounds product={product} placement={placement} />}>
            <ProductPlacement product={product} placement={placement} primary={index === 0} />
          </Suspense>
        );
      })}

      <CameraBridge target={ORBIT_TARGET} />
      <OrbitControls
        makeDefault
        target={[ORBIT_TARGET[0], ORBIT_TARGET[1], ORBIT_TARGET[2]]}
        enablePan={false}
        enableDamping
        dampingFactor={0.08}
        minDistance={1.6}
        maxDistance={14}
        // Stay above the floor: looking up from underneath the Room is never useful.
        maxPolarAngle={Math.PI / 2 - 0.03}
        minPolarAngle={0.15}
      />
    </Canvas>
  );
}
