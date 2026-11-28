#!/usr/bin/env python3
"""Remove Open Billie artifacts while leaving NetBird and unrelated workloads untouched."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError:
        if check:
            print(f"billie teardown: required command not found: {args[0]}", file=sys.stderr)
            raise SystemExit(1)
        return subprocess.CompletedProcess(args, 127, "", f"not found: {args[0]}")
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"billie teardown: {' '.join(args)} failed: {detail or result.returncode}", file=sys.stderr)
        raise SystemExit(1)
    return result


def confirm(prompt: str, expected: str, yes: bool = False) -> None:
    if yes:
        return
    try:
        answer = input(f"{prompt}\nType {expected!r} to continue: ").strip()
    except EOFError:
        answer = ""
    if answer != expected:
        print("billie teardown: cancelled; no changes made", file=sys.stderr)
        raise SystemExit(1)


def remove_symlink_if_billie(path: Path) -> None:
    if path.is_symlink():
        target = os.readlink(path)
        if "/opt/billie/" in target or target.startswith("/opt/billie/"):
            path.unlink(missing_ok=True)


def managed_sensor_addresses(config: str) -> tuple[str, list[ipaddress.IPv4Interface]] | None:
    """Read one interface and its static addresses from a Billie Netplan file."""
    interface_match = re.search(r"^\s{4}([A-Za-z0-9_.-]{1,15}):\s*$", config, re.MULTILINE)
    if not interface_match:
        return None
    interface = interface_match.group(1)
    addresses: list[ipaddress.IPv4Interface] = []
    for value in re.findall(r"^\s{8}-\s+((?:\d{1,3}\.){3}\d{1,3}/(?:[0-9]|[12]\d|3[0-2]))\s*$", config, re.MULTILINE):
        try:
            address = ipaddress.ip_interface(value)
        except ValueError:
            continue
        if address.version == 4:
            addresses.append(address)
    return interface, addresses


def remove_listener_firewall(firewall: object) -> None:
    if not isinstance(firewall, dict) or not isinstance(firewall.get("rules"), list):
        return
    if shutil.which("ufw") is None:
        return
    for rule in reversed(firewall["rules"]):
        if not isinstance(rule, dict) or rule.get("kind") not in {"allow", "route"}:
            continue
        args = rule.get("args")
        if not isinstance(args, list) or not all(isinstance(value, str) for value in args):
            continue
        command = ["ufw"]
        command.extend(["route", "delete"] if rule["kind"] == "route" else ["delete"])
        command.extend(args)
        run(command)



def _rule_option(arguments: list[str], option: str) -> str | None:
    try:
        return arguments[arguments.index(option) + 1]
    except (ValueError, IndexError):
        return None


def _matches_netavark_dnat(
    chain: str, arguments: list[str], bind_address: str, host_port: int, transport: str
) -> bool:
    destination = _rule_option(arguments, "-d")
    return (
        chain.startswith("NETAVARK-DN-")
        and _rule_option(arguments, "-j") == "DNAT"
        and _rule_option(arguments, "-p") == transport
        and _rule_option(arguments, "--dport") == str(host_port)
        and destination in {bind_address, f"{bind_address}/32"}
    )


def _matches_netavark_dispatch(arguments: list[str], host_port: int, transport: str) -> bool:
    target = _rule_option(arguments, "-j") or ""
    return (
        _rule_option(arguments, "-p") == transport
        and _rule_option(arguments, "--dport") == str(host_port)
        and target.startswith("NETAVARK-DN-")
    )


def _netavark_nat_rules(iptables: str) -> list[tuple[str, list[str]]] | None:
    result = run([iptables, "-t", "nat", "-S"], check=False)
    if result.returncode:
        return None
    rules: list[tuple[str, list[str]]] = []
    for line in result.stdout.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) >= 3 and parts[0] == "-A":
            rules.append((parts[1], parts[2:]))
    return rules


def _netavark_declared_chains(iptables: str) -> list[str] | None:
    result = run([iptables, "-t", "nat", "-S"], check=False)
    if result.returncode:
        return None
    chains: list[str] = []
    for line in result.stdout.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) == 2 and parts[0] == "-N" and parts[1].startswith("NETAVARK-DN-"):
            chains.append(parts[1])
    return chains


def _podman_container_ips(podman: str | None) -> set[str] | None:
    """Return IPv4 addresses for all Podman containers, including stopped ones."""
    if not podman:
        return set()
    result = run([podman, "ps", "--all", "--quiet"], check=False)
    if result.returncode:
        return None
    addresses: set[str] = set()
    for container_id in result.stdout.splitlines():
        inspected = run([podman, "inspect", container_id], check=False)
        if inspected.returncode:
            return None
        try:
            entries = json.loads(inspected.stdout)
            networks = entries[0].get("NetworkSettings", {}).get("Networks") or {}
            for network in networks.values():
                address = network.get("IPAddress")
                if address:
                    addresses.add(str(ipaddress.IPv4Address(address)))
        except (IndexError, KeyError, TypeError, ValueError, AttributeError):
            return None
    return addresses

def _netavark_target_ip(arguments: list[str]) -> str | None:
    target = _rule_option(arguments, "--to-destination")
    if not target:
        return None
    address = target.split(",", 1)[0].rsplit(":", 1)[0]
    try:
        return str(ipaddress.IPv4Address(address))
    except ipaddress.AddressValueError:
        return None


def _parse_quadlet_publish_port(value: str) -> tuple[str, int, str] | None:
    match = re.fullmatch(
        r"(?P<address>(?:[0-9]{1,3}\.){3}[0-9]{1,3}):(?P<host>[0-9]{1,5}):[0-9]{1,5}(?:/(?P<transport>tcp|udp))?",
        value.strip(),
    )
    if not match:
        return None
    try:
        address = str(ipaddress.IPv4Address(match.group("address")))
        port = int(match.group("host"))
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    return address, port, match.group("transport") or "tcp"


def remove_stale_netavark_forwards(
    bindings: set[tuple[str, int, str]], podman: str | None, *, all_orphaned: bool = True
) -> list[str]:
    """Remove orphaned Netavark forwards, preserving rules for any existing Podman container."""
    iptables = shutil.which("iptables")
    if not iptables:
        return ["iptables is unavailable; could not verify Netavark port forwards"]
    container_ips = _podman_container_ips(podman)
    if container_ips is None:
        return ["could not inspect Podman containers; Netavark port forwards were not changed"]
    rules = _netavark_nat_rules(iptables)
    if rules is None:
        return ["could not read the NAT table; Netavark port forwards were not changed"]

    removed = 0
    failures: list[str] = []
    affected_chains: set[str] = set()
    # Netavark rules can outlive the container and even Billie listener metadata.
    # Sweep only DNAT entries whose destination is not assigned to any Podman container.
    for chain, arguments in list(rules):
        if not chain.startswith("NETAVARK-DN-") or _rule_option(arguments, "-j") != "DNAT":
            continue
        target_ip = _netavark_target_ip(arguments)
        destination = _rule_option(arguments, "-d") or ""
        transport = _rule_option(arguments, "-p") or ""
        try:
            bind_address = str(ipaddress.IPv4Address(destination.split("/", 1)[0]))
            host_port = int(_rule_option(arguments, "--dport") or "0")
        except ValueError:
            failures.append(f"unreadable Netavark DNAT rule in {chain}")
            continue
        if target_ip is None:
            failures.append(f"unreadable Netavark DNAT target for {bind_address}:{host_port}/{transport}")
            continue
        if not all_orphaned and (bind_address, host_port, transport) not in bindings:
            continue
        if target_ip in container_ips:
            continue

        result = run([iptables, "-t", "nat", "-D", chain, *arguments], check=False)
        if result.returncode:
            failures.append(f"could not remove stale Netavark rule for {bind_address}:{host_port}/{transport}")
            continue
        affected_chains.add(chain)
        removed += 1
        # Netavark creates per-port SETMARK companions in the same chain.
        rules = _netavark_nat_rules(iptables) or []
        for related_chain, related in list(rules):
            related_target = _rule_option(related, "-j") or ""
            related_destination = _rule_option(related, "-d") or ""
            if (
                related_chain == chain
                and related_target == "NETAVARK-HOSTPORT-SETMARK"
                and _rule_option(related, "-p") == transport
                and _rule_option(related, "--dport") == str(host_port)
                and related_destination in {bind_address, f"{bind_address}/32"}
            ):
                result = run([iptables, "-t", "nat", "-D", related_chain, *related], check=False)
                if result.returncode:
                    failures.append(f"could not remove stale Netavark mark rule for {bind_address}:{host_port}/{transport}")
                else:
                    removed += 1

    rules = _netavark_nat_rules(iptables)
    if rules is None:
        return failures + ["could not verify the NAT table after Netavark cleanup"]

    # The root dispatcher is shared. Remove only a jump with no remaining DNAT for its port.
    ports = {(port, transport) for _address, port, transport in bindings}
    if all_orphaned:
        ports.update(
            (int(port), transport)
            for chain, arguments in rules
            if chain == "NETAVARK-HOSTPORT-DNAT"
            and (port := _rule_option(arguments, "--dport")) is not None
            and port.isdigit()
            and (transport := _rule_option(arguments, "-p")) in {"tcp", "udp"}
        )
    for host_port, transport in sorted(ports):
        has_dnat = any(
            chain.startswith("NETAVARK-DN-")
            and _rule_option(arguments, "-j") == "DNAT"
            and _rule_option(arguments, "-p") == transport
            and _rule_option(arguments, "--dport") == str(host_port)
            for chain, arguments in rules
        )
        if has_dnat:
            continue
        for chain, arguments in list(rules):
            if chain != "NETAVARK-HOSTPORT-DNAT" or not _matches_netavark_dispatch(arguments, host_port, transport):
                continue
            result = run([iptables, "-t", "nat", "-D", chain, *arguments], check=False)
            if result.returncode:
                failures.append(f"could not remove orphaned Netavark dispatch for port {host_port}/{transport}")
            else:
                removed += 1
        rules = _netavark_nat_rules(iptables) or []

    declared_chains = _netavark_declared_chains(iptables)
    if declared_chains is None:
        failures.append("could not verify Netavark chains after cleanup")
    else:
        for chain in declared_chains:
            if not all_orphaned and chain not in affected_chains:
                continue
            has_rules = any(rule_chain == chain for rule_chain, _arguments in rules)
            is_referenced = any(_rule_option(arguments, "-j") == chain for _rule_chain, arguments in rules)
            if has_rules or is_referenced:
                continue
            result = run([iptables, "-t", "nat", "-X", chain], check=False)
            if result.returncode:
                failures.append(f"could not remove empty Netavark chain {chain}")
            else:
                removed += 1
        rules = _netavark_nat_rules(iptables) or []
        remaining_chains = _netavark_declared_chains(iptables)
        if remaining_chains is None:
            failures.append("could not verify Netavark chains after removing empty chains")
        elif any(chain in remaining_chains for chain in declared_chains if chain not in {rule_chain for rule_chain, _args in rules}):
            failures.append("an empty Netavark DNAT chain remains")

    for chain, arguments in rules:
        scoped_binding = (
            _rule_option(arguments, "-d") or ""
        ).split("/", 1)[0]
        scoped_port = _rule_option(arguments, "--dport")
        scoped_transport = _rule_option(arguments, "-p")
        scoped_bindings = {(address, str(port), transport) for address, port, transport in bindings}
        in_scope = all_orphaned or (scoped_binding, scoped_port or "", scoped_transport or "") in scoped_bindings
        if in_scope and chain.startswith("NETAVARK-DN-") and _rule_option(arguments, "-j") == "DNAT":
            target_ip = _netavark_target_ip(arguments)
            if target_ip is None or target_ip not in container_ips:
                failures.append("a stale Netavark DNAT rule remains")
    for host_port, transport in sorted(ports):
        has_dnat = any(
            chain.startswith("NETAVARK-DN-")
            and _rule_option(arguments, "-j") == "DNAT"
            and _rule_option(arguments, "-p") == transport
            and _rule_option(arguments, "--dport") == str(host_port)
            for chain, arguments in rules
        )
        if not has_dnat and any(
            chain == "NETAVARK-HOSTPORT-DNAT" and _matches_netavark_dispatch(arguments, host_port, transport)
            for chain, arguments in rules
        ):
            failures.append(f"orphaned Netavark dispatch remains for port {host_port}/{transport}")
    if removed:
        print(f"Removed {removed} stale Netavark port-forward rule(s).")
    return sorted(set(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove Billie-managed runtime and configuration while retaining NetBird")
    parser.add_argument("--etc-dir", type=Path, default=Path("/etc/billie"))
    parser.add_argument("--runtime-dir", type=Path, default=Path("/run/billie"))
    parser.add_argument("--instance-prefix", default="billie")
    parser.add_argument("--preserve-credentials", action="store_true", help="keep node identity and fabric TLS credentials")
    parser.add_argument("--yes", action="store_true", help="skip the general confirmation prompt; credential purge still asks")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run with sudo")
    prefix = args.instance_prefix
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", prefix):
        parser.error("invalid Billie instance prefix")

    unit_result = run(["systemctl", "list-unit-files", "--no-legend", "--no-pager"], check=False)
    units: set[str] = set()
    for line in unit_result.stdout.splitlines():
        fields = line.split()
        if fields and (fields[0].startswith(f"{prefix}-") or fields[0].startswith("billie-kid-")) and fields[0].endswith((".service", ".timer", ".socket", ".target")):
            units.add(fields[0])
    for path in Path("/etc/systemd/system").glob("billie-kid-*.service"):
        units.add(path.name)
    for suffix in ("service", "timer", "socket", "target"):
        for path in Path("/etc/systemd/system").glob(f"{prefix}-*.{suffix}"):
            units.add(path.name)

    quadlet_dir = Path("/etc/containers/systemd")
    quadlets = sorted(quadlet_dir.glob(f"{prefix}-*.container"))
    images: set[str] = set()
    managed_listener_bindings: set[tuple[str, int, str]] = set()
    for path in quadlets:
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("Image="):
                    images.add(line.partition("=")[2].strip())
                elif line.startswith("PublishPort="):
                    binding = _parse_quadlet_publish_port(line.partition("=")[2])
                    if binding:
                        managed_listener_bindings.add(binding)
        except OSError:
            pass

    kid_root = Path("/opt/billie/kids")
    installed = []
    for metadata_path in kid_root.glob("*/*/bundle.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            installed.append(f"{metadata.get('id', metadata_path.parent.parent.name)}@{metadata.get('version', metadata_path.parent.name)}")
            image_id = metadata.get("imageId")
            if isinstance(image_id, str) and re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
                images.add(image_id)
        except (OSError, ValueError):
            installed.append(f"{metadata_path.parent.parent.name}@{metadata_path.parent.name} (metadata unreadable)")

    netplan_dir = Path("/etc/netplan")
    sensor_configs = sorted(netplan_dir.glob("99-billie-sensor-*.yaml")) + sorted(netplan_dir.glob("99-billie-sensor-*.yml"))
    legacy_billie_network = netplan_dir / "01-billie-network.yaml"
    if legacy_billie_network.is_file():
        sensor_configs.append(legacy_billie_network)
    managed_firewalls = []
    for listener_path in sorted((args.etc_dir / "kids").glob("*/listener.json")):
        try:
            listener = json.loads(listener_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(listener, dict):
            try:
                address = str(ipaddress.IPv4Address(listener.get("hostAddress", "")))
                host_port = listener.get("hostPort")
                transport = str(listener.get("transport", "")).lower()
                if type(host_port) is int and 1 <= host_port <= 65535 and transport in {"tcp", "udp"}:
                    managed_listener_bindings.add((address, host_port, transport))
            except (ipaddress.AddressValueError, TypeError):
                pass
        firewall = listener.get("firewall") if isinstance(listener, dict) else None
        if isinstance(firewall, dict) and firewall.get("rules"):
            managed_firewalls.append((listener_path, firewall))
    print("Billie teardown will remove:")
    print("  systemd units: " + (", ".join(sorted(units)) if units else "none found"))
    print("  installed kids: " + (", ".join(sorted(installed)) if installed else "none found"))
    print("  Billie Quadlet definitions: " + (", ".join(path.name for path in quadlets) if quadlets else "none found"))
    print("  Billie sensor Netplan files: " + (", ".join(path.name for path in sensor_configs) if sensor_configs else "none found"))
    print(f"  Billie-managed UFW listener rules: {sum(len(item[1].get('rules', [])) for item in managed_firewalls)}")
    print(f"  {args.etc_dir}, /opt/billie, /var/lib/{prefix}, {args.runtime_dir}, Billie helper scripts, and the billie-platform package")
    print("  Billie kid and Zenoh image references when they are not in use by another container")
    print("NetBird's service, enrollment, configuration, APT source, and package will be left untouched.")
    if args.preserve_credentials:
        print(f"Node identity and fabric TLS credentials under {args.etc_dir} will be preserved.")
    else:
        print(f"Node identity and fabric TLS credentials under {args.etc_dir} will be deleted after a second confirmation.")
    confirm("This operation removes the Billie runtime from this node.", "TEARDOWN BILLIE", args.yes)
    if not args.preserve_credentials:
        confirm("This permanently deletes Billie identity and fabric credentials.", "DELETE BILLIE CREDENTIALS")

    for _listener_path, firewall in managed_firewalls:
        remove_listener_firewall(firewall)

    for unit in sorted(units):
        run(["systemctl", "disable", "--now", unit], check=False)
    container_names: set[str] = set()
    podman = shutil.which("podman")
    if podman:
        result = run([podman, "ps", "--all", "--format", "{{.Names}}"], check=False)
        for name in result.stdout.splitlines():
            if name.startswith("billie-kid-") or name in {f"{prefix}-zenohd", f"{prefix}-fabric-client"}:
                container_names.add(name)
        for name in sorted(container_names):
            run([podman, "rm", "--force", name], check=False)

    # Only remove forwards for listeners Billie recorded. A full orphan sweep
    # can delete networking owned by another Podman workload.
    netavark_cleanup_residuals = remove_stale_netavark_forwards(
        managed_listener_bindings, podman, all_orphaned=False
    )

    systemd_dir = Path("/etc/systemd/system")
    for path in systemd_dir.glob("billie-kid-*.service"):
        path.unlink(missing_ok=True)
    for suffix in ("service", "timer", "socket", "target"):
        for path in systemd_dir.glob(f"{prefix}-*.{suffix}"):
            path.unlink(missing_ok=True)
    for wants_dir in Path("/etc/systemd/system").glob("*.wants"):
        if wants_dir.is_dir():
            for path in wants_dir.iterdir():
                if path.name in units and path.is_symlink():
                    path.unlink(missing_ok=True)
    for path in quadlets:
        path.unlink(missing_ok=True)
    run(["systemctl", "daemon-reload"], check=False)
    for unit in sorted(units):
        run(["systemctl", "reset-failed", unit], check=False)

    # Remove only network snippets explicitly created by billie network configure.
    # Do not run `netplan apply`: it reapplies every interface and can renew the
    # management DHCP lease, severing the SSH session during teardown.
    managed_sensor_configs: list[tuple[str, list[ipaddress.IPv4Interface]]] = []
    for path in sensor_configs:
        try:
            config = path.read_text(encoding="utf-8")
        except OSError:
            config = ""
        managed = managed_sensor_addresses(config)
        if managed is not None:
            managed_sensor_configs.append(managed)
        path.unlink(missing_ok=True)
    if sensor_configs and shutil.which("netplan"):
        generated = run(["netplan", "generate"], check=False)
        if generated.returncode:
            detail = (generated.stderr or generated.stdout or "").strip()
            print(f"billie teardown: removed its Netplan snippets, but generation reported an error: {detail}", file=sys.stderr)
    for interface, addresses in managed_sensor_configs:
        if not Path("/sys/class/net", interface).exists():
            continue
        for address in addresses:
            run(["ip", "address", "del", str(address), "dev", interface], check=False)

    shutil.rmtree(args.etc_dir / "kids", ignore_errors=True)
    shutil.rmtree(kid_root, ignore_errors=True)
    shutil.rmtree(Path("/var/lib") / prefix, ignore_errors=True)
    shutil.rmtree(args.runtime_dir, ignore_errors=True)
    if args.preserve_credentials:
        for path in args.etc_dir.iterdir() if args.etc_dir.is_dir() else ():
            if path.name == "identity":
                continue
            if path.name == "zenoh" and (path / "tls").is_dir():
                for child in path.iterdir():
                    if child.name != "tls":
                        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink(missing_ok=True)
                continue
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink(missing_ok=True)
    else:
        shutil.rmtree(args.etc_dir, ignore_errors=True)

    # Remove only the service accounts this platform marks with its own GECOS tag.
    passwd = run(["getent", "passwd"], check=False)
    for line in passwd.stdout.splitlines():
        fields = line.split(":")
        if len(fields) > 4 and fields[4].startswith("Open Billie kid "):
            run(["userdel", fields[0]], check=False)
    run(["groupdel", "billie-kids"], check=False)

    # Purge the Billie package but do not autoremove shared prerequisites.
    package_purge = run(["apt-get", "purge", "-y", "billie-platform"], check=False)
    for path in (Path("/usr/local/bin/billie"),):
        remove_symlink_if_billie(path)
    for path in (Path("/usr/local/libexec") / f"{prefix}-island-bridge.py", Path("/usr/local/libexec") / f"{prefix}-health"):
        path.unlink(missing_ok=True)
    shutil.rmtree(Path("/opt/billie"), ignore_errors=True)

    remaining_images = []
    if podman:
        for image in sorted(images):
            result = run([podman, "rmi", image], check=False)
            if result.returncode:
                remaining_images.append(image)
    residuals = list(netavark_cleanup_residuals)
    if package_purge.returncode:
        detail = (package_purge.stderr or package_purge.stdout or "").strip()
        print(f"billie teardown: package purge failed: {detail or package_purge.returncode}", file=sys.stderr)
        residuals.append("billie-platform package purge failed")
    for path in (Path("/opt/billie"), Path("/var/lib") / prefix, args.runtime_dir, Path("/usr/local/bin/billie"), Path("/usr/local/libexec") / f"{prefix}-island-bridge.py", Path("/usr/local/libexec") / f"{prefix}-health"):
        if path.exists() or path.is_symlink():
            residuals.append(str(path))
    for wants_dir in Path("/etc/systemd/system").glob("*.wants"):
        if wants_dir.is_dir():
            for path in wants_dir.iterdir():
                if path.name in units and path.is_symlink():
                    residuals.append(str(path))
    if not args.preserve_credentials and args.etc_dir.exists():
        residuals.append(str(args.etc_dir))
    residuals.extend(str(path) for path in Path("/etc/netplan").glob("99-billie-sensor-*.yaml"))
    residuals.extend(str(path) for path in Path("/etc/netplan").glob("99-billie-sensor-*.yml"))
    residuals.extend(str(path) for path in Path("/etc/systemd/system").glob("billie-kid-*.service"))
    residuals.extend(str(path) for path in Path("/etc/systemd/system").glob(f"{prefix}-*.service"))
    residuals.extend(str(path) for path in Path("/etc/systemd/system").glob(f"{prefix}-*.timer"))
    residuals.extend(str(path) for path in Path("/etc/systemd/system").glob(f"{prefix}-*.socket"))
    residuals.extend(str(path) for path in Path("/etc/systemd/system").glob(f"{prefix}-*.target"))
    residuals.extend(str(path) for path in Path("/etc/containers/systemd").glob(f"{prefix}-*.container"))
    if run(["getent", "group", "billie-kids"], check=False).returncode == 0:
        residuals.append("system group billie-kids")
    for line in run(["getent", "passwd"], check=False).stdout.splitlines():
        fields = line.split(":")
        if len(fields) > 4 and fields[4].startswith("Open Billie kid "):
            residuals.append(f"kid service account {fields[0]}")
    if podman:
        remaining = run([podman, "ps", "--all", "--format", "{{.Names}}"], check=False)
        for name in remaining.stdout.splitlines():
            if name.startswith("billie-kid-") or name in {f"{prefix}-zenohd", f"{prefix}-fabric-client"}:
                residuals.append(f"Podman container {name}")
    if residuals:
        print("Billie teardown: some managed artifacts remain:", file=sys.stderr)
        for item in sorted(set(residuals)):
            print(f"  {item}", file=sys.stderr)
        return 1
    print("Post-teardown check: no Billie-managed services, files, containers, sensor Netplan snippets, or stale listener port forwards remain.")
    print("Billie-managed services, configuration, packages, and node address snippets have been removed.")
    if args.preserve_credentials:
        print(f"Preserved identity and fabric TLS credentials under {args.etc_dir}.")
    else:
        print("Removed Billie identity and fabric TLS credentials.")
    if remaining_images:
        print("Image references still in use by other containers were retained: " + ", ".join(remaining_images))
    print("NetBird was not modified. Shared prerequisites and unrelated container images were retained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
