import { Canvas, useThree } from '@react-three/fiber';
import { useEffect, useMemo, useState } from 'react';
import { Mesh, Object3D, OrthographicCamera } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type { Product } from '@/shared/api/types';
import { configureProductLoader } from '../design/product-loaders';
import { markLoadError, markRendered } from './measurement';

const CELL_M = 4;

function CameraFit() {
  const camera = useThree((state) => state.camera);
  const size = useThree((state) => state.size);
  useEffect(() => {
    if (!(camera instanceof OrthographicCamera)) return;
    camera.position.set(0, 20, 22);
    camera.lookAt(0, 0, 0);
    camera.zoom = Math.min(size.width / 23, size.height / 18);
    camera.updateProjectionMatrix();
  }, [camera, size]);
  return null;
}

function prepareScene(scene: Object3D, productId: string, lod: number, drawn: () => void) {
  let reported = false;
  scene.traverse((object) => {
    if (!(object instanceof Mesh)) return;
    object.castShadow = true;
    object.receiveShadow = true;
    object.onAfterRender = () => {
      markRendered(productId, lod);
      if (!reported) {
        reported = true;
        drawn();
      }
    };
  });
}

function ProgressiveProduct({
  product,
  position,
  onLoadError,
  loader,
}: {
  product: Product;
  position: [number, number, number];
  onLoadError: (productId: string, cause: unknown) => void;
  loader: GLTFLoader;
}) {
  const [loaded, setLoaded] = useState<{ lod: number; scene: Object3D } | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      for (const lod of [...product.mesh.lods].reverse()) {
        try {
          const gltf = await loader.loadAsync(lod.url);
          if (cancelled) return;
          let resolveDrawn!: () => void;
          const drawn = new Promise<void>((resolve) => { resolveDrawn = resolve; });
          prepareScene(gltf.scene, product.id, lod.level, resolveDrawn);
          setLoaded({ lod: lod.level, scene: gltf.scene });
          await drawn;
          if (cancelled) return;
        } catch (cause) {
          markLoadError(product.id, cause);
          onLoadError(product.id, cause);
          return;
        }
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [loader, onLoadError, product]);

  return (
    <group name={`gallery-${product.id}`} position={position}>
      {loaded ? <primitive key={loaded.lod} object={loaded.scene} /> : (
        <mesh position={[0, 0.01, 0]}>
          <boxGeometry args={[0.18, 0.02, 0.18]} />
          <meshBasicMaterial color="#8e887d" wireframe />
        </mesh>
      )}
    </group>
  );
}

function GalleryProducts({
  products,
  onLoadError,
}: {
  products: readonly Product[];
  onLoadError: (productId: string, cause: unknown) => void;
}) {
  const renderer = useThree((state) => state.gl);
  const loader = useMemo(() => {
    const shared = new GLTFLoader();
    configureProductLoader(shared, renderer);
    return shared;
  }, [renderer]);

  return products.map((product, index) => {
    const column = index % 5;
    const row = Math.floor(index / 5);
    const x = (column - 2) * CELL_M;
    const z = (1.5 - row) * CELL_M;
    return (
      <group key={product.id}>
        <gridHelper args={[3.7, 4, '#b9b2a5', '#d8d1c5']} position={[x, 0, z]} />
        <ProgressiveProduct
          product={product}
          position={[x, 0.01, z]}
          onLoadError={onLoadError}
          loader={loader}
        />
      </group>
    );
  });
}

export default function CatalogueGalleryCanvas({
  products,
  onLoadError,
}: {
  products: readonly Product[];
  onLoadError: (productId: string, cause: unknown) => void;
}) {
  return (
    <Canvas
      orthographic
      camera={{ position: [0, 20, 22], zoom: 20, near: 0.1, far: 80 }}
      dpr={[1, 2]}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
      data-testid="catalogue-canvas"
    >
      <color attach="background" args={['#eeeae2']} />
      <hemisphereLight args={['#fffdf7', '#b8ad9c', 1.1]} />
      <directionalLight position={[8, 16, 12]} intensity={1.8} castShadow />
      <CameraFit />
      <GalleryProducts products={products} onLoadError={onLoadError} />
    </Canvas>
  );
}
