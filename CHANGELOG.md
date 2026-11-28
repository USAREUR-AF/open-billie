# Changelog

Notable changes to Open Billie are recorded here. The project has not made a
versioned public release yet; entries under `0.3.0` describe the current
release candidate and must be reviewed against the tagged source before release.

## [0.3.0] - Unreleased

### Added

- Guided platform setup, kid package selection/build/deployment, network
  configuration, and teardown workflows.
- Python, TypeScript, and Rust OETF example decoders and mapper implementations.
- `kids/examples/weather-station-bite`: a synthetic Rust kid whose decoder is
  the first-bite `bite` library reading a dictionary shipped as data, with a
  data-driven map to Canonical Track v2.
- `billie mapper generate --format bite-schema` reads the JSON Schema that
  `bite schema <dictionary>` prints.
- TCP and UDP sensor input support and local translator output for CoT,
  ASTERIX CAT-062, and SAPIENT.
- Kid bundle checksum verification, source-boundary scanning, release hygiene
  checks, and ARM64 platform smoke-test tooling.
- A release is one signed `SHA256SUMS` over every file it publishes: the
  platform `.deb` and tarball for amd64 and arm64, the synthetic
  weather-station-bite kid bundle for each, and SPDX SBOMs of each kid image
  and of the translator's crates. It is signed keylessly by the release
  workflow, which can also be run by hand as a dry run. See
  [RELEASING.md](RELEASING.md).
- Project licensing, contribution, security-reporting, provenance, and
  third-party inventory documents.
- Optional goat-transformers encoder path for CoT, ASTERIX CAT-062, and
  SAPIENT behind the cargo feature `goat-transformers`, selected per output
  format with `BILLIE_COT_ENCODER`, `BILLIE_CAT062_ENCODER`, and
  `BILLIE_SAPIENT_ENCODER`. The default is the native encoder; a build without
  the feature is unchanged. See the
  [encoder option](docs/architecture/GOAT_TRANSFORMERS_ENCODER_OPTION.md) for
  the measured differences from the native encoders.

### Changed

- Release file names use `-` between the version and the source revision
  (`billie-platform_0.3.0-<rev>_<arch>.deb`); the package's own version keeps
  `+`. `tools/install-to-node.sh` accepts both names.
- The goat-transformers encoder path is on by default (cargo feature
  `goat-transformers`): CoT and ASTERIX CAT-062 use it unless
  `BILLIE_COT_ENCODER` or `BILLIE_CAT062_ENCODER` says `native`; SAPIENT stays
  native. A `--no-default-features` build is native only.
- Translator requests now require explicit test and simulation flags before
  publication.
- Platform health reports degraded state when required services, sockets, or
  the local Zenoh health endpoint are unavailable.
- Platform and example-kid artifacts include applicable project license and
  third-party notice files.
- OETF example fixtures use neutral coordinates and its Python package uses a
  setuptools version that supports SPDX license metadata.
- License, notice, intent, conduct, security and contributing documents follow
  the USAREUR-AF open-source baseline: U.S. Government work under Apache-2.0,
  per-commit DCO sign-off, signed commits, code-owner review, private reporting.
- `NOTICE` lists the OETF TypeScript decoder files adapted from Billie Modular,
  an earlier U.S. Government project, under the same terms as the rest of Open
  Billie. The ISC notice naming DesertGOAT is removed; it did not reflect who
  wrote Billie Modular.
- `LICENSE` is the verbatim Apache-2.0 text; `INTENT.md` and `CONTRIBUTING.md`
  carry the Code.mil licensing intent and contribution policy.

### Security

- Update the OETF development toolchain to Vitest 4.1.12, Vite 6.4.5,
  and esbuild 0.25.12, and remove the old vite-node/Tinypool dependency chain.
- Update the CI Ansible Core pin from 2.17.14 to 2.21.6. This does not
  upgrade Ubuntu-managed Ansible on deployed nodes. See the
  [dependency security update notes](docs/UPGRADING.md#dependency-security-updates-2026-11-07).

### Fixed

- A kid could stop receiving sensor data after a restart that did not go
  through `billie kid activate`. `billie cat062 source set|remove` and
  `billie apply` restart the translator, and with it the kid; systemd
  restarts a kid on failure and at boot. The new container gets a new Podman
  address, but the DNAT rule for the host port to the removed container could
  stay first in the chain, so every datagram went to a dead address while the
  kid showed active. The kid unit now runs `billie-kid-ops.py prestart` before
  every start. It removes the old container and every port forward for the
  listener that targets no existing container, as activation does.
  `billie kid status` now checks that the listener's DNAT rules target the
  running container and reports a mismatch with the repair. A kid activated
  before this release keeps its old unit until `billie kid activate <id>` is
  run once.
- The island-to-fabric bridge forwarded CoT XML (`application/xml`) as its
  base64 text, so fabric subscribers received base64 instead of XML. The
  island's Zenoh REST plugin gives the payload of every encoding other than
  JSON (`application/json`, `text/json`, `text/json5`) and plain text
  (`text/plain`, `zenoh/string`) as base64. The bridge now decodes it and
  forwards the payload bytes: XML, ASTERIX and SAPIENT binary arrive unchanged,
  and JSON is written back as JSON.
- SAPIENT object identity creation is serialized so concurrent requests retain
  a single stable mapping per track identity.
- The public-boundary scanner no longer embeds private downstream product
  names in its source code.
- The ARM64 smoke-test image reference is pinned by digest.
