import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

declare global { interface Window {
  __curatorDraws?: { url: string; at: number; meshes: number }[];
  __curatorView?: { url: string; position: number[]; target: number[] };
  __curatorFrame?: { url: string; at: number; view: string; meshes: number; textures: number; loadedTextures: number; dimensions: number[] };
} }
export function MeshPreview({ url }: { url: string }) {
  const host = useRef<HTMLDivElement>(null);
  const keyboard = useRef<(key: string) => void>(() => {});
  const [status, setStatus] = useState('Loading Mesh…');
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
    catch { setStatus('Mesh preview failed: WebGL unavailable. Enable WebGL and retry.'); return; }
    let alive = true, frame = 0, drawn = false, meshCount = 0, extent = 1, namedView = 'orbit';
    let dimensions: number[] = [], textureCount = 0, loadedTextures = 0;
    setStatus('Loading Mesh…');
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor('#f6f8ed');
    element.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
    camera.position.set(3, 2, 3);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = false;
    controls.minDistance = 0.15; controls.maxDistance = 15;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x797e70, 3));
    const light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(4, 7, 5); scene.add(light);
    scene.add(new THREE.GridHelper(10, 10, '#a3b3a1', '#dce0d0'));
    const axes = new THREE.AxesHelper(0.5); scene.add(axes);
    const ktx = new KTX2Loader().setTranscoderPath('/decoders/basis/').detectSupport(renderer);
    const loader = new GLTFLoader().setKTX2Loader(ktx).setMeshoptDecoder(MeshoptDecoder);
    const captureView = () => { window.__curatorView = { url, position: camera.position.toArray(), target: controls.target.toArray() }; };
    const reset = () => { namedView = 'orbit'; controls.reset(); controls.update(); captureView(); };
    keyboard.current = (key) => {
      if (key === '0') { reset(); return; }
      if (['front', 'back', 'side'].includes(key)) {
        namedView = key;
        const direction = key === 'side' ? new THREE.Vector3(1, 0.15, 0) : new THREE.Vector3(0, 0.15, key === 'front' ? 1 : -1);
        camera.position.copy(controls.target).add(direction.multiplyScalar(extent * 2.1));
        controls.update(); captureView(); return;
      }
      namedView = 'orbit';
      const offset = camera.position.clone().sub(controls.target), spherical = new THREE.Spherical().setFromVector3(offset);
      if (key === 'ArrowLeft') spherical.theta -= 0.13;
      if (key === 'ArrowRight') spherical.theta += 0.13;
      if (key === 'ArrowUp') spherical.phi = Math.max(0.1, spherical.phi - 0.1);
      if (key === 'ArrowDown') spherical.phi = Math.min(Math.PI - 0.1, spherical.phi + 0.1);
      if (key === '+' || key === '=') spherical.radius *= 0.9;
      if (key === '-') spherical.radius *= 1.1;
      camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(spherical)); controls.update(); captureView();
    };
    const dispose = (root: THREE.Object3D) => root.traverse((object) => {
      if (!(object instanceof THREE.Mesh)) return;
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        for (const value of Object.values(material)) if (value instanceof THREE.Texture) value.dispose();
        material.dispose();
      }
    });
    loader.load(url, (gltf) => {
      if (!alive) { dispose(gltf.scene); return; }
      const box = new THREE.Box3().setFromObject(gltf.scene), size = box.getSize(new THREE.Vector3());
      extent = Math.max(size.x, size.y, size.z); dimensions = size.toArray();
      controls.target.copy(box.getCenter(new THREE.Vector3()));
      camera.position.copy(controls.target).add(new THREE.Vector3(extent * 1.25, extent * 0.65, extent * 1.7));
      controls.update(); controls.saveState(); captureView();
      const textures = new Set<THREE.Texture>();
      gltf.scene.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        meshCount++;
        for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
          for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
        }
        object.onAfterRender = () => {
          if (alive) window.__curatorFrame = { url, at: performance.now(), view: namedView, meshes: meshCount, textures: textureCount, loadedTextures, dimensions };
          if (!alive || drawn) return;
          drawn = true;
          window.__curatorDraws ??= [];
          window.__curatorDraws.push({ url, at: performance.now(), meshes: meshCount });
          setStatus('Mesh drawn · metres · +Y up · +Z front');
        };
      });
      textureCount = textures.size;
      loadedTextures = [...textures].filter((t) => {
        const image = t.image as { width?: number; height?: number } | undefined;
        return typeof image?.width === 'number' && image.width > 0 && typeof image.height === 'number' && image.height > 0;
      }).length;
      scene.add(gltf.scene);
      if (!meshCount) setStatus('Mesh preview failed: no renderable geometry. Retry preview.');
    }, undefined, (error) => { if (alive) setStatus(`Mesh preview failed: ${String(error)}. Retry preview.`); });
    const resize = () => {
      const width = element.clientWidth, height = element.clientHeight;
      renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize); observer.observe(element); resize();
    const render = () => { if (!alive) return; renderer.render(scene, camera); frame = requestAnimationFrame(render); };
    render();
    return () => {
      alive = false; cancelAnimationFrame(frame); observer.disconnect(); controls.dispose(); ktx.dispose(); dispose(scene);
      renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); keyboard.current = () => {};
    };
  }, [url, attempt]);
  return <section className="preview" aria-label="Mesh preview">
    <div ref={host} className={`canvas${expanded ? ' expanded' : ''}`} role="region" tabIndex={0} aria-label="Interactive Mesh viewport. Arrows rotate, plus and minus zoom, zero resets" onKeyDown={(event) => {
      if (event.repeat || event.ctrlKey || event.metaKey || event.altKey || (event.shiftKey && event.key !== '+')) return;
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', '+', '=', '-', '0'].includes(event.key)) { event.preventDefault(); event.stopPropagation(); keyboard.current(event.key); }
    }} />
    <div className="preview-caption"><span role="status">{status}</span><div><button onClick={() => keyboard.current('front')}>Front view</button><button onClick={() => keyboard.current('back')}>Back view</button><button onClick={() => keyboard.current('side')}>Side view</button><button aria-pressed={expanded} onClick={() => setExpanded((value) => !value)}>Large viewport</button><button onClick={() => keyboard.current('0')}>Reset view</button><button onClick={() => setAttempt((value) => value + 1)}>Retry preview</button></div></div>
    <p className="hint">1 m grid · Drag to orbit · Scroll to zoom · Focus viewport for arrows / + / − / 0</p>
  </section>;
}
