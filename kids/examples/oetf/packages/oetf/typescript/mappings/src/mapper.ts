import * as fs from 'node:fs';
import { OetfDecoder, type DecodedRecord } from '@open-billie/decoder-oetf';
import { LOOKUPS_PATH, loadMapping } from './paths';

type MappingStep = { conversion: string; params?: Record<string, unknown> };
type MappingRule = {
  from?: string;
  value?: unknown;
  to: string;
  enabled?: boolean;
  availableIf?: { field: string; equals: unknown };
  via?: MappingStep[];
};
type CanonicalMap = {
  source: { protocol: string; message: string };
  target: { message: string };
  enabled?: boolean;
  repeats?: { field: string; max?: number };
  mappings: MappingRule[];
};

const MAP = loadMapping('OETF_msg_16/canonical-track-v2.json') as CanonicalMap;
const LOOKUP: Record<string, string> = JSON.parse(
  fs.readFileSync(`${LOOKUPS_PATH}/OETF_classification_canonical.json`, 'utf8'),
) as Record<string, string>;

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'bigint') return Number(value);
  if (typeof value === 'string') {
    const labelled = value.match(/\((-?\d+(?:\.\d+)?)\)\s*$/);
    const unitValue = value.match(/^(-?\d+(?:\.\d+)?)\s+\S+$/);
    const match = labelled ?? unitValue;
    if (match) return Number(match[1]);
    if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
  }
  return undefined;
}

function readField(fields: Record<string, unknown>, path: string): unknown {
  if (Object.hasOwn(fields, path)) return fields[path];
  let value: unknown = fields;
  for (const part of path.split('.')) {
    if (typeof value !== 'object' || value === null || !(part in value)) return undefined;
    value = (value as Record<string, unknown>)[part];
  }
  return value;
}

function writeField(fields: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split('.');
  const leaf = parts.pop();
  if (!leaf) return;
  let target = fields;
  for (const part of parts) {
    if (typeof target[part] !== 'object' || target[part] === null || Array.isArray(target[part])) {
      target[part] = {};
    }
    target = target[part] as Record<string, unknown>;
  }
  target[leaf] = value;
}

function convert(value: unknown, steps: MappingStep[] = []): unknown {
  let current = value;
  for (const step of steps) {
    switch (step.conversion) {
      case 'uintToString':
        if (typeof current === 'number' || typeof current === 'bigint') current = String(current);
        break;
      case 'toBoolean': {
        const n = numberValue(current);
        if (typeof current === 'boolean') break;
        if (n === 0 || n === 1) current = n === 1;
        else current = undefined;
        break;
      }
      case 'epochMicrosToIso8601': {
        const micros = numberValue(current);
        if (micros !== undefined) current = new Date(Math.trunc(micros / 1000)).toISOString();
        break;
      }
      case 'scale': {
        const n = numberValue(current);
        const factor = Number(step.params?.factor);
        if (n !== undefined && Number.isFinite(factor)) current = n * factor;
        break;
      }
      case 'lookup': {
        const key = String(numberValue(current) ?? current);
        if (LOOKUP[key] !== undefined) current = LOOKUP[key];
        break;
      }
      case 'toCanonicalIdentifier': {
        const scheme = String(step.params?.scheme ?? '');
        if (!scheme) throw new Error('toCanonicalIdentifier requires params.scheme');
        if (typeof current === 'string' || typeof current === 'number' || typeof current === 'bigint') {
          current = [{ scheme, value: String(numberValue(current) ?? current) }];
        } else {
          current = undefined;
        }
        break;
      }
      default:
        throw new Error(`TypeScript OETF mapper does not implement conversion '${step.conversion}'`);
    }
  }
  return current;
}

/** Apply the shared OETF-to-canonical map, returning one canonical Track per repeated target. */
export function mapOetfRecord(record: DecodedRecord): Record<string, unknown>[] {
  if (!MAP.enabled || record.messageName !== MAP.source.message) return [];
  const rawCount = numberValue(readField(record.fields, MAP.repeats?.field ?? '')) ?? 0;
  const count = Math.max(0, Math.min(Math.floor(rawCount), MAP.repeats?.max ?? Number.MAX_SAFE_INTEGER));
  const mapped: Record<string, unknown>[] = [];

  for (let index = 0; index < count; index += 1) {
    const fields: Record<string, unknown> = {};
    for (const rule of MAP.mappings) {
      if (rule.enabled === false) continue;
      const interpolate = (name: string) => name.replaceAll('{n}', String(index));
      if (rule.availableIf) {
        const actual = readField(record.fields, interpolate(rule.availableIf.field));
        if (numberValue(actual) !== numberValue(rule.availableIf.equals) && actual !== rule.availableIf.equals) continue;
      }
      let value: unknown;
      if (rule.from) {
        const input = readField(record.fields, interpolate(rule.from));
        if (input === undefined || input === null || input === '(not present)' || input === '(invalid)') continue;
        value = convert(numberValue(input) ?? input, rule.via);
      } else {
        value = rule.value;
      }
      if (value !== undefined && value !== null) writeField(fields, interpolate(rule.to), value);
    }
    mapped.push({ messageName: MAP.target.message, fields });
  }
  return mapped;
}

/** Expose decoder wiring for consumers that want a compact decode-and-map call. */
export function decodeAndMapOetf(frame: Buffer): Record<string, unknown>[] {
  const decoder = new OetfDecoder();
  return decoder.feed(frame).flatMap(mapOetfRecord);
}
