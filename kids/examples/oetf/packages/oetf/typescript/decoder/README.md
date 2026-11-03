# @open-billie/decoder-oetf

This package is a streaming decoder for OETF (Open Example Track Format), a made-up, non-proprietary target wire format. The full spec is in [`docs/WIRE_FORMAT.md`](../../../../docs/WIRE_FORMAT.md).

## Usage

```ts
import { OetfDecoder } from '@open-billie/decoder-oetf';

const decoder = new OetfDecoder();
for (const r of decoder.feed(chunk)) {
  console.log(r.messageName, r.fields);   // "Track Report", { "Track 0 Latitude": 0.0, ... }
}
decoder.reset();                          // on disconnect
const errors = decoder.getRecentErrors(); // drain framing faults
```

Generate traffic for tests or simulators with the reference builder:

```ts
import { buildTrackReport } from '@open-billie/decoder-oetf';
socket.send(buildTrackReport({ sequence: n++, sensorId: 7 }, BigInt(Date.now()) * 1000n, tracks));
```

The decoder is stateful, so use one instance per stream. It is not thread-safe. `getPendingBytes()` reports buffered bytes so TCP runtimes can warn when a connection ends mid-frame.

## Runtime-shape contract

Every emitted record has the same `DecodedRecord` shape (`{ messageName, fields, meta }`) as the other Billie decoders:

- `fields` merges the header and body into one flat dictionary.
- Field names match the schema JSON, for example `"Track 0 Velocity east"`.
- Enum fields decode as `"Label (raw)"`. Unit fields decode as `"value units"`.
- Bit fields decode as `{ bitName: n, _raw }`.

Track fields beyond `Track count` decode as `"(not present)"`.

Latitude and longitude intentionally carry no `units` suffix. With a 1e-7 LSB, values near the equator or prime meridian print in exponent notation (`3e-7`), and the translator's `"value units"` stripper does not parse that notation.

## Framing and recovery

OETF frames start with the magic `OETF`, carry their length at offset 6, and end with a CRC-16/CCITT-FALSE trailer. Because the decoder can always scan forward to the next magic, a bad frame costs only that frame:

| Reason | Meaning |
|---|---|
| `sync-lost` | Bytes before a magic were skipped |
| `bad-version` | Format version ≠ 1 |
| `bad-length` | Length outside 18..4096 |
| `crc-mismatch` | Trailer CRC does not match |
| `unknown-type` | No schema for the message type. The record is still emitted as `unknown-<id>` with header fields. |
| `decode-failed` | The schema-driven parser threw |

## What this package owns

- Reading the shared decode schemas in [`packages/oetf/shared/schemas`](../../shared/schemas/): `header.json`, `msg_1.json` (Sensor Status), `msg_16.json` (Track Report, 8 track slots). The Python and Rust decoders read the same files. `SCHEMAS_DIR` (exported) is where they were found. This private workspace is used from the Open Billie repository and is not published to GitHub Packages.
- Framing, CRC verification, and resync.
- `builder.ts`, the encode-direction reference used by tests and simulators.

Translation to ASTERIX CAT-062, CoT and SAPIENT uses the separate OETF mapping package and the mapping engine documented by Open Billie.

The deployable listener, canonical map execution, and translator-socket adapter are in [`../runtime`](../runtime/README.md). Select `--decoder-language typescript` when building the OETF kid bundle.
