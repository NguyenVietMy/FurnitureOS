import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const productId = 'bed-prudence-tufted-queen-natural';
const source = join(root, 'public', 'products', productId, 'asset-manifest.json');
const destination = join(root, 'api', 'catalogue', 'providers', 'asset-manifest.json');
mkdirSync(dirname(destination), { recursive: true });
copyFileSync(source, destination);
console.log(`catalogue manifest: ${productId} -> api/catalogue/providers/`);
