// The TS decoder generated shared/conformance/vectors; this pins it so a change here
// cannot silently diverge from the Python and Rust ports that test against them.
// (The translations half is checked by the Python and Rust implementations.)

import * as fs from 'node:fs';
import * as path from 'node:path';
import { describe, it, expect } from 'vitest';
import { OetfDecoder } from '../decoder';

const DIR = path.join(__dirname, '..', '..', '..', 'shared', 'conformance', 'vectors');
const files = fs.readdirSync(DIR).filter((f) => f.endsWith('.json')).sort();

describe.each(files)('%s', (file) => {
    it('decodes exactly as recorded', () => {
        const v = JSON.parse(fs.readFileSync(path.join(DIR, file), 'utf-8'));
        const dec = new OetfDecoder();
        const records = (v.chunks as string[]).flatMap((h) => dec.feed(Buffer.from(h, 'hex')));
        expect(dec.getRecentErrors().map((e) => e.reason)).toEqual(v.errors);
        expect(records.map((r) => ({ messageName: r.messageName, msgId: r.meta?.msgId, fields: r.fields })))
            .toEqual(v.records.map((r: { messageName: string; msgId: number; fields: unknown }) =>
                ({ messageName: r.messageName, msgId: r.msgId, fields: r.fields })));
    });
});
