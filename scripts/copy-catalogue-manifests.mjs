import { copyFileSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const seedPath = join(root, 'api', 'catalogue', 'providers', 'abo-seed.json');
const seed = JSON.parse(readFileSync(seedPath, 'utf8'));
const destinationDir = join(root, 'api', 'catalogue', 'providers', 'manifests');
rmSync(destinationDir, { recursive: true, force: true });
mkdirSync(destinationDir, { recursive: true });
for (const { productId } of seed.products) {
  const source = join(root, 'public', 'products', productId, 'asset-manifest.json');
  const destination = join(destinationDir, `${productId}.json`);
  mkdirSync(dirname(destination), { recursive: true });
  copyFileSync(source, destination);
  console.log(`catalogue manifest: ${productId} -> api/catalogue/providers/manifests/`);
}
