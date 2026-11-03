#!/usr/bin/env python3
"""Check repository inputs that must remain pinned and provenance-documented."""

from __future__ import annotations

import re
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCKFILES = ("runtime/rust/Cargo.lock", "kids/examples/oetf/packages/oetf/rust/Cargo.lock", "kids/examples/oetf/pnpm-lock.yaml")
PROVENANCE = Path("docs/provenance/OETF_IMPORT.md")
PROVENANCE_FIELDS = (
    "Source workspace:",
    "Source revision:",
    "Package license metadata:",
    "License file:",
    "Destination:",
    "## Imported components",
)
IMAGE_FILE_SUFFIXES = {".containerfile", ".dockerfile"}
IMMUTABLE_VERSION_TAG = re.compile(r"^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")


def is_fixed_version_tag(image_name: str, tag: str) -> bool:
    if IMMUTABLE_VERSION_TAG.fullmatch(tag):
        return True
    # Debian publishes point-release tags with only major.minor, such as
    # 12.12-slim. Do not generalize this exception to app images like
    # python:3.12-slim, which floats across Python patch releases.
    return image_name.rsplit("/", 1)[-1] == "debian" and bool(
        re.fullmatch(r"\d+\.\d+-slim(?:-[A-Za-z0-9.-]+)?", tag)
    )


def check_lockfiles(errors: list[str]) -> None:
    for relative in LOCKFILES:
        path = ROOT / relative
        if not path.is_file() or not path.stat().st_size:
            errors.append(f"required dependency lockfile is missing or empty: {relative}")


def check_container_bases(errors: list[str]) -> None:
    excluded = {".git", "node_modules", "target", "dist", "build", "__pycache__"}
    candidates: list[Path] = []
    for directory, subdirectories, filenames in os.walk(ROOT):
        subdirectories[:] = [name for name in subdirectories if name not in excluded]
        for filename in filenames:
            lowered = filename.lower()
            if lowered in {"containerfile", "dockerfile"} or lowered.startswith(("containerfile.", "dockerfile.")) or Path(lowered).suffix in IMAGE_FILE_SUFFIXES or (lowered.endswith(".container.j2")):
                candidates.append(Path(directory) / filename)
    for path in candidates:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"^\s*(?:FROM\s+(?:(?:--platform=\S+)\s+)?(\S+)|Image=(.+))", line, re.IGNORECASE)
            if not match:
                continue
            image = (match.group(1) or match.group(2)).strip()
            # Quadlet image templates contain whitespace inside Jinja syntax.
            # Keep the entire value so we can inspect its declared default.
            if match.group(2):
                image = image.split()[0] if "{{" not in image else image
            if "{{" in image:
                configured_default = re.search(r"default\(['\"]([^'\"]+)['\"]\)", image)
                if configured_default:
                    image = image[:image.index("{{")] + configured_default.group(1)
                else:
                    errors.append(f"{path.relative_to(ROOT).as_posix()}:{number}: image template must declare an explicit version default")
                    continue
            if image.lower() == "scratch":
                continue
            if "@sha256:" in image:
                continue
            name, separator, tag = image.rpartition(":")
            if not separator or "/" in tag or not name or not is_fixed_version_tag(name, tag) or "$" in image:
                relative = path.relative_to(ROOT).as_posix()
                errors.append(f"{relative}:{number}: base/runtime image must use a SHA-256 digest or exact image version tag: {image}")


def check_provenance(errors: list[str]) -> None:
    path = ROOT / PROVENANCE
    if not path.is_file():
        errors.append(f"provenance record is missing: {PROVENANCE.as_posix()}")
        return
    contents = path.read_text(encoding="utf-8")
    for field in PROVENANCE_FIELDS:
        if field not in contents:
            errors.append(f"{PROVENANCE.as_posix()} is missing required field {field!r}")
    if "Destination: `kids/examples/oetf/`" not in contents:
        errors.append("OETF provenance must state its in-repository synthetic destination")
    if "License file: the source workspace had no license text." not in contents:
        errors.append("OETF provenance must document the source workspace license and repository license disposition")


def main() -> int:
    errors: list[str] = []
    check_lockfiles(errors)
    check_container_bases(errors)
    check_provenance(errors)
    if errors:
        for error in errors:
            print(f"release hygiene: {error}", file=sys.stderr)
        return 1
    print("Release hygiene checks passed: lockfiles, versioned container bases, and provenance metadata are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
