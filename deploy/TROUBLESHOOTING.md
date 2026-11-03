# Troubleshooting the first platform slice

## `billie` is not found after package installation

Confirm the Debian package installed and the command link exists:

    dpkg -l billie-platform
    ls -l /usr/local/bin/billie

If the package install was interrupted, finish it with `sudo apt-get -f install` and reinstall the package.

## `billie install` reports a missing dependency

The platform package declares Ansible Core, Podman, and systemd dependencies. Refresh apt metadata and complete dependency configuration:

    sudo apt-get update
    sudo apt-get install -f

The supported host for this slice is Ubuntu Server 24.04 on arm64 or amd64.

## `billie check` says the node is not initialized

Create the persistent node declaration once:

    sudo billie init <node-handle> --supply connected

For a disconnected node use `--supply airgap`. The identity is stored under `/etc/billie/identity/node.yml` and is not overwritten by this CLI.

## NetBird enrollment fails

`billie join` requires NetBird to be installed and its daemon running. Check `sudo netbird status`, confirm the management URL is reachable over HTTPS, and verify the setup key file is readable only by root. The CLI passes the file path to NetBird and does not print the key contents. Enrollment is not retried automatically.

## `billie verify` reports a missing or inactive health timer

Apply the baseline, then inspect the service and timer:

    sudo billie apply
    systemctl status billie-health.timer billie-health.service
    journalctl -u billie-health.service --no-pager -n 50
    sudo billie verify

The health record is ephemeral at `/run/billie/health.json`; it reports `state=degraded` and lists `failed_checks` when core local services or configured fabric services are unavailable. The timer also publishes the record to local Zenoh at `ops/<node-handle>/health`. When fabric is configured, the bridge forwards it to `<vendor-prefix>/ops/<node-handle>/health`. Confirm local publication with `curl -fsS http://127.0.0.1:8000/ops/<node-handle>/health` and inspect `journalctl -u billie-island-bridge` for a nonzero `forwarded` counter. A running health timer alone does not prove remote delivery.

## The release checksum check fails

Do not install the artifact. Rebuild it from a clean source tree and transfer the matching `.deb`, tarball, and architecture-specific `SHA256SUMS-amd64` or `SHA256SUMS-arm64` manifest together:

    bash tools/build-platform-release.sh
    cd dist && sha256sum -c SHA256SUMS-arm64

## macOS platform build cannot start

The Mac wizard builds the Linux package inside Docker or Podman. Start Docker Desktop, or start the existing Podman machine with `podman machine start`, then retry. The first build needs network access to download the Rust 1.75 builder image and its Linux packages. If the container build completes but the package is missing, check that the repository `dist/` directory is writable and inspect the builder output for a Rust target or cross-linker error.

## Workstation installer refuses the release signature

The installer fails closed if a bundle is missing or the signing identity does not match. Confirm the expected signer from the trusted release workflow and pass the full identity:

    bash tools/install-to-node.sh --target <user>@<host> --deb <path> --certificate-identity '<expected-workflow-identity>'

For key-based local testing, pass `--public-key <trusted-public-key>`. Do not use a public key downloaded alongside an untrusted package as the trust anchor.

## SSH installer cannot reach the node or use sudo

The installer requires an already-trusted host key, key-based SSH, `sudo -n true`, and apt. Connect once using your normal SSH process to trust the host key, configure non-interactive sudo for the deployment account, and retry. On failure, the installer prints the retained staging directory on the node.

## Workstation configurator cannot find the credential bundle files

Pass the folder containing the fabric CA root, one `*-cert.pem`, and one matching `*-key.pem`. The client certificate and key filename stems must match. Auxiliary certificates included in an enrollment bundle do not necessarily serve as the Zenoh fabric CA. The configurator recognizes `*-ca-root.pem`, `fabric-ca.pem`, or `ca.pem` as the fabric trust root. On Windows, make sure the files are readable from the Ubuntu WSL distribution.
## `billie bootstrap` cannot install NetBird

The connected bootstrap requires DNS/internet access to `pkgs.netbird.io` and Ubuntu APT repositories. Check these from the node, then retry:

    getent hosts pkgs.netbird.io

If bootstrap reports conflicting `Signed-By` paths for `netbird-archive-keyring.gpg` and `.asc`, the previous bootstrap left a duplicate NetBird APT source. Install Open Billie platform `0.2.0` or newer and rerun `sudo billie bootstrap`; it replaces the previous Billie-managed `netbird.list` before APT reads repository configuration and uses NetBird's official `.gpg` keyring format.
    sudo apt-get update
    sudo billie bootstrap

For an offline node, skip `bootstrap` and use `billie init <node-handle> --supply airgap`. Offline NetBird package staging is not implemented yet.

## `billie join` reports that NetBird is missing or inactive

Run `sudo billie bootstrap`, then check the local agent before retrying enrollment:

    sudo systemctl status netbird --no-pager
    sudo netbird status

A management-plane outage or invalid setup key is not repaired by bootstrap; check the management URL and obtain a fresh key from the network operator.

## `billie kid validate` reports missing Python modules

The platform package depends on `python3-yaml` and `python3-jsonschema`. If validation or bundle building is run from a source checkout on a workstation, install those modules for that workstation's Python 3 environment. `billie kid build` uses Podman or Docker Buildx.

## Kid image build fails with `Exec format error`

This occurs when the target image architecture differs from the workstation (such as x86_64 WSL building `linux/arm64`) and the image engine has no registered emulator. `--platform linux/arm64` selects the output architecture; it does not enable emulation. For rootless Podman in Ubuntu 24.04 WSL, install `uidmap`, `slirp4netns`, `qemu-user-static`, and `binfmt-support`, ensure the user has `/etc/subuid` and `/etc/subgid` ranges, enable `qemu-aarch64` with `sudo update-binfmts --enable qemu-aarch64`, and restart WSL if those mappings changed. Verify before retrying:

    podman run --rm --platform linux/arm64 docker.io/library/python:3.12.10-slim-bookworm python -c 'import platform; print(platform.machine())'

The command should print `aarch64`. Alternatively, use Docker Desktop with WSL integration and Buildx via `--engine docker`, or build on a native ARM64 Linux workstation. The Podman `/` shared-mount warning is distinct and does not explain this execution-format error.
## Kid validation warns that an image is a placeholder

The template and OETF example manifests intentionally use example image references. They pass structural source validation but are not deployable. Build a digest-pinned transfer bundle with:

    billie kid build <package-directory> --platform linux/arm64

The builder resolves the image digest in the bundle manifest; it does not edit the source manifest. `--strict` validation also rejects schema, mapping, lookup, or vector directories that do not contain JSON data.

## `billie kid install` rejects the bundle architecture

Build for the node's Linux architecture and transfer the `.tar.gz` with its adjacent `.sha256` sidecar. Raspberry Pi 64-bit Ubuntu uses `linux/arm64`; x86-64 Ubuntu uses `linux/amd64`.

## A kid service fails to activate

Inspect the unit and its recent application logs:

    systemctl status billie-kid-<id>.service --no-pager
    billie kid logs <id> --lines 100

Check that the selected host port is available, confirm `billie kid configure <id> --transport udp|tcp --bind-address <node-IP> --port <port>` selected a transport declared in the kid manifest, and confirm the decoder implements it. The manifest port is the container port; `--bind-address` selects an IPv4 address already assigned to the node, and `--port` chooses the node host port. Use the sensor-facing address reported by `sudo billie network interfaces`; it must be assigned to the selected interface. If the host port is already in use, choose another and reactivate. Also confirm the manifest declares `BILLIE_TRANSLATOR_SOCKET`. Activation supports one selected listener, stateless packages, and CoT, ASTERIX CAT062, or SAPIENT output. It requires the local translator and Zenoh island, but not the remote fabric, for local kid processing.

If UFW is active, `billie kid configure` creates and records the restricted input and routed rules for the chosen listener. It prompts for the sensor CIDR when run interactively; use the source address as observed on the node because NAT and simulator networking can change it. For one known sender, pass its observed address as `/32`. If `tcpdump` sees packets on the sensor interface but the kid receives none, inspect UFW's routed policy (`sudo ufw status verbose`), Podman port mapping, and the recorded listener config. Billie activation also removes orphaned Netavark port forwards while preserving forwards to active containers. Billie teardown removes recorded firewall rules. Rules created manually before this feature are not recorded and must be removed explicitly. Kid activation now removes stale listener forwards before starting the container, then verifies that the active container-engine forwarding rule (Netavark or CNI) targets the current container IP. Stale-rule cleanup is currently specific to Netavark. If activation reports a missing forward, check systemctl status billie-kid-<id>.service, sudo podman port billie-kid-<id>, and sudo iptables -t nat -S; do not treat an active systemd unit alone as proof that sensor packets reach the kid.

On the sending workstation, bind the synthetic sender to the address assigned to its sensor-link interface with `--udp-source`; otherwise the OS may route the packet out another interface.

## CAT062 source identity is missing or collides

CAT062 resolves the source pair by exact authenticated kid and canonical `sourceId`, then by a legacy global mapping until migrated, then by the optional node default. Check the current settings with `sudo billie cat062 source list`. For a single-source setup or fallback, configure the authorized node pair with `sudo billie cat062 default set --sac <0-255> --sic <0-255>`. For distinct sources, assign each pair with `sudo billie cat062 source set <kid> <sourceId> --sac <0-255> --sic <0-255>`. The CLI rejects duplicate pairs and restarts the translator after changes. If neither a matching mapping nor a node default exists, CAT062 encoding is rejected with `missing_source_identifier`.

## Remove a kid or the Billie platform

Stop a kid and retain its installed image and configuration:

    sudo billie kid deactivate <id>

Remove one installed version or all versions. Runtime configuration stays under `/etc/billie/kids/<id>` unless you explicitly add `--remove-config`:

    sudo billie kid remove <id> [--version <version>] [--remove-config]

To remove Billie services, state, credentials, and Billie-managed sensor networking, run `sudo billie teardown` and complete both confirmation prompts. NetBird is left untouched. Use `--preserve-credentials` only to retain the Billie identity and fabric TLS files.
