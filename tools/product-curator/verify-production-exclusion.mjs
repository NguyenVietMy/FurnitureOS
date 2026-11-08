import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { python } from './safety.mjs';
import { pythonFunctionPolicy } from '../../scripts/lib/function-bundle.mjs';

const markers = ['Product curator', '/mesh/attempt/', 'x-curator-token', 'Start owner sample', 'controlled-automated-owner-state', 'Expansion Mesh review', '/api/expansion', 'expansion-server.mjs'];
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
const policy = pythonFunctionPolicy(config);
assert.equal(policy.includeFiles, '{api/**,public/style-references/**}');assert.equal(policy.maxDuration,300);
execFileSync(python, ['-c', 'import api.index, api.main, sys; assert api.index.app is api.main.app; assert all(not any("curator" in str(getattr(r, "path", "")) for r in app.routes) for app in (api.index.app,api.main.app)); assert not any("curator" in name for name in sys.modules); print("api.index/api.main: no curator routes/modules")'], { cwd: REPO_ROOT, stdio: 'inherit', windowsHide: true });
const paths = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], { cwd: REPO_ROOT }).toString().split('\0').filter(Boolean);
for (const required of ['server.mjs', 'worker.mjs', 'unpack-native.ps1', 'ui/main.tsx', 'ui/MeshPreview.tsx', 'abo_adapter.py', 'playwright.config.ts','expansion.mjs','expansion-server.mjs','expansion.html','ui/expansion.tsx','promote-expansion.mjs','pin-expansion.mjs','promotion-lock.mjs','promotion-lock.py']) assert(paths.includes(`tools/product-curator/${required}`), `Required source invisible to Git: ${required}`);
console.log('PASS: normal dist and both API exports exclude curator routes/modules; shared function policy checked. Complete function contents/size and hosting remain UNRUN.');
