#!/usr/bin/env python3
"""Generate a synthetic, test-flagged OETF frame and optionally send it by UDP or TCP."""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OETF_PYTHON = ROOT / "kids" / "examples" / "oetf" / "packages" / "oetf" / "python" / "src"
sys.path.insert(0, str(OETF_PYTHON))

from billie_oetf.builder import FrameHeader, Track, build_track_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udp-host", help="send the generated frame to this UDP host")
    parser.add_argument("--tcp-host", help="send the generated frame stream to this TCP listener")
    parser.add_argument("--udp-port", type=int, default=5100, help="UDP input port (default: 5100)")
    parser.add_argument("--udp-source", help="optional local IPv4 address to bind before sending")
    parser.add_argument("--tcp-port", type=int, default=5100, help="TCP input port (default: 5100)")
    parser.add_argument("--tcp-source", help="optional local IPv4 address to bind before connecting")
    parser.add_argument("--tcp-repeat", type=int, default=1, help="frames to send on one TCP connection (default: 1)")
    parser.add_argument(
        "--tcp-chunk-size",
        type=int,
        default=0,
        help="split the TCP byte stream into writes of this size; 0 sends it in one write",
    )
    parser.add_argument("--output", type=Path, help="also write the generated frame bytes to this file")
    parser.add_argument("--track-id", type=int, default=311, help="track ID (0..4095 works with CAT-062)")
    parser.add_argument("--sensor-id", type=int, default=263, help="synthetic sensor ID")
    parser.add_argument("--sequence", type=int, default=1, help="starting synthetic frame sequence number")
    parser.add_argument("--latitude", type=float, default=0.0, help="synthetic latitude in degrees")
    parser.add_argument("--longitude", type=float, default=0.0, help="synthetic longitude in degrees")
    parser.add_argument("--altitude-m", type=float, default=100.0, help="synthetic altitude in metres")
    args = parser.parse_args()

    if args.udp_host and args.tcp_host:
        parser.error("choose either --udp-host or --tcp-host for one sample send")
    if not args.tcp_host and (args.tcp_repeat != 1 or args.tcp_chunk_size != 0):
        parser.error("--tcp-repeat and --tcp-chunk-size require --tcp-host")
    if not 1 <= args.tcp_repeat <= 1000:
        parser.error("--tcp-repeat must be between 1 and 1000")
    if not 0 <= args.tcp_chunk_size <= 65535:
        parser.error("--tcp-chunk-size must be 0 or between 1 and 65535")
    if not 0 <= args.track_id <= 4095:
        parser.error("--track-id must be between 0 and 4095 for the CAT-062 example output")
    if not 0 <= args.sensor_id <= 65535:
        parser.error("--sensor-id must be between 0 and 65535")
    if not -90 <= args.latitude <= 90:
        parser.error("--latitude must be between -90 and 90")
    if not -180 <= args.longitude <= 180:
        parser.error("--longitude must be between -180 and 180")

    frame_count = args.tcp_repeat if args.tcp_host else 1
    frames = []
    for index in range(frame_count):
        header = FrameHeader(
            sequence=args.sequence + index,
            sensor_id=args.sensor_id,
            test_data=True,
            simulated=True,
        )
        track = Track(
            id=args.track_id,
            classification=3,
            confidence_pct=87,
            lat_deg=args.latitude,
            lon_deg=args.longitude,
            alt_m=args.altitude_m,
            vel_east_ms=2.0,
            vel_north_ms=3.0,
            vel_up_ms=0.0,
            pos_sigma_east_m=5.0,
            pos_sigma_north_m=5.0,
            alt_sigma_m=10.0,
            vel_sigma_east_ms=1.0,
            vel_sigma_north_ms=1.0,
            rcs_dbsm=-10.0,
            age_s=0,
            confirmed=True,
            simulated=True,
        )
        frames.append(build_track_report(header, time.time_ns() // 1000, [track]))

    payload = b"".join(frames)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
        print(f"Wrote {len(payload)} byte(s) across {frame_count} synthetic OETF frame(s) to {args.output}")
    if args.udp_host:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            if args.udp_source:
                sender.bind((args.udp_source, 0))
            sender.sendto(frames[0], (args.udp_host, args.udp_port))
        source_note = f" from {args.udp_source}" if args.udp_source else ""
        print(f"Sent {len(frames[0])} byte test/simulated OETF frame{source_note} to {args.udp_host}:{args.udp_port}")
    if args.tcp_host:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sender:
            sender.settimeout(5.0)
            if args.tcp_source:
                sender.bind((args.tcp_source, 0))
            sender.connect((args.tcp_host, args.tcp_port))
            chunk_size = args.tcp_chunk_size or len(payload)
            for offset in range(0, len(payload), chunk_size):
                sender.sendall(payload[offset : offset + chunk_size])
        source_note = f" from {args.tcp_source}" if args.tcp_source else ""
        write_note = f" in {chunk_size}-byte writes" if args.tcp_chunk_size else " in one stream write"
        print(
            f"Sent {len(payload)} byte(s) across {frame_count} test/simulated OETF frame(s)"
            f"{source_note} over TCP to {args.tcp_host}:{args.tcp_port}{write_note}"
        )
    if not args.output and not args.udp_host and not args.tcp_host:
        print(frames[0].hex())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())