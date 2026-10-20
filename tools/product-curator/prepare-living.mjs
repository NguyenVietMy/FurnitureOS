import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { copyFile, mkdir, readFile } from 'node:fs/promises';
import { PRODUCT_ASSET_SOURCES } from '../../scripts/asset-pipeline.config.mjs';
import { buildProduct } from '../../scripts/build-product-assets.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { assertLocalContext, ownRoot, ownedPath, noLinks, noGitAncestor, nativeTool, hashFile, digest } from './safety.mjs';
import { durableFile } from './store.mjs';
import { livingProfile, LIVING_PROFILE } from './profiles.mjs';
import { adapter } from './catalogue.mjs';

// Preparation is immutable and never starts an owner review or accepts a Product.
export async function prepareLiving({ stateDir, sourceDir }) {
  assertLocalContext();
  const root = await ownRoot(stateDir);
  const inputDir = await noLinks(sourceDir);
  await noGitAncestor(inputDir);
  const { raw, seed, sources } = await livingProfile();
  await adapter({ mode: 'seed', profile: LIVING_PROFILE, seed });
  await durableFile(await ownedPath(root, 'preparation-started.json'), { profile: LIVING_PROFILE, seedSha256: digest(raw) });
  const tool = await nativeTool(root);
  const preparations = [];
  for (const source of sources.filter((s) => !PRODUCT_ASSET_SOURCES.some((old) => old.productId === s.productId))) {
    const dir = await ownedPath(root, 'preparations', source.productId);
    await mkdir(dir, { recursive: true });
    const sourcesDir = await ownedPath(root, 'preparations', source.productId, 'source');
    await mkdir(sourcesDir);
    const original = await noLinks(path.join(inputDir, source.sourceFile));
    assert.deepEqual(await hashFile(original), { bytes: source.sourceBytes, sha256: source.sourceSha256 });
    const sourcePath = path.join(sourcesDir, source.sourceFile);
    await copyFile(original, sourcePath);
    const input = { source, tool: tool.evidence, seedSha256: digest(raw) };
    await durableFile(path.join(dir, 'input.json'), input);
    await buildProduct(source, { bin: tool.bin, sourceDir: sourcesDir, workDir: path.join(dir, 'work'), outputDir: path.join(dir, 'output') });
    const verified = await verifyProductAssets(path.join(dir, 'output'), source, { sourcePath });
    const result = { source, input: await hashFile(path.join(dir, 'input.json')), tool: tool.evidence, files: verified.files };
    await durableFile(path.join(dir, 'result.json'), result);
    preparations.push(result);
  }
  const result = { profile: LIVING_PROFILE, seedSha256: digest(raw), preparations };
  await durableFile(await ownedPath(root, 'prepared.json'), result);
  return result;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  assert(args.length === 4 && args[0] === '--state-dir' && args[2] === '--source-dir', 'Use --state-dir <new-external> --source-dir <exact-task-sources>');
  await prepareLiving({ stateDir: args[1], sourceDir: args[3] });
}
