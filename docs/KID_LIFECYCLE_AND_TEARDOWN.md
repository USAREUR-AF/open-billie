# Kid lifecycle and Billie teardown

This document defines the operator workflow for building, installing, configuring, activating, and removing a kid package, and for removing the Billie platform from a node.

## Sensor interface and kid listener configuration

First inspect the node links, then assign the address to the dedicated sensor-facing port:

```sh
sudo billie network interfaces
sudo billie network configure --interface eth0 --address 192.0.2.20/24
sudo billie kid configure oetf --transport udp --bind-address 192.0.2.20 --port 5100
```

The network command asks for confirmation, refuses the default-route and current SSH interfaces, and writes a Billie-owned Netplan file without a gateway. It applies the address directly to only the selected interface, even when the sensor cable is not connected, so the node can be prepared before it is attached to the sensor. It does not run global `netplan apply`, which can renew the management interface's DHCP lease and disconnect SSH. Netplan persists the address across reboot. Replace `eth0` and the example address with the Pi's actual sensor interface and the site's address plan. `kid configure` selects the package-declared TCP or UDP input and host port; it does not change the OS interface address. Undo the managed static setting with `sudo billie network clear --interface eth0`.

## Kid package lifecycle

1. **Discover and validate source.** From an Open Billie checkout, scan candidate packages, then validate the selected package manifest and source files. Validation is local and must not execute package code.
2. **Build a node bundle.** Build the selected package for the target node architecture. The output is an OCI image bundle plus a separate checksum sidecar. The build stays separate from the Billie platform Debian release.
3. **Transfer and install.** Copy both bundle and checksum to the node. Installation verifies the sidecar, internal checksums, OCI image digest, manifest, and node architecture before loading the image. It does not activate the kid.
4. **Select listener configuration.** A package declares the listeners it implements. The operator chooses a declared listener, an IPv4 address already assigned to the node, and a host port. Transport is a package capability: choosing TCP is valid only when that package implements TCP input; a CLI flag cannot convert a UDP decoder into a TCP decoder. The configured transport, container port, host address, and host port are recorded under `/etc/billie/kids/<id>/` with root-only access.
5. **Activate and verify.** Activation creates and starts one systemd unit per kid, publishes only on the selected node address and forwards the selected host port to the declared container port, mounts only the translator socket, and applies the kid's protected runtime configuration. The operator checks service status and logs, then sends a synthetic sample and verifies the expected local Zenoh outputs. Fabric delivery is a separate check.
6. **Stop or remove.** Deactivation stops the service and retains the installed bundle and configuration. Removal first stops the service, removes its unit and selected installed version, and removes the image only when no remaining installed version references it. Runtime configuration is preserved unless the operator explicitly requests its deletion.
7. **Upgrade or roll back.** Install a new version alongside the current version, then use `sudo billie kid upgrade <id> --version <new-version>`. The previous successful deployment is retained in root-only state under `/var/lib/billie/kids/<id>/`; `sudo billie kid rollback <id>` restores its listener and runtime environment settings and switches the active/previous versions. Keep both package versions installed until satisfied. This covers stateless packages only; persistent paths are not yet supported.

Suggested command surface:

```text
billie kid scan [source-root ...]
billie kid validate <package-directory>
billie kid build <package-directory> --platform linux/arm64
sudo billie kid install <bundle.tar.gz>
sudo billie kid configure <id> --transport udp|tcp --bind-address <node-IP> --port <host-port> [--listener <name>] [--version <version>]
sudo billie kid activate <id> [--version <version>]
sudo billie kid upgrade <id> --version <new-version>
sudo billie kid rollback <id>
billie kid status <id>
billie kid logs <id>
sudo billie kid deactivate <id>
sudo billie kid remove <id> [--version <version>] [--remove-config]
```

A package manifest must declare each supported listener's name, transport (`udp` or `tcp`), container port, and runtime contract. `configure` may select only a listener declared by the package and may choose the host address and port. The address must already be configured on the node. The package runtime remains responsible for implementing that transport and consuming the declared port and bind settings. A package that supports only UDP must reject TCP selection with a clear error.

## Full Billie teardown

`sudo billie teardown` lists the Billie-managed artifacts, then removes its kid and platform units, Billie-owned sensor Netplan snippets, bridge and Zenoh configuration, runtime state, credentials, package, and unused Billie image references. It leaves NetBird, unrelated network configuration, shared prerequisites, and unrelated container images untouched.

The default teardown deletes `/etc/billie/identity` and `/etc/billie/zenoh/tls` after a second confirmation. Use `--preserve-credentials` only when a reinstall should reuse node identity and fabric certificates. It also removes UFW listener rules that `billie kid configure` recorded. The command removes and verifies orphaned Netavark port-forward and mark rules, even if listener metadata was already deleted by an earlier incomplete teardown. It preserves mappings to any existing Podman container, including stopped containers, and does not flush shared Podman chains. The command prints a final check for remaining Billie-managed services, files, containers, port forwards, and sensor Netplan snippets.

## Current implementation status

The CLI implements scan, validate, build, install, listener configuration, activate, upgrade, rollback, status, logs, deactivate, package removal, and full platform teardown for stateless packages. A package may declare multiple listener choices, but only one is active at a time. The manifest transport must be implemented by the kid; its port is the container port, while `kid configure --bind-address` and `--port` select the node address and host port. Activation supports the shared CoT, ASTERIX CAT062, and SAPIENT BSI Flex 335 v2.0 outputs. The OETF example declares TCP and UDP listener choices on container port 5100.

Use `sudo billie kid remove <id>` to remove installed package versions while preserving runtime configuration. Use `--remove-config` only when that configuration should also be deleted. Use `sudo billie teardown` for full removal. It deletes node identity and fabric TLS credentials after a second confirmation. `--preserve-credentials` is an explicit opt-out. NetBird remains installed and untouched. Billie-only images are removed when unused; shared prerequisites and unrelated images remain.

The teardown includes a final check for residual Billie-managed paths and services. It removes Billie-created sensor Netplan files, including the legacy `01-billie-network.yaml`, plus only the sensor addresses declared in those files and recorded UFW rules. It does not globally reapply Netplan, so unrelated interfaces and the management DHCP lease are left alone. Separately managed network configuration and NetBird are untouched. The Pi exercise should confirm the intended sensor address source and that NetBird remains connected.
