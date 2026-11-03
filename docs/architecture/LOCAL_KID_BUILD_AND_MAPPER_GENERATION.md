# Local kid build and mapper generation

## Purpose and status

Kid packages are built from their own local source repositories. GitHub Packages is not required. Proprietary source remains outside this repository; only synthetic examples such as OETF are tracked under `kids/`. The platform Debian package remains sensor-neutral.

The `billie` CLI provides kid scan, validate, build, install, configure, activate, status, logs, deactivate, and remove operations. The workstation setup wizard can discover a local kid, build it for the node architecture, transfer and install the bundle, configure one declared listener, and activate it. One listener is active per kid at a time.

## Discovery and validation

`billie kid scan [source-root ...] [--json]` inventories kid manifests, schema formats, listeners, outputs, component paths, validation status, and image readiness. In a source checkout, `kids/` is the default source root; on a node, the installed kid root is `/opt/billie/kids`. `BILLIE_KID_SOURCE_ROOTS` and positional roots support additional local source locations. Scanning reads manifests and files but does not execute package build scripts or pull images.

`billie kid validate <package> [--strict]` validates the manifest and component layout locally. Strict validation rejects development image placeholders and empty template data directories. Validation does not execute the kid or prove that its runtime works.

## Mapper generation

`billie mapper generate` accepts the Open Billie byte-offset JSON decode schema and Protocol Buffers `.proto` schemas. The protobuf adapter requires `protoc` and the Python protobuf descriptor module. It inventories message and field metadata and writes a reviewable mapper plan plus mapping-contract JSON files. It does not produce a complete executable mapper or infer field meaning.

Example JSON schema command:

```sh
billie mapper generate --schema schemas --format billie-json \
  --source-protocol my-sensor --target billie-canonical \
  --output mappings/mapper-plan.json --mappings-dir mappings/generated
```

Example protobuf command:

```sh
billie mapper generate --schema schemas/messages.proto --format protobuf \
  --source-protocol my-sensor --target billie-canonical \
  --proto-path schemas --output mappings/mapper-plan.json \
  --mappings-dir mappings/generated
```

`--interactive` prompts for target field names; it does not determine semantic equivalence, units, or conversion rules. Generated bindings remain unresolved unless reviewed. `--enable-direct` explicitly opts into direct copies for selected same-name fields; review their semantics before use. Keep source units, enum lookups, coordinate conventions, defaults, and omitted fields documented in the kid's mapping files and test vectors. The mapper emits canonical track records; the shared Rust translator constructs CoT, ASTERIX CAT062, or SAPIENT output.

## Build and delivery

`billie kid build <local-package> --platform linux/amd64|linux/arm64` validates the source, builds an OCI image using Podman or Docker Buildx, records the image digest, and creates a separate unsigned transfer bundle and `.sha256` sidecar. Use `--decoder-language python|rust|typescript` to select a deployable implementation explicitly; when multiple implementations are deployable, the builder prompts for one. Cross-architecture builds require the selected engine to support emulation for the target architecture.

The bundle contains the resolved manifest, OCI image archive, metadata, and checksums; it does not include the source repository. The checksum detects transfer changes but does not authenticate the builder. Kid bundle signing, persistent kid data, and simultaneous listeners are not implemented. Stateless upgrades and rollback are supported for installed versions.

Install and operate the package on the node:

```sh
sudo billie kid install /path/to/billie-kid-my-sensor_0.1.0.tar.gz
sudo billie network interfaces
sudo billie network configure --interface <sensor-interface> --address <node-ip>/<prefix>
sudo billie kid configure my-sensor --listener tracks-udp --transport udp \
  --bind-address <node-ip> --port 5100 --source-cidr <sensor-network>/<prefix>
sudo billie kid activate my-sensor --version 0.1.0
sudo billie kid status my-sensor
sudo billie kid logs my-sensor --lines 100
```

To update a running stateless kid, install its new bundle alongside the current version and run `sudo billie kid upgrade my-sensor --version 0.2.0`. The prior successful version, listener settings, and protected environment configuration are saved under `/var/lib/billie/kids/my-sensor/`. Use `sudo billie kid rollback my-sensor` to restore that deployment; the active and previous versions swap, so rollback can also return to the newer version. Keep both bundles installed until the upgrade is accepted.

The network command assigns a dedicated sensor-interface address without adding a gateway or DNS; it can be run before the sensor is connected. `kid configure` selects a manifest-declared listener, an address already assigned to the node, and the node host port. When UFW is active, the source CIDR must match the sender address as observed on the node, which may differ because of routing or NAT. The wizard can suggest a source address captured from live traffic or accept an expected CIDR when the sensor is not transmitting yet.

`kid activate` starts the systemd service and verifies that the active container-engine port-forward rule (Netavark or CNI) points to the current container IP. A running unit alone does not prove packets reach the kid; see [troubleshooting](../../deploy/TROUBLESHOOTING.md). Deactivate preserves installed files. Remove preserves protected runtime configuration unless `--remove-config` is supplied. Full platform removal is `sudo billie teardown`; it leaves NetBird untouched and deletes identity/fabric credentials after a second confirmation unless `--preserve-credentials` is specified.

## Remaining acceptance

Prior OETF UDP and TCP runs delivered output visible to an authorized subscriber. A later clean ARM64 Pi run with platform 0.2.1 exercised cleanup-before-start and exact active-forward verification; the operator confirmed OETF output through an authorized fabric subscriber. The operator also reports successful build, install, and exercise of a separate kid package from outside this repository. Its source and sensor data are intentionally excluded. See the [validation log](../TESTING.md) for the evidence boundary.
