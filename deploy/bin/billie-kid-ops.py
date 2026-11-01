#!/usr/bin/env python3
"""Install and operate unsigned Open Billie kid transfer bundles on a node."""

from __future__ import annotations

import argparse
try:
    import fcntl
except ImportError:  # Windows-only development checks do not manage node state.
    fcntl = None
import ipaddress
import importlib.util
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import NoReturn

try:
    import grp
    import pwd
except ImportError:  # These APIs are used only by the Linux node runtime.
    grp = None
    pwd = None

try:
    import yaml
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - depends on node package setup
    print(
        f"billie kid: missing Python dependency: {exc.name}; "
        "install the Open Billie platform prerequisites",
        file=sys.stderr,
    )
    raise SystemExit(2)


EXPECTED_FILES = {"billie-kid.yaml", "bundle.json", "image.oci.tar", "SHA256SUMS"}
MAX_METADATA_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024 * 1024
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
IMAGE_ID_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
BUILTIN_ENV = {
    "BILLIE_TRANSLATOR_SOCKET",
    "BILLIE_INPUT_PORT",
    "BILLIE_INPUT_BIND",
    "BILLIE_INPUT_TRANSPORT",
    "BILLIE_INPUT_LISTENER",
}
SUPPORTED_OUTPUT_FORMATS = {"cot", "asterix-cat062", "sapient"}
KID_GROUP = "billie-kids"
KID_REGISTRY = Path("/etc/billie/translator/kids.json")


def fail(message: str, code: int = 2) -> "NoReturn":
    print(f"billie kid: {message}", file=sys.stderr)
    raise SystemExit(code)


def run(command: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError:
        fail(f"required command not found: {command[0]}")
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        fail(f"command failed ({' '.join(command)}): {detail or result.returncode}")
    return result


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_platform() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine)
    return f"linux/{arch}" if arch else "unknown"


def bundle_member(bundle: tarfile.TarFile, name: str, limit: int) -> bytes:
    member = bundle.getmember(name)
    if not member.isfile() or member.size > limit:
        fail(f"bundle entry is not a regular file or exceeds its size limit: {name}", 1)
    stream = bundle.extractfile(member)
    if stream is None:
        fail(f"cannot read bundle entry: {name}", 1)
    return stream.read()


def parse_checksums(text: str, files: dict[str, bytes | Path]) -> None:
    expected: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match.group(2) in expected:
            fail("bundle SHA256SUMS file has invalid or duplicate entries", 1)
        expected[match.group(2)] = match.group(1)
    if set(expected) != set(files):
        fail("bundle SHA256SUMS must list exactly billie-kid.yaml, bundle.json, and image.oci.tar", 1)
    for name, data in files.items():
        digest = sha256_file(data) if isinstance(data, Path) else sha256_bytes(data)
        if digest != expected[name]:
            fail(f"bundle checksum mismatch: {name}", 1)


def verify_external_checksum(bundle_path: Path, checksum_path: Path | None) -> None:
    sidecar = checksum_path or Path(f"{bundle_path}.sha256")
    if not sidecar.is_file():
        fail(
            f"external bundle checksum not found: {sidecar}; transfer the .sha256 file produced by billie kid build",
            1,
        )
    lines = sidecar.read_text(encoding="ascii").splitlines()
    if len(lines) != 1:
        fail("external checksum file must contain one checksum line", 1)
    match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.+-]+)", lines[0])
    if not match or match.group(2) != bundle_path.name:
        fail("external checksum must name the selected bundle file", 1)
    if sha256_file(bundle_path) != match.group(1):
        fail("external bundle checksum does not match", 1)
    print(f"External checksum verified: {bundle_path.name}")


def schema_file() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "schemas" / "kid-manifest.schema.json", here.parent.parent / "schemas" / "kid-manifest.schema.json"):
        if candidate.is_file():
            return candidate
    fail("kid manifest schema is missing from this Billie installation")


def verify_manifest(manifest: object) -> dict:
    schema = json.loads(schema_file().read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        first = errors[0]
        fail(f"invalid kid manifest at {'.'.join(map(str, first.absolute_path)) or 'root'}: {first.message}", 1)
    return manifest


def verify_oci_archive(image_path: Path, expected_digest: str, expected_platform_value: str) -> None:
    try:
        with tarfile.open(image_path, "r:*") as image:
            index_bytes = image.extractfile("index.json")
            if index_bytes is None:
                fail("OCI image archive has no index.json", 1)
            index = json.load(index_bytes)
            descriptors = index.get("manifests", [])
            if len(descriptors) != 1:
                fail("OCI image archive must contain exactly one platform image", 1)
            descriptor = descriptors[0]
            digest = descriptor.get("digest", "")
            if digest != expected_digest or not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                fail("OCI manifest digest does not match bundle metadata", 1)
            blob = image.extractfile(f"blobs/sha256/{digest[7:]}")
            if blob is None:
                fail("OCI archive is missing its image manifest", 1)
            manifest_bytes = blob.read()
            if sha256_bytes(manifest_bytes) != digest[7:]:
                fail("OCI manifest content failed digest verification", 1)
            image_manifest = json.loads(manifest_bytes)
            config_digest = image_manifest.get("config", {}).get("digest", "")
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", config_digest):
                fail("OCI archive has an invalid image config digest", 1)
            platform = descriptor.get("platform", {})
            arch = platform.get("architecture")
            operating_system = platform.get("os")
            if not arch or not operating_system:
                config_blob = image.extractfile(f"blobs/sha256/{config_digest[7:]}")
                if config_blob is None:
                    fail("OCI archive is missing its image config", 1)
                config_bytes = config_blob.read()
                if sha256_bytes(config_bytes) != config_digest[7:]:
                    fail("OCI image config content failed digest verification", 1)
                image_config = json.loads(config_bytes)
                arch = arch or image_config.get("architecture", "unknown")
                operating_system = operating_system or image_config.get("os", "unknown")
            actual_platform = f"{operating_system}/{arch}"
            if actual_platform != expected_platform_value:
                fail(f"OCI image platform mismatch: metadata says {expected_platform_value}, archive is {actual_platform}", 1)
    except (OSError, tarfile.TarError, KeyError, TypeError, json.JSONDecodeError) as exc:
        fail(f"cannot inspect OCI image archive: {exc}", 1)


def unpack_bundle(bundle_path: Path, checksum_path: Path | None, temp_dir: Path) -> tuple[dict, dict, Path]:
    if not bundle_path.is_file():
        fail(f"bundle not found: {bundle_path}", 1)
    verify_external_checksum(bundle_path, checksum_path)
    try:
        with tarfile.open(bundle_path, "r:gz") as bundle:
            members = bundle.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or set(names) != EXPECTED_FILES:
                fail("bundle must contain exactly billie-kid.yaml, bundle.json, image.oci.tar, and SHA256SUMS", 1)
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in (".", ".."):
                    fail(f"unsafe bundle path: {name}", 1)
            file_bytes = {
                "billie-kid.yaml": bundle_member(bundle, "billie-kid.yaml", MAX_METADATA_BYTES),
                "bundle.json": bundle_member(bundle, "bundle.json", MAX_METADATA_BYTES),
            }
            image_member = bundle.getmember("image.oci.tar")
            if not image_member.isfile() or image_member.size > MAX_IMAGE_BYTES:
                fail("OCI image archive is not a regular file or exceeds 20 GiB", 1)
            image_path = temp_dir / "image.oci.tar"
            image_stream = bundle.extractfile(image_member)
            if image_stream is None:
                fail("cannot read OCI image archive", 1)
            with image_path.open("wb") as destination:
                shutil.copyfileobj(image_stream, destination, 1024 * 1024)
            sums = bundle_member(bundle, "SHA256SUMS", 4096).decode("ascii")
    except (OSError, tarfile.TarError, UnicodeDecodeError, KeyError) as exc:
        fail(f"cannot read kid bundle: {exc}", 1)
    parse_checksums(sums, {**file_bytes, "image.oci.tar": image_path})
    try:
        manifest = verify_manifest(yaml.safe_load(file_bytes["billie-kid.yaml"].decode("utf-8")))
        metadata = json.loads(file_bytes["bundle.json"].decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError, json.JSONDecodeError) as exc:
        fail(f"bundle metadata is invalid: {exc}", 1)

    if not isinstance(metadata, dict):
        fail("bundle.json must contain a JSON object", 1)
    kid_id = manifest["metadata"]["id"]
    version = manifest["metadata"]["version"]
    if metadata.get("schema") != "billie.kid.bundle.v1":
        fail("unsupported kid bundle schema", 1)
    if metadata.get("id") != kid_id or metadata.get("version") != version:
        fail("bundle metadata identity does not match its manifest", 1)
    if not VERSION_RE.fullmatch(version):
        fail("kid version is invalid", 1)
    image_id = metadata.get("imageId", "")
    if not IMAGE_ID_RE.fullmatch(image_id):
        fail("bundle image ID is invalid", 1)
    image_tag = f"localhost/open-billie/{kid_id}:{version.replace('+', '_build_')}"
    image = metadata.get("image", "")
    digest = metadata.get("ociManifestDigest", "")
    if image != manifest["runtime"]["image"] or image != f"localhost/open-billie/{kid_id}@{digest}":
        fail("bundle image reference does not match the manifest and package identity", 1)
    if metadata.get("imageTag") != image_tag:
        fail("bundle image tag does not match the package identity", 1)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        fail("bundle OCI digest is invalid", 1)
    if metadata.get("imageArchiveSha256") != sha256_file(image_path):
        fail("image archive checksum does not match bundle metadata", 1)
    verify_oci_archive(image_path, digest, metadata.get("platform", ""))
    current = expected_platform()
    if current != "unknown" and metadata.get("platform") != current:
        fail(f"bundle targets {metadata.get('platform')}; this node is {current}", 1)
    return manifest, metadata, image_path


def require_root() -> None:
    if os.geteuid() != 0:
        fail("run this command with sudo")


def installed_dir(kid_id: str, version: str) -> Path:
    return Path("/opt/billie/kids") / kid_id / version


def install_bundle(bundle: Path, checksum: Path | None) -> None:
    require_root()
    if shutil.which("podman") is None:
        fail("Podman is required on the node")
    with tempfile.TemporaryDirectory(prefix="billie-kid-install-") as temp_name:
        temp = Path(temp_name)
        manifest, metadata, image_archive = unpack_bundle(bundle.expanduser().resolve(), checksum, temp)
        kid_id = manifest["metadata"]["id"]
        version = manifest["metadata"]["version"]
        destination = installed_dir(kid_id, version)
        if destination.exists():
            fail(f"{kid_id}@{version} is already installed; install a new package version instead")

        print(f"Loading image {metadata['imageTag']} into Podman...")
        run(["podman", "load", "--input", str(image_archive)])
        result = run(["podman", "image", "inspect", metadata["imageTag"]], capture=True)
        try:
            image_info = json.loads(result.stdout)
            image_info = image_info[0] if isinstance(image_info, list) else image_info
        except (json.JSONDecodeError, IndexError, TypeError) as exc:
            fail(f"cannot inspect loaded kid image: {exc}")
        if not isinstance(image_info, dict):
            fail("loaded image metadata is not a JSON object")
        actual_image_id = image_info.get("Id", "")
        if isinstance(actual_image_id, str) and re.fullmatch(r"[a-f0-9]{64}", actual_image_id):
            actual_image_id = f"sha256:{actual_image_id}"
        if actual_image_id != metadata["imageId"]:
            fail("loaded image ID does not match the bundle metadata")

        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        stage = parent / f".{version}.installing-{os.getpid()}"
        stage.mkdir(mode=0o755)
        try:
            (stage / "billie-kid.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            (stage / "bundle.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
            os.chmod(stage / "billie-kid.yaml", 0o644)
            os.chmod(stage / "bundle.json", 0o644)
            stage.rename(destination)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    print(f"Installed {kid_id}@{version} at {destination}")
    print(f"Next: sudo billie kid activate {kid_id} --version {version}")


def installed_package(kid_id: str, version: str | None) -> tuple[Path, dict, dict]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", kid_id):
        fail("kid id must contain lowercase letters, digits, and hyphens")
    package_root = Path("/opt/billie/kids") / kid_id
    if not package_root.is_dir():
        fail(f"no installed package named {kid_id}", 1)
    versions = sorted(path for path in package_root.iterdir() if path.is_dir() and VERSION_RE.fullmatch(path.name))
    if version:
        versions = [path for path in versions if path.name == version]
    if not versions:
        fail(f"no installed version found for {kid_id}" + (f"@{version}" if version else ""), 1)
    if len(versions) > 1:
        fail(f"multiple versions installed for {kid_id}; select one with --version: {', '.join(p.name for p in versions)}", 1)
    root = versions[0]
    try:
        manifest = yaml.safe_load((root / "billie-kid.yaml").read_text(encoding="utf-8"))
        metadata = json.loads((root / "bundle.json").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        fail(f"installed kid metadata is unreadable: {exc}", 1)
    return root, manifest, metadata


def parse_environment(path: Path, declared: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read runtime configuration: {exc}", 1)
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            fail(f"invalid runtime config line {number}; use NAME=VALUE", 1)
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or name not in declared:
            fail(f"runtime config variable {name!r} is not declared by this kid", 1)
        if name in BUILTIN_ENV:
            fail(f"{name} is supplied by Billie and cannot be overridden", 1)
        if "\x00" in value:
            fail(f"runtime config line {number} contains a NUL byte", 1)
        values[name] = value
    return values


def assigned_ipv4_addresses() -> set[str]:
    result = run(["ip", "-o", "-4", "addr", "show"], capture=True, check=False)
    if result.returncode:
        fail("cannot inspect node IPv4 addresses; install iproute2 and retry")
    return {match.group(1) for match in re.finditer(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/", result.stdout)}


def interface_network_for_address(address: ipaddress.IPv4Address) -> tuple[str, ipaddress.IPv4Network]:
    result = run(["ip", "-o", "-4", "addr", "show"], capture=True)
    if result.returncode:
        fail("cannot inspect node IPv4 interfaces; install iproute2 and retry")
    for line in result.stdout.splitlines():
        device = re.match(r"\d+:\s+(\S+)", line)
        assigned = re.search(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/(\d+)", line)
        if device and assigned and assigned.group(1) == str(address):
            interface_address = ipaddress.ip_interface(f"{assigned.group(1)}/{assigned.group(2)}")
            return device.group(1).split("@", 1)[0], interface_address.network
    fail(f"cannot find the interface and subnet for {address}")


def remove_listener_firewall(firewall: dict | None) -> None:
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
        if rule["kind"] == "route":
            command.extend(["route", "delete"])
        else:
            command.append("delete")
        command.extend(args)
        result = run(command, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout or "unknown UFW error").strip()
            fail(f"could not remove Billie-managed firewall rule: {detail}")


def remove_existing_listener_firewall(kid_id: str) -> None:
    existing_config_path = Path("/etc/billie/kids") / kid_id / "listener.json"
    if not existing_config_path.is_file():
        return
    try:
        existing = json.loads(existing_config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"existing listener firewall configuration is unreadable: {exc}")
    firewall = existing.get("firewall")
    if (
        shutil.which("ufw") is None
        and isinstance(firewall, dict)
        and firewall.get("managed") is True
        and firewall.get("rules")
    ):
        fail("UFW-managed listener rules are recorded but UFW is not installed; reinstall UFW to remove them safely")
    remove_listener_firewall(firewall)


def configure_listener_firewall(
    kid_id: str,
    transport: str,
    bind_address: ipaddress.IPv4Address,
    host_port: int,
    source_cidr: str | None,
    container_port: int,
) -> dict:
    if shutil.which("ufw") is None:
        remove_existing_listener_firewall(kid_id)
        print("UFW is not active; no listener firewall rules were added.")
        return {"managed": False, "rules": []}
    status = run(["ufw", "status"], capture=True, check=False)
    if status.returncode:
        fail("could not inspect UFW status; refusing to configure an unmanaged listener firewall")
    if not status.stdout.strip().lower().startswith("status: active"):
        # A previous configuration may have created UFW rules before it was
        # disabled. Remove those recorded rules before overwriting the record.
        remove_existing_listener_firewall(kid_id)
        print("UFW is not active; no listener firewall rules were added.")
        return {"managed": False, "rules": []}

    sensor_interface, sensor_network = interface_network_for_address(bind_address)
    if source_cidr is None:
        if not sys.stdin.isatty():
            fail(f"UFW is active; rerun with --source-cidr using the sensor source address/network as observed on {sensor_interface} (suggested subnet: {sensor_network})")
        print(f"Use the source address/network as observed on {sensor_interface}; NAT or a simulator can change it. Interface subnet: {sensor_network}")
        answer = input("Allowed sensor source IPv4/CIDR (for one sender, use /32): ").strip()
        if not answer:
            fail("sensor source CIDR is required when UFW is active")
        source_cidr = answer
    try:
        source_network = ipaddress.ip_network(source_cidr, strict=False)
    except ValueError:
        fail("--source-cidr must be an IPv4 network in CIDR notation")
    if source_network.version != 4:
        fail("--source-cidr must be an IPv4 network in CIDR notation")

    inspected = json.loads(run(["podman", "network", "inspect", "podman"], capture=True).stdout)
    if not isinstance(inspected, list) or not inspected or not isinstance(inspected[0], dict):
        fail("cannot identify the Podman bridge network for UFW forwarding")
    network = inspected[0]
    subnets = network.get("subnets", [])
    if not isinstance(subnets, list) or not subnets or not isinstance(subnets[0], dict):
        fail("Podman default network has no inspectable IPv4 subnet")
    try:
        podman_subnet = ipaddress.ip_network(subnets[0]["subnet"], strict=False)
    except (KeyError, ValueError, TypeError):
        fail("Podman default network has an invalid IPv4 subnet")
    if podman_subnet.version != 4:
        fail("Podman default network must provide an IPv4 subnet for this listener")
    bridge = network.get("network_interface") or network.get("networkInterface") or "podman0"
    if not isinstance(bridge, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", bridge):
        fail("Podman default network has an invalid bridge interface name")

    comment = f"open-billie-kid-{kid_id}"
    protocol = transport.lower()
    inbound_args = [
        "allow", "in", "on", sensor_interface, "from", str(source_network),
        "to", str(bind_address), "port", str(host_port), "proto", protocol, "comment", comment,
    ]
    route_args = [
        "allow", "in", "on", sensor_interface, "out", "on", bridge,
        "from", str(source_network), "to", str(podman_subnet),
        "port", str(container_port), "proto", protocol, "comment", comment,
    ]
    remove_existing_listener_firewall(kid_id)

    rules = [{"kind": "allow", "args": inbound_args}, {"kind": "route", "args": route_args}]
    applied: list[dict] = []
    try:
        for rule in rules:
            command = ["ufw"]
            if rule["kind"] == "route":
                command.append("route")
            command.extend(rule["args"])
            run(command)
            applied.append(rule)
    except SystemExit:
        remove_listener_firewall({"rules": applied})
        raise
    print(f"UFW now permits {source_network} on {sensor_interface} to reach {bind_address}:{host_port}/{protocol}.")
    return {"managed": True, "sourceCidr": str(source_network), "sensorInterface": sensor_interface,
            "podmanSubnet": str(podman_subnet), "podmanBridge": bridge, "rules": rules}


def remove_stale_container(kid_id: str) -> None:
    run(["podman", "rm", "--force", "--ignore", f"billie-kid-{kid_id}"], check=False)


def cleanup_orphaned_port_forwards(bind_address: str, host_port: int, transport: str) -> list[str]:
    """Remove orphaned Netavark forwards for this kid listener only."""
    helper = Path(__file__).with_name("billie-teardown.py")
    spec = importlib.util.spec_from_file_location("billie_teardown_cleanup", helper)
    if spec is None or spec.loader is None:
        fail("cannot load Netavark cleanup helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    binding = {(bind_address, host_port, transport)}
    errors = module.remove_stale_netavark_forwards(binding, shutil.which("podman"), all_orphaned=False)
    if errors:
        print("WARNING: could not clean orphaned Podman port forwards: " + "; ".join(errors), file=sys.stderr)
    return errors


def netavark_listener_forward_present(
    rules_output: str, bind_address: str, host_port: int, transport: str, container_ip: str, container_port: int
) -> bool:
    """Check for an exact active Podman DNAT rule (Netavark or CNI)."""
    for line in rules_output.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 3 or parts[0] != "-A" or not parts[1].startswith(("NETAVARK-DN-", "CNI-DN-")):
            continue
        arguments = parts[2:]

        def option(name: str) -> str | None:
            try:
                return arguments[arguments.index(name) + 1]
            except (ValueError, IndexError):
                return None

        if (
            option("-j") == "DNAT"
            and option("-d") in {bind_address, f"{bind_address}/32"}
            and option("-p") == transport
            and option("--dport") == str(host_port)
            and option("--to-destination") == f"{container_ip}:{container_port}"
        ):
            return True
    return False


def verify_listener_port_forward(
    container_name: str, bind_address: str, host_port: int, transport: str, container_port: int, unit_name: str
) -> None:
    """Wait for and verify that Podman installed the active host-to-container forward."""
    iptables = shutil.which("iptables")
    last_error = ""
    for _attempt in range(20):
        inspected = run(["podman", "inspect", container_name], capture=True, check=False)
        if inspected.returncode == 0:
            try:
                entries = json.loads(inspected.stdout)
                networks = entries[0].get("NetworkSettings", {}).get("Networks") or {}
                addresses = {
                    str(ipaddress.IPv4Address(item["IPAddress"]))
                    for item in networks.values()
                    if isinstance(item, dict) and item.get("IPAddress")
                }
            except (IndexError, KeyError, TypeError, ValueError, AttributeError, json.JSONDecodeError):
                addresses = set()
        else:
            addresses = set()

        if iptables:
            nat = run([iptables, "-t", "nat", "-S"], capture=True, check=False)
            if nat.returncode == 0 and any(
                netavark_listener_forward_present(nat.stdout, bind_address, host_port, transport, address, container_port)
                for address in addresses
            ):
                return
            last_error = nat.stderr.strip() if nat.returncode else ""
        else:
            published = run(["podman", "port", container_name, f"{container_port}/{transport}"], capture=True, check=False)
            if published.returncode == 0 and f"{bind_address}:{host_port}" in published.stdout:
                return
            last_error = "iptables is unavailable; only Podman-reported port configuration could be checked"
        time.sleep(0.25)

    detail = f": {last_error}" if last_error else ""
    if iptables:
        fail(
            f"{unit_name} started, but no active Podman DNAT rule forwards {bind_address}:{host_port}/{transport} "
            f"to the kid container on port {container_port}; inspect Podman networking and retry activation{detail}"
        )
    fail(
        f"{unit_name} started, but Podman does not report the expected {bind_address}:{host_port} "
        f"listener mapping; inspect Podman networking and retry activation{detail}"
    )



def start_kid_service_with_verified_forward(
    unit_name: str,
    container_name: str,
    bind_address: str,
    host_port: int,
    transport: str,
    container_port: int,
    *,
    restart: bool = False,
) -> None:
    """Clean stale port rules before startup, then verify the new container forward."""
    cleanup_errors = cleanup_orphaned_port_forwards(bind_address, host_port, transport)
    if cleanup_errors and shutil.which("iptables"):
        fail("cannot safely activate kid while stale Podman port forwards remain: " + "; ".join(cleanup_errors))
    run(["systemctl", "restart" if restart else "start", unit_name])
    verify_listener_port_forward(
        container_name, bind_address, host_port, transport, container_port, unit_name
    )

def render_kid_systemd_unit(kid_id: str, version: str, runtime_socket: Path, runner: Path,
                            container_name: str, instance_prefix: str) -> str:
    return f"""[Unit]
Description=Open Billie kid {kid_id} {version}
StartLimitIntervalSec=60
StartLimitBurst=3
After={instance_prefix}-translator.service {instance_prefix}-zenohd.service
Requires={instance_prefix}-translator.service
Wants={instance_prefix}-zenohd.service
PartOf={instance_prefix}-translator.service

[Service]
Type=simple
ExecStartPre=/usr/bin/test -S {runtime_socket}
ExecStart=/usr/bin/bash {runner}
ExecStop=/usr/bin/podman stop --time 20 --ignore {container_name}
ExecStopPost=/usr/bin/podman rm --force --ignore {container_name}
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
NoNewPrivileges=true
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""


def unsupported_output_formats(outputs: list[dict]) -> list[str]:
    return sorted({item["format"] for item in outputs} - SUPPORTED_OUTPUT_FORMATS)


def ensure_kid_identity(kid_id: str) -> tuple[int, int]:
    """Create a stable, unprivileged host UID used to authenticate translator IPC."""
    run(["groupadd", "--system", "--force", KID_GROUP])
    group = grp.getgrnam(KID_GROUP)
    username = kid_service_username(kid_id)
    try:
        account = pwd.getpwnam(username)
    except KeyError:
        run([
            "useradd", "--system", "--no-create-home", "--home-dir", "/nonexistent",
            "--shell", "/usr/sbin/nologin", "--gid", KID_GROUP,
            "--comment", f"Open Billie kid {kid_id}", username,
        ])
        account = pwd.getpwnam(username)
    if (
        account.pw_gid != group.gr_gid
        or account.pw_uid < 100
        or account.pw_gecos != f"Open Billie kid {kid_id}"
    ):
        fail(f"kid runtime account {username} has an unsafe UID or group")
    return account.pw_uid, group.gr_gid


def kid_service_username(kid_id: str) -> str:
    return "bk-" + hashlib.sha256(kid_id.encode("utf-8")).hexdigest()[:12]


def update_translator_registry(
    kid_id: str, policy: dict | None, registry_path: Path = KID_REGISTRY
) -> None:
    """Atomically update the root-owned output allowlist read for every IPC request."""
    registry_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = registry_path.with_name(registry_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            if registry.get("schema") != "billie.translator.registry.v1" or not isinstance(registry.get("kids"), dict):
                fail("translator kid authorization registry has an unsupported schema")
        except FileNotFoundError:
            registry = {"schema": "billie.translator.registry.v1", "kids": {}}
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"translator kid authorization registry is unreadable: {exc}")
        if policy is None:
            registry["kids"].pop(kid_id, None)
        else:
            registry["kids"][kid_id] = policy
        staged = registry_path.with_name(f".{registry_path.name}.{os.getpid()}.tmp")
        try:
            staged.write_text(json.dumps(registry, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            os.chmod(staged, 0o600)
            staged.replace(registry_path)
        except OSError as exc:
            staged.unlink(missing_ok=True)
            fail(f"cannot update translator kid authorization registry: {exc}")


def configure_listener(kid_id: str, transport: str, bind_address: str, host_port: int, listener_name: str | None, version: str | None, source_cidr: str | None) -> None:
    require_root()
    package, manifest, _ = installed_package(kid_id, version)
    inputs = manifest["interfaces"]["inputs"]
    candidates = [item for item in inputs if item["transport"] == transport]
    if listener_name:
        candidates = [item for item in candidates if item["name"] == listener_name]
    if not candidates:
        available = ", ".join(f"{item['name']}={item['transport']}:{item['port']}" for item in inputs)
        fail(f"kid {kid_id} does not declare a matching {transport} listener; declared listeners: {available}")
    if len(candidates) > 1:
        fail(f"more than one {transport} listener is declared; select one with --listener")
    try:
        address = ipaddress.ip_address(bind_address)
    except ValueError:
        fail("--bind-address must be a valid IP address")
    if address.version != 4:
        fail("--bind-address currently supports IPv4 addresses only")
    if str(address) not in assigned_ipv4_addresses():
        fail(f"bind address {address} is not assigned to this node; configure the node interface first")
    if not 1 <= host_port <= 65535:
        fail("host port must be an integer from 1 through 65535")
    unit_name = f"billie-kid-{kid_id}.service"
    if run(["systemctl", "is-active", "--quiet", unit_name], check=False).returncode == 0:
        fail(f"{kid_id} is active; deactivate it before changing listener settings")
    chosen = candidates[0]
    firewall = configure_listener_firewall(kid_id, transport, address, host_port, source_cidr, chosen["port"])
    config_dir = Path("/etc/billie/kids") / kid_id
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config_dir, 0o700)
    config = {
        "schema": "billie.kid.listener.v2",
        "name": chosen["name"],
        "hostAddress": str(address),
        "transport": chosen["transport"],
        "containerPort": chosen["port"],
        "hostPort": host_port,
        "firewall": firewall,
    }
    destination = config_dir / "listener.json"
    staged = config_dir / f".listener.json.{os.getpid()}"
    try:
        staged.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        os.chmod(staged, 0o600)
        staged.replace(destination)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        remove_listener_firewall(firewall)
        fail(f"cannot write kid listener configuration: {exc}")
    print(f"Configured {kid_id} listener {chosen['name']}: {transport} {address}:{host_port} -> container port {chosen['port']}")


def activation_state_dir(kid_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", kid_id):
        fail("kid id must contain lowercase letters, digits, and hyphens")
    return Path("/var/lib/billie/kids") / kid_id


def read_activation_state(kid_id: str, name: str) -> dict | None:
    path = activation_state_dir(kid_id) / f"{name}.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"kid activation state is unreadable at {path}: {exc}")
    if not isinstance(state, dict) or state.get("schema") != "billie.kid.activation.v1":
        fail(f"kid activation state is invalid at {path}")
    return state


def write_activation_state(kid_id: str, name: str, state: dict) -> None:
    directory = activation_state_dir(kid_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    os.chown(directory, 0, 0)
    destination = directory / f"{name}.json"
    staged = directory / f".{name}.{os.getpid()}.tmp"
    try:
        staged.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        os.chmod(staged, 0o600)
        os.chown(staged, 0, 0)
        staged.replace(destination)
    except OSError as exc:
        staged.unlink(missing_ok=True)
        fail(f"cannot save kid activation state: {exc}")


def activation_snapshot(kid_id: str, version: str, runtime_dir: Path, instance_prefix: str) -> dict:
    config_dir = Path("/etc/billie/kids") / kid_id
    listener_path = config_dir / "listener.json"
    env_path = config_dir / "runtime.env"
    try:
        listener = json.loads(listener_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot snapshot kid listener configuration: {exc}")
    try:
        environment = env_path.read_text(encoding="utf-8") if env_path.is_file() else None
    except OSError as exc:
        fail(f"cannot snapshot protected kid runtime configuration: {exc}")
    return {
        "schema": "billie.kid.activation.v1",
        "version": version,
        "listener": listener,
        "environment": environment,
        "runtimeDir": str(runtime_dir),
        "instancePrefix": instance_prefix,
    }


def restore_activation_snapshot(kid_id: str, state: dict) -> None:
    version = state.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        fail("saved rollback version is invalid")
    package, manifest, _ = installed_package(kid_id, version)
    del package
    listener = state.get("listener")
    if not isinstance(listener, dict):
        fail("saved rollback listener configuration is invalid")
    matches = [item for item in manifest["interfaces"]["inputs"] if item.get("name") == listener.get("name")]
    if len(matches) != 1 or matches[0].get("transport") != listener.get("transport") or matches[0].get("port") != listener.get("containerPort"):
        fail(f"saved listener is not supported by {kid_id}@{version}; configure that version before rollback")
    address_text = listener.get("hostAddress")
    try:
        address = ipaddress.ip_address(address_text)
    except (TypeError, ValueError):
        fail("saved rollback bind address is invalid")
    if address.version != 4 or str(address) not in assigned_ipv4_addresses():
        fail(f"saved rollback bind address {address} is not assigned to this node")
    host_port = listener.get("hostPort")
    if not isinstance(host_port, int) or isinstance(host_port, bool) or not 1 <= host_port <= 65535:
        fail("saved rollback host port is invalid")

    # Recreate only this kid's managed firewall rules for the restored listener.
    current_path = Path("/etc/billie/kids") / kid_id / "listener.json"
    try:
        current = json.loads(current_path.read_text(encoding="utf-8")) if current_path.is_file() else {}
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"current kid listener configuration is unreadable: {exc}")
    source_cidr = listener.get("firewall", {}).get("sourceCidr") if isinstance(listener.get("firewall"), dict) else None
    firewall = configure_listener_firewall(
        kid_id, matches[0]["transport"], address, host_port, source_cidr, matches[0]["port"]
    )
    restored_listener = dict(listener)
    restored_listener["firewall"] = firewall
    config_dir = current_path.parent
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    staged = config_dir / f".listener.json.{os.getpid()}.rollback"
    staged.write_text(json.dumps(restored_listener, indent=2) + "\n", encoding="utf-8")
    os.chmod(staged, 0o600)
    os.chown(staged, 0, 0)
    staged.replace(current_path)

    env_path = config_dir / "runtime.env"
    environment = state.get("environment")
    if environment is None:
        env_path.unlink(missing_ok=True)
    elif isinstance(environment, str):
        staged_env = config_dir / f".runtime.env.{os.getpid()}.rollback"
        staged_env.write_text(environment, encoding="utf-8")
        os.chmod(staged_env, 0o600)
        os.chown(staged_env, 0, 0)
        staged_env.replace(env_path)
    else:
        fail("saved rollback runtime configuration is invalid")


def activate(kid_id: str, version: str | None, config: Path | None, runtime_dir: Path, instance_prefix: str) -> None:
    require_root()
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", instance_prefix):
        fail("Billie instance prefix is invalid")
    if shutil.which("podman") is None or shutil.which("systemctl") is None:
        fail("Podman and systemd are required to activate a kid")
    package, manifest, metadata = installed_package(kid_id, version)
    previous_activation = read_activation_state(kid_id, "active")
    runtime = manifest["runtime"]
    inputs = manifest["interfaces"]["inputs"]
    if not inputs:
        fail("kid package does not declare an input listener")
    if runtime["persistentPaths"]:
        fail("persistentPaths are not supported yet; remove them or wait for persistent volume support")
    requirements = manifest["interfaces"].get("requires", [])
    if requirements:
        fail(f"kid requirements are not supported by this activation release: {', '.join(requirements)}")
    if "BILLIE_TRANSLATOR_SOCKET" not in runtime.get("environment", []):
        fail("runtime.environment must declare BILLIE_TRANSLATOR_SOCKET for the shared Rust translator")
    unsupported_outputs = unsupported_output_formats(manifest["interfaces"]["outputs"])
    if unsupported_outputs:
        fail(f"this translator release does not implement output format(s): {', '.join(unsupported_outputs)}")

    allowed_env = set(runtime.get("environment", []))
    if allowed_env - BUILTIN_ENV and config is None and not (Path("/etc/billie/kids") / kid_id / "runtime.env").is_file():
        fail("this kid needs runtime environment values; pass --config <root-readable NAME=VALUE file>")
    config_dir = Path("/etc/billie/kids") / kid_id
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config_dir, 0o700)
    env_file = config_dir / "runtime.env"
    if config is not None:
        values = parse_environment(config.expanduser().resolve(), list(allowed_env))
        missing = sorted(allowed_env - BUILTIN_ENV - values.keys())
        if missing:
            fail(f"runtime configuration is missing declared variables: {', '.join(missing)}")
        staged = config_dir / f".runtime.env.{os.getpid()}"
        staged.write_text("".join(f"{name}={value}\n" for name, value in sorted(values.items())), encoding="utf-8")
        os.chmod(staged, 0o600)
        staged.replace(env_file)
    elif allowed_env - BUILTIN_ENV:
        values = parse_environment(env_file, list(allowed_env))
        missing = sorted(allowed_env - BUILTIN_ENV - values.keys())
        if missing:
            fail(f"protected runtime configuration is missing: {', '.join(missing)}")
        os.chmod(env_file, 0o600)

    listener_config_path = Path("/etc/billie/kids") / kid_id / "listener.json"
    if listener_config_path.is_file():
        try:
            listener_config = json.loads(listener_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"kid listener configuration is unreadable: {exc}")
        selected = [item for item in inputs if item["name"] == listener_config.get("name")]
        if len(selected) != 1:
            fail("configured listener is no longer declared by the installed package")
        input_config = selected[0]
        if listener_config.get("schema") != "billie.kid.listener.v2":
            fail("listener configuration is outdated; rerun billie kid configure with --bind-address and --port")
        bind_address = listener_config.get("hostAddress")
        try:
            address = ipaddress.ip_address(bind_address)
        except (TypeError, ValueError):
            fail("configured bind address is invalid; rerun billie kid configure")
        if address.version != 4 or str(address) not in assigned_ipv4_addresses():
            fail(f"configured bind address {address} is not assigned to this node; reconfigure the node interface or kid")
        if listener_config.get("transport") != input_config["transport"] or listener_config.get("containerPort") != input_config["port"]:
            fail("configured listener does not match the installed package manifest")
        host_port = listener_config.get("hostPort")
        if not isinstance(host_port, int) or isinstance(host_port, bool) or not 1 <= host_port <= 65535:
            fail("configured host port must be an integer from 1 through 65535")
    else:
        if len(inputs) != 1:
            fail("kid declares multiple listeners; run billie kid configure to select one before activation")
        fail("configure this kid before activation: billie kid configure <id> --transport udp|tcp --bind-address <node-IP> --port <host-port>")
    port = input_config["port"]
    transport = input_config["transport"]
    runtime_socket = runtime_dir / "translator.sock"
    uid, gid = ensure_kid_identity(kid_id)
    update_translator_registry(kid_id, {
        "uid": uid,
        "outputs": [
            {"name": item["name"], "format": item["format"], "profile": item.get("profile")}
            for item in manifest["interfaces"]["outputs"]
        ],
    })
    run(["systemctl", "stop", f"billie-kid-{kid_id}.service"], check=False)
    remove_stale_container(kid_id)
    container_name = f"billie-kid-{kid_id}"
    runner = package / "run-kid.sh"
    command = [
        "podman", "run", "--rm", "--name", container_name, "--pull=never",
        "--userns=host", "--user", f"{uid}:{gid}", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--read-only", "--tmpfs", "/tmp:rw,size=16m",
        "--publish", f"{bind_address}:{host_port}:{port}/{transport}",
        # Directory bind mounts follow a replaced socket inode across
        # translator restarts; file bind mounts continue to expose the stale inode.
        "--volume", f"{runtime_dir}:/run/billie:ro",
        "--env", "BILLIE_TRANSLATOR_SOCKET=/run/billie/translator.sock",
    ]
    if "BILLIE_INPUT_PORT" in allowed_env:
        command.extend(["--env", f"BILLIE_INPUT_PORT={port}"])
    if "BILLIE_INPUT_BIND" in allowed_env:
        command.extend(["--env", "BILLIE_INPUT_BIND=0.0.0.0"])
    if "BILLIE_INPUT_TRANSPORT" in allowed_env:
        command.extend(["--env", f"BILLIE_INPUT_TRANSPORT={transport}"])
    if "BILLIE_INPUT_LISTENER" in allowed_env:
        command.extend(["--env", f"BILLIE_INPUT_LISTENER={input_config['name']}"])
    if env_file.is_file() and allowed_env - BUILTIN_ENV:
        command.extend(["--env-file", str(env_file)])
    command.append(metadata["imageId"])
    command.extend(runtime["command"])
    runner.write_text("#!/usr/bin/env bash\nset -euo pipefail\nexec " + shlex.join(command) + "\n", encoding="utf-8")
    os.chmod(runner, 0o750)

    unit_path = Path("/etc/systemd/system") / f"{container_name}.service"
    unit_text = render_kid_systemd_unit(
        kid_id, manifest["metadata"]["version"], runtime_socket, runner, container_name, instance_prefix
    )
    temporary_unit = unit_path.with_suffix(f".service.{os.getpid()}.tmp")
    temporary_unit.write_text(unit_text, encoding="utf-8")
    os.chmod(temporary_unit, 0o644)
    temporary_unit.replace(unit_path)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", unit_path.name])
    active = run(["systemctl", "is-active", "--quiet", unit_path.name], check=False)
    start_kid_service_with_verified_forward(
        unit_path.name, container_name, str(address), host_port, transport, port,
        restart=active.returncode == 0,
    )
    successful = activation_snapshot(kid_id, manifest["metadata"]["version"], runtime_dir, instance_prefix)
    if previous_activation and previous_activation.get("version") != successful["version"]:
        write_activation_state(kid_id, "previous", previous_activation)
    write_activation_state(kid_id, "active", successful)
    print(f"Activated {kid_id}@{manifest['metadata']['version']} as {unit_path.name} ({transport} {host_port}->{port})")


def upgrade(kid_id: str, version: str, config: Path | None, runtime_dir: Path, instance_prefix: str) -> None:
    require_root()
    active = read_activation_state(kid_id, "active")
    if active is None:
        fail(f"{kid_id} has no recorded activation; use billie kid activate for its first deployment")
    if active.get("version") == version:
        fail(f"{kid_id}@{version} is already the recorded active version")
    installed_package(kid_id, version)
    unit_name = f"billie-kid-{kid_id}.service"
    if run(["systemctl", "is-active", "--quiet", unit_name], check=False).returncode != 0:
        fail(f"{kid_id} is not active; start its current version with billie kid activate before upgrading")
    current_snapshot = activation_snapshot(kid_id, active["version"], runtime_dir, instance_prefix)
    print(f"Upgrading {kid_id} from {active.get('version')} to {version}...")
    try:
        activate(kid_id, version, config, runtime_dir, instance_prefix)
    except SystemExit:
        restore_activation_snapshot(kid_id, current_snapshot)
        try:
            activate(kid_id, active["version"], None, runtime_dir, instance_prefix)
        except SystemExit:
            print("Upgrade failed and the previous version could not be restarted; inspect the kid service journal.", file=sys.stderr)
        raise


def rollback(kid_id: str, runtime_dir: Path, instance_prefix: str) -> None:
    require_root()
    previous = read_activation_state(kid_id, "previous")
    active = read_activation_state(kid_id, "active")
    if previous is None:
        fail(f"{kid_id} has no recorded previous activation to roll back to")
    if active is None:
        fail(f"{kid_id} has no recorded active deployment; use billie kid activate")
    if previous.get("version") == active.get("version"):
        fail(f"{kid_id} has no different previous version to roll back to")
    installed_package(kid_id, previous.get("version"))
    old_listener = activation_snapshot(kid_id, active["version"], runtime_dir, instance_prefix)
    restore_activation_snapshot(kid_id, previous)
    try:
        activate(kid_id, previous["version"], None, Path(previous.get("runtimeDir", runtime_dir)), previous.get("instancePrefix", instance_prefix))
    except SystemExit:
        # Restore the configuration and best-effort restart the version that was active before rollback.
        restore_activation_snapshot(kid_id, old_listener)
        try:
            activate(kid_id, active["version"], None, runtime_dir, instance_prefix)
        except SystemExit:
            print("Rollback failed and the prior version could not be restarted; inspect the kid service journal.", file=sys.stderr)
        raise
    print(f"Rolled back {kid_id} to {previous['version']}; the displaced version is available for another rollback.")


def remove_kid(kid_id: str, version: str | None, remove_config: bool) -> None:
    require_root()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", kid_id):
        fail("kid id must contain lowercase letters, digits, and hyphens")
    package_root = Path("/opt/billie/kids") / kid_id
    if not package_root.is_dir():
        fail(f"no installed package named {kid_id}", 1)
    installed = sorted(path for path in package_root.iterdir() if path.is_dir() and VERSION_RE.fullmatch(path.name))
    selected = [path for path in installed if path.name == version] if version else installed
    if not selected:
        fail(f"no installed version found for {kid_id}" + (f"@{version}" if version else ""), 1)
    deleting_all = len(selected) == len(installed)
    selected_versions = {path.name for path in selected}
    active_state = read_activation_state(kid_id, "active")
    previous_state = read_activation_state(kid_id, "previous")
    unit_name = f"billie-kid-{kid_id}.service"
    unit_path = Path("/etc/systemd/system") / unit_name
    service_active = run(["systemctl", "is-active", "--quiet", unit_name], check=False).returncode == 0
    if not deleting_all and active_state is None and unit_path.exists():
        fail(f"cannot safely remove a version of {kid_id}: its service has no recorded active version; deactivate it or remove all versions")
    if not deleting_all and service_active and active_state and active_state.get("version") in selected_versions:
        fail(f"{kid_id}@{active_state['version']} is active; deactivate it before removing that version")
    active_removed = deleting_all or (active_state is not None and active_state.get("version") in selected_versions)
    if active_removed:
        update_translator_registry(kid_id, None)
    if deleting_all:
        listener_path = Path("/etc/billie/kids") / kid_id / "listener.json"
        if listener_path.is_file():
            try:
                listener = json.loads(listener_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                fail(f"kid listener configuration is unreadable: {exc}")
            remove_listener_firewall(listener.get("firewall"))

    if active_removed:
        run(["systemctl", "disable", "--now", unit_name], check=False)
        remove_stale_container(kid_id)
        Path("/etc/systemd/system", unit_name).unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])

    state_dir = activation_state_dir(kid_id)
    if active_removed:
        (state_dir / "active.json").unlink(missing_ok=True)
    if deleting_all or (previous_state is not None and previous_state.get("version") in selected_versions):
        (state_dir / "previous.json").unlink(missing_ok=True)

    image_ids: set[str] = set()
    for package in selected:
        try:
            metadata = json.loads((package / "bundle.json").read_text(encoding="utf-8"))
            image_id = metadata.get("imageId")
            if isinstance(image_id, str) and IMAGE_ID_RE.fullmatch(image_id):
                image_ids.add(image_id)
        except (OSError, json.JSONDecodeError):
            pass
        shutil.rmtree(package)

    remaining_refs: set[str] = set()
    if package_root.exists():
        for metadata_path in Path("/opt/billie/kids").glob("*/*/bundle.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                image_id = metadata.get("imageId")
                if isinstance(image_id, str):
                    remaining_refs.add(image_id)
            except (OSError, json.JSONDecodeError):
                continue
    retained_images: list[str] = []
    for image_id in sorted(image_ids - remaining_refs):
        result = run(["podman", "rmi", image_id], check=False)
        if result.returncode:
            retained_images.append(image_id)

    if package_root.exists() and not any(package_root.iterdir()):
        package_root.rmdir()
    if not package_root.exists():
        username = kid_service_username(kid_id)
        try:
            account = pwd.getpwnam(username)
        except KeyError:
            account = None
        if account is not None and account.pw_gecos.startswith("Open Billie kid "):
            run(["userdel", username], check=False)
    if remove_config:
        # Rollback records duplicate protected runtime.env contents. Erase
        # those copies too when the operator explicitly removes configuration.
        for state_name in ("active", "previous"):
            snapshot = read_activation_state(kid_id, state_name)
            if snapshot is not None:
                snapshot["environment"] = None
                write_activation_state(kid_id, state_name, snapshot)
        shutil.rmtree(Path("/etc/billie/kids") / kid_id, ignore_errors=True)
    if deleting_all:
        shutil.rmtree(state_dir, ignore_errors=True)
    print(f"Removed {kid_id} version(s): {', '.join(path.name for path in selected)}")
    if retained_images:
        print("Some image data remains because Podman reports it is still in use: " + ", ".join(retained_images))
    print("Runtime configuration was " + ("removed" if remove_config else "preserved; use --remove-config to delete it"))


def main() -> int:
    parser = argparse.ArgumentParser(prog="billie kid")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install_parser = subparsers.add_parser("install", help="verify and install a local kid bundle")
    install_parser.add_argument("bundle", type=Path)
    install_parser.add_argument("--checksum", type=Path, help="external SHA-256 sidecar; defaults to <bundle>.sha256")
    activate_parser = subparsers.add_parser("activate", help="start an installed kid package")
    activate_parser.add_argument("kid_id")
    activate_parser.add_argument("--version")
    activate_parser.add_argument("--config", type=Path, help="root-readable NAME=VALUE environment file")
    activate_parser.add_argument("--runtime-dir", type=Path, default=Path(os.environ.get("BILLIE_RUNTIME_DIR", "/run/billie")))
    activate_parser.add_argument("--instance-prefix", default=os.environ.get("BILLIE_INSTANCE_PREFIX", "billie"))
    upgrade_parser = subparsers.add_parser("upgrade", help="activate a newly installed kid version while retaining the prior version")
    upgrade_parser.add_argument("kid_id")
    upgrade_parser.add_argument("--version", required=True)
    upgrade_parser.add_argument("--config", type=Path, help="root-readable NAME=VALUE environment file")
    upgrade_parser.add_argument("--runtime-dir", type=Path, default=Path(os.environ.get("BILLIE_RUNTIME_DIR", "/run/billie")))
    upgrade_parser.add_argument("--instance-prefix", default=os.environ.get("BILLIE_INSTANCE_PREFIX", "billie"))
    rollback_parser = subparsers.add_parser("rollback", help="reactivate the previous successful kid version")
    rollback_parser.add_argument("kid_id")
    rollback_parser.add_argument("--runtime-dir", type=Path, default=Path(os.environ.get("BILLIE_RUNTIME_DIR", "/run/billie")))
    rollback_parser.add_argument("--instance-prefix", default=os.environ.get("BILLIE_INSTANCE_PREFIX", "billie"))
    deactivate_parser = subparsers.add_parser("deactivate", help="stop an active kid without removing its package")
    deactivate_parser.add_argument("kid_id")
    configure_parser = subparsers.add_parser("configure", help="select a declared listener, node bind address, and host port")
    configure_parser.add_argument("kid_id")
    configure_parser.add_argument("--transport", choices=("udp", "tcp"), required=True)
    configure_parser.add_argument("--bind-address", required=True, help="IPv4 address already assigned to the node interface")
    configure_parser.add_argument("--port", type=int, required=True, help="node host port to listen on")
    configure_parser.add_argument("--source-cidr", help="IPv4 sensor source network allowed by UFW; prompts when omitted")
    configure_parser.add_argument("--listener", help="listener name when multiple matching transports are declared")
    configure_parser.add_argument("--version")
    remove_parser = subparsers.add_parser("remove", help="stop and remove an installed kid version")
    remove_parser.add_argument("kid_id")
    remove_parser.add_argument("--version", help="remove one version; omit to remove all installed versions")
    remove_parser.add_argument("--remove-config", action="store_true", help="also remove protected runtime configuration")
    status_parser = subparsers.add_parser("status", help="show active kid service state")
    status_parser.add_argument("kid_id")
    logs_parser = subparsers.add_parser("logs", help="show recent kid service logs")
    logs_parser.add_argument("kid_id")
    logs_parser.add_argument("--lines", type=int, default=80)
    args = parser.parse_args()

    if args.command == "install":
        install_bundle(args.bundle, args.checksum)
    elif args.command == "configure":
        configure_listener(args.kid_id, args.transport, args.bind_address, args.port, args.listener, args.version, args.source_cidr)
    elif args.command == "activate":
        activate(args.kid_id, args.version, args.config, args.runtime_dir, args.instance_prefix)
    elif args.command == "upgrade":
        upgrade(args.kid_id, args.version, args.config, args.runtime_dir, args.instance_prefix)
    elif args.command == "rollback":
        rollback(args.kid_id, args.runtime_dir, args.instance_prefix)
    elif args.command == "deactivate":
        require_root()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.kid_id):
            fail("kid id must contain lowercase letters, digits, and hyphens")
        update_translator_registry(args.kid_id, None)
        name = f"billie-kid-{args.kid_id}.service"
        run(["systemctl", "disable", "--now", name], check=False)
        remove_stale_container(args.kid_id)
        Path("/etc/systemd/system", name).unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])
        print(f"Deactivated {args.kid_id}; installed package versions were preserved")
    elif args.command == "remove":
        remove_kid(args.kid_id, args.version, args.remove_config)
    elif args.command == "status":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.kid_id):
            fail("kid id must contain lowercase letters, digits, and hyphens")
        name = f"billie-kid-{args.kid_id}.service"
        result = run(["systemctl", "status", "--no-pager", name], check=False)
        if result.returncode:
            print(f"Kid service is not active: {name}")
            return 1
    elif args.command == "logs":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.kid_id):
            fail("kid id must contain lowercase letters, digits, and hyphens")
        if not 1 <= args.lines <= 10000:
            fail("--lines must be from 1 through 10000")
        run(["journalctl", "--no-pager", f"--lines={args.lines}", "-u", f"billie-kid-{args.kid_id}.service"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
