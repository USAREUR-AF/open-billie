# Open Billie Project Plan

## Objective

Build a sensor-neutral Billie platform that follows the Billie Modular Golden Path for provisioning and operations, while keeping proprietary sensor packages and deployment identity outside this repository.

The primary reference is Billie Modular branch feat/deploy-platform-golden-path, commit 45ce20b7ec4ca5996bcbed20059fb0445eb9bf7f. OctoPod main (reviewed at 7e167aa) provides the provisioning and operator-flow reference that the Billie Modular Golden Path explicitly mirrors. These are design and implementation references, not safe source trees to copy wholesale.

## Target deployment flow

The first milestone is the single-node, self-hosted CLI path:

1. A host-provisioning stage produces a supported Ubuntu Server 24.04 node with SSH and the required operator access.
2. The workstation builds an allowlisted, versioned platform artifact and verifies its SHA256 manifest.
3. The operator transfers the artifact to the node and installs it with apt.
4. The operator runs billie install, then declares the node with billie init or joins the approved network through a secure enrollment flow.
5. For a connected node, the operator bootstraps NetBird and joins using a protected setup-key file; an isolated node uses billie init.
6. The operator previews changes with billie check, applies them with billie apply, and confirms platform health with billie verify.
7. Kid packages can be configured, activated, inspected, deactivated, and removed; the Billie platform can be torn down, deleting identity and fabric credentials by default after a second confirmation. Use --preserve-credentials to retain them.

The workstation is the build and delivery point. The node runs the platform locally and does not clone the full source repository.

### Current acceptance state

The workstation handoff and generic platform baseline have been exercised in development environments. Signed test artifacts, local bootstrap/init flows, mocked join behavior, check/apply/verify/status, synthetic kid validation and scanning, mapper generation, and the local translator contract have been checked. A clean ARM64 Pi run on platform 0.2.1 completed provisioning, OETF TCP kid deployment, and `billie verify`; the operator confirmed an OETF publication through an authorized fabric subscriber. Platform 0.3.0 introduces a breaking canonical track contract and requires v1 kids to be rebuilt. The production GitHub keyless release workflow and fresh NetBird enrollment still need validation. See [the upgrade guide](UPGRADING.md) and [the validation log](TESTING.md).

This acceptance covers local test-key signature verification and automated remote platform installation, plus local NetBird bootstrap and CLI join handoff. It does not validate the GitHub OIDC release job or a fresh NetBird management enrollment. The test Pi accepted the OETF 0.1.4 TCP runtime and all three encoder outputs. Platform 0.2.1 cleaned and verified the listener forward during the clean Pi run. Independent SAPIENT receiver checks remain. See the [validation log](TESTING.md).
## Architecture boundaries

- Platform: operator CLI, local Ansible convergence, host/runtime dependencies, generic service templates, health reporting, and release/update tooling.
- Node identity: per-node declarations and credentials live outside the source tree and survive platform upgrades.
- Kid packages: sensor-specific decoders, schemas, mappings, and lookups live in independently maintained packages, following the [kid package contract](architecture/KID_PACKAGE_CONTRACT.md). The core release never embeds those protocol details.
- Public components: public-standard encoders and generic translators may live in Open Billie after source and redistribution provenance is reviewed.
- Examples: synthetic fixtures only. Fictional sensor examples are permitted; real captures and proprietary protocol samples are not.
- Build outputs: release artifacts are assembled from a positive allowlist and tested for secrets, deployment identity, and sensor-specific material.

## Proprietary-data firewall

Do not import from sensor-specific repositories or directories: decoders, mappers, translators containing sensor rules, lookup tables, interface-control documents, protobuf schemas derived from private interfaces, packet captures, logs, or test fixtures. Do not add submodules or build-time dependencies on restricted repositories.

The Billie Modular Golden Path branch contains both generic platform behavior and sensor-specific packages or deployment details. Keep sensor-specific packages, site facts, credentials, and unrelated integrations outside Open Billie. Implement and review the generic provisioning, Zenoh, mTLS, routing, and bridge behavior in Open Billie.

Node names, IP addresses, organization URLs, NetBird setup keys, certificates, registry tokens, and per-site configuration stay outside Git and release payloads.

## Implementation phases

### Phase 0 - Source boundary

- Inventory candidate files from Billie Modular and Billie OSS-Beta.
- Classify each candidate as generic platform, public-standard component, synthetic example, or restricted.
- Record source, license/provenance, and inclusion decision for every imported file.
- Scan current files, Git history, generated artifacts, examples, and CI inputs for sensor-specific and deployment-specific data.

See [the source import matrix](SOURCE_IMPORT_MATRIX.md). The platform is implemented locally; the synthetic OETF components are included as a separately documented example kid with a provenance record.

### Phase 1 - Platform contract and first slice

- Define supported host OS and architecture requirements.
- Define the platform artifact, versioning, checksums, signature verification, and release allowlist. (Implemented; production release workflow validation remains.)
- Define persistent identity and data locations, separate from versioned platform software.
- Use billie for the implemented kid package lifecycle; a separate billie-builder application remains deferred.
- Build and verify the empty-node platform baseline. (Exercised on WSL2.)
- Add the workstation SSH installer and node-side NetBird bootstrap/init/join path. (Exercised on WSL2; real network enrollment remains.)
- Define the canonical mapper-to-translator runtime path before general kid deployment; the OETF example now exercises it, with further generic plug-in acceptance remaining.
- Define the canonical mapper-to-translator contract and shared Rust validation layer. (Implemented.) Canonical track identity is scoped by authenticated kid, source ID, track ID, and track generation; CoT and SAPIENT encode this full identity. CAT062 supports configured source-specific SAC/SIC assignments. CoT XML, initial CAT062, and SAPIENT BSI Flex 335 v2.0 protobuf serializers plus local IPC and the loopback Zenoh publisher are implemented. SAPIENT interoperability acceptance remains. The Open Billie Zenoh island, separate mTLS client, route bridge, and CLI fabric configuration are implemented; node acceptance remains.

### Phase 2 - Generic node runtime

- Implement the sensor-neutral local Ansible role and Podman/Quadlet services.
- Keep base platform services independent of any sensor package.
- Specify the generic kid manifest and repository template. (Contract and scaffold added; build/install/configure/activate/status/deactivate/remove commands are implemented.)
- Add a generic kid package validator, builder, installer, and activator. (Offline source validation, local OCI bundle building, checksum-verified node install, and selected-listener stateless activation are implemented; signatures and persistence remain.)
- Discover local kid repositories and report build/deployment readiness. (`billie kid scan` and the guided package-selection/build/deploy wizard are implemented.)
- Build kid artifacts directly from local source repositories; do not require publishing decoders or mappers to GitHub Packages. (Local Podman build, unsigned OCI transfer bundle, and node load/install path implemented.)
- Add schema adapters for the Billie JSON decode-schema format and Protocol Buffers. (Both adapters now generate mapping-contract files; JSON and protobuf fixtures pass through the existing OETF mapper engine. The protobuf path requires optional `protoc` and Python protobuf tooling.) Generate scaffolds from discovered fields, enums, units, and message structure; require review and explicit mapping choices for semantic conversions.
- Add local package discovery and a prompt-driven CLI flow. (The workstation setup wizard scans available packages and offers kid deployment; tools/deploy-kid.sh provides the standalone guided path. Explicit CLI flags remain available for automation.)
- Integrate the existing host-provisioning handoff rather than duplicating OS imaging and disk setup.

### Phase 3 - Synthetic acceptance path

- Use the in-repository OETF synthetic kid and sample frame to validate kid installation through the Open Billie platform transport. Keep its decoder, schemas, maps, and lookups together under `kids/examples/oetf`; do not publish the language packages to GitHub Packages.
- Verify dry-run output, idempotent apply, service health, and OETF output delivery. UDP and TCP have produced successful test Pi runs; a clean ARM64 TCP deployment on platform 0.2.1 passed `billie verify` and the operator confirmed publication through an authorized fabric subscriber. Stateless kid upgrade and rollback commands are implemented; the upgrade/rollback flow still needs Pi acceptance.
- Validate connected and offline image/package delivery where required.
- Exercise on a VM first, then on a supported Pi.

### Phase 4 - Release readiness

- Add CI checks for CLI behavior, Ansible syntax, package contents, dependency lockfiles/versioned image tags, and provenance metadata. (CI workflow added; validate it on GitHub before marking the gate complete.)
- Refuse release artifacts containing credentials, node identities, private package references, or sensor-specific data. (The workstation scanner checks current tracked files and release payloads for high-confidence credentials, private registry references, personal workstation paths, packet-capture files, internal product names, and deployment-specific IP literals. The reachable-history scan detects these classes but currently reports older commits; cleaning that history remains a release decision.)
- Document setup, use, upgrade, rollback, troubleshooting, and recovery from a clean-machine perspective.
- Establish the project license and third-party redistribution notices before publishing.

## Initial acceptance criteria

- A prepared Ubuntu Server 24.04 node can be installed and configured entirely through the documented CLI flow.
- The platform artifact contains no proprietary sensor implementation or deployment identity.
- The generic health timer is active and billie verify passes.
- Repeating apply does not change an already-converged node.
- A future release can be verified and rolled back without replacing node identity or deleting persistent data.
