from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

from billie_oetf import OetfDecoder
from billie_oetf.translator_runtime import _tcp_records

VECTOR = Path(__file__).resolve().parents[2] / "shared" / "conformance" / "vectors" / "track_report_two_tracks.json"


def test_tcp_stream_reassembles_fragmented_frames_and_splits_back_to_back_frames():
    frame = bytes.fromhex(json.loads(VECTOR.read_text("utf-8"))["chunks"][0])
    receiver, sender = socket.socketpair()
    decoder = OetfDecoder()
    records = []

    def consume():
        with receiver:
            records.extend(_tcp_records(receiver, decoder))

    worker = threading.Thread(target=consume)
    worker.start()
    sender.sendall(frame[:7])
    sender.sendall(frame[7:31])
    sender.sendall(frame[31:] + frame)
    sender.shutdown(socket.SHUT_WR)
    sender.close()
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert len(records) == 2
    assert all(record.message_name == "Track Report" for record in records)
    assert records[0].fields == records[1].fields
    assert decoder._buffer == bytearray()
