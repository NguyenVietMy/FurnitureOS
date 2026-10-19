import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { lstat, mkdir, readdir, readFile, realpath, writeFile, chmod } from 'node:fs/promises';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';

export const digest = (bytes) => createHash('sha256').update(bytes).digest('hex');
export const clone = (value) => structuredClone(value);
export const python = path.join(REPO_ROOT, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
export const OWNERSHIP = 'FurnitureOS Product curator v1';

export function assertLocalContext(env = process.env) {
  for (const key of ['CI', 'VERCEL', 'VERCEL_ENV', 'NETLIFY', 'AWS_LAMBDA_FUNCTION_NAME', 'K_SERVICE', 'WEBSITE_INSTANCE_ID']) {
    assert(!env[key], `Local curator refuses hosted/CI context: ${key}`);
  }
  assert(env.NODE_ENV !== 'production', 'Local curator refuses NODE_ENV=production');
  for (const key of ['GLTFPACK_PATH', 'FURNITUREOS_ASSET_SOURCE_DIR', 'FURNITUREOS_ASSET_WORK_DIR', 'FURNITUREOS_ASSET_TOOLS_DIR']) {
    assert(!env[key], `Unset ${key}; curator owns all native/source/work paths`);
  }
}
export const within = (parent, child) => {
  const relative = path.relative(path.resolve(parent), path.resolve(child));
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
};
export async function noLinks(target) {
  const absolute = path.resolve(target);
  let current = path.parse(absolute).root;
  for (const part of absolute.slice(current.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    try { assert(!(await lstat(current)).isSymbolicLink(), `Symlink/reparse path rejected: ${current}`); }
    catch (error) { if (error.code === 'ENOENT') break; throw error; }
  }
  return absolute;
}
export async function ownRoot(target) {
  const root = await noLinks(target);
  await noGitAncestor(root);
  const forbidden = [REPO_ROOT, path.dirname(REPO_ROOT)];
  assert(!forbidden.some((dir) => within(root, dir) || within(dir, root)), 'State directory overlaps checkout/worktrees');
  for (const dir of [path.parse(root).root, process.env.USERPROFILE, process.env.LOCALAPPDATA, process.env.TEMP, process.env.HOME].filter(Boolean)) {
    assert(path.resolve(dir).toLowerCase() !== root.toLowerCase() && !within(root, dir), 'Dangerous state directory root');
  }
  assert(root.split(path.sep).filter(Boolean).length >= 3, 'State directory is too broad');
  await mkdir(root, { recursive: true });
  const marker = path.join(root, '.product-curator-owner.json');
  const entries = await readdir(root);
  if (entries.length === 0) {
    await writeFile(marker, JSON.stringify({ owner: OWNERSHIP, id: randomUUID() }), { flag: 'wx' });
  } else {
    await noLinks(marker);
    assert.equal(JSON.parse(await readFile(marker, 'utf8')).owner, OWNERSHIP, 'Unknown populated state directory; choose a fresh empty directory');
  }
  assert.equal((await realpath(root)).toLowerCase(), root.toLowerCase(), 'State root resolves elsewhere');
  return root;
}
export async function ownedPath(root, ...parts) {
  const target = path.resolve(root, ...parts);
  assert(within(root, target) && target !== root, 'Path escaped owned root');
  await noLinks(target);
  await noGitAncestor(target);
  return target;
}
export async function noGitAncestor(target) {
  let ancestor = path.resolve(target);
  while (true) {
    try {
      await lstat(path.join(ancestor, '.git'));
      throw new Error(`State/work/source path is inside a Git checkout: ${ancestor}`);
    } catch (error) { if (!['ENOENT', 'ENOTDIR'].includes(error.code)) throw error; }
    const parent = path.dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }
}
export async function hashFile(file) {
  const bytes = await readFile(file);
  return { bytes: bytes.length, sha256: digest(bytes) };
}

// Official meshoptimizer v1.2 Windows release, independently frozen at setup.
// Other platforms fail closed until an explicit reviewed release pin is added.
export const NATIVE = {
  url: 'https://github.com/zeux/meshoptimizer/releases/download/v1.2/gltfpack-windows.zip',
  sha256: '52e0c061d8b42f1c6bd8fe1cbc1e26a9da579ad5a4f5dd30a8ee0d599062f6c4',
};
export async function nativeTool(root) {
  assertLocalContext();
  assert.equal(process.platform, 'win32', 'Curator native release is currently pinned for Windows only');
  const tools = await ownedPath(root, 'tools');
  await mkdir(tools, { recursive: true });
  const pinPath = path.join(tools, 'verified-tool.json');
  try {
    const pin = JSON.parse(await readFile(pinPath, 'utf8'));
    assert.equal(pin.archive.sha256, NATIVE.sha256, 'Native archive pin mismatch');
    const archive = await ownedPath(root, pin.archive.file);
    assert.deepEqual(await hashFile(archive), { bytes: pin.archive.bytes, sha256: NATIVE.sha256 }, 'Cached tool archive changed');
    const bin = await ownedPath(root, pin.binary.file);
    assert.deepEqual(await hashFile(bin), { bytes: pin.binary.bytes, sha256: pin.binary.sha256 }, 'Cached native binary changed');
    return { bin, evidence: pin };
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  const dir = await ownedPath(root, 'tools', randomUUID());
  await mkdir(dir);
  const archive = path.join(dir, 'gltfpack-windows.zip');
  const response = await fetch(NATIVE.url, { signal: AbortSignal.timeout(120_000) });
  assert(response.ok, `Native download HTTP ${response.status}`);
  const bytes = Buffer.from(await response.arrayBuffer());
  await writeFile(archive, bytes, { flag: 'wx' });
  assert.equal(digest(bytes), NATIVE.sha256, 'Native release archive checksum mismatch; retained for diagnosis');
  // Paths are passed as literal PowerShell arguments, never shell interpolated.
  const script = path.join(REPO_ROOT, 'tools/product-curator/unpack-native.ps1');
  execFileSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '-Archive', archive, '-Destination', dir], { stdio: 'pipe', windowsHide: true });
  const bin = await ownedPath(root, 'tools', path.basename(dir), 'gltfpack.exe');
  await chmod(bin, 0o700);
  const evidence = {
    version: 'meshoptimizer-v1.2', url: NATIVE.url,
    archive: { file: path.relative(root, archive), ...await hashFile(archive) },
    binary: { file: path.relative(root, bin), ...await hashFile(bin) },
  };
  await writeFile(pinPath, `${JSON.stringify(evidence, null, 2)}\n`, { flag: 'wx' });
  return { bin, evidence };
}
