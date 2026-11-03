// Round-trips builder → decoder and pins the framing-recovery behaviour.

import { describe, it, expect } from 'vitest';
import { OetfDecoder, crc16 } from '../decoder';
import { buildSensorStatus, buildTrackReport, buildFrame, type TrackInput } from '../builder';

const HDR = { sequence: 42, sensorId: 0x0107 };
const TS = 1_761_739_200_123_456n; // 2025-10-29T12:00:00.123456Z

const TRACK: TrackInput = {
    id: 311, classification: 3, confidencePct: 87,
    confirmed: true, mode3a: '7000',
    latDeg: 0.0, lonDeg: 0.0, altM: 152.4,
    velEastMs: -12.5, velNorthMs: 4.25, velUpMs: 1.5,
    posSigmaEastM: 3.2, posSigmaNorthM: 2.8, altSigmaM: 6.1,
    velSigmaEastMs: 0.9, velSigmaNorthMs: 0.7,
    rcsDbsm: -18.3, ageS: 74,
};

describe('crc16', () => {
    it('matches the CCITT-FALSE check value', () => {
        expect(crc16(Buffer.from('123456789', 'ascii'))).toBe(0x29b1);
    });
});

describe('Track Report', () => {
    it('decodes header and every track field in engineering units', () => {
        const frame = buildTrackReport(HDR, TS, [TRACK, { ...TRACK, id: 312, mode3a: undefined, coasting: true }]);
        const dec = new OetfDecoder();
        const [rec] = dec.feed(frame);

        expect(dec.getRecentErrors()).toEqual([]);
        expect(rec?.messageName).toBe('Track Report');
        expect(rec?.meta?.msgId).toBe(16);
        const f = rec!.fields;
        expect(f['Message type']).toBe('TRACK REPORT (16)');
        expect(f['Sequence number']).toBe(42);
        expect(f['Sensor ID']).toBe(0x0107);
        expect(f['Frame length']).toBe(`${frame.length} bytes`);
        expect(f['Timestamp']).toBe(`${TS} usec`);
        expect(f['Track count']).toBe(2);

        expect(f['Track 0 ID']).toBe(311);
        expect(f['Track 0 Classification']).toBe('Small UAS (3)');
        expect(f['Track 0 Latitude']).toBeCloseTo(0.0, 7);
        expect(f['Track 0 Longitude']).toBeCloseTo(0.0, 7);
        expect(f['Track 0 Altitude']).toBe('152.4 m');
        expect(f['Track 0 Velocity east']).toBe('-12.5 m/s');
        expect(f['Track 0 Mode 3/A code']).toBe(0o7000);
        expect(f['Track 0 RCS']).toBe('-18.3 dBsm');
        expect(f['Track 0 Flags']).toMatchObject({ Confirmed: 1, Coasting: 0, 'Mode 3/A valid': 1 });

        expect(f['Track 1 ID']).toBe(312);
        expect(f['Track 1 Flags']).toMatchObject({ Coasting: 1, 'Mode 3/A valid': 0 });
        expect(f['Track 2 ID']).toBe('(not present)');
    });
});

describe('Sensor Status', () => {
    it('decodes', () => {
        const frame = buildSensorStatus({ ...HDR, simulated: true }, {
            timestampUs: TS, latDeg: 38.9, lonDeg: -77.04, altM: 20, boresightDeg: 270.5,
            state: 2, activeTracks: 2, transmitting: true, timeSyncValid: true, positionValid: true,
        });
        expect(frame.length).toBe(46);
        const [rec] = new OetfDecoder().feed(frame);
        expect(rec?.messageName).toBe('Sensor Status');
        expect(rec?.fields['Operating state']).toBe('Scanning (2)');
        expect(rec?.fields['Boresight azimuth']).toBe('270.5 deg');
        expect(rec?.fields['Header flags']).toMatchObject({ 'Test data': 0, Simulated: 1 });
        expect(rec?.fields['Status flags']).toMatchObject({ Transmitting: 1, 'Over temperature': 0 });
    });
});

describe('streaming and recovery', () => {
    const a = buildTrackReport(HDR, TS, [TRACK]);
    const b = buildTrackReport({ ...HDR, sequence: 43 }, TS, [TRACK]);

    it('reassembles frames split at arbitrary byte boundaries', () => {
        const dec = new OetfDecoder();
        const all = Buffer.concat([a, b]);
        const out = [];
        for (let i = 0; i < all.length; i += 7) out.push(...dec.feed(all.subarray(i, i + 7)));
        expect(out.map((r) => r.fields['Sequence number'])).toEqual([42, 43]);
        expect(dec.getRecentErrors()).toEqual([]);
    });

    it('skips leading garbage up to the magic', () => {
        const dec = new OetfDecoder();
        const out = dec.feed(Buffer.concat([Buffer.from('deadbeef00112233445566778899', 'hex'), a]));
        expect(out).toHaveLength(1);
        expect(dec.getRecentErrors().map((e) => e.reason)).toEqual(['sync-lost']);
    });

    it('drops a CRC-corrupt frame and still decodes the next one', () => {
        const bad = Buffer.from(a);
        bad[40] ^= 0xff;
        const dec = new OetfDecoder();
        const out = dec.feed(Buffer.concat([bad, b]));
        expect(out.map((r) => r.fields['Sequence number'])).toEqual([43]);
        expect(dec.getRecentErrors().map((e) => e.reason)).toContain('crc-mismatch');
    });

    it('surfaces unknown message types without losing sync', () => {
        const dec = new OetfDecoder();
        const out = dec.feed(Buffer.concat([buildFrame(99, HDR, Buffer.alloc(4)), b]));
        expect(out.map((r) => r.messageName)).toEqual(['unknown-99', 'Track Report']);
        expect(dec.getRecentErrors().map((e) => e.reason)).toEqual(['unknown-type']);
    });
});
