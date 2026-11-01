"""Streaming OETF decoder — a port of the TypeScript ``decoder.ts``.

Framing: 4-byte magic ``OETF``, ``Frame length`` (uint16 LE) at offset 6,
CRC-16/CCITT-FALSE trailer. On any fault the decoder steps past the magic and
rescans, so one corrupt frame costs only that frame.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths
from .parser import parse

MAGIC = b"OETF"
FORMAT_VERSION = 1
HEADER_BYTES = 16
CRC_BYTES = 2
MIN_FRAME_SIZE = HEADER_BYTES + CRC_BYTES
MAX_FRAME_SIZE = 4096


@dataclass
class DecodedRecord:
    """Same shape as the TS ``DecodedRecord``: ``messageName`` + flat ``fields`` + ``meta``."""

    message_name: str
    fields: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FramingError:
    at: float
    reason: str  # sync-lost | bad-length | bad-version | crc-mismatch | unknown-type | decode-failed
    recovered_bytes: int | None = None
    detail: str | None = None


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). ``crc16(b"123456789") == 0x29B1``."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class OetfDecoder:
    """Stateful streaming decoder. One instance per stream; not thread-safe."""

    def __init__(self, schemas_dir: Path | str | None = None) -> None:
        self._schemas_dir = Path(schemas_dir) if schemas_dir else paths.SCHEMAS_DIR
        self._buffer = bytearray()
        self._errors: list[FramingError] = []
        self._schemas: dict[str, dict[str, Any] | None] = {}
        self._header = self._schema("header.json")
        assert self._header is not None

    def feed(self, chunk: bytes) -> list[DecodedRecord]:
        """Feed any number of bytes; return the complete records now available."""
        self._buffer += chunk
        records: list[DecodedRecord] = []

        while len(self._buffer) >= HEADER_BYTES:
            sync_at = self._buffer.find(MAGIC)
            if sync_at != 0:
                # Keep a possible partial magic at the tail so it can complete on the next feed.
                drop = len(self._buffer) - (len(MAGIC) - 1) if sync_at < 0 else sync_at
                self._err("sync-lost", f"Skipped {drop} byte(s) looking for magic 'OETF'.", drop)
                del self._buffer[:drop]
                continue

            version = self._buffer[4]
            size = int.from_bytes(self._buffer[6:8], "little")
            if version != FORMAT_VERSION:
                self._skip_bad_frame("bad-version", f"Format version {version}, expected {FORMAT_VERSION}.")
                continue
            if not MIN_FRAME_SIZE <= size <= MAX_FRAME_SIZE:
                self._skip_bad_frame("bad-length", f"Declared length {size} outside {MIN_FRAME_SIZE}..{MAX_FRAME_SIZE}.")
                continue
            if len(self._buffer) < size:
                break  # need more data

            frame = bytes(self._buffer[:size])
            expected = int.from_bytes(frame[-CRC_BYTES:], "little")
            actual = crc16(frame[:-CRC_BYTES])
            if expected != actual:
                # The length may itself be corrupt, so resync from the next magic.
                self._skip_bad_frame("crc-mismatch", f"CRC 0x{actual:04x} != trailer 0x{expected:04x}.")
                continue

            del self._buffer[:size]
            record = self.decode_frame(frame)
            if record:
                records.append(record)

        return records

    def reset(self) -> None:
        """Clear the accumulator (call on disconnect)."""
        self._buffer.clear()

    def get_recent_errors(self) -> list[FramingError]:
        """Drain the errors observed since the last call."""
        out, self._errors = self._errors, []
        return out

    def decode_frame(self, frame: bytes) -> DecodedRecord | None:
        """Decode one already-framed, CRC-checked buffer."""
        try:
            header = parse(frame, self._header)  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001 — mirror TS: record and drop
            self._err("decode-failed", f"Header decode threw: {e}")
            return None

        msg_id = frame[5]
        meta = {"rawHex": frame.hex(), "decodedAt": int(time.time() * 1000), "msgId": msg_id}
        body_schema = self._schema(f"msg_{msg_id}.json")
        if body_schema is None:
            self._err("unknown-type", f"No schema for message type {msg_id}.")
            return DecodedRecord(f"unknown-{msg_id}", header, meta)

        body: dict[str, Any] = {}
        try:
            body = parse(frame, body_schema)
        except Exception as e:  # noqa: BLE001
            self._err("decode-failed", f"Body decode for msg_{msg_id} threw: {e}")
        return DecodedRecord(body_schema["messageName"], {**header, **body}, meta)

    def _skip_bad_frame(self, reason: str, detail: str) -> None:
        self._err(reason, detail, len(MAGIC))
        del self._buffer[:len(MAGIC)]

    def _err(self, reason: str, detail: str, recovered: int | None = None) -> None:
        self._errors.append(FramingError(time.time(), reason, recovered, detail))

    def _schema(self, name: str) -> dict[str, Any] | None:
        if name not in self._schemas:
            p = self._schemas_dir / name
            self._schemas[name] = json.loads(p.read_text("utf-8")) if p.exists() else None
        return self._schemas[name]
