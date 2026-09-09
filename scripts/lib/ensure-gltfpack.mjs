import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { chmod, mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { repoPath } from './paths.mjs';

/**
 * gltfpack does meshopt compression, LOD simplification and KTX2/BasisU texture
 * encoding in one pass. Its npm build is compiled to WebAssembly and ships
 * *without* BasisU ("gltfpack was built without BasisU support"), so texture
 * compression is only available from the native release binaries — hence this
 * downloader rather than a devDependency.
 */
const GLTFPACK_VERSION = 'v1.2';

const RELEASE_ASSETS = {
  win32: 'gltfpack-windows.zip',
  linux: 'gltfpack-ubuntu.zip',
  darwin: 'gltfpack-macos.zip',
};

const TOOLS_DIR = repoPath('tools');

function binaryName() {
  return process.platform === 'win32' ? 'gltfpack.exe' : 'gltfpack';
}

async function extractZip(zipPath, destDir) {
  if (process.platform === 'win32') {
    execFileSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-Command',
        `Expand-Archive -LiteralPath '${zipPath}' -DestinationPath '${destDir}' -Force`,
      ],
      { stdio: 'inherit' },
    );
  } else {
    execFileSync('unzip', ['-o', zipPath, '-d', destDir], { stdio: 'inherit' });
  }
}

/**
 * Returns the path to a native gltfpack that supports BasisU, downloading the
 * pinned release into `tools/` on first use. Set GLTFPACK_PATH to use your own.
 */
export async function ensureGltfpack() {
  const override = process.env.GLTFPACK_PATH;
  if (override) return override;

  const binPath = path.join(TOOLS_DIR, binaryName());
  if (!existsSync(binPath)) {
    const asset = RELEASE_ASSETS[process.platform];
    if (!asset) {
      throw new Error(
        `No pinned gltfpack release for platform "${process.platform}". ` +
          'Install gltfpack manually and set GLTFPACK_PATH.',
      );
    }
    const url = `https://github.com/zeux/meshoptimizer/releases/download/${GLTFPACK_VERSION}/${asset}`;
    console.log(`  fetching gltfpack ${GLTFPACK_VERSION} for ${process.platform}`);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Failed to download ${url}: HTTP ${res.status}`);
    await mkdir(TOOLS_DIR, { recursive: true });
    const zipPath = path.join(TOOLS_DIR, asset);
    await writeFile(zipPath, Buffer.from(await res.arrayBuffer()));
    await extractZip(zipPath, TOOLS_DIR);
    if (process.platform !== 'win32') await chmod(binPath, 0o755);
  }

  // gltfpack exits non-zero for `-h`, so probe it the way we will actually call
  // it and only assert that the binary is runnable and BasisU-capable.
  const probe = spawnSync(binPath, ['-i', 'missing.gltf', '-o', 'missing.glb', '-tc'], {
    encoding: 'utf8',
  });
  if (probe.error) throw probe.error;
  const output = `${probe.stdout ?? ''}${probe.stderr ?? ''}`;
  if (output.includes('without BasisU support')) {
    throw new Error(
      `gltfpack at ${binPath} was built without BasisU support, so it cannot emit KTX2 textures. ` +
        'Point GLTFPACK_PATH at a native release build.',
    );
  }
  return binPath;
}

export async function sha256File(file) {
  return createHash('sha256').update(await readFile(file)).digest('hex');
}
