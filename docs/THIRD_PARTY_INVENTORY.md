# Third-party software inventory

Inventory status: source-level review of tracked manifests, lockfiles, container definitions, and standards provenance, 2026-11-03. The repository includes `tools/generate_kid_sbom.py`, which creates SPDX JSON from the exact OCI image archived in a checksum-verified kid bundle. Current-source OETF 0.2.0 arm64 candidate SBOMs were generated and reviewed locally; findings and remaining release gates are in [SBOM_REVIEW.md](SBOM_REVIEW.md). They are local, unsigned candidates from a dirty working tree, not release artifacts.

The repository's Apache-2.0 license applies to Open Billie-authored material. It does not relicense dependencies, base images, standards, or other separately identified work. The platform package now carries `LICENSE` and `THIRD_PARTY_NOTICES.md` in its versioned release tree. The kid builder preserves an optional package `licenses/` directory in the staged build context; each runtime image must explicitly copy the license and notice files it needs. Package versions below are pinned by the referenced lockfile where one exists; distribution packages and image tags can resolve to different patch builds over time.

## Source and build dependencies

| Area | Declared dependencies | Scope and current evidence | Inventory status |
|---|---|---|---|
| Workstation validation and platform automation | `ansible-core==2.17.14`, `jsonschema==4.23.0`, `PyYAML==6.0.2` | `requirements-ci.txt`; Ansible also runs on the node. Declared CI versions are pinned, but Python transitive dependencies are not locked here. | Direct dependencies identified; transitive lock and license-text capture remain |
| Platform Debian package | `bash`, `ansible-core`, `podman`, `systemd`, `python3`, `python3-yaml`, `python3-jsonschema`, `openssl`, `curl` | `tools/build-platform-release.sh` Debian `Depends`; Ubuntu resolves these from its configured APT repositories at install time. | Direct package names identified; resolved Ubuntu package versions/licenses vary by repository state |
| Rust platform translator | See `runtime/rust/Cargo.toml` and `runtime/rust/Cargo.lock` | The lockfile pins the translator and its crate dependency graph. Cargo.lock does not record SPDX license identifiers or license texts. | Exact versions are locked; crate license data needs generated review |
| OETF Python decoder | No runtime Python dependencies; `pytest>=8` is a test extra | `kids/examples/oetf/packages/oetf/python/pyproject.toml` | Runtime is dependency-free at Python package level; test dependency is not locked |
| OETF Rust decoder | `serde_json` and its transitive crates | `kids/examples/oetf/packages/oetf/rust/Cargo.toml` and `Cargo.lock` | Exact versions are locked; crate license data needs generated review |
| OETF TypeScript decoder and runtime | Workspace packages plus `@changesets/changelog-github`, `@changesets/cli`, `@types/node`, `typescript`, `vite-node`, `vitest`, and `yaml` | `kids/examples/oetf/package.json` and `pnpm-lock.yaml`. The lockfile pins the transitive graph. A local Windows install exposed 156 unique package/version/license metadata tuples, including Windows-specific optional packages. | Source graph is locked; target Linux/ARM64 package set and bundled notices need artifact-level capture |
| GitHub CI and release tooling | GitHub-hosted Ubuntu images; actions pinned by commit; Cosign installer pinned by commit/version | `.github/workflows/ci.yml` and `release.yml` | Build/release tooling identified; not shipped in the Billie runtime. Recheck action and tool licenses if redistributing them |

## Standards references and source material

| Format | Reference basis | What this repository contains | Distribution note |
|---|---|---|---|
| SAPIENT | BSI Flex 335 v2.0; Dstl's `SAPIENT-Proto-Files` v2 protobuf definitions | Open Billie-authored encoder code and a test-only Prost model that mirrors the public message field layout. No `.proto` files or BSI document text are included. | Dstl's upstream `LICENCE.txt` states Crown-owned copyright 2023 and Apache-2.0 for the protobuf files except where stated otherwise. BSI retains copyright in its standard document. Keep this attribution and do not reproduce the standard text. |
| ASTERIX CAT062 | EUROCONTROL SPEC-0149-9, Edition 1.21 | Open Billie-authored implementation of a documented subset; no specification text is included. | EUROCONTROL identifies the referenced PDF as a released issue intended for general public use. Preserve the source reference and do not copy the document into the repository. |
| Cursor on Target | MIL-STD-6090, Cursor on Target Message Standard | Open Billie-authored CoT serializer/profile; no standard document is included. | The current document record is available through DLA ASSIST. Preserve the standard reference; do not include the document itself. |

These entries identify implementation references and copied-material boundaries. They do not claim ownership of the standards or provide a legal determination about reproducing any third-party specification text.

## Container images and node-side external software

| Component | Source declaration | Included or used where | Remaining inventory work |
|---|---|---|---|
| Eclipse Zenoh | `docker.io/eclipse/zenoh` pinned by SHA-256 digest in the Quadlet templates | Pulled onto every Billie node; included in the node's container image store, outside the platform `.deb` payload | Arm64 candidate SBOM is generated and the Alpine package records declare licenses. The `zenohd` binary is not a separate Syft record; tie the pinned digest to an exact upstream release, retain its EPL-2.0 OR Apache-2.0 license/NOTICE material, and scan each released architecture |
| Open Billie Python OETF | `python:3.12.10-slim-bookworm`; pip 25.0.1 in the upstream Python image vendors distlib 0.3.9 | Synthetic sensor simulator and Python kid image | Arm64 candidate SBOM generated. The Python runtime license file is retained in the image; distlib PSF-2.0 and its six Windows launcher's BSD-style notice are reviewed in `THIRD_PARTY_NOTICES.md`. Debian package `licenseDeclared=NOASSERTION` records still require package-by-package review |
| Open Billie TypeScript OETF | `node:22.14.0-bookworm-slim` in build and runtime stages | TypeScript kid image | The multi-stage image keeps pnpm install, compiler, and test dependencies in the build stage. The rebuilt arm64 candidate SBOM confirms these development packages are absent, and the image contains the vendored version-matched Node `LICENSE`. Debian license metadata and other `LicenseRef` expressions remain under review |
| Open Billie Rust OETF | `rust:1.85.1-slim-bookworm` build stage and `debian:12.12-slim` runtime stage | Rust kid image | Arm64 candidate SBOM generated; resolve Debian base-image `NOASSERTION` records and review compiled crate notices for each release architecture |
| Platform builder | `rust:1.75.0-bookworm` plus Debian build/cross-compiler packages | Build-only container used by workstation setup | Record resolved builder digest and retain the toolchain/package inventory with release provenance. The current image installs build-essential, ca-certificates, coreutils, dpkg-dev, git, Python 3, tar, Rust targets, and an architecture-specific GNU cross compiler |
| ARM smoke-test image | `docker.io/library/ubuntu@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac` plus Bash, Coreutils, dpkg, and passwd | Test-only; not a Billie runtime image | Digest-pinned from the Docker Official Image listing; keep separate from product SBOM unless this image is distributed |
| NetBird | Installed from the NetBird APT repository by optional `billie bootstrap` | Node networking prerequisite; independent of the Billie `.deb` | Record the installed version and vendor license for deployment records; it is not bundled by Open Billie |
| Host packages and services | Ubuntu 24.04 APT packages, including Podman, Ansible, systemd, OpenSSL, curl, and Python libraries | Installed as separate OS packages on the node | Capture `dpkg-query` output and package copyright/license files from the actual target when producing a deployment SBOM |

The OETF TypeScript Containerfile now builds in a dedicated stage and copies only compiled workspace packages, package metadata, and shared OETF data into the runtime stage. Its final image does not contain the pnpm workspace install or TypeScript/Vitest development dependencies. The SBOM must still be generated and reviewed from the exact architecture-specific output bundle before distribution.

## License metadata observed in the local TypeScript dependency tree

The local Windows pnpm installation reported 156 unique package/version/license metadata tuples: 136 MIT, 10 ISC, 3 BSD-2-Clause, 3 BSD-3-Clause, 2 Apache-2.0, 1 Python-2.0, and 1 package with the metadata value `SEE LICENSE IN LICENSE`. The latter package, `spawndamnit@3.0.1`, includes an MIT license file. The `Python-2.0` entry is `argparse@2.0.1` and carries its upstream Python license text.

These counts are a source-workstation snapshot, not an authoritative list of packages in a Linux ARM64 container. Optional native packages differ by OS and architecture. Use the lockfile to identify versions and inspect the built image for the exact package set and license texts before release.

## Artifact SBOM and notice work required before distribution

For a kid bundle, generate the SPDX JSON SBOM with:

```sh
python3 tools/generate_kid_sbom.py dist/kids/billie-kid-<id>_<version>.tar.gz
```

The command requires Syft on `PATH`, verifies the adjacent `.sha256` transfer sidecar and the internal `image.oci.tar` entry in `SHA256SUMS`, extracts the OCI image to a temporary directory, and scans that archive. The generated `.sbom.spdx.json` is written beside the bundle by default; review the SBOM and capture the Syft version, bundle checksum, image digest, and target architecture in release records. Syft supports OCI archives and SPDX JSON output; see [supported scan sources](https://github.com/anchore/syft/wiki/Supported-Sources) and [output formats](https://github.com/anchore/syft/wiki/Output-Formats).

For every platform architecture and every kid image that will be distributed:

1. Record the final image digest and build source revision.
2. Generate an SPDX or CycloneDX SBOM from the final image, not only from the source manifest.
3. Include the platform package's resolved APT dependency versions and the Zenoh image digest in the deployment bill of materials.
4. Check each package's license expression and ensure required MIT, BSD, ISC, Apache, Python Software Foundation (PSF-2.0), and other license texts or notices are retained in the artifact or accompanying release materials. The OETF TypeScript image must retain the complete Node license bundle, and the Python image must retain the distlib launcher BSD notice.
5. Verify generated notices against the final OCI archive and Debian package contents; do not infer them from source-only lockfiles. The platform and OETF build definitions now copy the project license and third-party notice file into their output artifacts; confirm the files are present in each final release.
6. Keep build-only tools separate from runtime dependencies in the SBOM and release notes.

The local OETF 0.2.0 candidate SBOMs cover Python, Rust, and TypeScript arm64 kid images, and an arm64 SBOM exists for the pinned Zenoh image. Review of the Python candidate resolved the distlib package license and the separate notice for its bundled Windows launcher binaries. The TypeScript candidate now includes the exact Node license file. Debian package license expressions, the pinned Zenoh release identity/notices, and the platform's statically linked translator dependencies and resolved APT versions remain open. Platform package and deployment-specific host inventories need completion before a complete deployment bill of materials is available. See [SBOM_REVIEW.md](SBOM_REVIEW.md) for details.

## Maintainer follow-up

- Confirm the copyright holder and authority to license each project-authored contribution. Do not list a contractor or organization unless it holds rights in the included work.
- The maintainer DCO declaration is present in `CONTRIBUTORS.md`. Each future code contributor must add their own declaration before code acceptance; do not add it on another person's behalf.
- Review the generated artifact SBOMs and notices for the exact target architectures before publishing platform or kid artifacts.
- If this project is ever released as a government-sponsored project, confirm the applicable organization approval, distribution, and reporting process with the responsible program and legal/security reviewers. Code.mil's workflow is guidance here, not a substitute for that approval.
