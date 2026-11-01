// Streaming-byte decoder for OETF (Open Example Track Format).
// - Accepts streaming chunks via feed(); accumulates until complete frames are available.
// - Framing rule: 4-byte magic "OETF", 'Frame length' (uint16 LE) at offset 6, CRC-16 trailer.
// - Recovers from desync by scanning forward to the next magic, so one corrupt
//   frame costs only that frame (unlike size-prefix-only protocols).

import * as fs from 'fs';
import * as path from 'path';
import { MessageParser, MessageSchema } from './parser';

export const MAGIC = Buffer.from('OETF', 'ascii');
export const FORMAT_VERSION = 1;
const HEADER_BYTES = 16;
const CRC_BYTES = 2;
const MIN_FRAME_SIZE = HEADER_BYTES + CRC_BYTES;
const MAX_FRAME_SIZE = 4096;
const VERSION_OFFSET = 4;
const LENGTH_OFFSET = 6;
// __dirname is the package dir under tsx (dev) or `<pkg>/dist` under node (prod).
const PKG_ROOT = path.basename(__dirname) === 'dist' ? path.join(__dirname, '..') : __dirname;
// The schemas are language-neutral and live once in packages/oetf/shared.
// This private workspace reads them directly from the Open Billie repository.
export const SCHEMAS_DIR = [
    path.join(PKG_ROOT, 'shared', 'schemas'),
    path.join(PKG_ROOT, '..', '..', 'shared', 'schemas'),
].find((d) => fs.existsSync(d)) ?? path.join(PKG_ROOT, '..', '..', 'shared', 'schemas');

/**
 * Decoded OETF record emitted by {@link OetfDecoder.feed}.
 *
 * `messageName` is the human-readable name from the schema file
 * (`msg_<id>.json`), e.g. `"Track Report"`. `fields` is a flat dictionary
 * of header fields merged with body fields. `meta` carries non-protocol
 * provenance (raw hex, decode timestamp, numeric msgId).
 */
export interface DecodedRecord {
    messageName: string;
    fields: Record<string, unknown>;
    meta?: {
        rawHex?: string;
        decodedAt?: number;
        msgId?: number;
        [k: string]: unknown;
    };
}

/**
 * A single framing or decode failure observed by the decoder.
 *
 * Surface via {@link OetfDecoder.getRecentErrors} after a `feed()` call;
 * the decoder swallows errors internally to keep the stream alive but
 * records them so the caller can log or alarm.
 */
export interface FramingError {
    at: number;
    reason: 'sync-lost' | 'bad-length' | 'bad-version' | 'crc-mismatch' | 'unknown-type' | 'decode-failed';
    recoveredBytes?: number;
    detail?: string;
}

/**
 * CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no xorout).
 * Check value for ASCII "123456789" is 0x29B1.
 */
export function crc16(data: Uint8Array): number {
    let crc = 0xffff;
    for (const byte of data) {
        crc ^= byte << 8;
        for (let i = 0; i < 8; i++) {
            crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
        }
    }
    return crc;
}

/**
 * Streaming decoder for OETF.
 *
 * Framing: every frame starts with the ASCII magic `OETF`; `uint16 LE` at
 * offset 6 holds the total frame size (header + body + CRC). The last two
 * bytes are a CRC-16/CCITT-FALSE over everything before them. On any
 * framing fault the decoder discards bytes up to the next magic and keeps
 * going, recording a {@link FramingError}.
 *
 * Stateful: one instance per stream. Call {@link reset} on disconnect.
 *
 * @example
 * ```ts
 * const decoder = new OetfDecoder();
 * socket.on('message', (datagram) => {
 *   for (const record of decoder.feed(datagram)) {
 *     console.log(record.messageName, record.fields);
 *   }
 * });
 * ```
 */
export class OetfDecoder {
    private buffer: Buffer = Buffer.alloc(0);
    private readonly errors: FramingError[] = [];
    private readonly schemaCache: Map<string, MessageSchema> = new Map();
    private readonly headerSchema: MessageSchema;

    constructor() {
        this.headerSchema = this.loadSchemaFile('header.json');
    }

    /**
     * Feed streaming bytes; emit zero or more complete records.
     *
     * Safe to call with any chunk size, including partial frames or
     * multiple frames glued together. Records are emitted in arrival order.
     */
    public feed(chunk: Buffer): DecodedRecord[] {
        this.buffer = Buffer.concat([this.buffer, chunk]);
        const records: DecodedRecord[] = [];

        while (this.buffer.length >= HEADER_BYTES) {
            const syncAt = this.buffer.indexOf(MAGIC);
            if (syncAt !== 0) {
                // Keep a possible partial magic at the tail so it can complete on the next feed.
                const drop = syncAt < 0 ? this.buffer.length - (MAGIC.length - 1) : syncAt;
                this.errors.push({
                    at: Date.now(),
                    reason: 'sync-lost',
                    recoveredBytes: drop,
                    detail: `Skipped ${drop} byte(s) looking for magic 'OETF'.`,
                });
                this.buffer = this.buffer.subarray(drop);
                continue;
            }

            const version = this.buffer.readUInt8(VERSION_OFFSET);
            const size = this.buffer.readUInt16LE(LENGTH_OFFSET);

            if (version !== FORMAT_VERSION) {
                this.skipBadFrame('bad-version', `Format version ${version}, expected ${FORMAT_VERSION}.`);
                continue;
            }
            if (size < MIN_FRAME_SIZE || size > MAX_FRAME_SIZE) {
                this.skipBadFrame('bad-length', `Declared length ${size} outside ${MIN_FRAME_SIZE}..${MAX_FRAME_SIZE}.`);
                continue;
            }
            if (this.buffer.length < size) {
                // Need more data
                break;
            }

            const frame = this.buffer.subarray(0, size);
            const expected = frame.readUInt16LE(size - CRC_BYTES);
            const actual = crc16(frame.subarray(0, size - CRC_BYTES));
            if (expected !== actual) {
                // The length may itself be corrupt, so resync from the next magic
                // rather than trusting it to skip the whole frame.
                this.skipBadFrame('crc-mismatch',
                    `CRC 0x${actual.toString(16).padStart(4, '0')} != trailer 0x${expected.toString(16).padStart(4, '0')}.`);
                continue;
            }

            this.buffer = this.buffer.subarray(size);
            const record = this.decodeFrame(frame);
            if (record) records.push(record);
        }

        return records;
    }

    /**
     * Clear the internal accumulator. Call when a stream drops so the next
     * one starts framing from byte 0.
     */
    public reset(): void {
        this.buffer = Buffer.alloc(0);
    }

    /** Number of stream bytes waiting for the rest of a frame. */
    public getPendingBytes(): number {
        return this.buffer.length;
    }

    /**
     * Drain and return all framing/decoding errors observed since the last
     * call. Subsequent calls return an empty list until new errors occur.
     */
    public getRecentErrors(): FramingError[] {
        const out = this.errors.slice();
        this.errors.length = 0;
        return out;
    }

    /**
     * Decode a single, already-framed and CRC-checked buffer. Used by tests
     * and by callers that have done their own framing.
     *
     * Returns `null` on decode failure (a {@link FramingError} is appended).
     */
    public decodeFrame(frame: Buffer): DecodedRecord | null {
        const parser = new MessageParser(frame, { littleEndian: true });
        let headerFields: Record<string, unknown>;
        try {
            headerFields = parser.parse(this.headerSchema) as Record<string, unknown>;
        } catch (e) {
            this.errors.push({
                at: Date.now(),
                reason: 'decode-failed',
                detail: `Header decode threw: ${(e as Error).message}`,
            });
            return null;
        }

        const msgId = frame.readUInt8(5);
        let bodySchema: MessageSchema;
        try {
            bodySchema = this.loadSchemaFile(`msg_${msgId}.json`);
        } catch {
            this.errors.push({
                at: Date.now(),
                reason: 'unknown-type',
                detail: `No schema for message type ${msgId}.`,
            });
            return {
                messageName: `unknown-${msgId}`,
                fields: headerFields,
                meta: { rawHex: frame.toString('hex'), decodedAt: Date.now(), msgId },
            };
        }

        let bodyFields: Record<string, unknown> = {};
        try {
            bodyFields = parser.parse(bodySchema) as Record<string, unknown>;
        } catch (e) {
            this.errors.push({
                at: Date.now(),
                reason: 'decode-failed',
                detail: `Body decode for msg_${msgId} threw: ${(e as Error).message}`,
            });
        }

        return {
            messageName: bodySchema.messageName,
            fields: { ...headerFields, ...bodyFields },
            meta: {
                rawHex: frame.toString('hex'),
                decodedAt: Date.now(),
                msgId,
            },
        };
    }

    /** Record a fault on the frame at the head of the buffer and step past its magic. */
    private skipBadFrame(reason: FramingError['reason'], detail: string): void {
        this.errors.push({ at: Date.now(), reason, recoveredBytes: MAGIC.length, detail });
        this.buffer = this.buffer.subarray(MAGIC.length);
    }

    private loadSchemaFile(fileName: string): MessageSchema {
        const cached = this.schemaCache.get(fileName);
        if (cached) return cached;
        const fullPath = path.join(SCHEMAS_DIR, fileName);
        const text = fs.readFileSync(fullPath, 'utf-8');
        const schema = JSON.parse(text) as MessageSchema;
        this.schemaCache.set(fileName, schema);
        return schema;
    }
}
