// Read-only source inspection plus an exclusive external manifest write.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { REPO_ROOT } from '../../scripts/lib/paths.mjs';
import { noGitAncestor, noLinks, digest, hashFile } from './safety.mjs';
import { durableFile } from './store.mjs';

const args = process.argv.slice(2);
assert(args.length === 6 && args[0] === '--baseline' && args[2] === '--plan' && args[4] === '--out', 'Usage: node tools/product-curator/freeze-source.mjs --baseline <BASELINE.json> --plan <PLAN.md> --out <new-external-manifest.json>');
const out = await noLinks(args[5]); await noGitAncestor(out);
const baseline = JSON.parse(await readFile(args[1], 'utf8'));
const git = (argv) => execFileSync('git', argv, { cwd: REPO_ROOT }).toString();
const head = git(['rev-parse', 'HEAD']).trim(); assert.equal(head, baseline.head);
const staged = git(['diff', '--cached', '--name-only']); assert.equal(staged, '', 'Do not stage source');
const tracked = git(['ls-files', '-z']).split('\0').filter(Boolean);
const untracked = git(['ls-files', '--others', '--exclude-standard', '-z']).split('\0').filter(Boolean);
const all = [...new Set([...tracked, ...untracked])].sort();
const original = new Map(baseline.records.map((r) => [r.path, r]));
const records = [];
for (const file of all) {
  const previous = original.get(file);
  try {
    const current = await hashFile(path.join(REPO_ROOT, file));
    const status = !previous ? 'added' : previous.sha256 === current.sha256 && previous.bytes === current.bytes ? 'unchanged' : 'modified';
    records.push({ path: file, status, ...current, baselineSha256: previous?.sha256 ?? null });
    if (status !== 'unchanged' && /\.(?:mjs|py|json|ts|tsx|css|html|ps1|md)$/.test(file)) {
      const text = await readFile(path.join(REPO_ROOT, file), 'utf8');
      assert(!/[\t ]+\r?$/m.test(text), `Trailing whitespace in ${file}`);
      assert(text.endsWith('\n') && !text.endsWith('\n\n'), `Missing or extra EOF newline in ${file}`);
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    records.push({ path: file, status: 'deleted', bytes: 0, sha256: null, baselineSha256: previous?.sha256 ?? null });
  }
}
// Source deliverables must appear without force-adding tools or runtime output.
async function inspectTool(dir) {
  for (const item of await readdir(path.join(REPO_ROOT, dir), { withFileTypes: true })) {
    const file = `${dir}/${item.name}`;
    if (item.isDirectory() && !['node_modules', '__pycache__', 'dist'].includes(item.name)) await inspectTool(file);
    else if (item.isFile() && /\.(?:mjs|py|json|ts|tsx|css|html|ps1|md)$/.test(item.name)) assert(all.includes(file), `Source deliverable is ignored: ${file}`);
  }
}
await inspectTool('tools/product-curator');
for (const record of records) {
  if (record.path.startsWith('public/') || record.path.startsWith('src/') || ['api/catalogue/providers/abo-seed.json', 'scripts/asset-pipeline.config.mjs', 'package-lock.json', 'uv.lock', 'vercel.json', 'api/index.py'].includes(record.path)) assert.equal(record.status, 'unchanged', `Protected production/default source changed: ${record.path}`);
}
execFileSync('git', ['diff', '--check'], { cwd: REPO_ROOT });
const manifest = {
  recordType: 'builder final raw source freeze', createdAt: new Date().toISOString(), repo: REPO_ROOT, head,
  planSha256: digest(await readFile(args[3])), baselineAggregateSha256: baseline.aggregateSha256,
  aggregateAlgorithm: 'SHA256 of UTF-8 JSON.stringify(records) in ascending Git path order',
  aggregateSha256: digest(JSON.stringify(records)), count: records.length,
  changed: records.filter((r) => r.status !== 'unchanged').map((r) => r.path),
  status: git(['status', '--porcelain=v1', '--untracked-files=all']), records,
};
await durableFile(out, manifest);
console.log(JSON.stringify({ file: out, ...await hashFile(out), aggregateSha256: manifest.aggregateSha256, count: manifest.count, changed: manifest.changed, head, planSha256: manifest.planSha256 }, null, 2));
