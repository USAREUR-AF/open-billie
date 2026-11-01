#!/usr/bin/env python3
"""Discover local Billie kid packages without running their build scripts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - depends on target installation
    print(
        f"billie kid scan: missing Python dependency: {exc.name}; install python3-yaml",
        file=sys.stderr,
    )
    raise SystemExit(2)


SKIP_DIRS = {
    ".git", ".hg", ".svn", ".tox", ".venv", "venv", "node_modules",
    "target", "dist", "build", "__pycache__", ".pytest_cache",
}
MANIFEST_NAME = "billie-kid.yaml"


def is_billie_json_schema(path: Path) -> bool:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            return False
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    fields = document.get("fields") if isinstance(document, dict) else None
    return isinstance(fields, list) and bool(fields) and all(
        isinstance(field, dict) and "offset" in field and "type" in field
        for field in fields
    )


def find_sources(roots: list[Path]) -> tuple[list[Path], dict[Path, dict[str, int]], list[str]]:
    found: set[Path] = set()
    schemas: dict[Path, dict[str, int]] = {}
    errors: list[str] = []
    for input_root in roots:
        root = input_root.expanduser().resolve()
        if not root.is_dir():
            errors.append(f"source root is not a directory: {input_root}")
            continue
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirnames[:] = sorted(
                name for name in dirnames
                if name not in SKIP_DIRS and not name.startswith(".")
                and not (current_path / name).is_symlink()
            )
            if MANIFEST_NAME in filenames:
                found.add((current_path / MANIFEST_NAME).resolve())
            for filename in filenames:
                source_file = current_path / filename
                if source_file.is_symlink():
                    continue
                if source_file.suffix == ".proto":
                    formats = schemas.setdefault(current_path.resolve(), {})
                    formats["protobuf"] = formats.get("protobuf", 0) + 1
                elif source_file.suffix.lower() == ".json" and is_billie_json_schema(source_file):
                    formats = schemas.setdefault(current_path.resolve(), {})
                    formats["billie-json"] = formats.get("billie-json", 0) + 1
    return sorted(found), schemas, errors


def schema_summary(package: Path, manifest: dict[str, Any]) -> str:
    schema_path = (package / manifest["components"]["schemas"]).resolve()
    files = sorted(schema_path.rglob("*") if schema_path.is_dir() else [schema_path])
    protobuf = [file for file in files if file.is_file() and file.suffix == ".proto"]
    json_files = [file for file in files if file.is_file() and file.suffix.lower() == ".json" and is_billie_json_schema(file)]
    kinds: list[str] = []
    if protobuf:
        kinds.append(f"Protocol Buffers ({len(protobuf)} .proto)")
    if json_files:
        kinds.append(f"JSON decode schemas ({len(json_files)} files)")
    return " + ".join(kinds) if kinds else "no schema files found"


def validate_package(package: Path, validator: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(validator), str(package)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout.splitlines()
    error_lines = [line.removeprefix("ERROR: ") for line in result.stderr.splitlines()]
    warnings = [line.removeprefix("WARNING: ") for line in output if line.startswith("WARNING: ")]
    if result.returncode != 0:
        return {
            "path": str(package),
            "validation": "invalid",
            "issues": error_lines or ["validator failed"],
        }

    try:
        manifest = yaml.safe_load((package / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {
            "path": str(package),
            "validation": "invalid",
            "issues": [f"cannot read manifest: {exc}"],
        }

    metadata = manifest["metadata"]
    runtime = manifest["runtime"]
    interfaces = manifest["interfaces"]
    image = runtime["image"]
    local_image = "not checked"
    if image.endswith("@sha256:" + "0" * 64) or ".invalid/" in image:
        local_image = "placeholder"
    elif shutil.which("podman"):
        try:
            probe = subprocess.run(
                ["podman", "image", "exists", image],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            local_image = "present" if probe.returncode == 0 else "not present"
        except (OSError, subprocess.TimeoutExpired):
            local_image = "probe unavailable"

    inputs = [f"{item['transport']}:{item['port']}" for item in interfaces["inputs"]]
    outputs = [f"{item['name']}:{item['format']}" for item in interfaces["outputs"]]
    return {
        "id": metadata["id"],
        "version": metadata["version"],
        "displayName": metadata["displayName"],
        "path": str(package),
        "schemaFormat": schema_summary(package, manifest),
        "inputs": inputs,
        "outputs": outputs,
        "image": image,
        "localImage": local_image,
        "validation": "valid_with_warnings" if warnings else "valid",
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="billie kid scan",
        description="Find local kid packages and report source, interface, and image readiness.",
    )
    parser.add_argument("roots", nargs="*", type=Path, help="source directories to scan")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable JSON inventory")
    args = parser.parse_args()

    roots = args.roots
    if not roots:
        configured = os.environ.get("BILLIE_KID_SOURCE_ROOTS", "")
        if configured:
            roots = [Path(value) for value in configured.split(os.pathsep) if value]
        else:
            local_kids = Path.cwd() / "kids"
            installed_kids = Path("/opt/billie/kids")
            package_root = Path.cwd()
            if (package_root / MANIFEST_NAME).is_file():
                roots = [package_root]
            elif local_kids.is_dir():
                roots = [local_kids]
            elif installed_kids.is_dir():
                roots = [installed_kids]
            else:
                roots = []

    manifests, schema_directories, root_errors = find_sources(roots)
    validator = Path(__file__).resolve().with_name("billie-kid-validate.py")
    if not validator.is_file():
        print(f"billie kid scan: validator is missing: {validator}", file=sys.stderr)
        return 2

    packages = [validate_package(manifest.parent, validator) for manifest in manifests]
    packages.sort(key=lambda item: (item.get("id", "~"), item.get("version", ""), item["path"]))
    package_roots = [manifest.parent.resolve() for manifest in manifests]
    schema_sources = []
    for directory, formats in sorted(schema_directories.items()):
        if any(root == directory or root in directory.parents for root in package_roots):
            continue
        labels = []
        if formats.get("billie-json"):
            labels.append(f"Billie JSON byte-offset ({formats['billie-json']} files)")
        if formats.get("protobuf"):
            labels.append(f"Protocol Buffers ({formats['protobuf']} .proto files)")
        schema_sources.append({
            "path": str(directory),
            "schemaFormat": " + ".join(labels),
            "status": "needs_manifest",
            "suggestedAction": "generate a billie-kid.yaml and mapper scaffold",
        })
    report = {
        "roots": [str(root.expanduser()) for root in roots],
        "packages": packages,
        "schemaSources": schema_sources,
        "errors": root_errors,
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for error in root_errors:
            print(f"ERROR: {error}")
        if not packages:
            if not schema_sources:
                print("No kid manifests or supported decode schemas found. Supply one or more local source roots.")
        for item in packages:
            package_id = item.get("id", "unknown")
            version = item.get("version", "unknown")
            state = item["validation"]
            if item.get("localImage") == "placeholder":
                state += ", image placeholder"
            elif item.get("localImage") == "not present":
                state += ", image not built locally"
            elif item.get("localImage") == "not checked":
                state += ", Podman unavailable"
            elif item.get("localImage") == "probe unavailable":
                state += ", image availability unknown"
            print(f"{package_id}@{version}: {state}")
            print(f"  source: {item['path']}")
            if item.get("schemaFormat"):
                print(f"  schema: {item['schemaFormat']}")
            if item.get("inputs"):
                print(f"  inputs: {', '.join(item['inputs'])}")
            if item.get("outputs"):
                print(f"  outputs: {', '.join(item['outputs'])}")
            for issue in item.get("issues", []):
                print(f"  ERROR: {issue}")
            for warning in item.get("warnings", []):
                print(f"  WARNING: {warning}")
        for item in schema_sources:
            print(f"Unpackaged schema source: {item['schemaFormat']}")
            print(f"  source: {item['path']}")
            print(f"  next: {item['suggestedAction']}")

    return 1 if root_errors or any(item["validation"] == "invalid" for item in packages) else 0


if __name__ == "__main__":
    raise SystemExit(main())
