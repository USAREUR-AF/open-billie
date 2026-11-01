"""billie-oetf — Python decoder, builder and CAT-062 / CoT / SAPIENT mapper for OETF (Open Example Track Format).

Shares its schemas, maps and lookup tables with the TypeScript and Rust
implementations; see ``packages/oetf/shared/conformance``.
"""

from .builder import (
    MAX_TRACKS, MSG_SENSOR_STATUS, MSG_TRACK_REPORT,
    FrameHeader, SensorStatus, Track, build_frame, build_sensor_status, build_track_report,
)
from .decoder import FORMAT_VERSION, MAGIC, DecodedRecord, FramingError, OetfDecoder, crc16
from .mapper import Mapper

RUNTIME_SHAPE_VERSION = 1
PROTOCOL_NAME = "oetf"

__all__ = [
    "MAX_TRACKS", "MSG_SENSOR_STATUS", "MSG_TRACK_REPORT", "FrameHeader", "SensorStatus", "Track",
    "build_frame", "build_sensor_status", "build_track_report",
    "FORMAT_VERSION", "MAGIC", "DecodedRecord", "FramingError", "OetfDecoder", "crc16",
    "Mapper", "RUNTIME_SHAPE_VERSION", "PROTOCOL_NAME",
]
