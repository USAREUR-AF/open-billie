# Billie kid package template

Use this directory as the starting point for an independently maintained kid repository. Replace every `example-kid` value, add your own decoder, schemas, mappings, lookups, and synthetic test vectors, and build your runtime image. Do not put real credentials, deployment endpoints, or private captures in the package repository.

For the full process from protocol and schema design through mapper implementation, build, deployment, and verification, see the [kid package authoring guide](../../docs/KID_PACKAGE_AUTHORING_GUIDE.md).

## Package contents

- `billie-kid.yaml`: package identity, immutable runtime image, component paths, and declared network interfaces.
- `decoder/`: your language-specific framing and decoding implementation.
- `schemas/`: schemas that belong to this kid.
- `mapper/`: the language-specific mapping adapter.
- `mappings/`: this kid's source mappings.
- `lookups/`: tables referenced by this kid's mappings.
- `tests/vectors/`: synthetic input and expected decoder/mapping output.
- `Containerfile`: builds the self-contained runtime image.
- `config.example.yaml`: safe example values only; node-specific settings are supplied during activation.

The manifest format is documented in [the kid package contract](../../docs/architecture/KID_PACKAGE_CONTRACT.md) and described by [the JSON Schema](../../schemas/kid-manifest.schema.json). Paths in the manifest are relative to this directory. Pin the released image by its SHA-256 digest, not a mutable tag.

Validate the scaffold with `billie kid validate .`. This checks the manifest and source layout offline. It will report empty data directories and the placeholder image as warnings; `--strict` rejects those warnings. After replacing the example implementation and filling the schemas, mappings, lookups, and vectors, build a transfer bundle from a workstation with Podman or Docker Buildx:

```sh
billie kid build . --platform linux/arm64
```

Choose `linux/amd64` or `linux/arm64` to match the target node. Cross-platform builds need the selected engine to support the target architecture; Docker Buildx is detected when Podman is unavailable. The command writes an OCI image archive, resolved manifest, bundle metadata, and checksums under `dist/kids/`. Copy the bundle and checksum sidecar to the node, then install them:

Declare each decoder in `decoderImplementations` in the manifest. Mark an implementation `deployable` only when its language-specific Containerfile and runtime command provide the complete input listener, mapping, and translator-socket flow. Mark decoder libraries without that runtime as `library-only` and explain the missing piece with `reason`. When multiple implementations are deployable, the build command prompts for one; automation can pass `--decoder-language python|rust|typescript`. The chosen decoder, mapper, command, and language are recorded in the bundle.

At activation, Billie runs the image as a dedicated unprivileged host UID and the `billie-kids` group. It drops all Linux capabilities and mounts the shared translator socket. Make every runtime file and directory readable by an arbitrary non-root UID; do not depend on a fixed UID in the image. If the process needs writable storage, declare and document that requirement rather than writing into the image filesystem.

```sh
scp dist/kids/billie-kid-example-kid_0.1.0.tar.gz \
  dist/kids/billie-kid-example-kid_0.1.0.tar.gz.sha256 operator@<node-address>:/tmp/
```

Run the following commands on the node:

```sh
sudo billie kid install /tmp/billie-kid-example-kid_0.1.0.tar.gz
sudo billie network interfaces
sudo billie network configure --interface eth0 --address 192.0.2.20/24
sudo billie kid configure example-kid --transport udp --bind-address 192.0.2.20 --port 5100 --source-cidr 192.0.2.0/24
sudo billie kid activate example-kid
billie kid status example-kid
billie kid logs example-kid
```

Before configuring the kid, inspect the node links and set a static address on its dedicated sensor-facing interface. Replace `eth0` and `192.0.2.20/24` with the interface and address plan for your node. The example address is reserved for documentation. The network command asks for confirmation, adds no gateway or DNS, and protects default-route and current SSH interfaces. `kid configure` then selects the already assigned bind address, transport, and host port.

The bundle is unsigned; the external checksum detects transfer changes but does not authenticate who built it. A package declares which TCP or UDP listener it implements and the port inside its container. `kid configure` selects a listener declared by that package, an already assigned node bind address, and the host port; it cannot change the decoder's transport implementation. When UFW is active, it asks which sensor source CIDR to allow and creates scoped input and Podman forwarding rules; supply `--source-cidr` in noninteractive use. Billie records these rules so `kid remove` and full teardown can delete them. Assign a static address to the dedicated sensor port first with `sudo billie network configure --interface <interface> --address <IPv4/CIDR>`. The network command does not add a gateway or DNS. One selected listener is active at a time. `sudo billie kid deactivate example` stops the service and preserves installed files. Remove a package with `sudo billie kid remove example`; add `--remove-config` only when you also want to delete its protected runtime configuration. Full node removal is `sudo billie teardown`; it removes node identity and fabric certificates after a second confirmation, and leaves NetBird untouched. Use `--preserve-credentials` only to keep the identity and certificates.
