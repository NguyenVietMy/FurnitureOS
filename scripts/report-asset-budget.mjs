// Re-measures every published Product asset from disk and checks it against the
// budget. This does not trust the manifest: it stats the files, re-reads the
// KTX2 headers and re-measures the glTF bounds, then compares. Run it after
// `npm run assets:build`, or on its own to confirm nothing drifted.
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { readFile } from 'node:fs/promises';
import { ASSET_BUDGET_BYTES, MAX_TEXTURE_PX } from './asset-pipeline.config.mjs';
import { ktx2Info } from './lib/ktx2-info.mjs';
import { measureGltf } from './lib/gltf-measure.mjs';
import { repoPath } from './lib/paths.mjs';

const productsDir = repoPath('public', 'products');
if (!existsSync(productsDir)) {
  console.error('No published Products. Run "npm run assets:build".');
  process.exit(1);
}

let failures = 0;
const fail = (message) => {
  failures += 1;
  console.error(`  FAIL ${message}`);
};

for (const productId of readdirSync(productsDir)) {
  const dir = join(productsDir, productId);
  if (!statSync(dir).isDirectory()) continue;
  const manifest = JSON.parse(await readFile(join(dir, 'asset-manifest.json'), 'utf8'));
  console.log(`\n${productId}`);

  let exclusive = 0;
  for (const lod of manifest.lods) {
    let lodBytes = 0;
    for (const file of lod.files) {
      const path = join(dir, file);
      if (!existsSync(path)) { fail(`missing ${file}`); continue; }
      lodBytes += statSync(path).size;
    }
    exclusive += lodBytes;
    const measured = await measureGltf(join(dir, `lod${lod.level}.gltf`));
    const required = measured.extensionsRequired;
    for (const extension of ['EXT_meshopt_compression', 'KHR_texture_basisu']) {
      if (!required.includes(extension)) fail(`lod${lod.level} does not require ${extension}`);
    }
    if (lodBytes !== lod.exclusiveBytes) {
      fail(`lod${lod.level} is ${lodBytes} bytes on disk, manifest says ${lod.exclusiveBytes}`);
    }
    console.log(
      `  lod${lod.level}  ${String(measured.triangles).padStart(6)} tris  ` +
        `${String(lodBytes).padStart(7)} B  bounds ${measured.size.map((v) => v.toFixed(3)).join(' x ')}`,
    );
  }

  let shared = 0;
  for (const texture of manifest.sharedTextures) {
    const path = join(dir, texture.file);
    if (!existsSync(path)) { fail(`missing ${texture.file}`); continue; }
    const bytes = statSync(path).size;
    shared += bytes;
    const info = await ktx2Info(path);
    if (info.width > MAX_TEXTURE_PX || info.height > MAX_TEXTURE_PX) {
      fail(`${texture.file} is ${info.width}x${info.height}, over the ${MAX_TEXTURE_PX} px cap`);
    }
    if (info.supercompression !== 'BasisLZ') {
      fail(`${texture.file} is ${info.supercompression}, expected BasisLZ`);
    }
    console.log(
      `  tex   ${info.width}x${info.height} ${info.supercompression} ` +
        `${String(bytes).padStart(7)} B  ${texture.file}`,
    );
  }

  // Shared textures are counted once, not once per level.
  const total = exclusive + shared;
  const verdict = total <= ASSET_BUDGET_BYTES ? 'within' : 'OVER';
  console.log(
    `  total ${total} B (${(total / 1024 / 1024).toFixed(2)} MB) ${verdict} the ` +
      `${(ASSET_BUDGET_BYTES / 1024 / 1024).toFixed(0)} MB budget; shared textures counted once (${shared} B)`,
  );
  if (total > ASSET_BUDGET_BYTES) fail(`${productId} is over budget`);
  if (total !== manifest.budget.totalCompressedBytes) {
    fail(`disk total ${total} does not match manifest ${manifest.budget.totalCompressedBytes}`);
  }
}

if (failures) {
  console.error(`\n${failures} asset budget check(s) failed.`);
  process.exit(1);
}
console.log('\nAll published Product assets are within budget and correctly formatted.');
