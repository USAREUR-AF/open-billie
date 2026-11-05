# Kid package contract

## Goal

Open Billie provides a stable host and package lifecycle. A kid repository supplies its own decoder, schemas, sensor-to-output mappings, lookups, and synthetic conformance vectors. Billie validates, builds, installs, configures, starts, inspects, deactivates, upgrades, rolls back, and removes supported stateless packages without knowing their wire format. One declared listener is selected at a time. Signing, persistent data, simultaneous multiple listeners, and fleet management remain future work.

Each kid remains an independently versioned source package. Build it from a local checkout of its repository; publishing it to GitHub Packages is not required for build or deployment. Proprietary kid source stays in its separate repository and outside the Open Billie checkout. Only synthetic examples such as OETF belong under the tracked `kids/` tree. Do not include any kid implementation in the sensor-neutral platform Debian package. A deployment selects the kid source/release it is authorized to use.

## Package source layout

Every kid repository should use this layout, with language-specific source beneath `decoder/` and `mapper/`:

```text
billie-kid.yaml
README.md
Containerfile
decoder/                 # raw input framing and decode implementation
schemas/                 # schemas owned by this kid
mapper/                  # executable mapping/runtime adapter
mappings/                # this kid's mapping rules
lookups/                 # lookup tables consumed by mappings
tests/vectors/           # synthetic input and expected output only
config.example.yaml      # safe, non-secret example configuration
```

The decoder, mapper, schemas, mapping rules, lookups, and runtime image ship together as one kid release. A decoder author may use TypeScript, Python, Rust, or another supported runtime; Billie core treats the kid as a declared package and does not load language-specific code into its own process.

The `Containerfile` should place the executable in the image and may set a default `CMD`. Keep `ENTRYPOINT` unset so the manifest's `runtime.command` can select the process at activation.

## Manifest

`billie-kid.yaml` is the package metadata entry point. Its v1 schema is [kid-manifest.schema.json](../../schemas/kid-manifest.schema.json). It identifies the package and declares:

- a stable lowercase package ID and independent semantic version;
- an OCI image pinned by digest, plus the command used to start the kid;
- named ingress listeners with transport and container port;
- named logical outputs with the requested encoder format and optional profile; the Open Billie platform supplies the route and publisher;
- paths to the decoder, mapper, schemas, mapping rules, lookup tables, and synthetic conformance vectors;
- decoder implementations by language, with each marked `deployable` only when it declares a decoder, mapper, Containerfile, and runtime command, or `library-only` with a reason;
- required public Billie interfaces or encoders, when applicable.

Paths are relative to the package root. Manifests may not contain credentials, deployment identity, or private service endpoints. Credentials and per-node endpoints are injected from protected node configuration at activation time.

## Runtime boundary

The kid image owns sensor-specific input handling, decoding, and user-defined mapping. It receives traffic on only the TCP/UDP listeners declared for the kid, applies its included schemas, mappings, conversions, and lookups, then sends a versioned canonical record and logical output selection to the Billie Rust translator over a local Unix domain socket. The kid does not implement or own the shared output encoders or platform transport.

The Billie Rust runtime owns translation from the canonical record to the selected output format and the shared CoT, ASTERIX CAT062, and SAPIENT BSI Flex 335 v2.0 encoders. SAPIENT requires a stable node UUID, generated once during node initialization or explicitly supplied through `BILLIE_SAPIENT_NODE_ID`. The Open Billie platform transport adapter accepts the encoded protobuf payload and maps the logical output to the node's local Zenoh route. Open Billie platform provisions the Zenoh island, remote fabric endpoint, mTLS certificate and key files, vendor-prefix bridge, service lifecycle, and troubleshooting. Fabric settings are not embedded in a kid image, manifest, or translation request. The platform CLI configures non-secret endpoint/prefix values and accepts certificate file paths; the private key contents stay in protected node storage. The mapper defines sensor meaning and conversions. The translator validates required canonical values and fills format-specific structure without inventing sensor-specific values.

See [Decoder-to-Translator Runtime Contract](DECODER_TRANSLATOR_RUNTIME_CONTRACT.md) for the local message boundary, ownership table, configuration split, and verification requirements. The builder selects only implementations marked deployable. When several are deployable, it prompts interactively; `--decoder-language` selects one for scripts and CI. The selected language, decoder, mapper, and runtime command are written to the built bundle manifest. Source-only decoder libraries remain visible to the operator but cannot be selected for deployment until their input and translator runtime adapter is complete.

The Billie host lifecycle must not interpret sensor bytes or sensor-specific mapping rules. It validates the manifest, runs the pinned kid image through Podman, supplies protected runtime configuration, manages the local translator interface, and reports health and logs. The shared translation interface is versioned independently of kid packages.

## Package lifecycle

The CLI lifecycle is:

1. `billie kid validate <package>` checks the manifest against the shared JSON Schema, required `README.md` and `Containerfile`, declared component paths, JSON data, interface names, and image digest format. It is an offline source check; `--strict` rejects development placeholders and empty template data directories.
2. `billie kid build <local-package> --platform linux/amd64|linux/arm64 [--decoder-language python|rust|typescript]` discovers declared implementations, prompts when multiple deployable languages are available, builds the selected local OCI image, and creates an unsigned bundle with the selected implementation in its digest-pinned manifest and external checksum sidecar.
3. `sudo billie kid install <bundle.tar.gz>` requires the matching sidecar, validates the bundle and node architecture, loads its image into rootful Podman, and installs metadata under `/opt/billie/kids/<id>/<version>` without changing node identity.
4. `sudo billie kid configure <id> --transport udp|tcp --bind-address <node-IP> --port <host-port> [--source-cidr <sensor-CIDR>] [--listener <name>]` selects a declared listener and the node interface address and host port. The manifest's `port` is the container listener port. Use `sudo billie network configure --interface <sensor-interface> --address <IPv4/CIDR>` to assign the node address first. The network command writes a Billie-owned Netplan snippet without gateway or DNS and applies the address directly to that interface, including when no cable is attached. It does not run global `netplan apply`, which could renew the management interface's DHCP lease and disconnect SSH. Netplan preserves the setting across reboot; `kid configure --bind-address` then selects that address for the listener. When UFW is active, configure prompts for the sensor source CIDR as observed by the node (NAT can change it), then creates and records scoped input and Podman forwarding rules. Kid removal and full teardown delete those recorded rules. A transport flag cannot add a transport the package does not implement. One selected listener runs at a time.
5. `sudo billie kid activate <id> [--version <version>] [--config <file>]` creates and starts a systemd service using the selected listener, the local translator socket, and protected environment configuration. Open Billie platform continues to own local Zenoh and fabric transport.
6. `billie kid status|logs <id>` reports the service state and journal without printing configured environment values.
7. `sudo billie kid deactivate <id>` stops and disables the service while preserving installed versions.
8. `sudo billie kid upgrade <id> --version <version>` activates a newly installed version while retaining the previous successful deployment for rollback.
9. `sudo billie kid rollback <id>` restores the previous stateless deployment and swaps active and previous versions.
10. `sudo billie kid remove <id> [--version <version>] [--remove-config]` removes one or all installed versions. Removing an inactive older version leaves the running kid untouched. It retains protected runtime configuration unless explicitly asked to remove it, and deletes the image only when no remaining installed package references it.

The platform base release remains sensor-neutral. `billie kid build <local-package> --platform linux/amd64|linux/arm64` uses local Podman or Docker Buildx and creates a separate `.tar.gz` transfer bundle under `dist/kids/` (or `--output`). The bundle contains the resolved manifest, OCI image archive, metadata, and internal checksums; the adjacent `.sha256` file lets the installer detect transfer corruption. The bundle does not include the source repository. It is unsigned, so checksums do not identify who built it. A GitHub package registry is not required. Node-side install, listener configuration, activation, status, logs, deactivation, upgrade, rollback, and removal are implemented for stateless packages; one selected listener runs at a time. Persistent paths, signatures, and fleet management remain future work. `sudo billie teardown` removes Billie-managed files, network snippets, services, and credentials after a second confirmation; `--preserve-credentials` is an explicit opt-out and NetBird is untouched. Kid bundles remain separate from the core Debian package and its release checksum manifest.

Install a new version alongside the active one with `sudo billie kid install <bundle.tar.gz>`, then activate it with `sudo billie kid upgrade <id> --version <new-version>`. A successful activation records the previous deployment's version, listener settings, and protected runtime environment under `/var/lib/billie/kids/<id>/` with root-only permissions. `sudo billie kid rollback <id>` restores that recorded stateless deployment and swaps the active/previous records, allowing the same command to roll forward again. Keep the prior version installed until the new version is accepted. Rollback fails clearly if the saved version is no longer installed or its listener is no longer declared by that package. Runtime environment snapshots may contain secrets and are only readable by root. Persistent package paths are unsupported and are not included in snapshots.

## Conformance and data boundary

Every kid release must include synthetic test vectors that exercise input framing, decode, schema validation, mapping, and output. The generic integration fixture must use the Open Billie local output transport and verify local routing. Platform acceptance also verifies the vendor-prefix bridge and mTLS fabric client. Real sensor captures, private interface documents, credentials, and deployment-specific endpoints are not valid examples or test inputs for this repository.

OETF is intended to be the first synthetic external kid used to prove the contract. Its decoder repository remains independent; changes there should be made only in that repository by its maintainer.
