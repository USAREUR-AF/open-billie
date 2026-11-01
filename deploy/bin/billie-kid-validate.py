#!/usr/bin/env python3
"""Offline validation for an Open Billie kid source directory."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover - depends on target installation
    print(
        f"billie kid validate: missing Python dependency: {exc.name}; "
        "install python3-yaml and python3-jsonschema",
        file=sys.stderr,
    )
    raise SystemExit(2)


COMPONENTS = {
    "decoder": None,
    "mapper": None,
    "schemas": "directory",
    "mappings": "directory",
    "lookups": "directory",
    "vectors": "directory",
}
DATA_COMPONENTS = ("schemas", "mappings", "lookups", "vectors")
IMAGE_DIGEST = re.compile(r"^.+@sha256:[a-f0-9]{64}$")


def schema_path() -> Path:
    here = Path(__file__).resolve().parent
    candidates = (here.parent / "schemas" / "kid-manifest.schema.json",
                  here.parent.parent / "schemas" / "kid-manifest.schema.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("cannot locate schemas/kid-manifest.schema.json")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="billie kid validate",
        description="Validate a kid manifest and its local component paths without network access.",
    )
    parser.add_argument("package", type=Path, help="kid source directory containing billie-kid.yaml")
    parser.add_argument(
        "--strict", action="store_true",
        help="treat development placeholders and empty template data directories as errors",
    )
    args = parser.parse_args()

    root = args.package.expanduser().resolve()
    if not root.is_dir():
        fail(f"package directory does not exist: {root}")
        return 1

    manifest_path = root / "billie-kid.yaml"
    if not manifest_path.is_file():
        fail(f"manifest not found: {manifest_path}")
        return 1
    problems: list[str] = []
    for required_file in ("README.md", "Containerfile"):
        if not (root / required_file).is_file():
            problems.append(f"required package file is missing: {required_file}")

    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        fail(f"cannot read YAML manifest: {exc}")
        return 1

    try:
        schema = json.loads(schema_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        fail(f"cannot load kid manifest schema: {exc}")
        return 2

    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "manifest"
            fail(f"{location}: {error.message}")
        return 1

    warnings: list[str] = []
    components = manifest["components"]
    resolved_components: dict[str, Path] = {}

    for name, expected_type in COMPONENTS.items():
        relative = Path(components[name])
        target = (root / relative).resolve()
        if target == root:
            problems.append(f"components.{name} must not point at the package root")
            continue
        try:
            target.relative_to(root)
        except ValueError:
            problems.append(f"components.{name} escapes the package directory: {relative}")
            continue
        if not target.exists():
            problems.append(f"components.{name} does not exist: {relative}")
            continue
        if expected_type == "directory" and not target.is_dir():
            problems.append(f"components.{name} must be a directory: {relative}")
            continue
        if expected_type is None and not (target.is_dir() or target.is_file()):
            problems.append(f"components.{name} must be a file or directory: {relative}")
            continue
        resolved_components[name] = target

    for language, implementation in manifest.get("decoderImplementations", {}).items():
        if not isinstance(implementation, dict):
            continue
        for field in ("decoder", "mapper"):
            relative = Path(implementation[field])
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                problems.append(f"decoderImplementations.{language}.{field} escapes the package directory")
                continue
            if not target.is_file():
                problems.append(f"decoderImplementations.{language}.{field} is missing: {relative}")
        if implementation["status"] == "deployable":
            relative = Path(implementation["containerfile"])
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                problems.append(f"decoderImplementations.{language}.containerfile escapes the package directory")
                continue
            if not target.is_file():
                problems.append(f"decoderImplementations.{language}.containerfile is missing: {relative}")

    for name in DATA_COMPONENTS:
        directory = resolved_components.get(name)
        if directory is None or not directory.is_dir():
            continue
        json_files = sorted(directory.rglob("*.json"))
        if not json_files:
            warnings.append(f"components.{name} contains no JSON data yet")
        for data_file in json_files:
            try:
                data_file.resolve().relative_to(root)
            except ValueError:
                problems.append(f"JSON file escapes the package directory: {data_file}")
                continue
            try:
                json.loads(data_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"invalid JSON in {data_file.relative_to(root)}: {exc}")

    interfaces = manifest["interfaces"]
    runtime = manifest["runtime"]
    if runtime.get("persistentPaths"):
        problems.append("runtime.persistentPaths are not supported by the current node runtime")
    if interfaces.get("requires"):
        problems.append("interfaces.requires contains node capabilities not supported by the current activation runtime")
    if "BILLIE_TRANSLATOR_SOCKET" not in runtime.get("environment", []):
        problems.append("runtime.environment must declare BILLIE_TRANSLATOR_SOCKET for the shared translator")
    for direction in ("inputs", "outputs"):
        names = [entry["name"] for entry in interfaces[direction]]
        if len(names) != len(set(names)):
            problems.append(f"interfaces.{direction} contains duplicate names")
    image = runtime["image"]
    if not IMAGE_DIGEST.fullmatch(image):
        problems.append("runtime.image must be pinned by a lowercase sha256 digest")
    elif image.endswith("@sha256:" + "0" * 64) or ".invalid/" in image:
        warnings.append("runtime.image is a development placeholder and is not deployable")

    for problem in problems:
        fail(problem)
    if problems:
        return 1

    if args.strict and warnings:
        for warning in warnings:
            fail(warning)
        return 1

    metadata = manifest["metadata"]
    print(f"Valid kid source: {metadata['id']}@{metadata['version']}")
    print(f"Manifest: {manifest_path}")
    for name in COMPONENTS:
        if name in resolved_components:
            print(f"  {name}: {components[name]}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if warnings:
        print("Source structure is valid; resolve warnings before treating it as deployable.")
    else:
        print("Manifest, component paths, JSON data, and runtime digest are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
