// =============================================================================
// @open-billie/mappings-oetf
//
// Absolute paths to the language-neutral shared OETF maps and lookup tables.
// =============================================================================

import * as fs from 'node:fs';
import * as path from 'node:path';

const PKG_ROOT = path.join(__dirname, '..');

function sharedDir(sub: string): string {
  const packed = path.join(PKG_ROOT, 'shared', sub);
  return fs.existsSync(packed) ? packed : path.join(PKG_ROOT, '..', '..', 'shared', sub);
}

/** Absolute path to the per-message/target OETF mappings. */
export const MAPPINGS_PATH = sharedDir('mappings');

/** Absolute path to lookup tables referenced by the mappings. */
export const LOOKUPS_PATH = sharedDir('lookups');

/** List map files relative to `MAPPINGS_PATH`. */
export function listMappingFiles(): string[] {
  const files: string[] = [];
  const walk = (directory: string, relative: string): void => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const next = relative ? `${relative}/${entry.name}` : entry.name;
      if (entry.isDirectory()) walk(path.join(directory, entry.name), next);
      else if (entry.name.endsWith('.json')) files.push(next);
    }
  };
  walk(MAPPINGS_PATH, '');
  return files.sort();
}

/** Load and parse one map JSON document. */
export function loadMapping(relativePath: string): unknown {
  const fullPath = path.join(MAPPINGS_PATH, relativePath);
  if (!fs.existsSync(fullPath)) throw new Error(`@open-billie/mappings-oetf: no mapping at ${relativePath}`);
  return JSON.parse(fs.readFileSync(fullPath, 'utf8')) as unknown;
}
