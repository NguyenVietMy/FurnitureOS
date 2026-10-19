import { open, readFile } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { buildProduct } from '../../scripts/build-product-assets.mjs';
import { verifyProductAssets } from '../../scripts/lib/verify-product-assets.mjs';
import { nativeTool, ownedPath, hashFile, assertLocalContext } from './safety.mjs';
import { project } from './catalogue.mjs';
import { durableFile } from './store.mjs';

// A private child process keeps synchronous gltfpack work off the HTTP loop.
// Input is a durable attempt file, not argv fragments derived from a Product.
let stage = 'startup';
const progress = async (value) => { stage = value; process.send?.({ type: 'stage', stage }); };
try {
  assertLocalContext();
  const root = process.argv[2];
  const attemptFile = await ownedPath(root, 'attempts', process.argv[3], 'input.json');
  const input = JSON.parse(await readFile(attemptFile, 'utf8'));
  const attemptDir = path.dirname(attemptFile);
  const sourceDir = await ownedPath(root, 'sources', input.attempt.id);
  const workDir = await ownedPath(root, 'attempts', input.attempt.id, 'work');
  const outputDir = await ownedPath(root, 'attempts', input.attempt.id, 'output');
  await progress('native-tool');
  const { bin, evidence: tool } = await nativeTool(root);
  const source = input.freeze.orderedSources.find((p) => p.productId === input.candidate.productId);
  await buildProduct(source, { bin, sourceDir, workDir, outputDir, progress });
  await progress('independent-validation');
  const verified = await verifyProductAssets(outputDir, source, { sourcePath: path.join(sourceDir, source.sourceFile) });
  await progress('metadata');
  const entry = await project(input.freeze, input.candidate, input.attempt, verified.manifest);
  // Flush all referenced artifacts before the durable acceptance may refer to them.
  for (const record of verified.files) {
    const file = await open(path.join(outputDir, record.file), 'r+');
    try { await file.sync(); } finally { await file.close(); }
  }
  const evidence = {
    kind: 'real-native-conversion', attemptId: input.attempt.id, source,
    input: await hashFile(attemptFile), tool, files: verified.files,
    implementation: await Promise.all([
      'scripts/build-product-assets.mjs', 'scripts/asset-pipeline.config.mjs',
      'scripts/lib/verify-product-assets.mjs', 'scripts/lib/gltf-measure.mjs',
      'scripts/lib/asset-validation.mjs', 'scripts/lib/ktx2-info.mjs',
      'tools/product-curator/worker.mjs', 'tools/product-curator/safety.mjs',
      'tools/product-curator/catalogue.mjs', 'tools/product-curator/abo_adapter.py',
      'api/catalogue/providers/abo.py', 'api/catalogue/contract.py', 'api/catalogue/static.py', 'api/models.py',
    ].map(async (file) => ({ file, ...await hashFile(path.join(REPO_ROOT, file)) }))),
    finishedAt: Date.now(), entry,
  };
  await durableFile(path.join(attemptDir, 'result.json'), evidence);
  process.send?.({ type: 'result', evidence });
} catch (error) {
  console.error(error.stack ?? error);
  process.send?.({ type: 'failure', stage, error: String(error.message ?? error) });
  process.exitCode = 1;
}
