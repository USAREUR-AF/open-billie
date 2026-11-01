#!/usr/bin/env python3
"""Build a local kid image and create a portable, unsigned kid bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

try:
    import yaml
except ImportError as exc:  # pragma: no cover - depends on workstation setup
    print(
        f"billie kid build: missing Python dependency: {exc.name}; "
        "install PyYAML (Ubuntu/Debian: python3-yaml)",
        file=sys.stderr,
    )
    raise SystemExit(2)


def fail(message: str) -> "NoReturn":
    print(f"billie kid build: {message}", file=sys.stderr)
    raise SystemExit(2)


def run(command: list[str], *, capture: bool = False, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            cwd=cwd,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError:
        fail(f"required command not found: {command[0]}")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        fail(f"command failed ({' '.join(command)}): {detail or exc.returncode}")
    return result.stdout.strip() if capture else ""


def command_succeeds(command: list[str]) -> bool:
    try:
        return subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except FileNotFoundError:
        return False


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_manifest_digest(archive: Path) -> tuple[str, str, str]:
    try:
        with tarfile.open(archive, "r:*") as bundle:
            index = json.load(bundle.extractfile("index.json"))
            descriptors = index.get("manifests", [])
            if len(descriptors) != 1:
                fail("expected a single-platform OCI archive containing one image manifest")
            descriptor = descriptors[0]
            digest = descriptor.get("digest", "")
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
                fail("Podman produced an OCI archive with an invalid manifest digest")
            blob_path = f"blobs/sha256/{digest.split(':', 1)[1]}"
            manifest_blob = bundle.extractfile(blob_path)
            if manifest_blob is None:
                fail("OCI archive is missing its image manifest")
            manifest_bytes = manifest_blob.read()
            if hashlib.sha256(manifest_bytes).hexdigest() != digest[7:]:
                fail("OCI archive manifest digest does not match its contents")
            image_manifest = json.loads(manifest_bytes)
            config_digest = image_manifest.get("config", {}).get("digest", "")
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", config_digest):
                fail("OCI archive has an invalid image config digest")
            platform = descriptor.get("platform", {})
            architecture = platform.get("architecture")
            operating_system = platform.get("os")
            if not architecture or not operating_system:
                config_path = f"blobs/sha256/{config_digest.split(':', 1)[1]}"
                config_blob = bundle.extractfile(config_path)
                if config_blob is None:
                    fail("OCI archive is missing its image config")
                image_config = json.load(config_blob)
                architecture = architecture or image_config.get("architecture", "unknown")
                operating_system = operating_system or image_config.get("os", "unknown")
            return digest, f"{operating_system}/{architecture}", config_digest
    except (OSError, tarfile.TarError, KeyError, TypeError, json.JSONDecodeError) as exc:
        fail(f"cannot inspect Podman OCI archive: {exc}")


def engine_path(path: Path, executable: str) -> str:
    """Convert WSL paths for the Windows Docker client when needed."""
    if os.name == "posix" and executable.lower().endswith(".exe"):
        result = subprocess.run(["wslpath", "-w", str(path)], check=True, text=True, capture_output=True)
        return result.stdout.strip()
    return str(path)


def select_decoder_implementation(
    manifest: dict, package: Path, requested: str | None
) -> tuple[str, dict]:
    implementations = manifest.get("decoderImplementations")
    if implementations is None:
        # Backward-compatible packages use their declared components and
        # Containerfile as a single Python implementation.
        implementations = {
            "python": {
                "status": "deployable",
                "decoder": manifest["components"]["decoder"],
                "mapper": manifest["components"]["mapper"],
                "containerfile": "Containerfile",
                "command": manifest["runtime"]["command"],
            }
        }
    deployable = {
        language: definition
        for language, definition in implementations.items()
        if isinstance(definition, dict) and definition.get("status") == "deployable"
    }
    if not deployable:
        fail("manifest has no deployable decoder implementation")

    if requested:
        if requested not in deployable:
            details = "; ".join(
                f"{language}: {definition.get('reason', 'not marked deployable')}"
                for language, definition in implementations.items()
                if isinstance(definition, dict) and language not in deployable
            )
            fail(
                f"decoder language '{requested}' is not deployable for this kid; "
                f"available: {', '.join(sorted(deployable))}. {details}"
            )
        selected = requested
    elif len(deployable) == 1:
        selected = next(iter(deployable))
        print(f"Decoder implementation: {selected} (only deployable option)")
    elif sys.stdin.isatty():
        choices = sorted(deployable)
        print("Deployable decoder implementations:")
        for index, language in enumerate(choices, start=1):
            print(f"  {index}. {language}")
        while True:
            answer = input("Choose decoder language: ").strip()
            if answer.isdigit() and 1 <= int(answer) <= len(choices):
                selected = choices[int(answer) - 1]
                break
            if answer in deployable:
                selected = answer
                break
            print(f"Choose a number from 1 to {len(choices)}, or a language name.")
    else:
        fail(
            "multiple decoder implementations are deployable; pass "
            "--decoder-language python|rust|typescript in non-interactive use"
        )

    implementation = deployable[selected]
    for field in ("decoder", "mapper", "containerfile", "command"):
        if field not in implementation:
            fail(f"decoderImplementations.{selected} is missing '{field}'")
    for field in ("decoder", "mapper", "containerfile"):
        source = (package / implementation[field]).resolve()
        try:
            source.relative_to(package)
        except ValueError:
            fail(f"decoderImplementations.{selected}.{field} escapes the package directory")
        if not source.is_file():
            fail(f"decoderImplementations.{selected}.{field} is missing: {source}")
    print(f"Selected decoder implementation: {selected}")
    return selected, implementation


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="billie kid build",
        description="Build a kid from a local source repository and create a portable bundle.",
    )
    parser.add_argument("package", type=Path, help="local directory containing billie-kid.yaml and Containerfile")
    parser.add_argument("--output", type=Path, help="bundle output directory (default: this checkout's dist/kids)")
    docker_executable = os.environ.get("BILLIE_DOCKER_BIN") or shutil.which("docker.exe") or shutil.which("docker") or "docker"
    available_engines = [engine for engine in ("podman", "docker") if shutil.which(engine)]
    parser.add_argument(
        "--engine", choices=("podman", "docker"), default=available_engines[0] if available_engines else None,
        required=not available_engines,
        help="workstation image builder (Podman or Docker Buildx; node runtime remains Podman)",
    )
    host_arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    parser.add_argument(
        "--platform", choices=("linux/amd64", "linux/arm64"),
        default=f"linux/{host_arch}" if host_arch else None,
        required=host_arch is None,
        help="target OCI platform (default: this workstation's architecture)",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing bundle with the same id and version")
    parser.add_argument(
        "--decoder-language", choices=("python", "rust", "typescript"),
        help="decoder implementation to build (interactive selection when multiple runtimes are deployable)",
    )
    args = parser.parse_args()

    package = args.package.expanduser().resolve()
    if not package.is_dir():
        fail(f"package directory does not exist: {package}")
    manifest_path = package / "billie-kid.yaml"
    if not manifest_path.is_file() or not (package / "Containerfile").is_file():
        fail("package must contain billie-kid.yaml and Containerfile")
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        fail(f"cannot read package manifest: {exc}")
    try:
        package_id = manifest["metadata"]["id"]
        version = manifest["metadata"]["version"]
    except (TypeError, KeyError) as exc:
        fail(f"manifest is missing package identity fields: {exc}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", str(package_id)):
        fail("metadata.id must be a lowercase package id")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?", str(version)):
        fail("metadata.version must be a semantic version")

    validator = Path(__file__).with_name("billie-kid-validate.py")
    if not validator.is_file():
        fail(f"kid validator is missing: {validator}")
    run([sys.executable, str(validator), str(package)])
    decoder_language, decoder_implementation = select_decoder_implementation(
        manifest, package, args.decoder_language
    )
    selected_executable = "podman" if args.engine == "podman" else docker_executable
    if shutil.which(selected_executable) is None:
        fail(f"selected container build engine is not installed: {args.engine}")
    if args.engine == "docker" and not command_succeeds([docker_executable, "buildx", "version"]):
        fail("Docker Buildx is required for OCI ARM64 bundle builds; install or enable the Docker Buildx plugin")

    output = (args.output or Path(__file__).resolve().parents[2] / "dist" / "kids").expanduser().resolve()
    safe_version = str(version).replace("+", "_build_")
    image_tag = f"localhost/open-billie/{package_id}:{safe_version}"
    bundle_name = f"billie-kid-{package_id}_{version}.tar.gz"
    destination = output / bundle_name
    checksum_sidecar = output / f"{bundle_name}.sha256"
    if (destination.exists() or checksum_sidecar.exists()) and not args.force:
        fail(f"bundle already exists: {destination}; use --force to replace it")

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".billie-kid-build-", dir=output) as temp_name:
        temp = Path(temp_name)
        image_archive = temp / "image.oci.tar"
        if args.engine == "podman":
            run([
                "podman", "build", "--pull=missing", "--platform", args.platform,
                "--file", str(package / decoder_implementation["containerfile"]), "--tag", image_tag, str(package),
            ])
            run(["podman", "save", "--format", "oci-archive", "--output", str(image_archive), image_tag])
        else:
            run([
                docker_executable, "buildx", "build", "--pull", "--platform", args.platform,
                "--file", engine_path(package / decoder_implementation["containerfile"], docker_executable), "--tag", image_tag,
                "--output", "type=oci,dest=image.oci.tar", engine_path(package, docker_executable),
            ], cwd=temp)
        oci_digest, architecture, image_id = image_manifest_digest(image_archive)
        if architecture != args.platform:
            fail(f"image builder produced {architecture}, but --platform requested {args.platform}")
        if args.engine == "podman":
            image_info_result = json.loads(run(["podman", "image", "inspect", image_tag], capture=True))
            image_info = image_info_result[0] if isinstance(image_info_result, list) else image_info_result
            actual_image_id = image_info.get("Id", "") if isinstance(image_info, dict) else ""
            if isinstance(actual_image_id, str) and re.fullmatch(r"[a-f0-9]{64}", actual_image_id):
                actual_image_id = f"sha256:{actual_image_id}"
            if not isinstance(image_info, dict) or actual_image_id != image_id:
                fail("Podman image ID does not match the OCI archive config digest")
        image_reference = f"localhost/open-billie/{package_id}@{oci_digest}"

        staged_manifest = dict(manifest)
        staged_manifest.pop("decoderImplementations", None)
        staged_components = dict(manifest["components"])
        staged_components["decoder"] = decoder_implementation["decoder"]
        staged_components["mapper"] = decoder_implementation["mapper"]
        staged_manifest["components"] = staged_components
        staged_runtime = dict(manifest["runtime"], image=image_reference)
        staged_runtime["command"] = decoder_implementation["command"]
        staged_manifest["runtime"] = staged_runtime
        stage = temp / "validated-package"
        stage.mkdir()
        (stage / "billie-kid.yaml").write_text(
            yaml.safe_dump(staged_manifest, sort_keys=False), encoding="utf-8"
        )
        shutil.copy2(package / "README.md", stage / "README.md")
        shutil.copy2(package / decoder_implementation["containerfile"], stage / "Containerfile")
        copied: set[str] = set()
        for component in staged_manifest["components"].values():
            relative = Path(component)
            source = (package / relative).resolve()
            try:
                source.relative_to(package)
            except ValueError:
                fail(f"component path escapes the package directory: {component}")
            key = relative.as_posix()
            if key in copied:
                continue
            copied.add(key)
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
        run([sys.executable, str(validator), str(stage), "--strict"])

        manifest_file = temp / "billie-kid.yaml"
        manifest_file.write_text(yaml.safe_dump(staged_manifest, sort_keys=False), encoding="utf-8")

        metadata = {
            "schema": "billie.kid.bundle.v1",
            "id": package_id,
            "version": version,
            "image": image_reference,
            "imageTag": image_tag,
            "imageId": image_id,
            "platform": architecture,
            "decoderLanguage": decoder_language,
            "ociManifestDigest": oci_digest,
            "imageArchiveSha256": sha256(image_archive),
            "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "signature": None,
        }
        metadata_file = temp / "bundle.json"
        metadata_file.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        sums_file = temp / "SHA256SUMS"
        sums_file.write_text(
            f"{sha256(manifest_file)}  billie-kid.yaml\n"
            f"{sha256(metadata_file)}  bundle.json\n"
            f"{sha256(image_archive)}  image.oci.tar\n",
            encoding="ascii",
        )

        partial = destination.with_suffix(destination.suffix + ".tmp")
        try:
            with tarfile.open(partial, "w:gz") as tar_bundle:
                for item in (manifest_file, metadata_file, image_archive, sums_file):
                    tar_bundle.add(item, arcname=item.name, recursive=False)
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
    checksum_sidecar.write_text(f"{sha256(destination)}  {destination.name}\n", encoding="ascii")
    print(f"Built kid bundle: {destination}")
    print(f"  package: {package_id}@{version}")
    print(f"  decoder: {decoder_language}")
    print(f"  image: {image_reference}")
    print(f"  platform: {architecture}")
    print(f"  checksum: {checksum_sidecar}")
    print("Bundle is unsigned; checksum detects file changes but does not identify its publisher.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
