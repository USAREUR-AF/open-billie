// Reference frame builder for OETF. The inverse of the decoder, kept beside it
// so tests and simulators produce byte-exact frames from engineering units.
// Not used on the decode path.

import { crc16, FORMAT_VERSION, MAGIC } from './decoder';

export const MSG_SENSOR_STATUS = 1;
export const MSG_TRACK_REPORT = 16;
export const MAX_TRACKS = 8;
const TRACK_BLOCK_BYTES = 40;

export interface FrameHeader {
    sequence: number;
    sensorId: number;
    testData?: boolean;
    simulated?: boolean;
}

export interface SensorStatusInput {
    timestampUs: bigint;
    latDeg: number;
    lonDeg: number;
    altM: number;
    boresightDeg: number;
    /** 0 Off, 1 Standby, 2 Scanning, 3 Degraded, 4 Fault */
    state: number;
    activeTracks: number;
    transmitting?: boolean;
    timeSyncValid?: boolean;
    positionValid?: boolean;
    overTemperature?: boolean;
}

export interface TrackInput {
    id: number;
    /** 0 Unknown, 1 Fixed wing, 2 Rotary wing, 3 Small UAS, 4 Balloon, 5 Bird, 6 Surface vehicle, 7 Clutter */
    classification: number;
    confidencePct: number;
    confirmed?: boolean;
    coasting?: boolean;
    finalUpdate?: boolean;
    simulated?: boolean;
    /** Octal Mode 3/A as a string, e.g. "7000". Omit when not available. */
    mode3a?: string;
    latDeg: number;
    lonDeg: number;
    altM: number;
    velEastMs: number;
    velNorthMs: number;
    velUpMs: number;
    posSigmaEastM: number;
    posSigmaNorthM: number;
    altSigmaM: number;
    velSigmaEastMs: number;
    velSigmaNorthMs: number;
    rcsDbsm: number;
    ageS: number;
}

const flag = (on: boolean | undefined, bit: number): number => (on ? 1 << bit : 0);

/** Wrap a body (bytes after the 16-byte header) into a complete frame with CRC. */
export function buildFrame(msgType: number, header: FrameHeader, body: Buffer): Buffer {
    const frame = Buffer.alloc(16 + body.length + 2);
    MAGIC.copy(frame, 0);
    frame.writeUInt8(FORMAT_VERSION, 4);
    frame.writeUInt8(msgType, 5);
    frame.writeUInt16LE(frame.length, 6);
    frame.writeUInt32LE(header.sequence >>> 0, 8);
    frame.writeUInt16LE(header.sensorId, 12);
    frame.writeUInt16LE(flag(header.testData, 0) | flag(header.simulated, 1), 14);
    body.copy(frame, 16);
    frame.writeUInt16LE(crc16(frame.subarray(0, frame.length - 2)), frame.length - 2);
    return frame;
}

export function buildSensorStatus(header: FrameHeader, s: SensorStatusInput): Buffer {
    const body = Buffer.alloc(28);
    body.writeBigUInt64LE(s.timestampUs, 0);
    body.writeInt32LE(Math.round(s.latDeg * 1e7), 8);
    body.writeInt32LE(Math.round(s.lonDeg * 1e7), 12);
    body.writeInt32LE(Math.round(s.altM * 100), 16);
    body.writeUInt16LE(Math.round(s.boresightDeg * 100), 20);
    body.writeUInt8(s.state, 22);
    body.writeUInt8(s.activeTracks, 23);
    body.writeUInt16LE(
        flag(s.transmitting, 0) | flag(s.timeSyncValid, 1) | flag(s.positionValid, 2) | flag(s.overTemperature, 3),
        24,
    );
    return buildFrame(MSG_SENSOR_STATUS, header, body);
}

export function buildTrackReport(header: FrameHeader, timestampUs: bigint, tracks: TrackInput[]): Buffer {
    if (tracks.length > MAX_TRACKS) throw new Error(`OETF Track Report carries at most ${MAX_TRACKS} tracks`);
    const body = Buffer.alloc(12 + tracks.length * TRACK_BLOCK_BYTES);
    body.writeBigUInt64LE(timestampUs, 0);
    body.writeUInt8(tracks.length, 8);
    tracks.forEach((t, n) => {
        const o = 12 + n * TRACK_BLOCK_BYTES;
        body.writeUInt16LE(t.id, o);
        body.writeUInt8(t.classification, o + 2);
        body.writeUInt8(t.confidencePct, o + 3);
        body.writeUInt16LE(
            flag(t.confirmed, 0) | flag(t.coasting, 1) | flag(t.finalUpdate, 2) | flag(t.simulated, 3) | flag(t.mode3a !== undefined, 4),
            o + 4,
        );
        body.writeUInt16LE(t.mode3a !== undefined ? parseInt(t.mode3a, 8) : 0, o + 6);
        body.writeInt32LE(Math.round(t.latDeg * 1e7), o + 8);
        body.writeInt32LE(Math.round(t.lonDeg * 1e7), o + 12);
        body.writeInt32LE(Math.round(t.altM * 100), o + 16);
        body.writeInt16LE(Math.round(t.velEastMs * 100), o + 20);
        body.writeInt16LE(Math.round(t.velNorthMs * 100), o + 22);
        body.writeInt16LE(Math.round(t.velUpMs * 100), o + 24);
        body.writeUInt16LE(Math.round(t.posSigmaEastM * 100), o + 26);
        body.writeUInt16LE(Math.round(t.posSigmaNorthM * 100), o + 28);
        body.writeUInt16LE(Math.round(t.altSigmaM * 100), o + 30);
        body.writeUInt16LE(Math.round(t.velSigmaEastMs * 100), o + 32);
        body.writeUInt16LE(Math.round(t.velSigmaNorthMs * 100), o + 34);
        body.writeInt16LE(Math.round(t.rcsDbsm * 10), o + 36);
        body.writeUInt16LE(Math.min(t.ageS, 0xffff), o + 38);
    });
    return buildFrame(MSG_TRACK_REPORT, header, body);
}
