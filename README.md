# Open Billie

Open Billie is a sensor-neutral project intended for open-source distribution for preparing a node, building sensor-specific kid packages, and publishing normalized data through the shared Billie translator and Zenoh path. It follows the single-node provisioning flow from the Billie Modular Golden Path and OctoPod.

A project-level license has not yet been declared. Do not redistribute this repository or bundled third-party material until the project license and required notices are finalized.

The node runs Billie locally after installation. Keep proprietary sensor protocols, decoders, mappings, captures, credentials, and deployment-specific endpoint details outside this repository. The in-repository OETF package and sensor simulator use synthetic data.

## Start here

Read the [provisioning guide](deploy/README.md) before installing. It lists prerequisites, Windows/macOS/Linux instructions, credential inputs, wizard prompts, and troubleshooting steps.

### Workstation support

- **Windows 10/11:** Run the guided workflow from PowerShell; it launches Bash inside Ubuntu 24.04 on WSL 2. Use a normal Ubuntu distribution, not Docker Desktop’s internal WSL distribution. SSH keys and host-key trust must be available to the WSL user running the wizard.
- **Linux:** Run the Bash workflow from a terminal at the repository root.
- **macOS:** Run the Bash workflow from a terminal. The wizard builds the Linux platform package in a Docker or Podman Linux container, or installs an existing release. Kid package builds use the same container engine.

The target node is **Ubuntu Server 24.04**, `amd64` or `arm64`, with SSH access and non-interactive `sudo`. The wizard checks the selected release, node architecture, SSH access, and prerequisites before installing. For kid image builds, install Podman or Docker Buildx; cross-architecture builds also need image emulation. The provisioning guide has platform-specific setup details.

### Run the guided setup

From the repository root:

**Windows PowerShell**

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\setup.ps1
```

**Linux or macOS**

```sh
bash tools/setup.sh
```

The wizard builds a local platform release or uses an existing one, verifies it, installs it over SSH, configures node identity and fabric settings, checks the platform, and then offers the kid deployment wizard. It may bootstrap NetBird when enrollment is needed; obtain the one-time setup key from the network administrator. You will need the authorized Zenoh endpoint, key prefix, CA certificate, client certificate, and private key when connecting to a fabric. The wizard accepts a credential folder and does not ask you to paste private-key contents.

## Build and deploy a kid

A kid package contains a sensor decoder, schema, user-defined mapping and lookups, synthetic conformance vectors, and a runtime adapter. The user mapping converts sensor fields into Billie’s canonical record. The shared Rust translator fills the selected CoT, ASTERIX CAT062, or SAPIENT output format. The Open Billie platform owns local Zenoh, fabric mTLS, routes, and the bridge; kid packages do not need fabric credentials or their own encoders.

Start with the [kid package authoring guide](docs/KID_PACKAGE_AUTHORING_GUIDE.md), [package template](kids/_template/README.md), and [kid package contract](docs/architecture/KID_PACKAGE_CONTRACT.md). The guide covers schema and contract design through decoder and mapper implementation, conformance testing, build, install, configuration, and activation.

See [upgrade notes](docs/UPGRADING.md) before updating an existing node; platform 0.3.0 requires kids to use the v2 canonical track contract.

The local tools can scan and validate kid sources, build a package for `linux/amd64` or `linux/arm64`, and ask which deployable decoder implementation to use when multiple are available. The guided deployment flow transfers and installs the selected package, lets you choose a declared TCP or UDP listener, configures the node sensor-facing address and host port, and activates the kid. A node address can be set on a dedicated sensor interface before a sensor is connected. One listener is active per kid at a time.

Kid bundles are separate from the platform release and are currently unsigned. Their checksums detect file changes but do not authenticate the builder. Do not treat a checksum as a signature.

## Data flow

```text
Sensor TCP/UDP input
        -> kid decoder and user mapping
        -> canonical record over local Unix socket
        -> shared Rust translator and encoder
        -> local Zenoh route
        -> Open Billie platform mTLS bridge and remote fabric
```

The [decoder-to-translator contract](docs/architecture/DECODER_TRANSLATOR_RUNTIME_CONTRACT.md) and [Open Billie Zenoh and fabric security notes](docs/architecture/GOLDEN_PATH_ZENOH.md) describe these boundaries.

## Teardown

Remove a kid while keeping Billie installed with `sudo billie kid deactivate <id>` and `sudo billie kid remove <id>`. Remove the Billie platform with `sudo billie teardown`. Teardown lists what it will remove, asks for confirmation, and requires a second confirmation before deleting node identity and fabric credentials. NetBird is left untouched. See the [lifecycle and teardown guide](docs/KID_LIFECYCLE_AND_TEARDOWN.md).

## Current status and limits

The platform supports Ubuntu Server 24.04 on `amd64` and `arm64`. The public OETF example has Python, TypeScript, and Rust decoder runtimes with TCP/UDP capabilities; the sensor simulator can exercise a declared listener. A clean ARM64 Pi run on platform 0.2.1 completed platform provisioning, OETF kid installation and TCP activation, and `billie verify`. The kid logged accepted CoT, CAT062, and SAPIENT output; the operator confirmed an OETF publication through an authorized fabric subscriber. The 0.2.1 listener-forwarding fix was exercised on the Pi. Platform 0.3.0 changes the canonical track contract; rebuild v1 kids before upgrading. See the [upgrade guide](docs/UPGRADING.md) and [validation log](docs/TESTING.md) for scope and remaining gaps.

Other open validation includes independent SAPIENT receiver interoperability, fresh live NetBird enrollment, independent remote health receipt, and the published GitHub signing workflow. See the [testing log](docs/TESTING.md) and [project plan](docs/PROJECT_PLAN.md) for evidence and remaining work.

## Project boundaries

Open Billie core does not include proprietary sensor data or depend on a GitHub package registry for private kid packages. Keep each sensor owner’s decoder, schemas, mappings, lookups, and data in its own controlled source repository. Include only synthetic examples or material whose public provenance and licensing are clear.
