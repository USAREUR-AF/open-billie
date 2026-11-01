#!/usr/bin/env python3
"""Continuously transmit synthetic, test-flagged OETF frames over UDP or TCP."""

from __future__ import annotations

import argparse
import os
import socket
import time

from billie_oetf.builder import FrameHeader, Track, build_track_report


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be an integer") from exc


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{name} must be a number") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default=os.environ.get("SENSOR_DESTINATION", "192.0.2.20"))
    parser.add_argument("--port", type=int, default=env_int("SENSOR_PORT", 5100))
    parser.add_argument("--transport", choices=("udp", "tcp"), default=os.environ.get("SENSOR_TRANSPORT", "udp").lower())
    parser.add_argument("--interval", type=float, default=env_float("SENSOR_INTERVAL_SECONDS", 1.0))
    parser.add_argument("--count", type=int, default=env_int("SENSOR_COUNT", 0), help="frames to send; 0 runs continuously")
    parser.add_argument("--track-id", type=int, default=env_int("SENSOR_TRACK_ID", 311))
    parser.add_argument("--sensor-id", type=int, default=env_int("SENSOR_ID", 263))
    parser.add_argument("--sequence", type=int, default=env_int("SENSOR_START_SEQUENCE", 1))
    parser.add_argument("--latitude", type=float, default=env_float("SENSOR_LATITUDE", 0.0))
    parser.add_argument("--longitude", type=float, default=env_float("SENSOR_LONGITUDE", 0.0))
    parser.add_argument("--altitude-m", type=float, default=env_float("SENSOR_ALTITUDE_M", 100.0))
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.transport not in {"udp", "tcp"}:
        parser.error("transport must be udp or tcp")
    if args.interval <= 0:
        parser.error("interval must be greater than zero")
    if args.count < 0:
        parser.error("count must be zero (continuous) or a positive integer")
    if not 0 <= args.track_id <= 4095:
        parser.error("track-id must be from 0 through 4095")
    if not 0 <= args.sensor_id <= 65535:
        parser.error("sensor-id must be from 0 through 65535")
    if not -90 <= args.latitude <= 90:
        parser.error("latitude must be from -90 through 90")
    if not -180 <= args.longitude <= 180:
        parser.error("longitude must be from -180 through 180")
    return args


def main() -> int:
    args = parse_args()
    destination = (args.destination, args.port)
    sequence = args.sequence & 0xFFFFFFFF
    sent_count = 0
    print(
        f"Synthetic OETF sensor sending {args.transport.upper()} to {destination[0]}:{destination[1]} "
        f"every {args.interval:g}s; count={'continuous' if args.count == 0 else args.count}",
        flush=True,
    )

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if args.transport == "udp" else None
    try:
        while args.count == 0 or sent_count < args.count:
            timestamp_us = time.time_ns() // 1_000
            drift = (sent_count % 101) * 0.00001
            track = Track(
                id=args.track_id,
                classification=3,
                confidence_pct=87,
                lat_deg=args.latitude + drift,
                lon_deg=args.longitude + drift,
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
            frame = build_track_report(
                FrameHeader(sequence=sequence, sensor_id=args.sensor_id, test_data=True, simulated=True),
                timestamp_us,
                [track],
            )
            try:
                if args.transport == "udp":
                    assert sender is not None
                    written = sender.sendto(frame, destination)
                else:
                    if sender is None:
                        sender = socket.create_connection(destination, timeout=5)
                    sender.sendall(frame)
                    written = len(frame)
            except OSError as exc:
                if args.transport == "tcp":
                    if sender is not None:
                        sender.close()
                    sender = None
                    print(f"TCP sensor waiting to connect to {destination[0]}:{destination[1]}: {exc}", flush=True)
                    time.sleep(min(max(args.interval, 0.5), 2.0))
                    continue
                raise
            sent_count += 1
            print(
                f"sent sequence={sequence} track={args.track_id} bytes={written} "
                f"test=true simulated=true",
                flush=True,
            )
            sequence = (sequence + 1) & 0xFFFFFFFF
            if args.count == 0 or sent_count < args.count:
                time.sleep(args.interval)
    finally:
        if sender is not None:
            sender.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Sensor simulation stopped.", flush=True)
