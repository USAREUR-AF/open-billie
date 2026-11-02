#!/usr/bin/env python3
"""Verify the built platform .deb and tarball contain the same safe allowlist."""

from __future__ import annotations

import re
import subprocess
import sys
import tarfile
from pathlib import Path

from check_public_boundary import content_findings, path_findings

PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def unsafe_path(path: str) -> bool:
    normalized = path.strip("./")
    lower = normalized.lower()
    parts = lower.split("/")
    return (
        lower.endswith((".pem", ".key", "/.env", "/inventory.yml"))
        or lower in {".env", "inventory.yml", "node.yml"}
        or "host_vars" in parts
        or "kids" in parts
        or any("oetf" in component for component in parts)
    )


def tar_files(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name.removeprefix("./").lstrip("/")
            stream = archive.extractfile(member)
            if stream is not None:
                files[name] = stream.read()
    return files


def deb_files(path: Path) -> set[str]:
    listing = subprocess.run(["dpkg-deb", "--contents", str(path)], check=True, text=True, capture_output=True).stdout
    entries = {
        entry.removeprefix("./").rstrip("/")
        for line in listing.splitlines()
        if (entry := line.split()[-1]).startswith("./") and not line.lstrip().startswith("d")
    }
    prefixes = {match.group(1) for entry in entries if (match := re.match(r"^(opt/billie/platform/releases/[^/]+)/", entry))}
    if len(prefixes) != 1 or any(not entry.startswith(next(iter(prefixes), "")) for entry in entries):
        raise ValueError("Debian payload contains paths outside one versioned Billie release directory")
    prefix = next(iter(prefixes)) + "/"
    return {entry.removeprefix(prefix) for entry in entries}


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_release_artifact.py <platform.deb> <platform.tar.gz>", file=sys.stderr)
        return 2
    deb, tarball = map(Path, sys.argv[1:])
    try:
        tar_contents = tar_files(tarball)
        package_paths = deb_files(deb)
    except (OSError, tarfile.TarError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"artifact audit: could not inspect release artifacts: {exc}", file=sys.stderr)
        return 1
    tar_paths = set(tar_contents)
    if tar_paths != package_paths:
        missing = sorted(tar_paths - package_paths)
        extra = sorted(package_paths - tar_paths)
        print(f"artifact audit: .deb and tarball contents differ (deb missing={missing}, extra={extra})", file=sys.stderr)
        return 1
    bad_paths = sorted(path for path in tar_paths if unsafe_path(path) or path_findings(path))
    if bad_paths:
        print("artifact audit: forbidden paths found: " + ", ".join(bad_paths), file=sys.stderr)
        return 1
    for path, data in tar_contents.items():
        problems = content_findings(data)
        if problems or PRIVATE_KEY.search(data):
            kind = ", ".join(problems) if problems else "private key material"
            print(f"artifact audit: {kind} found in {path}", file=sys.stderr)
            return 1
    print(f"Artifact audit passed: {len(tar_paths)} matching platform files; no kid source or credential paths found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
