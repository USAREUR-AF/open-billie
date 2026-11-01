#!/usr/bin/env python3
"""Safely configure or disable Open Billie Golden Path fabric attachment."""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ETC = Path(os.environ.get("BILLIE_ETC_DIR", "/etc/billie"))
ENDPOINT_RE = re.compile(r"^tls/[A-Za-z0-9.-]+:[0-9]{1,5}$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")

def regular_file(path: Path, label: str) -> None:
    try:
        info = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} is unavailable") from error
    if not stat.S_ISREG(info.st_mode) or not info.st_size or not os.access(path, os.R_OK):
        raise ValueError(f"{label} must be a readable regular file")

def install_copy(source: Path, target: Path, mode: int) -> None:
    regular_file(source, "certificate input")
    fd, temporary = tempfile.mkstemp(prefix=".billie-cert-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

def configure(args: argparse.Namespace) -> None:
    if not ENDPOINT_RE.fullmatch(args.endpoint):
        raise ValueError("endpoint must use proto/host:port, for example tls/fabric.example.net:7447")
    if not PREFIX_RE.fullmatch(args.prefix):
        raise ValueError("prefix must be a scoped Zenoh key prefix without wildcards")
    if any(part in (".", "..") for part in args.prefix.split("/")):
        raise ValueError("prefix segments cannot be dot paths")
    port = int(args.endpoint.rsplit(":", 1)[1])
    if not 1 <= port <= 65535:
        raise ValueError("endpoint port must be between 1 and 65535")
    for label, path in (
        ("CA certificate", Path(args.ca_file)),
        ("client certificate", Path(args.client_cert_file)),
        ("client private key", Path(args.client_key_file)),
    ):
        regular_file(path, label)
    try:
        subprocess.run(
            ["openssl", "x509", "-in", args.ca_file, "-noout"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["openssl", "x509", "-in", args.client_cert_file, "-checkend", "0", "-noout"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["openssl", "verify", "-CAfile", args.ca_file, args.client_cert_file],
            check=True, capture_output=True, text=True,
        )
        cert_pub = subprocess.run(
            ["openssl", "x509", "-in", args.client_cert_file, "-pubkey", "-noout"],
            check=True, capture_output=True,
        ).stdout
        key_pub = subprocess.run(
            ["openssl", "pkey", "-in", args.client_key_file, "-pubout"],
            check=True, capture_output=True,
        ).stdout
    except FileNotFoundError as error:
        raise ValueError("openssl is required to validate fabric certificate files") from error
    except subprocess.CalledProcessError as error:
        raise ValueError("fabric certificate or private key is invalid or unreadable") from error
    if cert_pub != key_pub:
        raise ValueError("client certificate does not match the supplied private key")
    zenoh_dir = ETC / "zenoh"
    tls_dir = zenoh_dir / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(zenoh_dir, 0o750)
    os.chmod(tls_dir, 0o700)
    install_copy(Path(args.ca_file), tls_dir / "ca.pem", 0o644)
    install_copy(Path(args.client_cert_file), tls_dir / "client.pem", 0o644)
    install_copy(Path(args.client_key_file), tls_dir / "client-key.pem", 0o600)
    config = {
        "billie_fabric_enabled": True,
        "billie_fabric_endpoint": args.endpoint,
        "billie_fabric_prefix": args.prefix,
    }
    config_path = zenoh_dir / "fabric.json"
    fd, temporary = tempfile.mkstemp(prefix=".fabric-", dir=zenoh_dir, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, config_path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    print(f"Fabric settings saved to {config_path}; apply with sudo billie apply.")

def disable(_: argparse.Namespace) -> None:
    zenoh_dir = ETC / "zenoh"
    for path in (zenoh_dir / "fabric.json", zenoh_dir / "fabric-client.enabled"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for name in ("ca.pem", "client.pem", "client-key.pem"):
        try:
            (zenoh_dir / "tls" / name).unlink()
        except FileNotFoundError:
            pass
    print("Fabric settings and installed certificate copies removed; apply with sudo billie apply.")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("configure", help="install mTLS files and configure fabric attachment")
    setup.add_argument("--endpoint", required=True)
    setup.add_argument("--prefix", required=True)
    setup.add_argument("--ca-file", required=True)
    setup.add_argument("--client-cert-file", required=True)
    setup.add_argument("--client-key-file", required=True)
    setup.set_defaults(action=configure)
    remove = sub.add_parser("disable", help="remove fabric settings and certificate copies")
    remove.set_defaults(action=disable)
    args = parser.parse_args()
    try:
        args.action(args)
    except (OSError, ValueError) as error:
        print(f"billie zenoh: {error}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
