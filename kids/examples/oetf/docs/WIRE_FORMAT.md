# OETF — Open Example Track Format, revision 1

OETF is a made-up, non-proprietary binary wire format for sensor target data. It exists so Billie modular examples, demos, and tests have a realistic source system that carries no vendor IP. It is not derived from, and does not intend to match, any real radar's interface. Anyone may implement it.

## Conventions

- **Byte order:** little-endian for every multi-byte field.
- **Transport:** a UDP datagram may contain one or more frames. TCP is a byte stream: frames may be split across reads or several frames may arrive together. The frame length makes each frame self-delimiting, so the receiver must buffer and parse the stream rather than rely on read boundaries.
- **Integers** are two's complement where signed. **Bit 0** is the least significant bit of the field.
- **Position** is WGS-84 latitude/longitude. **Altitude** is height above the ellipsoid (HAE).
- **Velocity** is local ENU (east, north, up) at the target.
- **Time** is microseconds since the Unix epoch (UTC).
- **Reserved** fields are written as zero and ignored on read.

## Frame

```
+--------------------+---------------------------+-----------+
| Header (16 bytes)  | Body (type-specific)      | CRC (2)   |
+--------------------+---------------------------+-----------+
|<-------------------- Frame length ------------------------>|
```

### Header

| Offset | Type   | Field           | Notes |
|-------:|--------|-----------------|-------|
| 0      | 4×char | Magic           | ASCII `OETF` (`4F 45 54 46`) |
| 4      | uint8  | Format version  | `1` |
| 5      | uint8  | Message type    | `1` Sensor Status, `16` Track Report |
| 6      | uint16 | Frame length    | Whole frame, header and CRC included. 18..4096 |
| 8      | uint32 | Sequence number | Per sensor, starts at 0, wraps |
| 12     | uint16 | Sensor ID       | Assigned per deployment |
| 14     | uint16 | Header flags    | bit 0 Test data, bit 1 Simulated, others 0 |

### CRC trailer

The trailer is a `uint16` CRC-16/CCITT-FALSE computed over every byte from offset 0 up to the trailer. The parameters are poly `0x1021`, init `0xFFFF`, no reflection and no final XOR. The check value for `"123456789"` is `0x29B1`.

### Receiver rules

1. Scan for the magic and discard any bytes before it.
2. Reject the frame if the version is not 1 or the length falls outside 18..4096. Skip past the magic and rescan.
3. Wait until `Frame length` bytes are buffered, then verify the CRC. If the CRC fails, skip past the magic and rescan. Do not trust the length to skip the whole frame, because the length may be the corrupt field.
4. A receiver should surface unknown message types and continue.

## Message 1 — Sensor Status (46 bytes)

| Offset | Type   | Field              | Units / LSB |
|-------:|--------|--------------------|-------------|
| 16     | uint64 | Timestamp          | µs since epoch |
| 24     | int32  | Sensor latitude    | 1e-7 deg |
| 28     | int32  | Sensor longitude   | 1e-7 deg |
| 32     | int32  | Sensor altitude    | 0.01 m HAE |
| 36     | uint16 | Boresight azimuth  | 0.01 deg from true north, clockwise |
| 38     | uint8  | Operating state    | 0 Off, 1 Standby, 2 Scanning, 3 Degraded, 4 Fault |
| 39     | uint8  | Active track count | |
| 40     | uint16 | Status flags       | bit 0 Transmitting, 1 Time sync valid, 2 Position valid, 3 Over temperature |
| 42     | uint16 | Reserved           | |
| 44     | uint16 | CRC                | |

## Message 16 — Track Report (30 + 40·N bytes)

| Offset | Type   | Field       | Notes |
|-------:|--------|-------------|-------|
| 16     | uint64 | Timestamp   | µs since epoch, applies to every track in the frame |
| 24     | uint8  | Track count | N, 0..8 |
| 25     | uint8  | Reserved    | |
| 26     | uint16 | Reserved    | |
| 28     | —      | Track block × N | 40 bytes each, see below |
| 28+40N | uint16 | CRC         | |

A sensor with more than 8 tracks sends several Track Reports with the same timestamp.

### Track block (40 bytes, offsets relative to block start)

| Rel | Type   | Field                | Units / LSB |
|----:|--------|----------------------|-------------|
| 0   | uint16 | ID                   | Stable for the track's life |
| 2   | uint8  | Classification       | 0 Unknown, 1 Fixed wing, 2 Rotary wing, 3 Small UAS, 4 Balloon, 5 Bird, 6 Surface vehicle, 7 Clutter |
| 3   | uint8  | Confidence           | % (0..100) |
| 4   | uint16 | Flags                | bit 0 Confirmed, 1 Coasting, 2 Final update, 3 Simulated, 4 Mode 3/A valid |
| 6   | uint16 | Mode 3/A code        | 12-bit octal ABCD, 3 bits per digit, A in bits 11–9 |
| 8   | int32  | Latitude             | 1e-7 deg |
| 12  | int32  | Longitude            | 1e-7 deg |
| 16  | int32  | Altitude             | 0.01 m HAE |
| 20  | int16  | Velocity east        | 0.01 m/s |
| 22  | int16  | Velocity north       | 0.01 m/s |
| 24  | int16  | Velocity up          | 0.01 m/s |
| 26  | uint16 | Position sigma east  | 0.01 m (1σ) |
| 28  | uint16 | Position sigma north | 0.01 m (1σ) |
| 30  | uint16 | Altitude sigma       | 0.01 m (1σ) |
| 32  | uint16 | Velocity sigma east  | 0.01 m/s (1σ) |
| 34  | uint16 | Velocity sigma north | 0.01 m/s (1σ) |
| 36  | int16  | RCS                  | 0.1 dBsm |
| 38  | uint16 | Age                  | s since initiation, saturates at 65535 |

## Example frame

The following is a Track Report with one track: sequence 42, sensor `0x0107`, timestamp 2025-10-29T12:00:00.123456Z. The track is ID 311, Small UAS, 87 % confidence, confirmed, Mode 3/A 7000, at 0.0 N 0.0 E and 152.4 m. Its velocity is (−12.5, 4.25, 1.5) m/s, RCS is −18.3 dBsm and age is 74 s. The whole frame is 70 bytes. `buildTrackReport` in `packages/oetf/typescript/decoder/builder.ts` produces it byte for byte.

```
4f455446 01 10 4600 2a000000 0701 0000      header: magic, v1, type 16, len 70, seq 42, sensor 0x0107, flags 0
40d235df4a420600 01 00 0000                 timestamp, track count 1, reserved
3701 03 57 1100 000e                        ID 311, class 3, conf 87, flags 0x11, Mode 3/A 0o7000
00000000 00000000 883b0000                  lat, lon, alt (cm)
1efb a901 9600                              vel E/N/U (cm/s)
4001 1801 6202 5a00 4600                    sigmas: pos E/N, alt, vel E/N (cm, cm/s)
49ff 4a00                                   RCS (0.1 dBsm), age (s)
51ee                                        CRC-16/CCITT-FALSE
```

## Mapping to ASTERIX CAT-062, CoT and SAPIENT

The maps live in [`packages/oetf/shared/mappings/`](../packages/oetf/shared/mappings/). Field-by-field tables are in [`packages/oetf/typescript/mappings/README.md`](../packages/oetf/typescript/mappings/README.md).
