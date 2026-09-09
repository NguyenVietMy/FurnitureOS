import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, '..', '..');

export function repoPath(...segments) {
  return path.join(REPO_ROOT, ...segments);
}
