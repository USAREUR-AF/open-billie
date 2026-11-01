"""Reference OETF frame builder — a port of the TypeScript ``builder.ts``.

Produces byte-identical frames to the TS builder (rounding follows JS
``Math.round``), so tests and simulators in any language emit the same traffic.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from .decoder import FORMAT_VERSION, MAGIC, crc16

MSG_SENSOR_STATUS = 1
MSG_TRACK_REPORT = 16
MAX_TRACKS = 8
_TRACK_BLOCK = struct.Struct("<HBBHHiiihhhHHHHHhH")


def _round(x: float) -> int:
    return math.floor(x + 0.5)  # JS Math.round


def _flags(*bits: bool) -> int:
    return sum(1 << i for i, on in enumerate(bits) if on)


@dataclass
class FrameHeader:
    sequence: int
    sensor_id: int
    test_data: bool = False
    simulated: bool = False


@dataclass
class SensorStatus:
    timestamp_us: int
    lat_deg: float
    lon_deg: float
    alt_m: float
    boresight_deg: float
    state: int  # 0 Off, 1 Standby, 2 Scanning, 3 Degraded, 4 Fault
    active_tracks: int
    transmitting: bool = False
    time_sync_valid: bool = False
    position_valid: bool = False
    over_temperature: bool = False


@dataclass
class Track:
    id: int
    classification: int  # 0 Unknown … 7 Clutter, see docs/WIRE_FORMAT.md
    confidence_pct: int
    lat_deg: float
    lon_deg: float
    alt_m: float
    vel_east_ms: float
    vel_north_ms: float
    vel_up_ms: float
    pos_sigma_east_m: float
    pos_sigma_north_m: float
    alt_sigma_m: float
    vel_sigma_east_ms: float
    vel_sigma_north_ms: float
    rcs_dbsm: float
    age_s: int
    confirmed: bool = False
    coasting: bool = False
    final_update: bool = False
    simulated: bool = False
    mode3a: str | None = None  # octal string, e.g. "7000"


def build_frame(msg_type: int, header: FrameHeader, body: bytes) -> bytes:
    """Wrap a body into a complete frame with header and CRC."""
    length = 16 + len(body) + 2
    head = MAGIC + struct.pack(
        "<BBHIHH", FORMAT_VERSION, msg_type, length, header.sequence & 0xFFFFFFFF,
        header.sensor_id, _flags(header.test_data, header.simulated),
    )
    frame = head + body
    return frame + struct.pack("<H", crc16(frame))


def build_sensor_status(header: FrameHeader, s: SensorStatus) -> bytes:
    body = struct.pack(
        "<QiiiHBBHH", s.timestamp_us, _round(s.lat_deg * 1e7), _round(s.lon_deg * 1e7),
        _round(s.alt_m * 100), _round(s.boresight_deg * 100), s.state, s.active_tracks,
        _flags(s.transmitting, s.time_sync_valid, s.position_valid, s.over_temperature), 0,
    )
    return build_frame(MSG_SENSOR_STATUS, header, body)


def build_track_report(header: FrameHeader, timestamp_us: int, tracks: list[Track]) -> bytes:
    if len(tracks) > MAX_TRACKS:
        raise ValueError(f"OETF Track Report carries at most {MAX_TRACKS} tracks")
    body = struct.pack("<QBBH", timestamp_us, len(tracks), 0, 0)
    for t in tracks:
        body += _TRACK_BLOCK.pack(
            t.id, t.classification, t.confidence_pct,
            _flags(t.confirmed, t.coasting, t.final_update, t.simulated, t.mode3a is not None),
            int(t.mode3a, 8) if t.mode3a is not None else 0,
            _round(t.lat_deg * 1e7), _round(t.lon_deg * 1e7), _round(t.alt_m * 100),
            _round(t.vel_east_ms * 100), _round(t.vel_north_ms * 100), _round(t.vel_up_ms * 100),
            _round(t.pos_sigma_east_m * 100), _round(t.pos_sigma_north_m * 100), _round(t.alt_sigma_m * 100),
            _round(t.vel_sigma_east_ms * 100), _round(t.vel_sigma_north_ms * 100),
            _round(t.rcs_dbsm * 10), min(t.age_s, 0xFFFF),
        )
    return build_frame(MSG_TRACK_REPORT, header, body)
