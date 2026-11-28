# Release review: 0.3.0

The review the [release checklist](../OPEN_SOURCE_RELEASE_CHECKLIST.md) asks for before a platform or kid artifact is distributed: what the release ships, file by file, and its SBOMs and licence notices for each image digest and architecture.

State: **amd64 reviewed; arm64 waits for the release workflow's dry run.** The checklist boxes are ticked when both architectures are reviewed.

## What was reviewed

amd64: the files of a local build that runs `release.yml`'s build-job steps in order. It was built from `main` with the release-workflow, public-text and crate-notice changes merged in. The build is the same as the workflow's, except that it ran on a workstation, not a runner. The dry run's files replace it when they exist.

| File | Size |
|---|---:|
| `billie-platform_0.3.0-<rev>_amd64.deb` | 1.0 MB |
| `billie-platform-0.3.0-<rev>_amd64.tar.gz` | 1.2 MB |
| `billie-kid-weather-station-bite_0.1.0_amd64.tar.gz` | 30 MB |
| `billie-kid-weather-station-bite_0.1.0_amd64.spdx.json` | 2.5 MB |
| `billie-platform_0.3.0-<rev>_amd64.crates.spdx.json` | 56 KB |

## Contents, file by file

**Platform package.** It holds 34 files (35 with the `THIRD_PARTY_CRATES.txt` this change adds) under `/opt/billie/platform/releases/<version>/`, plus `DEBIAN/control` and `DEBIAN/postinst`:
- the CLI and its 10 helper scripts (`bin/`), and the translator binary;
- `VERSION`, `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` and `THIRD_PARTY_CRATES.txt`;
- `schemas/kid-manifest.schema.json`;
- the local Ansible plays, inventory and `ansible.cfg` (`platform/`), and 11 templates.

The tarball holds the same tree. `tools/check_release_artifact.py` checks that the two match and that the tree holds no key, `.env`, inventory or host variables. Each file was read. They hold no credentials, real sensor data, deployment addresses or site names. The one address is the Zenoh image the platform runs, pinned by digest.

**Kid bundle.** It holds `billie-kid.yaml`, `bundle.json`, `SHA256SUMS` and `image.oci.tar`:
- **Image:** linux/amd64, 6 layers, on Debian 12.12-slim.
- **Kid files:** `/usr/local/bin/billie-bite-kid`, the synthetic weather-station dictionary and its vectors (`/app/schemas/weather-station/`), the map to Canonical Track v2, one lookup table, and `/licenses/`.
- **Environment:** bind, port, transport, translator socket, the dictionary paths and the outputs. No secrets.
- **Not pinned:** the base images are named by tag in the Containerfile, so the bundle records the resolved digest but a rebuild may resolve another.

**Needle scan.** goatprivate's leak gate (1705 needles) ran over the unpacked package, the tarball, the bundle's files, the image's `/app` and `/licenses`, both SBOMs and the printable strings of both binaries. Every hit was upstream text, and none is ours:
- the Debian packages' maintainer addresses in the kid SBOM, and one Debian maintainer's name that matches a needle;
- SAPIENT specification section numbers in the translator, read as addresses.

**Licence texts.** Kept as their licences require: the Node.js licence under the OETF example (not in this release) and the files copied unchanged from goat-transformers.

## SBOMs and licence notices

| Image or binary | Architecture | Digest | SBOM | Finding |
|---|---|---|---|---|
| weather-station-bite kid image | amd64 | `sha256:f88077c9…` (OCI manifest) | `…_amd64.spdx.json`, Syft 1.57.2 | Debian base packages, each with its `/usr/share/doc/<package>/copyright` in the image. The decoder's 15 third-party crates had no licence text in the image (fixed below). |
| translator, in the platform package | amd64 | the package's `SHA256SUMS-amd64` entry | `…crates.spdx.json` (the lockfile's crates) | 12 third-party crates (MIT, MIT or Apache-2.0, Unlicense or MIT, and goat-transformers under Apache-2.0) were compiled in with no licence text in the package (fixed below). |
| Zenoh image the platform runs | amd64, arm64 | `docker.io/eclipse/zenoh@sha256:157965d7…` | Syft 1.57.2, kept with this review, not published | 18 Alpine packages, each with a declared licence. `zenohd` is not seen as a package. The platform pulls the image from its registry and does not redistribute it. |

**Fixed in this change.** `tools/crate_notices.py` writes, from each lockfile, every third-party crate the binary is built from: its version, licence expression and source, and the licence files it ships, verbatim. For a crate inside a git repository it takes the files at the repository's root.
- **The translator's file:** `runtime/rust/THIRD_PARTY_CRATES.txt`, installed in the platform release beside `THIRD_PARTY_NOTICES.md`.
- **The kid's file:** `kids/examples/weather-station-bite/licenses/THIRD_PARTY_CRATES.txt`, copied into the image at `/licenses/` by the Containerfile's existing `COPY licenses/`.
- **The check:** CI fails when either file is not current.

**Still open.**
- The Syft SBOMs leave `licenseConcluded` as `NOASSERTION`. This review does not rewrite them.
- The crates SBOM lists the lockfile's crates, test-only ones included. `THIRD_PARTY_CRATES.txt` lists the ones built into the binary.

## arm64

Not yet reviewed. When the dry run's `signed` artifact exists, the same reads and scans are run over its arm64 files and recorded here, together with the dry run's amd64 files.
