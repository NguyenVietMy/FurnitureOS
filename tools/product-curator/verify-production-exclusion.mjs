import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { python } from './safety.mjs';

const markers = ['Product curator', '/mesh/attempt/', 'x-curator-token', 'Start owner sample', 'controlled-automated-owner-state'];
async function inspect(dir) {
  for (const item of await readdir(dir, { withFileTypes: true })) {
    const file = path.join(dir, item.name);
    assert(!item.name.includes('curator'), `Curator packaged into ${file}`);
    if (item.isDirectory()) await inspect(file);
    else if (/\.(?:html|js|css|json)$/.test(item.name)) {
      const text = await readFile(file, 'utf8');
      for (const marker of markers) assert(!text.includes(marker), `${marker} leaked into ${file}`);
    }
  }
}
await inspect(path.join(REPO_ROOT, 'dist'));
const config = JSON.parse(await readFile(path.join(REPO_ROOT, 'vercel.json'), 'utf8'));
assert.equal(config.buildCommand, 'npm run build'); assert.equal(config.outputDirectory, 'dist');
assert.equal(config.functions['api/index.py'].includeFiles, '{api/**,public/style-references/**}');
execFileSync(python, ['-c', 'import api.index, sys; assert not any("curator" in str(getattr(r, "path", "")) for r in api.index.app.routes); assert not any("curator" in name for name in sys.modules); print("api.index: no curator routes/modules")'], { cwd: REPO_ROOT, stdio: 'inherit', windowsHide: true });
const paths = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: REPO_ROOT }).toString().split('\0').filter(Boolean);
for (const required of ['server.mjs', 'worker.mjs', 'unpack-native.ps1', 'ui/main.tsx', 'ui/MeshPreview.tsx', 'abo_adapter.py', 'playwright.config.ts']) assert(paths.includes(`tools/product-curator/${required}`), `Required source invisible to Git: ${required}`);
console.log('PASS: normal dist, api.index and function packaging exclude the curator; required tool source is visible to Git.');
