import { Detailed } from '@react-three/drei';
import { useFrame, useLoader, useThree } from '@react-three/fiber';
import { useLayoutEffect, useMemo, useRef } from 'react';
import { Box3, DoubleSide, Frustum, Group, LOD, Material, Matrix4, Mesh, Object3D, Vector3 } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type { Placement, Product, ProductFace, Vec3 } from '@/shared/api/types';
import { configureProductLoader } from './product-loaders';
import { currentSceneDebug } from './scene-debug';

export const LOD_DISTANCES_M = [0, 5.5, 9.5];
const toVec3 = (vector: Vector3): Vec3 => [vector.x, vector.y, vector.z];
export function ProductPlacement({
  product,
  placement,
  primary,
  sceneRevision,
}: {
  product: Product;
  placement: Placement;
  primary: boolean;
  sceneRevision: number;
}) {
  const renderer = useThree((state) => state.gl);
  const mainCamera = useThree((state) => state.camera);
  const urls = product.mesh.lods.map((lod) => lod.url);
  const gltfs = useLoader(GLTFLoader, urls, (loader) => configureProductLoader(loader, renderer, sceneRevision));
  const scenes = useMemo(() => gltfs.map((gltf) => gltf.scene.clone(true)), [gltfs]);
  const groupRef = useRef<Group>(null);
  const lodRef = useRef<LOD>(null);
  const activeLevelRef = useRef(-1);
  const observedFrameRef = useRef(-1);
  const renderedMeshesRef = useRef(new Set<string>());
  const instanceId = placement.instanceId ?? product.id;

  useLayoutEffect(() => {
    const group = groupRef.current;
    const highestDetail = scenes[0];
    if (!group || !highestDetail) return;

    let meshCount = 0;
    const renderedMeshes = renderedMeshesRef.current;
    const restorers: Array<() => void> = [];
    for (const scene of scenes) {
      scene.traverse((object) => {
        if (object instanceof Mesh) {
          object.castShadow = true;
          object.receiveShadow = true;
          if (scene === highestDetail) meshCount += 1;
          const previous = object.onAfterRender;
          object.onAfterRender = (...args) => {
            previous?.apply(object, args);
            const renderCamera = args[2];
            if (renderCamera !== mainCamera) return;
            const currentLevel = lodRef.current?.getCurrentLevel() ?? -1;
            if (currentLevel !== activeLevelRef.current) return;
            const frame = renderer.info.render.frame;
            if (frame !== observedFrameRef.current) {
              observedFrameRef.current = frame;
              renderedMeshes.clear();
            }
            renderedMeshes.add(object.uuid);
            const instance = currentSceneDebug(sceneRevision)?.instances[instanceId];
            if (!instance) return;
            instance.renderedMeshCount = renderedMeshes.size;
            instance.mainCameraMeshCount = renderedMeshes.size;
            instance.actualFrameRendered = instance.screenVisible
              && instance.materialsReady
              && instance.activeMeshCount > 0
              && renderedMeshes.size === instance.activeMeshCount;
          };
          restorers.push(() => { object.onAfterRender = previous; });
        }
      });
    }
    group.updateMatrixWorld(true);
    const box = new Box3().setFromObject(highestDetail);
    const size = new Vector3();
    const worldPosition = new Vector3();
    box.getSize(size);
    group.getWorldPosition(worldPosition);
    const debug = currentSceneDebug(sceneRevision);
    if (!debug) return () => restorers.forEach((restore) => restore());
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
      activeMeshCount: 0,
      renderedMeshCount: 0,
      mainCameraMeshCount: 0,
      actualFrameRendered: false,
      materialsReady: false,
      screenVisible: false,
    };
    debug.products[product.id] = { ready: true, activeLod: lodRef.current?.getCurrentLevel() ?? 0, worldBounds, placement: publishedPlacement };
    debug.ready = Object.values(debug.instances).every((entry) => entry.ready);
    if (primary) { debug.productId = product.id; debug.worldBounds = worldBounds; debug.placement = publishedPlacement; }
    return () => restorers.forEach((restore) => restore());
  }, [instanceId, mainCamera, placement, primary, product.id, renderer.info.render, sceneRevision, scenes]);

  useFrame(({ camera }) => {
    const debug = currentSceneDebug(sceneRevision);
    if (!debug) return;
    const activeLod = lodRef.current?.getCurrentLevel() ?? -1;
    const instanceDebug = debug.instances[instanceId];
    const productDebug = debug.products[product.id];
    if (instanceDebug) {
      instanceDebug.activeLod = activeLod;
      const activeObject = lodRef.current?.levels[activeLod]?.object;
      const activeMeshes: Mesh[] = [];
      if (activeObject?.visible) activeObject.traverse((object: Object3D) => {
        if (!(object instanceof Mesh) || !object.visible) return;
        let parent = object.parent;
        while (parent && parent !== activeObject) {
          if (!parent.visible) return;
          parent = parent.parent;
        }
        activeMeshes.push(object);
      });
      const materials = activeMeshes.flatMap((mesh) => (
        Array.isArray(mesh.material) ? mesh.material : [mesh.material]
      )).filter((material): material is Material => material instanceof Material);
      const bounds = activeObject ? new Box3().setFromObject(activeObject) : new Box3();
      const frustum = new Frustum().setFromProjectionMatrix(
        new Matrix4().multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse),
      );
      const corners = bounds.isEmpty() ? [] : [
        new Vector3(bounds.min.x, bounds.min.y, bounds.min.z),
        new Vector3(bounds.min.x, bounds.min.y, bounds.max.z),
        new Vector3(bounds.min.x, bounds.max.y, bounds.min.z),
        new Vector3(bounds.min.x, bounds.max.y, bounds.max.z),
        new Vector3(bounds.max.x, bounds.min.y, bounds.min.z),
        new Vector3(bounds.max.x, bounds.min.y, bounds.max.z),
        new Vector3(bounds.max.x, bounds.max.y, bounds.min.z),
        new Vector3(bounds.max.x, bounds.max.y, bounds.max.z),
      ].map((point) => point.project(camera));
      const minX = Math.max(-1, Math.min(...corners.map((point) => point.x)));
      const maxX = Math.min(1, Math.max(...corners.map((point) => point.x)));
      const minY = Math.max(-1, Math.min(...corners.map((point) => point.y)));
      const maxY = Math.min(1, Math.max(...corners.map((point) => point.y)));
      const screenCoverage = corners.length === 8
        ? Math.max(0, maxX - minX) * Math.max(0, maxY - minY) / 4
        : 0;
      const screenVisible = !bounds.isEmpty()
        && activeObject?.visible === true
        && frustum.intersectsBox(bounds)
        && corners.some((point) => point.z >= -1 && point.z <= 1)
        && screenCoverage >= 0.002;
      if (activeLod !== activeLevelRef.current || instanceDebug.activeMeshCount !== activeMeshes.length || !screenVisible) {
        renderedMeshesRef.current.clear();
        instanceDebug.renderedMeshCount = 0;
        instanceDebug.mainCameraMeshCount = 0;
      }
      activeLevelRef.current = activeLod;
      instanceDebug.activeMeshCount = activeMeshes.length;
      instanceDebug.materialsReady = materials.length > 0
        && materials.every((material) => material.visible && material.opacity > 0);
      instanceDebug.screenVisible = screenVisible;
      instanceDebug.actualFrameRendered = instanceDebug.actualFrameRendered
        && screenVisible
        && instanceDebug.materialsReady
        && instanceDebug.mainCameraMeshCount === activeMeshes.length;
    }
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
