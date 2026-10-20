import assert from 'node:assert/strict';
import { cp, lstat } from 'node:fs/promises';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { noLinks } from './safety.mjs';

// A promoted candidate may already be in the copied public union. Reuse only
// exact independently validated bytes; a mismatched directory is never replaced.
export async function copyCandidate(preview, source, destination) {
  await noLinks(destination);
  let present = false;
  try { assert((await lstat(destination)).isDirectory(), 'Candidate target is not a directory'); present = true; }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  if (!present) await cp(preview.directory, destination, { recursive: true, force: false, errorOnExist: true });
  const verified = await verifyProductAssets(destination, source);
  assert.deepEqual(verified.files, preview.files, 'Controlled runtime candidate bytes differ from immutable preparation');
}
