// Local entry point for @open-billie/decoder-oetf.
//
// Exports the streaming Decoder + supporting types, plus the reference frame
// builder used by tests and simulators. The runtime shape
// (`{ messageName, fields }`) is the cross-package contract.

export { OetfDecoder, crc16, MAGIC, FORMAT_VERSION } from './decoder';
export type { DecodedRecord, FramingError } from './decoder';
export { buildFrame, buildSensorStatus, buildTrackReport, MSG_SENSOR_STATUS, MSG_TRACK_REPORT, MAX_TRACKS } from './builder';
export type { FrameHeader, SensorStatusInput, TrackInput } from './builder';
export type { MessageSchema, FieldDefinition, BitDefinition, DataType, DecodedValue } from './parser';

/** Contract-version constant. Bumped on breaking changes to the runtime shape. */
export const RUNTIME_SHAPE_VERSION = 1 as const;

/** Protocol name as referenced in mapping files. */
export const PROTOCOL_NAME = 'oetf' as const;
