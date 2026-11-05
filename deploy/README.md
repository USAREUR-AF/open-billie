# Install and configure Open Billie

This guide takes you from a workstation checkout to an installed Billie platform on a prepared Ubuntu node, then optionally into kid deployment. The same guided setup runs on Linux, macOS, and Windows through WSL. It prompts for platform build/install, configures the node identity and fabric, then offers the kid deployment wizard.

For a complete sensor-package authoring walkthrough, see [Create a Billie kid package](../docs/KID_PACKAGE_AUTHORING_GUIDE.md).

## Prerequisites

The requirements depend on which steps you will run. A workstation that installs a prebuilt release does not need Rust or Debian packaging tools. Building a kid requires an OCI image engine. The target node is always a prepared Ubuntu Server machine.

### Required for every workstation

- A checkout of this repository and permission to read the selected kid source folder.
- A terminal and Bash. The guided scripts work with macOS's built-in Bash 3.2; Homebrew Bash is optional.
- OpenSSH client tools, `ssh` and `scp`, with the node reachable over LAN, VPN, or another authorized route.
- A key-based SSH login whose private key is already unlocked by `ssh-agent` or the operating-system keychain. The wizards use non-interactive SSH and cannot prompt for a key passphrase.
- The node's SSH host key recorded in `known_hosts` and its fingerprint verified through a trusted channel. On first connection, connect manually, verify the fingerprint, and then run the wizard. Do not accept an unverified host key.
- Python 3.10 or newer, plus **PyYAML** and **jsonschema** for scanning, validating, and building kid packages.
- GNU `sha256sum`. macOS provides this through Homebrew Coreutils; the scripts require the GNU command and `--check --strict` behavior.
- A deployment account on the node with non-interactive `sudo` (`sudo -n true` must succeed). The guided setup and kid wizard check this before making changes.

### Select the workstation packages for your platform

#### macOS

Install Xcode command line tools if they are not already present, then install Homebrew using its official installer. In a new terminal, install Git, Python, and GNU Coreutils:

```sh
xcode-select --install
brew install git python@3.12 coreutils
export PATH="$(brew --prefix coreutils)/libexec/gnubin:$PATH"
```

Create a Python virtual environment and install the validation libraries. Activate this environment in every terminal used to run setup or the kid wizard:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install PyYAML jsonschema
```

Install **Docker Desktop** with Buildx, or Podman Desktop. The Linux container engine is used both to build the platform `.deb` on macOS and to build kid images. For Podman, initialize a machine if you do not already have one, then start it before building:

```sh
podman machine init
podman machine start
podman info
```

Check existing machines first with `podman machine list`; do not run `podman machine init` again if a machine already exists.

For Docker, verify the engine and builder are available:

```sh
docker version
docker buildx version
docker buildx inspect --bootstrap
```

The guided setup can build the Billie platform on macOS inside a Linux container. It uses a Rust 1.75 Debian-based builder, selects a Linux container matching the Mac's CPU architecture, and cross-compiles for the selected node architecture. The first build downloads the builder image and packages. This platform build uses a cross-compiler and does not need ARM emulation. The same Docker/Podman engine is later used for the kid image build; Apple Silicon builds ARM64 kid images natively, while an Intel Mac needs ARM64 emulation for ARM64 kid images. If the selected Docker builder rejects `--output type=oci` during a kid build, create and select a container builder with `docker buildx create --name open-billie-builder --driver docker-container --use`, then run `docker buildx inspect --bootstrap`.

The setup and kid deployment wizards check that an engine is installed and responding before they build. They report whether Docker or Podman is missing, stopped, or ready; for kid builds they also check for Docker Buildx. If both engines are installed, the wizard uses a running Podman engine first, then a running Docker engine. It will not choose an installed but stopped Podman machine over a working Docker engine. To inspect readiness yourself, run `bash tools/check-container-prerequisites.sh platform` or `bash tools/check-container-prerequisites.sh kid`. If both engines are ready and you want to choose one explicitly, set `BILLIE_CONTAINER_ENGINE=docker` or `BILLIE_CONTAINER_ENGINE=podman` in the terminal before starting the wizard.

The platform builder itself still runs in Linux because it needs Linux tools such as `dpkg-deb` and GNU `readlink -f`. The setup wizard runs it in the configured container engine, then uses the generated package and checksum files from `dist/`. A local build is unsigned and defaults to checksum-only verification. Signed prebuilt releases require `sha256sum` and Cosign.

#### Ubuntu or Debian workstation

For the complete guided flow, install the system Python modules (this also avoids Ubuntu 24.04's restriction on global `pip` installs):

```sh
sudo apt-get update
sudo apt-get install -y git bash openssh-client python3 python3-yaml python3-jsonschema coreutils tar
```

For kid builds, install **one** image engine:

```sh
sudo apt-get install -y podman uidmap slirp4netns
```

Rootless Podman needs subordinate UID/GID ranges in `/etc/subuid` and `/etc/subgid` for the user running the wizard. Confirm them with `grep "^$(id -un):" /etc/subuid /etc/subgid`; use your distribution's documented range allocation if either is missing. `slirp4netns` supplies rootless networking. On a native same-architecture build, ARM emulation is not required.

To build the platform `.deb` locally, also install Rust/Cargo (Rust 1.75 or newer) and Debian packaging tools:

```sh
sudo apt-get install -y rustc cargo dpkg-dev
rustc --version
cargo --version
```

The build script needs `dpkg-deb`, `tar`, and GNU `sha256sum`; `dpkg-dev` supplies the Debian packaging tools on Ubuntu/Debian. The script also checks the selected Rust standard-library target and cross linker.

#### Cross-building a platform release for ARM64 from Linux x86-64

Install the GNU aarch64 cross compiler and the matching Rust standard library target for the active toolchain. For rustup-managed Rust:

```sh
sudo apt-get install -y gcc-aarch64-linux-gnu
rustup target add aarch64-unknown-linux-gnu
BILLIE_TARGET_TRIPLE=aarch64-unknown-linux-gnu bash tools/build-platform-release.sh
```

For a kid image build from x86-64 to ARM64, the OCI engine also needs ARM64 binfmt/QEMU emulation; see [cross-architecture kid builds](#cross-architecture-kid-builds).

#### Windows 10/11

Use Ubuntu 24.04 in WSL 2; the setup launcher and Bash scripts run inside that distribution. Install the same Ubuntu/Debian packages above there. For Docker Desktop, enable WSL integration for Ubuntu and use `--engine docker` if Podman is not installed in WSL. SSH keys and `known_hosts` inside WSL are separate from Windows OpenSSH unless you explicitly configure them to share files. Keep the repository on a WSL-accessible drive and run the wizard from the corresponding WSL path.

#### Signed-release verification

Published signed releases additionally require **Cosign** and the release identity or trusted public key provided by the project maintainers. Keep the `.deb`, matching `.tar.gz`, architecture-specific `SHA256SUMS-<arch>`, and the three adjacent Cosign bundles (`.sigstore.json` for the manifest, `.deb`, and tarball) together. Checksum-only mode needs the package, tarball, and manifest but verifies integrity only; it does not establish who built them. Do not use checksum-only for a public release unless you have independently authenticated the artifact source.

Install Cosign from its official release or your operating system's trusted package source when using signed verification. You do not need Cosign for a checksum-only local development install.

### Optional contributor and test tools

These tools are not needed to install a published platform release or run the basic kid deployment wizard. Install them only for the associated development work:

- Rust/Cargo 1.75 or newer for platform translator builds and Rust tests. The OETF Rust decoder also needs Cargo.
- Node.js and pnpm for TypeScript decoder and mapping package checks. Follow the repository's `package.json` and `pnpm-lock.yaml` toolchain declarations for required versions.
- `pytest` for the Python test suites; package runtime and build dependencies are described in each package's `pyproject.toml`.
- Ansible syntax-check tools and ShellCheck are optional local checks; CI runs the broader validation matrix.

### Target node prerequisites

- Ubuntu Server 24.04 on supported `amd64` or `arm64` hardware.
- SSH server, systemd, `apt`, network access to Ubuntu package repositories, and a reachable sensor-facing interface.
- A user account with key-based SSH and non-interactive `sudo`.
- If Billie must join NetBird, a valid management URL and a one-time setup key from the network administrator. Existing connected NetBird peers are preserved; enrollment material is not required when already connected.
- If connecting to a remote Zenoh fabric, an authorized endpoint, key prefix, fabric CA, client certificate, and matching client private key. Obtain these through the fabric administrator's approved channel and keep them outside the repository.
- Optional: `tcpdump` on the node if using the kid wizard's live sensor-source IP detection. You can enter the expected source IP and mask manually when detection is unavailable.

The setup does not install Ubuntu or create SSH, sensor, NetBird, or fabric credentials. The platform package installs its declared node dependencies, including Podman, Ansible, Python YAML/schema libraries, and service tools. It does not install `tcpdump`; install it on the node with `sudo apt-get install tcpdump` if you want live sensor-source detection instead of entering the expected source manually.

### Cross-architecture kid builds

The platform installation phase installs Billie on the node. The optional kid wizard builds from the source checkout and transfers the resulting image bundle. If the workstation and target architectures differ (for example, x86-64 Linux or WSL building `linux/arm64` for a Raspberry Pi), the selected image engine must provide ARM emulation for every Containerfile `RUN` step. A platform flag alone does not provide emulation. Native ARM64 Linux and Apple Silicon builds targeting ARM64 do not need emulation.

On Linux with Podman, install and register QEMU/binfmt:

```sh
sudo apt-get install -y qemu-user-static binfmt-support
sudo update-binfmts --enable qemu-aarch64
```

For Docker Engine on Linux, install binfmt handlers with Docker's documented privileged helper:

```sh
docker run --privileged --rm tonistiigi/binfmt --install arm64
```

Docker Desktop provides emulation for Docker builds. On macOS Intel, confirm the selected Docker/Podman VM actually supports ARM64 emulation before relying on it. The builder's `--platform linux/arm64` setting selects the output architecture; it does not install emulation.

For Ubuntu 24.04 in WSL using rootless Podman, install the build prerequisites before starting the kid build:

    sudo apt-get update
    sudo apt-get install -y uidmap slirp4netns qemu-user-static binfmt-support
    grep "^$(id -un):" /etc/subuid /etc/subgid
    sudo update-binfmts --enable qemu-aarch64
    test -e /proc/sys/fs/binfmt_misc/qemu-aarch64 && echo "ARM64 emulation registered"

The `grep` command should show a subordinate UID and GID range for your Linux user. This requirement applies to rootless Podman on Linux and WSL. If either range is missing, check that `100000-165535` is unused in `/etc/subuid` and `/etc/subgid`, then add it with `sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$(id -un)"`. Restart the WSL distribution after changing those files. From PowerShell, use `wsl.exe --terminate Ubuntu-24.04`, then reopen Ubuntu.

Verify emulation before building the kid:

    podman run --rm --platform linux/arm64 docker.io/library/python:3.12.10-slim-bookworm python -c 'import platform; print(platform.machine())'

It should print `aarch64`. If ARM binfmt is unavailable in WSL, use Docker Desktop with WSL integration and Buildx instead, selecting `--engine docker`; Docker Desktop supplies multi-platform emulation. The same architecture check is useful on Linux and macOS. If Docker reports that the OCI exporter is unsupported by the default `docker` driver, create a container builder once:

```sh
docker buildx create --name open-billie-builder --driver docker-container --use
docker buildx inspect --bootstrap
```

Native ARM64 Linux can build the ARM64 image without emulation. The Podman warning that `/` is not a shared mount is separate from `Exec format error` and is not itself the cause of that build failure.
## Start the guided setup

From the repository root, run:

### Linux

    bash tools/setup.sh

### macOS

Install Xcode command line tools if prompted, and activate the Python virtual environment described above. Run:

    bash tools/setup.sh

The wizard asks **What would you like to do?** and lists **[1] Build a new image** or **[2] Use an existing image** on separate lines. Build is the default when you press Enter. On macOS, the build runs in a Linux container, so start Docker Desktop or the Podman machine first. Select the target node architecture; the wizard leaves the resulting `.deb`, matching tarball, and checksum manifest under `dist/`. Mac Bash 3.2 is sufficient for setup, install, configure, and kid deployment.

### Windows 10/11

Install and launch an Ubuntu 24.04 WSL distribution. Do not use the Docker Desktop WSL distribution.

    wsl.exe --install -d Ubuntu-24.04

From PowerShell opened at the repository root, launch the guided script with:

    powershell.exe -ExecutionPolicy Bypass -File .\tools\setup.ps1

The launcher starts the shared Bash setup inside Ubuntu WSL. You can also open that distribution directly, install the listed prerequisites, access the repository from its WSL path, and run `bash tools/setup.sh` there. Configure SSH key-based access inside that WSL distribution (`~/.ssh/config` and its key permissions). WSL and Windows OpenSSH use separate SSH configuration and key stores unless explicitly configured to share them.

The script prompts you to choose a local build or an existing release, identify the target account and host, and select signed verification or checksum-only local development. It then builds or validates the matching artifact, transfers and installs it, and continues to the interactive node configuration. After node verification succeeds, it asks whether to start the kid deployment wizard. Locally built packages default to checksum-only because they have no release signatures; existing releases default to signed verification. You can stop at each confirmation prompt before the next phase. It never asks you to paste private-key contents.

## What the guided flow does

1. Checks required commands and supported target architecture.
2. Builds the platform package locally, or verifies the release files you select.
3. Confirms SSH host trust, SSH access, target Ubuntu version, architecture, and passwordless sudo.
4. Transfers the verified release and installs it with `apt`.
5. Prompts for the Billie node handle and checks whether NetBird is already connected. If not, it can bootstrap NetBird and request an administrator-issued one-time setup key.
6. Prompts for the remote Zenoh endpoint and one credential-bundle folder; discovers and validates the CA, matching certificate/key, and prefix, then securely streams the files through temporary protected storage on the node.
7. Runs `billie check`, `billie apply`, and `billie verify` and reports the outcome.
8. Offers the kid wizard. It scans packages in `kids/` and also lets you point to a package folder elsewhere, selects one, builds for the connected node's architecture, transfers and installs the bundle, then guides sensor listener setup and activation. Declining leaves a ready-to-run command: `bash tools/deploy-kid.sh <user@node>`.

The node runs Billie locally after installation; it does not need a clone of this repository. Sensor-specific decoder and mapping packages are supplied separately.

## Build and deploy a kid

The optional guided kid wizard builds locally from the source checkout and deploys to the node. Start it after node configuration when setup offers, or run `bash tools/deploy-kid.sh <user@node>` later. It scans `kids/`, excludes the `_template` scaffold from deployable choices, and includes a numbered option to choose a package folder outside the repository. The selected external folder must contain `billie-kid.yaml` and pass the normal source validator; it remains in place, while the built bundle is written to this checkout’s `dist/kids/`. In WSL, enter either a Windows path or its corresponding `/mnt/<drive>/...` path; paths with spaces are supported. The wizard detects the node architecture over SSH, checks that the local container engine is ready, then invokes the package builder. The builder asks which deployable decoder implementation to use when needed and builds the Containerfile named by that implementation in `billie-kid.yaml` (for example, `Containerfile.rust` or `Containerfile.typescript`). It does not require a separate manual `docker build` or `podman build`. If the same bundle already exists, the wizard asks before replacing it.

The wizard names the two sides of the sensor link separately. **Billie sensor-facing IP and subnet mask** are assigned to the node interface; this can be done before a cable or sensor is connected, and does not add a gateway or DNS. **Sensor source IP and subnet mask** describe incoming packet sources and are used only to scope the node firewall; Billie does not configure the external sensor. When UFW is active, the wizard can detect the source IP on the wire and default to a single-host mask (`255.255.255.255`); if the sensor is not connected or sending yet, enter the expected source IP and mask manually. NAT or workstation routing may make the observed source differ from the sensor’s own configured address. The wizard then asks for the listener transport and **Billie listener port** (the port the sensor sends to); the package’s container port is shown separately. It installs the bundle, configures the selected input, activates the kid, and prints its status. All node address changes require confirmation. Live source detection requires tcpdump on the node.

Kid source stays in its own repository (the in-tree OETF package is synthetic). Build its container on the workstation; the platform Debian package remains sensor-neutral. Install the platform release containing the kid operations helper on the node before using the node-side commands below.

From the Open Billie checkout, choose the image platform to match the node:

    bash deploy/bin/billie kid validate kids/examples/oetf
    bash deploy/bin/billie kid build kids/examples/oetf --platform linux/arm64
    bash deploy/bin/billie kid build kids/examples/oetf --decoder-language typescript --platform linux/arm64

The builder discovers decoder implementations declared in `decoderImplementations` and offers an interactive choice when more than one is deployable. Use `--decoder-language python|rust|typescript` to select explicitly in scripts or CI. It reports source-only implementations but will not build them until their package has a complete runtime adapter, container build recipe, and command. It builds with the implementation's declared Containerfile and records the selected language in the bundle manifest. The OETF example declares Python, TypeScript, and Rust runtimes for UDP or TCP ingress. All three adapters have been exercised on the test Pi. A clean ARM64 TCP run with platform 0.2.1 passed `billie verify`; the kid logged all three output formats and the operator confirmed publication through an authorized fabric subscriber. Platform 0.2.1 cleans stale listener forwards before starting and verifies the active rule. SAPIENT interoperability with an independent receiver remains unverified.

Use `linux/amd64` for x86-64 nodes. The builder prefers a running Podman engine and falls back to running Docker with Buildx; cross-platform builds require the chosen engine to support the target architecture. It writes a `.tar.gz` bundle and adjacent `.sha256` sidecar under `dist/kids/`. Copy both files to the node using SSH/SCP:

    scp dist/kids/billie-kid-oetf_0.1.4.tar.gz operator@<node>:/tmp/
    scp dist/kids/billie-kid-oetf_0.1.4.tar.gz.sha256 operator@<node>:/tmp/

Configure the dedicated sensor-facing Ethernet interface on the node. First identify the interface; do not use an interface marked as carrying the default route:

    sudo billie network interfaces
    sudo billie network configure --interface eth0 --address 192.0.2.20/24

The network command asks before applying the change. It creates a Billie-owned Netplan snippet with no gateway or DNS, then applies the address directly to only the selected interface. It deliberately does not run global `netplan apply`, which can renew a different interface's management DHCP lease and drop SSH. The address can be assigned before a sensor cable is attached; Netplan makes it persistent across reboot. Billie refuses the active default-route or SSH interface. Use the interface name reported for the node's sensor port; `eth0` is an example. `192.0.2.20/24` is documentation-only; choose an address and prefix for your sensor network. To undo only this Billie-managed setting, run `sudo billie network clear --interface eth0`.

Install and activate on the node:

    sudo billie kid install /tmp/billie-kid-oetf_0.1.4.tar.gz
    sudo billie kid configure oetf --transport udp --bind-address 192.0.2.20 --port 5100 --source-cidr 192.0.2.0/24
    sudo billie kid activate oetf
    billie kid status oetf
    billie kid logs oetf

The installer requires the matching sidecar and validates its checksum, the bundle's internal checksums, OCI manifest digest, target architecture, and manifest before loading the image. The manifest declares the listener transport and the port used inside the container. `kid configure` selects a declared UDP or TCP listener, a node address that is already assigned to an interface, and the node's host port. It binds only to that address. Replace the documentation-only address in the command with an IPv4 address assigned to the node sensor interface. It is not part of the package contract. It cannot turn a UDP-only decoder into a TCP decoder. Activation creates a systemd service that publishes the selected host port to the declared container port and mounts the local translator socket into the container. Open Billie platform continues to own Zenoh and mTLS. For a kid that declares additional environment variables, provide a root-readable `NAME=VALUE` file with `--config`; it is copied to `/etc/billie/kids/<id>/runtime.env` with mode `0600`. Never place credentials in the manifest or bundle.

When UFW is active, billie kid configure requires the sensor source network as observed on the node, then adds an interface- and source-scoped input rule and Podman routed rule. Do not use the node bind address as the source unless the sender actually uses that address. NAT and multi-address workstations can change which source the Pi sees. The workstation kid wizard offers live tcpdump detection and proposes the observed sender as /32; if no packet is available, enter the expected sender CIDR manually. The direct billie kid configure command prompts for the source CIDR when --source-cidr is omitted. Both rules are recorded with listener configuration; removing the kid or running sudo billie teardown removes those managed rules. For another host firewall, configure an equivalent restricted input and forwarding rule through that firewall normal administration process; Billie changes only UFW rules it created and recorded.

### Configure CAT062 source identities

ASTERIX CAT062 identifies a track with a numeric 12-bit track number and a SAC/SIC source pair. If multiple sources can use overlapping track numbers, assign each source ID a distinct pair. For example, with synthetic assignments:

The protected node configuration uses an optional node-wide fallback and per-kid source mappings:

```json
{
  "default": {"sac": 4, "sic": 21},
  "kids": {
    "oetf": {
      "sources": {
        "sensor-a": {"sac": 4, "sic": 23}
      }
    }
  }
}
```

The `default` property may be omitted. Each configured SAC/SIC pair, including the default, must be unique.

    sudo billie cat062 source set oetf sensor-a --sac 4 --sic 22
    sudo billie cat062 source set oetf sensor-b --sac 4 --sic 23
    sudo billie cat062 source list

Use SAC/SIC values authorized for your system in real deployments. Assignments are keyed by authenticated kid and canonical `sourceId`; the same source ID can have a separate assignment for each kid. CAT062 resolves an exact kid/source assignment first, a legacy global assignment while it is being migrated second, and the optional node default last. For a single-source setup or fallback for unmapped sources, configure the authorized node pair with `sudo billie cat062 default set --sac <0-255> --sic <0-255>`; inspect it with `sudo billie cat062 default show` and clear it with `sudo billie cat062 default clear`. For multiple sources that need distinct identities, assign each source explicitly. `source remove <kid> <sourceId>` removes only that assignment. Without a match or node default, the translator rejects CAT062 output for that track. Each successful change restarts the shared translator. The map is stored in `/etc/billie/translator/cat062-sources.json` with root-only permissions and is removed by full Billie teardown.

To send the synthetic OETF frame from a workstation connected to the node's sensor link, use the node sensor-interface address and the workstation's address on that same link. Replace the placeholders with the addresses shown by `billie network interfaces` and your workstation network configuration:

    python tools/generate-oetf-sample.py --udp-host <node-sensor-ip> --udp-port 5100 --udp-source <workstation-sensor-ip>

To exercise TCP instead, select the oetf-tcp listener in the wizard, then send two back-to-back stream frames in small writes:

    python tools/generate-oetf-sample.py --tcp-host <node-sensor-ip> --tcp-port 5100 --tcp-source <workstation-sensor-ip> --tcp-repeat 2 --tcp-chunk-size 7
Omit `--udp-source` when the host routing table already selects the correct interface. The sample is synthetic and test-flagged.

Bundles are unsigned. Checksums detect accidental or in-transit changes only when compared against the separately transferred sidecar; they do not authenticate the publisher. Activation supports one selected input listener at a time, stateless packages, and the shared CoT, ASTERIX CAT062, and SAPIENT BSI Flex 335 v2.0 encoders. SAPIENT uses the node UUID generated during initialization and publishes one protobuf message per Zenoh sample. Use `sudo billie kid deactivate <id>` to stop a kid while retaining its installed versions. To upgrade, install the new bundle alongside the active version, then run `sudo billie kid upgrade <id> --version <new-version>`. The previous successful version, listener settings, and protected runtime environment are kept in root-only state under `/var/lib/billie/kids/<id>/`; `sudo billie kid rollback <id>` restores that deployment and swaps the active/previous versions. This supports stateless kids only. Keep both versions installed until you accept the upgrade. Use `sudo billie kid remove <id> [--version <version>]` to remove a version or all versions; runtime configuration is preserved unless `--remove-config` is specified. For a complete removal, run `sudo billie teardown`. It removes Billie configuration and credentials, the platform package, kids, Billie-managed sensor network snippets, recorded UFW listener rules, and Billie-only images when unused. NetBird and unrelated packages/images remain untouched. Teardown asks for confirmation and requires a second confirmation before deleting identity and fabric credentials. Use `--preserve-credentials` only when you explicitly want to keep those files.

### Credential folder layout

Both credential sources provide one fabric CA root and one matching client pair. A local folder uses this layout:

    credential-bundle/
      fabric-ca.pem
      <vendor-prefix>-cert.pem
      <vendor-prefix>-key.pem
      <vendor-prefix>-cli-ca.pem             # ignored by the configurator
      <vendor-prefix>-cli-profile.cbor       # ignored by the configurator

The preferred CA root name is `*-ca-root.pem`; if none is present, the configurator accepts one `fabric-ca.pem` or `ca.pem`. Exactly one preferred CA root and one `*-cert.pem` must be present; the matching `<certificate-prefix>-key.pem` is selected automatically. Extra unrelated key files are ignored. An auxiliary onboarding CA or profile file is not the Zenoh router trust root and is not selected by the configurator.

The configurator offers `[1] One-time API bundle URL` (default) or `[2] Local folder`. The API option asks for the complete one-time HTTPS bundle URL returned by machine enrollment, including the host and full path:

    https://<organization-host>/api/bundle/<token>/<bundle-id>.tar.gz

Paste the complete URL at the hidden prompt; the wizard does not add or prefill any part of the URL. The URL is treated as a bearer capability: it is not printed or placed in process arguments. The workstation downloads it over verified HTTPS, refuses redirects, validates archive paths and file types, and extracts into a private temporary directory. The wizard discovers the Zenoh endpoint from the included onboarding markdown or Python examples and asks for confirmation. Extracted files must meet the CA/certificate/key layout above. Temporary files are removed when configuration exits. If a one-time URL was consumed during a failed attempt, request a fresh URL from enrollment. The local-folder option remains available.

## Manual commands

The guided script is the recommended path. Advanced users can run [the installer](../tools/install-to-node.sh) and [node configuration flow](../tools/configure-node.sh) separately. See [troubleshooting](TROUBLESHOOTING.md) for recovery steps.

## Security and data handling

- Release signatures are required by default for published artifacts. Checksum-only mode is for local development and controlled local installs; a checksum alone does not establish who built an artifact.
- The setup key is entered at a hidden prompt and removed from its temporary node file after enrollment.
- Fabric certificates are copied to temporary protected storage on the node, imported into Billie-managed root-only storage, and removed from the temporary location.
- Do not commit credentials, private sensor data, or host-specific inventory to this repository.
