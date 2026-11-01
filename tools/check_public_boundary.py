#!/usr/bin/env python3
"""Reject credentials, workstation paths, capture files, and deployment IPs."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".pcap", ".pcapng", ".cap"}
FORBIDDEN_NAMES = {".env", "inventory.yml", "id_rsa", "id_ed25519"}
RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private key or certificate material", re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?(?:PRIVATE KEY|CERTIFICATE)-----")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("Slack token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private package registry", re.compile(rb"(?:npm|yarn)\.pkg\.github\.com|packages\.github\.com", re.IGNORECASE)),
    ("credential assignment", re.compile(rb"(?i)\b(?:api[_-]?key|client[_-]?secret|netbird[_-]?setup[_-]?key|password|access[_-]?token)\b\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{24,}")),
    ("personal workstation path", re.compile(rb"(?i)(?:[A-Z]:" + rb"\x5cUsers\x5c" + rb"[^\\<>\" ]+|\x2fmnt\x2f[a-z]\x2fUsers\x2f[^/<>\" ]+|\x2fhome\x2f[^/<>\" ]+)")),
    ("internal downstream product name", re.compile(rb"(?i)(?:pan" + rb"oscope|ef" + rb"di)")),
)


def path_findings(name: str) -> list[str]:
    normalized = name.replace("\\", "/")
    lower = normalized.lower()
    parts = lower.split("/")
    findings: list[str] = []
    if Path(parts[-1]).suffix in FORBIDDEN_SUFFIXES or parts[-1] in FORBIDDEN_NAMES or "host_vars" in parts:
        findings.append("credential or packet-capture path")
    if any(rule[1].search(name.encode("utf-8", "replace")) for rule in RULES if rule[0] == "personal workstation path"):
        findings.append("personal workstation path")
    return findings


def content_findings(data: bytes, *, scan_ip_literals: bool = True) -> list[str]:
    findings = [label for label, pattern in RULES if pattern.search(data)]
    # Private, link-local, and carrier-grade addresses are commonly deployment
    # facts. Permit RFC 5737 documentation ranges and Podman's default bridge
    # subnet, which appears in generic runtime and firewall fixtures.
    documentation_networks = tuple(
        ipaddress.ip_network(value)
        for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "10.88.0.0/16")
    )
    if not scan_ip_literals:
        return findings
    for match in re.finditer(rb"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])", data):
        literal = match.group().decode("ascii")
        try:
            address = ipaddress.ip_address(literal)
        except ValueError:
            continue
        # Dotted decimal subnet masks are documentation syntax, not node IPs.
        try:
            network = ipaddress.IPv4Network(f"0.0.0.0/{literal}")
        except (ValueError, ipaddress.NetmaskValueError):
            network = None
        if network is not None and str(network.netmask) == literal:
            continue
        if address.is_global or any(address in network for network in documentation_networks):
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            continue
        findings.append("deployment-specific IP literal")
        break
    return findings


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    return [value.decode("utf-8", "replace") for value in result.stdout.split(b"\0") if value]


def scan_source() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for name in tracked_files():
        for label in path_findings(name):
            findings.append((name, label))
        path = ROOT / name
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:
            continue
        for label in content_findings(data):
            findings.append((name, label))
    return findings


def scan_history() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    process = subprocess.Popen(
        ["git", "log", "--all", "--format=%H", "--patch", "--no-ext-diff", "--no-renames"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    commit = "unknown"
    for line in process.stdout:
        if re.fullmatch(rb"[0-9a-f]{40}\n?", line):
            commit = line.strip().decode("ascii", "replace")
            continue
        if line.startswith((b"+++ b/", b"--- a/")):
            path = line[6:].strip().decode("utf-8", "replace")
            for label in path_findings(path):
                findings.append((f"commit {commit[:12]}:{path}", label))
        # Git history is part of the public source surface. Scan all patch lines;
        # old deployment addresses must be removed from reachable history before publication.
        for label in content_findings(line):
            findings.append((f"commit {commit[:12]}", label))
    stderr = process.stderr.read() if process.stderr is not None else b""
    result = process.wait()
    if result:
        raise RuntimeError(f"git history scan failed with exit code {result}: {stderr.decode('utf-8', 'replace').strip()}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="also scan all reachable Git commit patches")
    args = parser.parse_args()
    findings = scan_source()
    if args.history:
        findings.extend(scan_history())
    if findings:
        for name, label in findings:
            print(f"public-boundary check: {name}: {label}", file=sys.stderr)
        return 1
    print("Public-boundary scan passed; no high-confidence credentials, workstation paths, private registries, capture files, or deployment-specific IP literals found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
