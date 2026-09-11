import { Detailed } from '@react-three/drei';
import { useFrame, useLoader, useThree } from '@react-three/fiber';
import { useLayoutEffect, useMemo, useRef } from 'react';
import { Box3, DoubleSide, Group, LOD, Mesh, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type { Placement, Product, ProductFace, Vec3 } from '@/shared/api/types';
import { configureProductLoader } from './product-loaders';
import { sceneDebug } from './scene-debug';

export const LOD_DISTANCES_M = [0, 5.5, 9.5];
const toVec3 = (vector: Vector3): Vec3 => [vector.x, vector.y, vector.z];
export function ProductPlacement({ product, placement, primary }: { product: Product; placement: Placement; primary: boolean }) {
  const renderer = useThree((state) => state.gl);
  const urls = product.mesh.lods.map((lod) => lod.url);
  const gltfs = useLoader(GLTFLoader, urls, (loader) => configureProductLoader(loader, renderer));
  const scenes = useMemo(() => gltfs.map((gltf) => gltf.scene.clone(true)), [gltfs]);
  const groupRef = useRef<Group>(null);
  const lodRef = useRef<LOD>(null);
  const instanceId = placement.instanceId ?? product.id;

  useLayoutEffect(() => {
    const group = groupRef.current;
    const highestDetail = scenes[0];
    if (!group || !highestDetail) return;

    let meshCount = 0;
    for (const scene of scenes) {
      scene.traverse((object) => {
        if (object instanceof Mesh) {
          object.castShadow = true;
          object.receiveShadow = true;
          if (scene === highestDetail) meshCount += 1;
        }
      });
    }
    group.updateMatrixWorld(true);
    const box = new Box3().setFromObject(highestDetail);
    const size = new Vector3();
    const worldPosition = new Vector3();
    box.getSize(size);
    group.getWorldPosition(worldPosition);
    const debug = sceneDebug();
    const worldBounds = { min: toVec3(box.min), max: toVec3(box.max), size: toVec3(size) };
    const publishedPlacement = { position: placement.position, yaw: placement.yaw, wallId: placement.wallContact?.wallId ?? null };
    debug.instances[instanceId] = {
      instanceId,
      productId: product.id,
      ready: true,
      activeLod: lodRef.current?.getCurrentLevel() ?? 0,
      worldBounds,
      publishedPlacement,
      renderedTransform: {
        position: toVec3(worldPosition),
        yaw: group.rotation.y,
        matrixWorld: group.matrixWorld.toArray(),
      },
      meshCount,
    };
    debug.products[product.id] = { ready: true, activeLod: lodRef.current?.getCurrentLevel() ?? 0, worldBounds, placement: publishedPlacement };
    debug.ready = Object.values(debug.instances).every((entry) => entry.ready);
    if (primary) { debug.productId = product.id; debug.worldBounds = worldBounds; debug.placement = publishedPlacement; }
  }, [instanceId, placement, primary, product.id, scenes]);

  useFrame(({ camera }) => {
    const debug = sceneDebug();
    const activeLod = lodRef.current?.getCurrentLevel() ?? -1;
    const instanceDebug = debug.instances[instanceId];
    const productDebug = debug.products[product.id];
    if (instanceDebug) instanceDebug.activeLod = activeLod;
    if (productDebug) productDebug.activeLod = activeLod;
    if (primary) {
      debug.framesRendered += 1;
      debug.camera = toVec3(camera.position);
      debug.activeLod = activeLod;
    }
  });

  return (
    <group
      ref={groupRef}
      name={`placement-${instanceId}`}
      position={[placement.position[0], placement.position[1], placement.position[2]]}
      rotation={[0, placement.yaw, 0]}
    >
      <Detailed ref={lodRef} distances={LOD_DISTANCES_M}>
        {scenes.map((scene, index) => (
          <primitive key={urls[index] ?? index} object={scene} />
        ))}
      </Detailed>
    </group>
  );
}
export function AccessRegions({ product, placement }: { product: Product; placement: Placement }) {
  const rectangles = useMemo(() => product.accessRegions.map((region) => { const normal = faceNormal(region.face, placement.yaw); const halfExtent = region.face === 'front' || region.face === 'back' ? product.dimensionsM.depthM / 2 : product.dimensionsM.widthM / 2; const spanM = region.face === 'front' || region.face === 'back' ? product.dimensionsM.widthM : product.dimensionsM.depthM; return { region, footprint: { centre: [placement.position[0] + normal[0] * (halfExtent + region.depthM / 2), placement.position[2] + normal[1] * (halfExtent + region.depthM / 2)] as const, yaw: Math.atan2(normal[0], normal[1]), widthM: spanM, depthM: region.depthM } }; }), [product, placement]);
  return <group name="access-regions">{rectangles.map(({ region, footprint }) => <mesh key={region.face} position={[footprint.centre[0], 0.004, footprint.centre[1]]} rotation={[-Math.PI / 2, 0, footprint.yaw]}><planeGeometry args={[footprint.widthM, footprint.depthM]} /><meshBasicMaterial color="#8f9c8a" transparent opacity={0.14} side={DoubleSide} /></mesh>)}</group>;
}
// Rendering-only visualisation. FastAPI remains the only source of fit truth.
function faceNormal(face: ProductFace, yaw: number): readonly [number, number] { const forward: readonly [number, number] = [Math.sin(yaw), Math.cos(yaw)]; const right: readonly [number, number] = [Math.cos(yaw), -Math.sin(yaw)]; return face === 'front' ? forward : face === 'back' ? [-forward[0], -forward[1]] : face === 'right' ? right : [-right[0], -right[1]]; }
