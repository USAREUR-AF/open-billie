# Billie Modular Golden Path Source Import Matrix

## Review basis

- Source repository: Billie Modular
- Reference branch: feat/deploy-platform-golden-path
- Reviewed revision: 45ce20b7ec4ca5996bcbed20059fb0445eb9bf7f
- Target: Open Billie, a sensor-neutral project
- Status: initial sensor-neutral platform slice implemented locally; the original synthetic OETF example is now included separately under `kids/examples/oetf/`; no source files were copied wholesale from the Billie Modular Golden Path branch

The Billie Modular Golden Path branch is a mixed platform and application tree. A clean-looking platform directory is not sufficient evidence that its contents are generic: its release builder currently includes the platform tree recursively, and the role contains both reusable host work and optional integration-specific behavior. Reuse is therefore file- and task-level, not branch-level.

## Import dispositions

| Source surface | Disposition | Open Billie treatment |
|---|---|---|
| deploy/bin/billie | Adapt; do not copy unchanged | Preserve the explicit operator lifecycle and transparent command execution. Start with single-node install, init/join, check, apply, verify, status, and health. Remove fleet-registry coupling and every declaration tied to a particular sensor, vendor, or private service. |
| deploy/platform/ansible.cfg and local inventory patterns | Candidate for reuse | Keep local convergence and predictable Ansible behavior. Recheck paths, privilege assumptions, supported Python, and all inventory inputs. |
| Main platform playbook, teardown playbook, and generic role tasks | Split and rewrite | Separate host/runtime baseline from optional kid activation and external integrations. Keep idempotent tasks, check-mode behavior, and safe teardown semantics. Nothing is imported until each task and variable is classified. |
| Platform defaults and example host variables | Rewrite as synthetic templates | Retain only generic node settings and obvious placeholders. No real node names, addresses, URLs, package namespaces, credentials, sensor names, or vendor-specific settings. |
| Generic health, watchdog, runtime, and fabric templates | Candidate after review | Review one file at a time for embedded endpoints, package names, identity assumptions, topic/key expressions, and sensor assumptions. Keep the resulting Open Billie templates generic and explicitly configured. |
| Integration-specific service units, scripts, variables, discovery tools, and feed clients | Exclude | Keep all sensor-specific and organization-specific integrations in their separate repositories. Open Billie must not package or depend on them. |
| deploy/tools/build-platform-release.sh | Reimplement its approach | Preserve versioned artifacts and positive allowlisting. The current recursive platform payload would carry mixed role content, so Open Billie needs a reviewed allowlist and an artifact-content gate. |
| Air-gap bundle and package delivery tools | Adapt selectively | Keep the connected-build / offline-delivery pattern if needed. Enumerate every package and image in the bundle; no implicit private registry pulls or unreviewed runtime payloads. |
| Platform tests | Recreate for Open Billie | Keep the ideas behind CLI declaration validation, pinned images, names-no-deployment checks, and package-content tests. Rebuild fixtures from generic values and synthetic data only. |
| Deployment guide, playbook, and lessons learned | Rewrite | Preserve the operator sequence and useful failure lessons. Replace all machine, account, endpoint, token, and organization-specific instructions with generic placeholders and safe secret-input patterns. |
| Application Builder packages and UI | Boundary reference only | Keep the separation between platform operations and kid/application lifecycle. Current package operations are `billie kid` subcommands; a separate builder UI is out of scope. Do not import private registry assumptions. |
| Sensor package trees, decoder/mapping examples, capture and analysis tools | Exclude | These contain sensor-specific behavior or data and remain outside this repository. Do not add them as submodules, workspace dependencies, generated artifacts, or CI inputs. |
| `billie-decoder-oetf` synthetic example | Include as an isolated sample kid | OETF is explicitly described by its source docs as a made-up format not modeled on real sensor interfaces. Its decoder implementations, schemas, maps, lookups, and synthetic conformance vectors live only under `kids/examples/oetf/`; the core release builder does not include this path. See the [OETF import record](provenance/OETF_IMPORT.md). |
| Licenses, notices, and release workflows | Review independently | Open Billie-authored source is Apache-2.0. Preserve applicable notices for approved source reuse and review generated artifact dependencies before redistribution. The repository license does not cover third-party dependencies or standards text. |

## Required release allowlist

The platform artifact may contain only reviewed platform CLI/runtime files, required documentation, and explicitly approved public-standard components. Synthetic kid examples may exist in the repository for conformance work, but remain outside the core artifact. It must exclude:

- node identity, inventory, host variables, private certificates, keys, tokens, and environment files;
- all sensor-specific decoders, mappings, lookups, schemas, captures, logs, and derived fixtures;
- private package references, private registries, and organization-specific feed configuration;
- generated files or build inputs that are not named in the allowlist.

The release build must fail when forbidden content is present. CI should inspect both the source selection and the final artifact; relying on .gitignore or a denylist is not enough.

## Gate before importing code

For every proposed file, record:

1. source path and exact source revision;
2. generic behavior to retain;
3. sensor, organization, or identity assumptions to remove;
4. license and third-party notice requirements;
5. destination path in Open Billie;
6. verification that the resulting file and its generated outputs contain no restricted data.

No source file is approved merely because its filename or parent directory looks generic.

## Implemented initial platform slice

The first local implementation is intentionally limited to the smallest sensor-neutral platform slice:

1. versioned platform artifact builder with a positive allowlist;
2. platform CLI for install/init-or-join/check/apply/verify;
3. local Ansible playbook and a minimal generic Podman/Quadlet runtime;
4. synthetic-only example and package-content checks.

The generic host baseline works without a kid package. The isolated OETF example provides synthetic decoder and mapper fixtures. Generic kid validation, local image build, bundle install, listener configuration, activation, and host-to-Zenoh orchestration are implemented. The operator reports that a separate, externally sourced kid package for a different sensor was built, installed, and exercised successfully. Its source and sensor identity remain outside this repository; see the validation log for the evidence boundary.
