#!/usr/bin/env python3
"""One-way local Zenoh island to fabric client bridge.

This bridge only reads the local island REST stream and writes through the
separate client-mode session. It adds the configured vendor prefix at the
boundary and never subscribes to fabric traffic.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

SUB_URL = os.environ.get("BILLIE_ISLAND_REST_URL", "http://127.0.0.1:8000").rstrip("/")
PUB_URL = os.environ.get("BILLIE_FABRIC_REST_URL", "http://127.0.0.1:8001").rstrip("/")
PREFIX = os.environ.get("BILLIE_FABRIC_PREFIX", "").strip("/")
MAX_EVENT_BYTES = 8 * 1024 * 1024
COUNTERS = {"forwarded": 0, "rejected": 0, "errors": 0, "skipped": 0, "parse_errors": 0}
COUNTER_LOCK = threading.Lock()


def validate_prefix(prefix: str) -> bool:
    return bool(
        prefix
        and re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", prefix)
        and all(part not in (".", "..") for part in prefix.split("/"))
    )


def fabric_key(local_key: str) -> str | None:
    parts = local_key.split("/")
    if (
        not local_key
        or local_key.startswith("@")
        or any(part in ("", ".", "..") for part in parts)
        or "*" in local_key
        or "?" in local_key
    ):
        return None
    if local_key == PREFIX or local_key.startswith(PREFIX + "/"):
        return local_key
    return PREFIX + "/" + local_key


def sample_body(value: object, content_type: str) -> bytes:
    if not isinstance(value, str):
        return json.dumps(value, separators=(",", ":")).encode("utf-8")
    if content_type.startswith("text/") or content_type in ("application/json", "application/xml"):
        return value.encode("utf-8")
    return base64.b64decode(value, validate=True)


def increment(name: str) -> None:
    with COUNTER_LOCK:
        COUNTERS[name] += 1


def forward(event: str, sample: dict) -> None:
    key = sample.get("key")
    destination = fabric_key(key) if isinstance(key, str) else None
    if destination is None:
        increment("skipped")
        return
    url = PUB_URL + "/" + urllib.parse.quote(destination, safe="/")
    method = "DELETE" if event.upper() == "DELETE" else "PUT"
    data = None
    headers = {}
    if method == "PUT":
        if "value" not in sample:
            increment("skipped")
            return
        content_type = str(sample.get("encoding") or "application/octet-stream")
        try:
            data = sample_body(sample["value"], content_type)
        except (ValueError, TypeError):
            increment("parse_errors")
            return
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read(4096)
            if 200 <= response.status < 300:
                increment("forwarded")
            else:
                increment("rejected")
    except urllib.error.HTTPError as error:
        error.read(4096)
        increment("rejected")
    except (urllib.error.URLError, TimeoutError, OSError):
        increment("errors")


def heartbeat() -> None:
    while True:
        time.sleep(30)
        with COUNTER_LOCK:
            snapshot = " ".join(f"{key}={value}" for key, value in COUNTERS.items())
        print(f"[billie-island-bridge] {snapshot}", flush=True)


def consume_stream() -> None:
    request = urllib.request.Request(SUB_URL + "/**", headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(request, timeout=60) as response:
        event = "PUT"
        data_lines: list[str] = []
        size = 0
        draining_oversized_line = False
        while True:
            raw_line = response.readline(MAX_EVENT_BYTES + 2)
            if not raw_line:
                break
            if len(raw_line) == MAX_EVENT_BYTES + 2 and not raw_line.endswith(b"\n"):
                increment("parse_errors")
                draining_oversized_line = True
                data_lines, size = [], 0
                continue
            if draining_oversized_line:
                if raw_line in (b"\n", b"\r\n"):
                    draining_oversized_line = False
                    event, data_lines, size = "PUT", [], 0
                continue
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data_lines:
                    try:
                        sample = json.loads("\n".join(data_lines))
                        if isinstance(sample, dict):
                            forward(event, sample)
                        else:
                            increment("parse_errors")
                    except (json.JSONDecodeError, TypeError):
                        increment("parse_errors")
                event, data_lines, size = "PUT", [], 0
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line[6:].strip() or "PUT"
            elif line.startswith("data:"):
                size += len(line)
                if size > MAX_EVENT_BYTES:
                    data_lines, size = [], MAX_EVENT_BYTES + 1
                    increment("parse_errors")
                elif size <= MAX_EVENT_BYTES:
                    data_lines.append(line[5:].lstrip())


def main() -> None:
    if not validate_prefix(PREFIX):
        raise SystemExit("BILLIE_FABRIC_PREFIX is missing or invalid; refusing unscoped forwarding")
    threading.Thread(target=heartbeat, daemon=True).start()
    while True:
        try:
            consume_stream()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            print(f"[billie-island-bridge] local stream unavailable; retrying: {type(error).__name__}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
