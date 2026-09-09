// Publishes the BasisU transcoder that KTX2Loader needs.
//
// three ships the transcoder inside node_modules; drei's useGLTF would instead
// pull it from a Google CDN at runtime. We copy the version that matches the
// installed three into public/decoders/basis/ so the app has no third-party
// runtime dependency and the browser proof can assert the requests are served
// from our own origin.
import { copyFileSync, mkdirSync, existsSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { repoPath } from './lib/paths.mjs';

const require = createRequire(import.meta.url);
const FILES = ['basis_transcoder.js', 'basis_transcoder.wasm'];

const sourceDir = dirname(require.resolve('three/examples/jsm/libs/basis/basis_transcoder.js'));
const targetDir = repoPath('public', 'decoders', 'basis');
mkdirSync(targetDir, { recursive: true });

for (const file of FILES) {
  const from = join(sourceDir, file);
  if (!existsSync(from)) {
    throw new Error(`three does not ship ${file} at ${from}; cannot publish the KTX2 transcoder`);
  }
  const to = join(targetDir, file);
  copyFileSync(from, to);
  console.log(`decoders: ${file} ${statSync(to).size} bytes -> public/decoders/basis/`);
}
