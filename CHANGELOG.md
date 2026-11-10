# Changelog

Notable changes to Open Billie are recorded here. The project has not made a
versioned public release yet; entries under `0.3.0` describe the current
release candidate and must be reviewed against the tagged source before release.

## [0.3.0] - Unreleased

### Added

- Guided platform setup, kid package selection/build/deployment, network
  configuration, and teardown workflows.
- Python, TypeScript, and Rust OETF example decoders and mapper implementations.
- TCP and UDP sensor input support and local translator output for CoT,
  ASTERIX CAT-062, and SAPIENT.
- Kid bundle checksum verification, source-boundary scanning, release hygiene
  checks, and ARM64 platform smoke-test tooling.
- Project licensing, contribution, security-reporting, provenance, and
  third-party inventory documents.

### Changed

- Add pull-request DCO validation, weekly Dependabot updates, and public Scorecard reporting; display the Scorecard badge in the README.
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

- SAPIENT object identity creation is serialized so concurrent requests retain
  a single stable mapping per track identity.
- The public-boundary scanner no longer embeds private downstream product
  names in its source code.
- The ARM64 smoke-test image reference is pinned by digest.
