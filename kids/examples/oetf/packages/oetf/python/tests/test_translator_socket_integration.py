"""Synthetic OETF mapping to the Golden Path translator socket contract."""

from __future__ import annotations

import json
import socket
import threading

import pytest

from billie_oetf import FrameHeader, Mapper, OetfDecoder, Track, build_track_report
from billie_oetf.translator_runtime import _translate


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="translator IPC uses Linux Unix sockets")
def test_canonical_oetf_record_is_sent_to_translator_by_logical_output(tmp_path):
    frame = build_track_report(
        FrameHeader(42, 0x0107),
        1_761_739_200_123_456,
        [
            Track(
                id=311,
                classification=3,
                confidence_pct=87,
                lat_deg=0.0,
                lon_deg=0.0,
                alt_m=152.4,
                vel_east_ms=-12.5,
                vel_north_ms=4.25,
                vel_up_ms=1.5,
                pos_sigma_east_m=3.2,
                pos_sigma_north_m=2.8,
                alt_sigma_m=6.1,
                vel_sigma_east_ms=0.9,
                vel_sigma_north_ms=0.7,
                rcs_dbsm=-18.3,
                age_s=74,
                confirmed=True,
            )
        ],
    )
    decoded = OetfDecoder().feed(frame)
    canonical = Mapper().translate("oetf", decoded[0], "billie-canonical")[0]["fields"]

    socket_path = str(tmp_path / "translator.sock")
    received: list[dict] = []
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(1)

    def translator_stub():
        with listener:
            connection, _ = listener.accept()
            with connection, connection.makefile("rb") as request_file:
                request = json.loads(request_file.readline())
                received.append(request)
                response = {
                    "apiVersion": "billie.dev/translation-v1",
                    "kind": "TranslateResult",
                    "requestId": request["requestId"],
                    "status": "published",
                    "outputName": request["target"]["outputName"],
                    "format": request["target"]["format"],
                    "bytesPublished": 128,
                }
                connection.sendall(json.dumps(response).encode() + b"\n")

    worker = threading.Thread(target=translator_stub, daemon=True)
    worker.start()
    response = _translate(socket_path, "oetf", "tracks-cot", "cot", canonical)
    worker.join(timeout=2)

    assert response["status"] == "published"
    assert received[0]["kid"] == "oetf"
    assert received[0]["target"] == {"outputName": "tracks-cot", "format": "cot"}
    assert received[0]["record"]["apiVersion"] == "billie.dev/track-v2"
    assert received[0]["record"]["trackId"] == "311"
    assert received[0]["record"]["sourceId"] == "263"
    assert received[0]["record"]["trackGeneration"] == "fixture-1"
    assert received[0]["record"]["position"]["latitudeDeg"] == 0.0
    assert received[0]["record"]["classification"] == "uas"
