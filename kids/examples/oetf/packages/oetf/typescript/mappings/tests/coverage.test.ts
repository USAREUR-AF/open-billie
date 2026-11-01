// Guards the map files against drift from the decoder schemas: every `from`
// must resolve on a real decoded record, and every decoded field must appear
// in `mappings`, the `unmapped` ledger, or the `repeats` driver.

import * as fs from 'node:fs';
import * as path from 'node:path';
import { describe, it, expect } from 'vitest';
import { OetfDecoder, buildTrackReport, type TrackInput } from '@open-billie/decoder-oetf';
import { LOOKUPS_PATH, listMappingFiles, loadMapping } from '../src/index';
import { mapOetfRecord } from '../src/mapper';

interface MapDoc {
    source: { message: string };
    repeats?: { field: string };
    mappings: { from?: string; availableIf?: { field: string }; via?: { conversion: string; params?: { table?: string } }[] }[];
    unmapped?: { from: string }[];
}

const TRACK: TrackInput = {
    id: 1, classification: 1, confidencePct: 50, mode3a: '1200',
    latDeg: 1, lonDeg: 1, altM: 1, velEastMs: 1, velNorthMs: 1, velUpMs: 1,
    posSigmaEastM: 1, posSigmaNorthM: 1, altSigmaM: 1, velSigmaEastMs: 1, velSigmaNorthMs: 1, rcsDbsm: 1, ageS: 1,
};

const record = new OetfDecoder().feed(buildTrackReport({ sequence: 0, sensorId: 0 }, 0n, [TRACK]))[0]!;

function resolves(fields: Record<string, unknown>, name: string): boolean {
    if (name in fields) return true;
    const dot = name.lastIndexOf('.');
    if (dot < 0) return false;
    const parent = fields[name.slice(0, dot)];
    return typeof parent === 'object' && parent !== null && name.slice(dot + 1) in parent;
}

const at0 = (s: string): string => s.replace(/\{n\}/g, '0');

it('maps RCS to the canonical SAPIENT object-info identifier', () => {
    const tracks = mapOetfRecord(record);
    expect(tracks[0]?.fields.identifiers).toEqual([
        { scheme: 'sapient-object-info', value: '1' },
    ]);
});

it('preserves OETF header and per-track status flags in canonical output', () => {
    const frame = buildTrackReport(
        { sequence: 8, sensorId: 7, testData: true, simulated: true },
        1_761_739_200_123_456n,
        [{ ...TRACK, confirmed: false, coasting: true, finalUpdate: true, simulated: true }],
    );
    const decoded = new OetfDecoder().feed(frame)[0]!;
    const [track] = mapOetfRecord(decoded);
    expect(track?.fields).toMatchObject({
        sourceId: '7',
        trackGeneration: 'fixture-1',
        testData: true,
        headerSimulated: true,
        simulated: true,
        confirmed: false,
        coasting: true,
        finalUpdate: true,
    });
});

describe.each(listMappingFiles())('%s', (file) => {
    const doc = loadMapping(file) as MapDoc;
    const froms = doc.mappings.flatMap((m) => (m.from ? m.from.split('|') : []));
    const ledger = [...(doc.unmapped ?? []).map((u) => u.from), ...(doc.repeats ? [doc.repeats.field] : [])];

    it('targets the decoder message name', () => {
        expect(doc.source.message).toBe(record.messageName);
    });

    it('every from / availableIf / unmapped field resolves on a decoded record', () => {
        const names = [...froms, ...ledger, ...doc.mappings.flatMap((m) => (m.availableIf ? [m.availableIf.field] : []))];
        const missing = names.map(at0).filter((n) => !resolves(record.fields, n));
        expect(missing).toEqual([]);
    });

    it('every decoded field is mapped or ledgered', () => {
        const covered = new Set([...froms, ...ledger].map(at0));
        const coveredParents = new Set([...covered].map((n) => n.split('.')[0]));
        const decoded = Object.keys(record.fields)
            .filter((k) => !/^Reserved/.test(k) && !/^Track [1-9]/.test(k));
        const uncovered = decoded.filter((k) => !covered.has(k) && !coveredParents.has(k));
        expect(uncovered).toEqual([]);
    });

    it('every lookup table it references ships in lookups/', () => {
        const tables = doc.mappings.flatMap((m) => m.via ?? [])
            .filter((v) => v.conversion === 'lookup')
            .map((v) => v.params?.table);
        for (const t of tables) expect(fs.existsSync(path.join(LOOKUPS_PATH, `${t}.json`))).toBe(true);
    });
});
