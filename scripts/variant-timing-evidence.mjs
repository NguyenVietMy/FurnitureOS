import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

export function createTimingEvidence(directory) {
  mkdirSync(directory); // Existing attempts, including failures, are never reused.
  return (name, record) => writeFileSync(resolve(directory, name), JSON.stringify(record, null, 2), { flag: 'wx' });
}
