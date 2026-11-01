// Schema-driven byte reader for OETF frames (little-endian on the wire).
// Operates on a Buffer for one complete message frame. Produces a structured
// record of { messageName, fields } that matches the runtime shape contract.

export type DataType =
    | 'uint8' | 'uint16' | 'uint32' | 'uint48' | 'uint64'
    | 'int8' | 'int16' | 'int32'
    | 'real32' | 'real64';

export interface BitDefinition {
    name: string;
    bitStart: number;
    length: number;
    values?: { [key: string]: string };
    valuesBy?: {
        field: string | string[];
        map: { [contextKey: string]: { [bitValue: string]: string } };
    };
}

export interface FieldDefinition {
    name: string;
    offset: number;
    type: DataType;
    bits?: BitDefinition[];
    values?: { [key: string]: string };
    units?: string;
    scale?: number;
    notes?: string;
    validIf?: { field: string; bit?: string; minCount?: number };
}

export interface MessageSchema {
    messageName: string;
    messageSize?: number;
    fields: FieldDefinition[];
}

export const TYPE_SIZE: { [k: string]: number } = {
    uint8: 1, int8: 1,
    uint16: 2, int16: 2,
    uint32: 4, int32: 4, real32: 4,
    uint48: 6,
    uint64: 8, real64: 8,
};

/** Decoded value: either a raw scalar, a presentation-formatted string, a bit-field record, or a sentinel. */
export type DecodedValue = number | string | bigint | { [bitName: string]: number | string };

export class MessageParser {
    private view: DataView;
    private readonly littleEndian: boolean;

    constructor(frame: Buffer, opts?: { littleEndian?: boolean }) {
        // Copy into an independent ArrayBuffer so the view isn't tied to the
        // original Buffer's offset/length window.
        const ab = new ArrayBuffer(frame.byteLength);
        new Uint8Array(ab).set(frame);
        this.view = new DataView(ab);
        this.littleEndian = opts?.littleEndian ?? false;
    }

    public get byteLength(): number { return this.view.byteLength; }

    private extractBits(value: number | bigint, start: number, len: number): number {
        const v = typeof value === 'bigint' ? Number(value) : value;
        return (v >> start) & ((1 << len) - 1);
    }

    private getRawValue(offset: number, type: DataType): number | bigint {
        switch (type) {
            case 'uint8': return this.view.getUint8(offset);
            case 'uint16': return this.view.getUint16(offset, this.littleEndian);
            case 'uint32': return this.view.getUint32(offset, this.littleEndian);
            case 'uint48': {
                const hi = this.view.getUint16(offset, this.littleEndian);
                const lo = this.view.getUint32(offset + 2, this.littleEndian);
                return hi * 0x100000000 + lo;
            }
            case 'uint64': return this.view.getBigUint64(offset, this.littleEndian);
            case 'int8': return this.view.getInt8(offset);
            case 'int16': return this.view.getInt16(offset, this.littleEndian);
            case 'int32': return this.view.getInt32(offset, this.littleEndian);
            case 'real32': return this.view.getFloat32(offset, this.littleEndian);
            case 'real64': return this.view.getFloat64(offset, this.littleEndian);
            default: throw new Error(`Unknown type: ${type as string}`);
        }
    }

    public parse(schema: MessageSchema): { [field: string]: DecodedValue } {
        const result: { [field: string]: DecodedValue } = {};
        const rawBitValues: { [field: string]: { [bit: string]: number } } = {};
        const rawFieldValues: { [field: string]: number } = {};
        for (const field of schema.fields) {
            if (field.validIf) {
                if (field.validIf.bit !== undefined) {
                    const parentBits = rawBitValues[field.validIf.field];
                    if (!parentBits || parentBits[field.validIf.bit] !== 1) {
                        result[field.name] = '(invalid)';
                        continue;
                    }
                } else if (field.validIf.minCount !== undefined) {
                    const count = rawFieldValues[field.validIf.field];
                    if (count === undefined || count < field.validIf.minCount) {
                        result[field.name] = '(not present)';
                        continue;
                    }
                }
            }
            const sz = TYPE_SIZE[field.type];
            if (sz !== undefined && field.offset + sz > this.view.byteLength) {
                result[field.name] = '(beyond message)';
                continue;
            }
            const value = this.getRawValue(field.offset, field.type);
            if (field.bits && field.bits.length > 0) {
                const bits: { [k: string]: number | string } = {};
                const rawByName: { [k: string]: number } = {};
                for (const b of field.bits) {
                    const raw = this.extractBits(value, b.bitStart, b.length);
                    rawByName[b.name] = raw;
                    let resolved: string | number = raw;
                    if (b.values && b.values[String(raw)] !== undefined) {
                        resolved = `${b.values[String(raw)]} (${raw})`;
                    } else if (b.valuesBy) {
                        const fields = Array.isArray(b.valuesBy.field) ? b.valuesBy.field : [b.valuesBy.field];
                        const ctxKey = fields.map(fn => String(rawByName[fn])).join('.');
                        const subMap = b.valuesBy.map[ctxKey];
                        if (subMap && subMap[String(raw)] !== undefined) {
                            resolved = `${subMap[String(raw)]} (${raw})`;
                        }
                    }
                    bits[b.name] = resolved;
                }
                // Expose the parent's unmasked numeric value as `_raw` so mappings
                // can reach the full uint when a target field expects the whole
                // bit-packed value (e.g., CAT062 I062/270, ISA fixed32 raw type).
                bits['_raw'] = typeof value === 'bigint' ? Number(value) : value;
                rawBitValues[field.name] = rawByName;
                result[field.name] = bits;
            } else {
                let num: number | string = typeof value === 'bigint' ? value.toString() : value;
                if (typeof value === 'number') rawFieldValues[field.name] = value;
                if (typeof num === 'number' && field.scale !== undefined) num = num * field.scale;
                if (field.values && field.values[String(num)] !== undefined) {
                    result[field.name] = `${field.values[String(num)]} (${num})`;
                } else if (field.units) {
                    result[field.name] = `${num} ${field.units}`;
                } else {
                    result[field.name] = num;
                }
            }
        }
        return result;
    }
}
