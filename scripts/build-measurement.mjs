import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
const seedPath = resolve(repoRoot, 'api/catalogue/providers/abo-seed.json');
const inputRoots = ['api', 'public/products', 'scripts', 'src'];

function filesBelow(path) {
  if (!existsSync(path)) return [];
  if (statSync(path).isFile()) return [path];
  return readdirSync(path, { withFileTypes: true })
    .filter((entry) => entry.name !== '__pycache__')
    .flatMap((entry) => filesBelow(resolve(path, entry.name)));
}

function digestFiles(files) {
  const hash = createHash('sha256');
  for (const file of files.sort()) {
    hash.update(relative(repoRoot, file).replaceAll('\\', '/'));
    hash.update('\0');
    hash.update(readFileSync(file));
    hash.update('\0');
  }
  return hash.digest('hex');
}

const manifestDir = resolve(repoRoot, 'api/catalogue/providers/manifests');
const inputs = inputRoots.flatMap((path) => filesBelow(resolve(repoRoot, path)))
  .filter((path) => !path.startsWith(`${manifestDir}\\`) && path !== manifestDir && !path.endsWith('.pyc'));
inputs.push(resolve(repoRoot, 'package.json'), resolve(repoRoot, 'package-lock.json'), resolve(repoRoot, 'vite.config.ts'));
const sourceInputDigest = digestFiles([...new Set(inputs)]);
const buildId = `measurement-${sourceInputDigest.slice(0, 16)}`;
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const result = spawnSync(npm, ['run', 'build'], {
  cwd: repoRoot,
  env: {
    ...process.env,
    VITE_ENABLE_CATALOGUE_GALLERY: '1',
    VITE_MEASUREMENT_BUILD_ID: buildId,
  },
  stdio: 'inherit',
  shell: process.platform === 'win32',
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);

const distDir = resolve(repoRoot, 'dist');
const distFiles = filesBelow(distDir).filter((path) => !path.endsWith('measurement-build.json'));
const distDigest = digestFiles(distFiles);
const seed = JSON.parse(readFileSync(seedPath, 'utf8'));
const record = {
  schemaVersion: 1,
  buildId,
  catalogueVersion: seed.catalogueVersion,
  productCount: seed.products.length,
  productIds: seed.products.map((product) => product.productId),
  sourceInputDigest,
  distDigest,
  digestScope: 'All dist files except this record; paths and bytes are hashed in ordinal path order.',
  files: distFiles.map((path) => ({
    path: relative(distDir, path).replaceAll('\\', '/'),
    bytes: statSync(path).size,
    sha256: createHash('sha256').update(readFileSync(path)).digest('hex'),
  })),
};
writeFileSync(resolve(distDir, 'measurement-build.json'), `${JSON.stringify(record, null, 2)}\n`);
console.log(`Controlled measurement build ${buildId}`);
console.log(`Catalogue ${record.catalogueVersion}; ${record.productCount} Products; dist SHA-256 ${distDigest}`);
