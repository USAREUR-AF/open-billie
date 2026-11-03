#!/usr/bin/env python3
"""Generate an SPDX JSON SBOM from the OCI image embedded in a kid bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import NoReturn


def fail(message: str) -> NoReturn:
    print(f"kid SBOM: {message}", file=sys.stderr)
    raise SystemExit(2)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(bundle_path: Path) -> None:
    sidecar = Path(f"{bundle_path}.sha256")
    if not sidecar.is_file():
        fail(f"checksum sidecar not found: {sidecar}")
    match = re.fullmatch(r"\s*([a-fA-F0-9]{64})\s+(.+?)\s*", sidecar.read_text(encoding="ascii"))
    if not match or match.group(2) != bundle_path.name:
        fail(f"invalid checksum sidecar: {sidecar}")
    if sha256_file(bundle_path).lower() != match.group(1).lower():
        fail(f"bundle checksum does not match: {bundle_path}")


def extract_verified_image(bundle_path: Path, destination: Path) -> None:
    try:
        with tarfile.open(bundle_path, "r:gz") as bundle:
            sums_member = bundle.getmember("SHA256SUMS")
            sums_stream = bundle.extractfile(sums_member)
            image_member = bundle.getmember("image.oci.tar")
            image_stream = bundle.extractfile(image_member)
            if sums_stream is None or image_stream is None:
                fail("bundle is missing SHA256SUMS or image.oci.tar data")
            sums = sums_stream.read().decode("ascii")
            expected = None
            for line in sums.splitlines():
                fields = line.split(None, 1)
                if len(fields) == 2 and fields[1].lstrip("* ") == "image.oci.tar":
                    expected = fields[0]
                    break
            if not expected or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
                fail("bundle SHA256SUMS has no valid image.oci.tar entry")
            digest = hashlib.sha256()
            with destination.open("wb") as output:
                for chunk in iter(lambda: image_stream.read(1024 * 1024), b""):
                    digest.update(chunk)
                    output.write(chunk)
            if digest.hexdigest().lower() != expected.lower():
                fail("image.oci.tar checksum does not match the bundle manifest")
    except (OSError, tarfile.TarError, KeyError, UnicodeError) as exc:
        fail(f"cannot read kid bundle {bundle_path}: {exc}")


def read_bundle_metadata(bundle_path: Path) -> tuple[str, str]:
    try:
        with tarfile.open(bundle_path, "r:gz") as bundle:
            metadata_stream = bundle.extractfile("bundle.json")
            if metadata_stream is None:
                fail("bundle is missing bundle.json")
            metadata = json.load(metadata_stream)
        image = metadata.get("image")
        version = metadata.get("version")
        if not isinstance(image, str) or not image or not isinstance(version, str) or not version:
            fail("bundle.json must contain non-empty image and version fields")
        return image, version
    except (OSError, tarfile.TarError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read bundle metadata {bundle_path}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="billie-kid-<id>_<version>.tar.gz bundle")
    parser.add_argument("--output", type=Path, help="SPDX JSON destination (defaults beside the bundle)")
    args = parser.parse_args()

    bundle_path = args.bundle.resolve()
    if not bundle_path.is_file():
        fail(f"bundle not found: {bundle_path}")
    syft = shutil.which("syft")
    if not syft:
        fail("Syft is required; install it from https://github.com/anchore/syft")
    output = args.output.resolve() if args.output else bundle_path.with_name(
        f"{bundle_path.name.removesuffix('.tar.gz')}.sbom.spdx.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    verify_bundle(bundle_path)
    image_reference, version = read_bundle_metadata(bundle_path)
    with tempfile.TemporaryDirectory(prefix="billie-kid-sbom-") as temp_dir:
        image_archive = Path(temp_dir) / "image.oci.tar"
        extract_verified_image(bundle_path, image_archive)
        subprocess.run(
            [
                syft,
                "scan",
                f"oci-archive:{image_archive}",
                "--source-name",
                image_reference,
                "--source-version",
                version,
                "-o",
                f"spdx-json={output}",
            ],
            check=True,
        )
    print(f"Generated SPDX JSON SBOM: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
