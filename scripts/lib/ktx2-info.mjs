import { readFile } from 'node:fs/promises';

/** Human-readable names for the supercompression schemes we can emit. */
export const SUPERCOMPRESSION_SCHEMES = {
  0: 'none',
  1: 'BasisLZ',
  2: 'Zstandard',
  3: 'ZLIB',
};

const KTX2_IDENTIFIER = Buffer.from([
  0xab, 0x4b, 0x54, 0x58, 0x20, 0x32, 0x30, 0xbb, 0x0d, 0x0a, 0x1a, 0x0a,
]);

/**
 * Reads the KTX2 header without decoding the payload, so texture dimensions and
 * supercompression scheme can be asserted without a transcoder.
 *
 * Header layout (KTX 2.0 §3.1): 12-byte identifier, then u32 vkFormat (12),
 * typeSize (16), pixelWidth (20), pixelHeight (24), pixelDepth (28),
 * layerCount (32), faceCount (36), levelCount (40), supercompressionScheme (44).
 */
export async function ktx2Info(file) {
  const buf = await readFile(file);
  if (!buf.subarray(0, 12).equals(KTX2_IDENTIFIER)) {
    throw new Error(`${file} is not a KTX2 file`);
  }
  const supercompressionScheme = buf.readUInt32LE(44);
  return {
    bytes: buf.length,
    vkFormat: buf.readUInt32LE(12),
    width: buf.readUInt32LE(20),
    height: buf.readUInt32LE(24),
    faceCount: buf.readUInt32LE(36),
    levelCount: buf.readUInt32LE(40),
    supercompressionScheme,
    supercompression: SUPERCOMPRESSION_SCHEMES[supercompressionScheme] ?? 'unknown',
  };
}

