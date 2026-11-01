"""Regenerate the shared OETF byte-offset schemas (read by the TS, Python and Rust decoders).

The Track Report repeats a fixed 40-byte block per track, so its schema is
generated rather than hand-written. Run from the repo root:

    python tools/gen-schemas.py

See docs/WIRE_FORMAT.md for the normative layout this mirrors.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "packages" / "oetf" / "shared" / "schemas"

HEADER_BYTES = 16
MAX_TRACKS = 8
TRACK_BLOCK_BYTES = 40
TRACK_REPORT_FIXED = 28  # header + timestamp + count + reserved

CLASSIFICATION = {
    "0": "Unknown",
    "1": "Fixed wing",
    "2": "Rotary wing",
    "3": "Small UAS",
    "4": "Balloon",
    "5": "Bird",
    "6": "Surface vehicle",
    "7": "Clutter",
}

OPERATING_STATE = {
    "0": "Off",
    "1": "Standby",
    "2": "Scanning",
    "3": "Degraded",
    "4": "Fault",
}


def header():
    return {
        "messageName": "Header",
        "fields": [
            {"name": "Magic", "offset": 0, "type": "uint32",
             "notes": "ASCII 'OETF' (bytes 4F 45 54 46). Little-endian uint32 0x4654454F."},
            {"name": "Format version", "offset": 4, "type": "uint8",
             "notes": "1 for this revision. Decoder rejects other versions."},
            {"name": "Message type", "offset": 5, "type": "uint8",
             "values": {"1": "SENSOR STATUS", "16": "TRACK REPORT"}},
            {"name": "Frame length", "offset": 6, "type": "uint16", "units": "bytes",
             "notes": "Total frame size including the 16-byte header and the 2-byte CRC trailer."},
            {"name": "Sequence number", "offset": 8, "type": "uint32",
             "notes": "Per-sensor running counter starting at 0; wraps after 0xFFFFFFFF."},
            {"name": "Sensor ID", "offset": 12, "type": "uint16"},
            {"name": "Header flags", "offset": 14, "type": "uint16", "bits": [
                {"name": "Test data", "bitStart": 0, "length": 1},
                {"name": "Simulated", "bitStart": 1, "length": 1},
            ]},
        ],
    }


def sensor_status():
    return {
        "messageName": "Sensor Status",
        "messageSize": 46,
        "fields": [
            {"name": "Timestamp", "offset": 16, "type": "uint64", "units": "usec",
             "notes": "Microseconds since 1970-01-01T00:00:00Z."},
            {"name": "Sensor latitude", "offset": 24, "type": "int32", "scale": 1e-7,
             "notes": "Degrees, WGS-84. LSB = 1e-7 deg. No units suffix so near-zero values stay numeric."},
            {"name": "Sensor longitude", "offset": 28, "type": "int32", "scale": 1e-7,
             "notes": "Degrees, WGS-84. LSB = 1e-7 deg."},
            {"name": "Sensor altitude", "offset": 32, "type": "int32", "scale": 0.01, "units": "m",
             "notes": "Height above WGS-84 ellipsoid. LSB = 1 cm."},
            {"name": "Boresight azimuth", "offset": 36, "type": "uint16", "scale": 0.01, "units": "deg",
             "notes": "Clockwise from true north. LSB = 0.01 deg."},
            {"name": "Operating state", "offset": 38, "type": "uint8", "values": OPERATING_STATE},
            {"name": "Active track count", "offset": 39, "type": "uint8"},
            {"name": "Status flags", "offset": 40, "type": "uint16", "bits": [
                {"name": "Transmitting", "bitStart": 0, "length": 1},
                {"name": "Time sync valid", "bitStart": 1, "length": 1},
                {"name": "Position valid", "bitStart": 2, "length": 1},
                {"name": "Over temperature", "bitStart": 3, "length": 1},
            ]},
            {"name": "Reserved", "offset": 42, "type": "uint16"},
        ],
    }


def track_block(n):
    base = TRACK_REPORT_FIXED + n * TRACK_BLOCK_BYTES
    present = {"field": "Track count", "minCount": n + 1}

    def f(name, rel, typ, **kw):
        return {"name": f"Track {n} {name}", "offset": base + rel, "type": typ, **kw, "validIf": present}

    return [
        f("ID", 0, "uint16"),
        f("Classification", 2, "uint8", values=CLASSIFICATION),
        f("Confidence", 3, "uint8", units="%"),
        f("Flags", 4, "uint16", bits=[
            {"name": "Confirmed", "bitStart": 0, "length": 1},
            {"name": "Coasting", "bitStart": 1, "length": 1},
            {"name": "Final update", "bitStart": 2, "length": 1},
            {"name": "Simulated", "bitStart": 3, "length": 1},
            {"name": "Mode 3/A valid", "bitStart": 4, "length": 1},
        ]),
        f("Mode 3/A code", 6, "uint16",
          notes="12-bit octal ABCD packed 3 bits per digit (A in bits 11-9). Meaningful only when Flags.Mode 3/A valid = 1."),
        f("Latitude", 8, "int32", scale=1e-7, notes="Degrees, WGS-84. LSB = 1e-7 deg."),
        f("Longitude", 12, "int32", scale=1e-7, notes="Degrees, WGS-84. LSB = 1e-7 deg."),
        f("Altitude", 16, "int32", scale=0.01, units="m", notes="Height above WGS-84 ellipsoid. LSB = 1 cm."),
        f("Velocity east", 20, "int16", scale=0.01, units="m/s"),
        f("Velocity north", 22, "int16", scale=0.01, units="m/s"),
        f("Velocity up", 24, "int16", scale=0.01, units="m/s"),
        f("Position sigma east", 26, "uint16", scale=0.01, units="m"),
        f("Position sigma north", 28, "uint16", scale=0.01, units="m"),
        f("Altitude sigma", 30, "uint16", scale=0.01, units="m"),
        f("Velocity sigma east", 32, "uint16", scale=0.01, units="m/s"),
        f("Velocity sigma north", 34, "uint16", scale=0.01, units="m/s"),
        f("RCS", 36, "int16", scale=0.1, units="dBsm"),
        f("Age", 38, "uint16", units="s", notes="Seconds since track initiation; saturates at 65535."),
    ]


def track_report():
    fields = [
        {"name": "Timestamp", "offset": 16, "type": "uint64", "units": "usec",
         "notes": "Microseconds since 1970-01-01T00:00:00Z. Applies to every track in the frame."},
        {"name": "Track count", "offset": 24, "type": "uint8",
         "notes": f"Number of 40-byte track blocks that follow (0..{MAX_TRACKS})."},
        {"name": "Reserved", "offset": 25, "type": "uint8"},
        {"name": "Reserved 2", "offset": 26, "type": "uint16"},
    ]
    for n in range(MAX_TRACKS):
        fields.extend(track_block(n))
    return {"messageName": "Track Report", "fields": fields}


def write(name, doc):
    path = OUT / name
    path.write_text(json.dumps(doc, indent=4) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(OUT.parent.parent.parent.parent)}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    write("header.json", header())
    write("msg_1.json", sensor_status())
    write("msg_16.json", track_report())
