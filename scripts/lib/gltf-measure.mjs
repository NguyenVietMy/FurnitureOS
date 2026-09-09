import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { getBounds } from '@gltf-transform/functions';
import { MeshoptDecoder, MeshoptEncoder } from 'meshoptimizer';

let io;

/** A NodeIO that can read gltfpack output (meshopt + quantization + basisu). */
export async function packedIO() {
  if (!io) {
    await MeshoptDecoder.ready;
    await MeshoptEncoder.ready;
    io = new NodeIO()
      .registerExtensions(ALL_EXTENSIONS)
      .registerDependencies({ 'meshopt.decoder': MeshoptDecoder, 'meshopt.encoder': MeshoptEncoder });
  }
  return io;
}

const round = (v) => Math.round(v * 1e6) / 1e6;

/**
 * Measures a glTF file the way the placement path cares about it: axis-aligned
 * bounds in metres, in the asset's own coordinate frame, with no viewer-side
 * scaling applied.
 */
export async function measureGltf(file) {
  const doc = await (await packedIO()).read(file);
  const root = doc.getRoot();
  const scene = root.getDefaultScene() ?? root.listScenes()[0];
  if (!scene) throw new Error(`${file} has no scene`);
  const { min, max } = getBounds(scene);

  let triangles = 0;
  let vertices = 0;
  for (const mesh of root.listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const position = prim.getAttribute('POSITION');
      if (!position) continue;
      vertices += position.getCount();
      const indices = prim.getIndices();
      triangles += (indices ? indices.getCount() : position.getCount()) / 3;
    }
  }

  const textures = root.listTextures().map((texture) => {
    const size = texture.getSize();
    return {
      name: texture.getName(),
      mimeType: texture.getMimeType(),
      uri: texture.getURI(),
      width: size?.[0] ?? null,
      height: size?.[1] ?? null,
    };
  });

  return {
    min: min.map(round),
    max: max.map(round),
    size: max.map((v, i) => round(v - min[i])),
    triangles,
    vertices,
    extensionsRequired: root.listExtensionsRequired().map((e) => e.extensionName).sort(),
    extensionsUsed: root.listExtensionsUsed().map((e) => e.extensionName).sort(),
    textures,
  };
}
