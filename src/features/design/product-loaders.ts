import {
  DataTexture,
  RGBAFormat,
  SRGBColorSpace,
  UnsignedByteType,
  type CompressedTexture,
  type WebGLRenderer,
} from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { sceneDebug } from './scene-debug';

/**
 * Loader wiring for published Product Meshes.
 *
 * The Meshes require EXT_meshopt_compression and KHR_texture_basisu, so both
 * decoders have to be attached explicitly. The BasisU transcoder is served from
 * our own origin (see `scripts/copy-decoders.mjs`) rather than a third-party
 * CDN, which is why this file exists instead of a one-line `useGLTF`.
 */

export const KTX2_TRANSCODER_PATH = '/decoders/basis/';

/** A flat, unobtrusive stand-in used when a texture cannot be decoded. */
function neutralTexture(): DataTexture {
  const texture = new DataTexture(
    new Uint8Array([176, 168, 158, 255]),
    1,
    1,
    RGBAFormat,
    UnsignedByteType,
  );
  texture.colorSpace = SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

/**
 * A KTX2 loader that degrades instead of failing.
 *
 * If the transcoder or a texture file cannot be fetched — an offline user, a
 * blocked request, a bad deploy — the Product should still appear at the right
 * size in the right place, untextured, rather than the whole Room disappearing
 * behind a rejected Suspense boundary. Each fallback is counted so the browser
 * proof can force the failure and check what happens.
 */
class ResilientKTX2Loader extends KTX2Loader {
  override load(
    url: string,
    onLoad: (data: CompressedTexture) => void,
    onProgress?: (event: ProgressEvent) => void,
    _onError?: (err: unknown) => void,
  ): void {
    const debug = sceneDebug();
    debug.textures.requested += 1;
    super.load(
      url,
      (texture) => {
        debug.textures.decoded += 1;
        onLoad(texture);
      },
      onProgress,
      (error) => {
        debug.textures.fallback += 1;
        console.warn(`[furnitureos] KTX2 texture unavailable: ${url}`, error);
        // Deliberately not forwarding to `onError`: GLTFLoader settles one
        // promise per texture, and rejecting it would tear down the whole Mesh.
        // Handing back a neutral texture keeps the Product on screen.
        onLoad(neutralTexture() as unknown as CompressedTexture);
      },
    );
  }
}

export function configureProductLoader(loader: GLTFLoader, renderer: WebGLRenderer): void {
  const ktx2Loader = new ResilientKTX2Loader()
    .setTranscoderPath(KTX2_TRANSCODER_PATH)
    .detectSupport(renderer);
  loader.setKTX2Loader(ktx2Loader);
  loader.setMeshoptDecoder(MeshoptDecoder);
}
