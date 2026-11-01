"""Synthetic OETF TCP/UDP ingress, canonical mapping, and Billie translator client."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import uuid
from collections.abc import Iterator
from typing import Any

from . import Mapper, OetfDecoder

OUTPUTS = (("tracks-cot", "cot"), ("tracks-cat062", "asterix-cat062"), ("tracks-sapient", "sapient"))
_running = True


def _stop(_signum: int, _frame: Any) -> None:
    global _running
    _running = False


def _translate(socket_path: str, kid: str, output_name: str, fmt: str, track: dict) -> dict:
    request = {
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateRequest",
        "requestId": str(uuid.uuid4()),
        "kid": kid,
        "target": {"outputName": output_name, "format": fmt},
        "record": track,
    }
    encoded = json.dumps(request, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(10.0)
        client.connect(socket_path)
        client.sendall(encoded)
        with client.makefile("rb") as response_file:
            line = response_file.readline(64 * 1024 + 1)
    if not line.endswith(b"\n") or len(line) > 64 * 1024:
        raise RuntimeError("translator returned an invalid or oversized response line")
    response = json.loads(line)
    if response.get("requestId") != request["requestId"]:
        raise RuntimeError("translator response requestId did not match")
    if response.get("status") != "published":
        error = response.get("error", {})
        raise RuntimeError(
            f"translator rejected output ({error.get('code', 'unknown')}): "
            f"{error.get('message', 'no error detail provided')}"
        )
    if response.get("outputName") != output_name or response.get("format") != fmt:
        raise RuntimeError("translator response output selection did not match")
    return response


def _report_errors(decoder: OetfDecoder) -> None:
    for error in decoder.get_recent_errors():
        print(f"OETF framing {error.reason}: {error.detail}", file=sys.stderr, flush=True)


def _publish_records(records: list, mapper: Mapper, translator_socket: str) -> None:
    for decoded in records:
        for canonical in mapper.translate("oetf", decoded, "billie-canonical"):
            track = canonical["fields"]
            for output_name, fmt in OUTPUTS:
                try:
                    response = _translate(translator_socket, "oetf", output_name, fmt, track)
                    print(
                        f"translator accepted output={output_name} format={fmt} "
                        f"bytes={response.get('bytesPublished', 0)}",
                        flush=True,
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    print(f"OETF output {output_name} failed: {exc}", file=sys.stderr, flush=True)


def _feed(decoder: OetfDecoder, mapper: Mapper, translator_socket: str, chunk: bytes) -> None:
    _publish_records(decoder.feed(chunk), mapper, translator_socket)
    _report_errors(decoder)


def _tcp_records(connection: socket.socket, decoder: OetfDecoder) -> Iterator:
    """Yield decoded records from a TCP byte stream until EOF, resetting on disconnect."""
    try:
        while _running:
            try:
                chunk = connection.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                break
            records = decoder.feed(chunk)
            _report_errors(decoder)
            yield from records
    finally:
        if decoder._buffer:
            print(
                f"OETF TCP stream ended with {len(decoder._buffer)} incomplete frame byte(s); discarding them",
                file=sys.stderr,
                flush=True,
            )
        decoder.reset()


def serve(bind_host: str, port: int, translator_socket: str, transport: str = "udp") -> int:
    global _running
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    mapper = Mapper()

    try:
        if transport == "udp":
            decoder = OetfDecoder()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as ingress:
                ingress.settimeout(0.5)
                ingress.bind((bind_host, port))
                print(
                    f"OETF UDP listening on {bind_host}:{port}; translator socket {translator_socket}",
                    flush=True,
                )
                while _running:
                    try:
                        datagram, _sender = ingress.recvfrom(65535)
                    except TimeoutError:
                        continue
                    _feed(decoder, mapper, translator_socket, datagram)
        elif transport == "tcp":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ingress:
                ingress.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                ingress.settimeout(0.5)
                ingress.bind((bind_host, port))
                ingress.listen(8)
                print(
                    f"OETF TCP listening on {bind_host}:{port}; translator socket {translator_socket}",
                    flush=True,
                )
                while _running:
                    try:
                        connection, peer = ingress.accept()
                    except TimeoutError:
                        continue
                    print(f"OETF TCP connected from {peer[0]}:{peer[1]}", flush=True)
                    decoder = OetfDecoder()
                    with connection:
                        connection.settimeout(0.5)
                        try:
                            for decoded in _tcp_records(connection, decoder):
                                _publish_records([decoded], mapper, translator_socket)
                                _report_errors(decoder)
                        except OSError as exc:
                            print(f"OETF TCP connection ended with an error: {exc}", file=sys.stderr, flush=True)
                    print(f"OETF TCP disconnected from {peer[0]}:{peer[1]}", flush=True)
        else:
            raise ValueError(f"unsupported input transport: {transport}")
    except OSError as exc:
        print(f"OETF runtime failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind-host", default=os.environ.get("BILLIE_INPUT_BIND", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("BILLIE_INPUT_PORT", "5100")))
    parser.add_argument(
        "--transport",
        choices=("udp", "tcp"),
        default=os.environ.get("BILLIE_INPUT_TRANSPORT", "udp").lower(),
    )
    parser.add_argument(
        "--translator-socket",
        default=os.environ.get("BILLIE_TRANSLATOR_SOCKET", "/run/billie/translator.sock"),
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    return serve(args.bind_host, args.port, args.translator_socket, args.transport)


if __name__ == "__main__":
    raise SystemExit(main())
