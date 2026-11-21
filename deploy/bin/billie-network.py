#!/usr/bin/env python3
"""Configure a dedicated, static sensor-facing IPv4 interface with Netplan."""
from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path("/etc/netplan")


def fail(message: str, code: int = 2) -> None:
    print(f"billie network: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, text=True, check=False, capture_output=capture)
    except FileNotFoundError:
        fail(f"required command not found: {args[0]}")
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        fail(f"command failed ({' '.join(args)}): {detail or result.returncode}")
    return result


def require_root() -> None:
    if os.geteuid() != 0:
        fail("run this command with sudo")


def interface_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", value) or value == "lo":
        fail("interface must be a Linux network interface name other than lo")
    if not Path("/sys/class/net", value).exists():
        fail(f"network interface does not exist: {value}; run billie network interfaces")
    return value


def managed_path(interface: str) -> Path:
    return CONFIG_DIR / f"99-billie-sensor-{interface}.yaml"


def render_netplan_config(interface: str, address: ipaddress.IPv4Interface) -> str:
    """Render a dedicated sensor interface, including when it has no carrier."""
    return (
        "# Managed by Open Billie. Remove with: sudo billie network clear --interface " + interface + "\n"
        "network:\n  version: 2\n  ethernets:\n    " + interface + ":\n"
        "      dhcp4: false\n      dhcp6: false\n      accept-ra: false\n"
        "      addresses:\n        - " + str(address) + "\n      optional: true\n      ignore-carrier: true\n"
    )


def managed_ipv4_addresses(config: bytes | None) -> list[ipaddress.IPv4Interface]:
    """Read addresses from a prior Billie-managed Netplan snippet."""
    if not config:
        return []
    text = config.decode("utf-8")
    if not text.startswith("# Managed by Open Billie."):
        fail("refusing to replace a sensor Netplan file not managed by Open Billie")
    addresses: list[ipaddress.IPv4Interface] = []
    for value in re.findall(r"^\s*-\s+((?:\d{1,3}\.){3}\d{1,3}/(?:[0-9]|[12]\d|3[0-2]))\s*$", text, re.MULTILINE):
        try:
            address = ipaddress.ip_interface(value)
        except ValueError:
            fail(f"invalid IPv4 address in the Billie-managed Netplan file: {value}")
        if address.version == 4:
            addresses.append(address)
    return addresses


def assigned_ipv4_addresses(interface: str) -> set[ipaddress.IPv4Interface]:
    output = run(["ip", "-o", "-4", "address", "show", "dev", interface], capture=True).stdout
    addresses: set[ipaddress.IPv4Interface] = set()
    for value in re.findall(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})", output):
        try:
            addresses.add(ipaddress.ip_interface(value))
        except ValueError:
            continue
    return addresses


def restore_sensor_addresses(
    interface: str,
    addresses: list[ipaddress.IPv4Interface],
    added_address: ipaddress.IPv4Interface | None = None,
    added_address_preexisted: bool = False,
) -> None:
    """Best-effort runtime rollback without reapplying the whole network stack."""
    if added_address is not None and not added_address_preexisted:
        subprocess.run(["ip", "address", "del", str(added_address), "dev", interface], check=False)
    for address in addresses:
        subprocess.run(["ip", "address", "replace", str(address), "dev", interface], check=False)


def apply_sensor_address(interface: str, address: ipaddress.IPv4Interface, previous: list[ipaddress.IPv4Interface]) -> None:
    """Apply only this interface's runtime address; avoid a global netplan apply."""
    assigned = assigned_ipv4_addresses(interface)
    run(["ip", "address", "replace", str(address), "dev", interface])
    for old_address in previous:
        if old_address != address and old_address in assigned:
            run(["ip", "address", "del", str(old_address), "dev", interface])


def interfaces() -> None:
    if shutil.which("ip") is None:
        fail("iproute2 is required; install it with apt")
    result = run(["ip", "-brief", "-4", "address", "show"], capture=True)
    links = run(["ip", "-brief", "link", "show"], capture=True).stdout
    routes = run(["ip", "-o", "route", "show", "default"], capture=True).stdout
    routes += run(["ip", "-o", "-6", "route", "show", "default"], capture=True).stdout
    default_devs = set(re.findall(r"\bdev\s+(\S+)", routes))
    macs = {}
    link_rows = {}
    for line in links.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            macs[parts[0]] = parts[2]
            link_rows[parts[0]] = line
    address_rows = {line.split()[0]: line for line in result.stdout.splitlines() if line.split()}
    print("IPv4 interfaces (use name/MAC to identify the sensor port; default-route interfaces are marked):")
    for name, link_line in link_rows.items():
        address_line = address_rows.get(name)
        ipv4 = " ".join(address_line.split()[2:]) if address_line and len(address_line.split()) > 2 else "NO IPv4 ADDRESS"
        marker = " [DEFAULT ROUTE]" if name in default_devs else ""
        print(f"  {link_line}  IPv4={ipv4}{marker}")
def ensure_safe_interface(interface: str) -> None:
    routes = run(["ip", "-o", "route", "show", "default"], capture=True).stdout
    routes += run(["ip", "-o", "-6", "route", "show", "default"], capture=True).stdout
    default_devs = set(re.findall(r"\bdev\s+(\S+)", routes))
    if interface in default_devs:
        fail(f"{interface} carries the node's default route; refusing to change a likely management/internet interface")
    # Sudo may drop SSH_CONNECTION. Detect any established TCP socket whose local
    # address belongs to this interface before changing its network configuration.
    if shutil.which("ss"):
        sockets = run(["ss", "-Htn", "state", "established"], capture=True).stdout
        assigned = set()
        addresses = run(["ip", "-o", "address", "show", "dev", interface], capture=True).stdout
        assigned.update(match.group(1).split("%")[0] for match in re.finditer(r"\binet6?\s+([^/\s]+)/", addresses))
        for row in sockets.splitlines():
            fields = row.split()
            if len(fields) < 5:
                continue
            local = fields[3]
            host = local[1:local.find("]")] if local.startswith("[") else local.rsplit(":", 1)[0]
            if host.split("%")[0] in assigned:
                fail(f"{interface} carries an established TCP connection; refusing to risk disconnecting an active session")
    ssh_connection = os.environ.get("SSH_CONNECTION", "").split()
    if ssh_connection:
        family = "-6" if ":" in ssh_connection[0] else "-4"
        route = run(["ip", "-o", family, "route", "get", ssh_connection[0]], capture=True).stdout
        match = re.search(r"\bdev\s+(\S+)", route)
        if match and match.group(1) == interface:
            fail(f"{interface} carries this SSH session; refusing to risk disconnecting the CLI")


def confirm(summary: str, assume_yes: bool) -> None:
    print(summary)
    if assume_yes:
        return
    try:
        answer = input("Apply this network change now? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        fail("cancelled; no network changes were applied", 1)


def configure(interface_value: str, address_value: str, assume_yes: bool) -> None:
    require_root()
    interface = interface_name(interface_value)
    ensure_safe_interface(interface)
    try:
        address = ipaddress.ip_interface(address_value)
    except ValueError:
        fail("--address must be an IPv4 CIDR such as 192.0.2.20/24")
    if address.version != 4:
        fail("only IPv4 static sensor addresses are supported currently")
    if address.ip.is_unspecified or address.ip.is_multicast or address.ip.is_loopback:
        fail("--address must be a unicast IPv4 address")
    if address.ip == address.network.network_address or address.ip == address.network.broadcast_address:
        fail("--address must be a usable host address, not the network or broadcast address")
    existing = run(["ip", "-o", "-4", "address", "show"], capture=True).stdout
    for line in existing.splitlines():
        found_dev = re.match(r"\d+:\s+(\S+)", line)
        found_ip = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", line)
        if found_dev and found_ip and found_ip.group(1) == str(address.ip) and found_dev.group(1).split("@")[0] != interface:
            fail(f"{address.ip} is already assigned to {found_dev.group(1)}")
    if shutil.which("netplan") is None:
        fail("Netplan is required on the supported Ubuntu node")
    path = managed_path(interface)
    confirm(
        f"Will assign {address} to {interface} with no gateway or DNS, using {path}.\n"
        "This is intended for a dedicated sensor link and is applied even when no cable is connected. Existing default-route and SSH interfaces are protected.",
        assume_yes,
    )
    CONFIG_DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
    old_data = path.read_bytes() if path.exists() else None
    previous_addresses = managed_ipv4_addresses(old_data)
    address_was_assigned = address in assigned_ipv4_addresses(interface)
    body = render_netplan_config(interface, address)
    path.write_text(body, encoding="utf-8")
    os.chmod(path, 0o600)
    runtime_updated = False
    try:
        run(["netplan", "generate"])
        runtime_updated = True
        apply_sensor_address(interface, address, previous_addresses)
    except SystemExit:
        if old_data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(old_data)
            os.chmod(path, 0o600)
        subprocess.run(["netplan", "generate"], check=False)
        if runtime_updated:
            restore_sensor_addresses(interface, previous_addresses, address, address_was_assigned)
        raise
    print(f"Configured {interface} with {address}; only this interface was changed, and no default route was added.")
    print(f"Use this bind address for the kid: {address.ip}")


def clear(interface_value: str, assume_yes: bool) -> None:
    require_root()
    interface = interface_name(interface_value)
    ensure_safe_interface(interface)
    path = managed_path(interface)
    if not path.is_file():
        fail(f"no Billie-managed sensor network config exists for {interface}", 1)
    confirm(f"Will remove {path} and only Billie-managed addresses from {interface}; other interfaces will not be reapplied.", assume_yes)
    backup = path.read_bytes()
    addresses = managed_ipv4_addresses(backup)
    assigned = assigned_ipv4_addresses(interface)
    path.unlink()
    runtime_updated = False
    try:
        run(["netplan", "generate"])
        runtime_updated = True
        for address in addresses:
            if address in assigned:
                run(["ip", "address", "del", str(address), "dev", interface])
    except SystemExit:
        path.write_bytes(backup)
        os.chmod(path, 0o600)
        subprocess.run(["netplan", "generate"], check=False)
        if runtime_updated:
            restore_sensor_addresses(interface, addresses)
        raise
    print(f"Removed Billie-managed static address configuration for {interface}; other interfaces were not reapplied.")


def main() -> int:
    parser = argparse.ArgumentParser(prog="billie network", description="Configure the node's dedicated sensor-facing interface.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("interfaces", help="list IPv4 interfaces and identify default-route interfaces")
    config = sub.add_parser("configure", help="assign a static IPv4 CIDR to a dedicated sensor interface")
    config.add_argument("--interface", required=True, help="Linux interface name shown by 'billie network interfaces'")
    config.add_argument("--address", required=True, help="static IPv4 CIDR, for example 192.0.2.20/24")
    config.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    remove = sub.add_parser("clear", help="remove only the Billie-managed sensor interface configuration")
    remove.add_argument("--interface", required=True)
    remove.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()
    if args.command == "interfaces":
        interfaces()
    elif args.command == "configure":
        configure(args.interface, args.address, args.yes)
    elif args.command == "clear":
        clear(args.interface, args.yes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
