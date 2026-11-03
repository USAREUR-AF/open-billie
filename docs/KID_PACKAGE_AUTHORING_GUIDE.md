# Create a Billie kid package: from schema to deployment

This guide takes a new sensor integration from its protocol description to a running kid on a Billie node. It covers package design, schemas, mapper decisions, runtime behavior, tests, image builds, transfer, installation, activation, and verification.

A kid is an independently maintained package. Its decoder, sensor schema, mapping rules, lookups, and runtime stay in the kid repository. Open Billie supplies the host lifecycle, shared translator and encoders, and Zenoh and fabric transport. Keep proprietary source, captures, credentials, and endpoint details out of the Open Billie repository.

Read the [Kid Package Contract](architecture/KID_PACKAGE_CONTRACT.md), [Decoder-to-Translator Runtime Contract](architecture/DECODER_TRANSLATOR_RUNTIME_CONTRACT.md), [canonical track schema](../schemas/canonical-track-v2.schema.json), and [canonical track fields and units](../schemas/CANONICAL_TRACK_V2.md) alongside this guide.

## 1. Prepare the workstation and node

The workstation holds the kid source and builds the deployment bundle. The Ubuntu node runs the platform and kid locally.

### Workstation prerequisites

- Git and an Open Billie checkout for the template, schemas, and CLI tools.
- Python 3.10 or later, plus the YAML and JSON Schema modules required by the source tools.
- Podman, or Docker with Buildx, for building the kid image.
- SSH and SCP access to the prepared node.
- A build engine that can produce the node's architecture. Cross-architecture builds may require image emulation.

On Windows, run Bash workflows from Ubuntu in WSL 2. On macOS and Linux, use a Bash terminal. The authoring commands are the same; container engine setup and cross-architecture emulation vary by platform.

### Node prerequisites

- A prepared Ubuntu 24.04 node with an Open Billie platform release installed.
- SSH access as a user with non-interactive sudo.
- A reachable address and known node architecture.
- A dedicated sensor-facing interface if the sensor connects directly over Ethernet. Do not assign its sensor address to the management/default-route interface.

Create an isolated Python environment for source tools rather than changing the operating system Python:

Linux or macOS:

    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install PyYAML jsonschema

Windows users should create and activate the environment inside Ubuntu WSL using the same commands. Activate it again in each new terminal before running Open Billie source tools.

Check the local checkout and CLI:

Linux or macOS:

```sh
cd /path/to/open-billie
python3 --version
bash deploy/bin/billie kid --help
```

Windows PowerShell with WSL:

```powershell
wsl.exe -d Ubuntu-24.04 -- bash -lc 'cd /mnt/c/path/to/open-billie && python3 --version && bash deploy/bin/billie kid --help'
```

The deployment node does not need the kid source checkout. Build and transfer the bundle from the workstation.

## 2. Create an independent kid repository

Create the kid repository outside the Open Billie checkout. Copy the scaffold into it:

Linux or macOS:

```sh
mkdir -p "$HOME/src/my-sensor-kid"
cp -a /path/to/open-billie/kids/_template/. "$HOME/src/my-sensor-kid/"
cd "$HOME/src/my-sensor-kid"
git init
```

Windows PowerShell:

```powershell
Copy-Item -Recurse C:\path\to\open-billie\kids\_template "$env:USERPROFILE\src\my-sensor-kid"
Set-Location "$env:USERPROFILE\src\my-sensor-kid"
git init
```

On Windows, run subsequent Bash and container-build commands from WSL against this checkout. Keep proprietary kid source in its own repository; the tracked Open Billie kids directory is for public synthetic examples such as OETF.

The scaffold contains a manifest, Containerfile, and directories for decoder, mapper, schemas, mappings, lookups, and test vectors. Replace its example values and README. Its image and implementation placeholders are intentionally not deployable.

## 3. Document the sensor protocol

Before writing code, record the wire contract from an authoritative interface document:

- Transport: UDP datagrams or TCP streams.
- Framing: fixed size, length prefix, delimiter, sync marker, or another protocol rule.
- Byte order, offsets, field widths, signedness, scaling, units, and valid ranges.
- Message IDs, versions, enum values, flags, optional and repeated fields.
- Checksum/CRC, sequence behavior, timestamps, reconnect behavior, and maximum frame size.
- Expected handling for truncated, malformed, corrupt, and unknown-version messages.

TCP is a byte stream: a read can contain a partial frame or multiple frames. Reassemble frames using the protocol's framing rule. For UDP, define whether one datagram contains one complete message or whether the protocol explicitly defines fragmentation. Do not assume that transport packet boundaries are message boundaries unless the protocol says so.

These details belong in the kid repository. Keep private protocol documents and proprietary captures out of Open Billie.

## 4. Define schemas for decoded source data

Keep the source decode schema separate from the Billie canonical track schema. The decoder turns sensor bytes into typed source fields; the mapper converts those fields into canonical records.

Store source schemas under the package's schemas directory. The mapper generator accepts:

- Open Billie byte-offset JSON decode schemas.
- Protocol Buffers .proto files, using protoc and the Python protobuf descriptor module.

A JSON decode schema should describe message identifiers, offsets, wire types, signedness, scale, units, enums, and repetition. A protobuf schema should preserve field numbers, types, cardinality, nested messages, oneofs, and enum domains. Also keep a JSON Schema for the decoder's normalized decoded-record structure under schemas: the current package validator checks JSON data files there, while mapper generation reads the .proto descriptor. Run protoc and test each schema against synthetic input; the package validator does not compile .proto files.

The shared translator consumes billie.dev/track-v2 canonical records. It does not consume raw sensor schemas or infer sensor meaning. Required fields are a stable trackId, sourceId, trackGeneration, observedAt as RFC 3339, and WGS-84 latitude and longitude. Optional canonical fields have defined units and semantics. Omit measurements and status fields the sensor does not provide; do not invent them.

## 5. Generate and review a mapper plan

The mapper generator inventories source fields and creates a reviewable plan. It does not decide that similarly named fields have the same meaning, and the plan is not an executable mapper.

For a Billie JSON decode schema:

```sh
bash /path/to/open-billie/deploy/bin/billie mapper generate \
  --schema schemas \
  --format billie-json \
  --source-protocol my-sensor \
  --target billie-canonical \
  --output mappings/mapper-plan.json \
  --mappings-dir mappings/generated \
  --interactive
```

For Protocol Buffers:

```sh
bash /path/to/open-billie/deploy/bin/billie mapper generate \
  --schema schemas/messages.proto \
  --format protobuf \
  --source-protocol my-sensor \
  --target billie-canonical \
  --proto-path schemas \
  --output mappings/mapper-plan.json \
  --mappings-dir mappings/generated \
  --interactive
```

Generated bindings remain unresolved until reviewed. A person must decide target fields, unit conversions, coordinate conventions, enum lookups, repeated-field handling, identifiers, and required constants. Same-name copies are disabled by default. The enable-direct option creates candidate copies but does not remove the need for semantic review.

For every source field, record one decision in the kid's mapping documentation: map it to a canonical field with an explicit conversion; preserve it as a namespaced identifier where appropriate; intentionally omit it with a reason; or reject it as unsupported. Do not map directly to CoT, CAT062, or SAPIENT structures. The mapper emits canonical records; the shared Rust translator constructs the requested output format.

Keep transformations in mappings and lookup tables in lookups. Include provenance to the source field. Re-review mappings and vectors whenever the source schema changes.

## 6. Implement and test the decoder and mapper

The current manifest schema and builder support Python, Rust, and TypeScript implementation entries. Supporting another implementation language requires extending the manifest schema and builder, in addition to providing a container runtime and adapter that follows the same translator contract.

The kid runtime must:

1. Bind to the container listener and port Billie supplies. The platform sets BILLIE_INPUT_PORT and BILLIE_INPUT_TRANSPORT; the runtime binds inside the container so the host address and firewall rules control exposure.
2. Decode protocol-defined frames and validate sizes, versions, checksums, and field ranges.
3. Apply the kid's reviewed mappings, conversions, and lookups.
4. Emit canonical records and select a logical output declared in the manifest.
5. Send a versioned, newline-delimited JSON request to the Unix socket named by BILLIE_TRANSLATOR_SOCKET. Check the response and correlate it using requestId.

A translation request has this shape:

```json
{
  "apiVersion": "billie.dev/translation-v1",
  "kind": "TranslateRequest",
  "requestId": "unique-request-id",
  "kid": "my-sensor",
  "target": { "outputName": "tracks-cot", "format": "cot" },
  "record": {
    "apiVersion": "billie.dev/track-v2",
    "kind": "Track",
    "trackId": "311",
    "sourceId": "sensor-a",
    "trackGeneration": "generation-1",
    "observedAt": "2026-10-31T12:00:00Z",
    "testData": false,
    "headerSimulated": false,
    "simulated": false,
    "position": { "latitudeDeg": 0.0, "longitudeDeg": 0.0 }
  }
}
```

outputName and format must match interfaces.outputs in the manifest. The translator rejects a request that omits `testData`, `headerSimulated`, or `simulated`; do not map an unknown source state to false. The platform exposes only the translator socket to the kid. Do not implement Zenoh in the kid, include fabric credentials, or log secrets or full raw messages.

Add synthetic input and expected decoded/canonical output vectors under tests/vectors. Include valid, malformed, truncated, unknown-version, and boundary cases. Test mapper conversions and lookups. If supporting TCP, test fragmentation and multiple frames per connection. If supporting UDP, test datagram handling. Keep real sensor captures in the sensor owner's private repository.

## 7. Complete the manifest and image

Edit billie-kid.yaml:

- Set a unique lowercase metadata.id, semantic metadata.version, display name, description, and repository.
- Point components at the decoder, mapper, schemas, mappings, lookups, and vectors.
- Declare only implemented listeners. Each input has a name, udp or tcp transport, and container port.
- Declare logical outputs using supported formats: cot, asterix-cat062, or sapient. SAPIENT output also requires the platform-initialized stable node UUID; the kid must not generate or store a separate fabric identity.
- Set the runtime command and required environment variables, including BILLIE_TRANSLATOR_SOCKET, BILLIE_INPUT_PORT, and BILLIE_INPUT_TRANSPORT when used.
- Put the package's license and required third-party notices under `licenses/`; the builder includes this directory in the staged Containerfile context. Copy applicable files into the final runtime image.
- Add decoderImplementations per language. Mark one deployable only when decoder, mapper, Containerfile, and command implement the full ingress-to-translator path. Otherwise mark it library-only and explain what is missing.
- The source manifest requires a digest-shaped image reference. During build, Billie replaces that source value in the bundle manifest with the immutable digest of the image just built. The scaffold placeholder is acceptable during development validation, but it produces a warning and is not deployable; strict source validation rejects it.

The manifest schema is strict about supported output formats and paths. The declared port is inside the container; the operator separately selects the node IP and host port. A CLI transport choice cannot add a transport the runtime does not implement.

Build a minimal Containerfile with the runtime, source required at execution, and schemas/mappings/lookups read at runtime. Exclude build-only files and credentials. Keep runtime.command consistent with the image. The platform overrides the image user with a dedicated, unprivileged host UID and the `billie-kids` group, drops all Linux capabilities, and mounts the shared translator socket. Make runtime files readable by an arbitrary non-root UID; do not depend on a fixed image UID or a writable root filesystem. Write only to explicitly allocated temporary storage.

## 8. Validate, test, and build locally

From an Open Billie source checkout, validate the kid package. Validation is offline and does not execute the kid:

```sh
bash /path/to/open-billie/deploy/bin/billie kid validate /path/to/my-sensor-kid
```

Resolve missing files, invalid paths, and empty schemas/mappings/lookups/vectors. A development image placeholder is reported as a warning on the first source validation; the builder replaces it with the built image digest in the deployment bundle. Use strict validation only after the source manifest itself contains a real, non-placeholder image digest. Run the kid's own unit and conformance tests. Do not mark an implementation deployable until its decoder, mapper, and runtime adapter pass.

Query the node architecture:

```sh
ssh operator@<node-address> 'dpkg --print-architecture'
```

Build for that architecture and select the implementation you intend to ship:

```sh
bash /path/to/open-billie/deploy/bin/billie kid build \
  /path/to/my-sensor-kid \
  --platform linux/arm64 \
  --decoder-language rust
```

Use linux/amd64 for an amd64 node. If multiple implementations are deployable, the builder prompts unless decoder-language is supplied. Cross-architecture builds need container-engine emulation support.

The build creates a kid bundle in Open Billie's dist/kids directory and a neighboring .sha256 sidecar. The bundle contains the resolved manifest and image archive, not the source repository. Keep source and release artifacts in the kid owner's repository and artifact storage.

## 9. Transfer and install

Copy the bundle and its checksum to the node:

```sh
scp /path/to/open-billie/dist/kids/billie-kid-my-sensor_0.1.0.tar.gz \
  /path/to/open-billie/dist/kids/billie-kid-my-sensor_0.1.0.tar.gz.sha256 \
  operator@<node-address>:/tmp/
```

Install on the node:

```sh
ssh operator@<node-address> \
  'sudo billie kid install /tmp/billie-kid-my-sensor_0.1.0.tar.gz'
```

Installation verifies the external checksum, internal bundle checksums, image digest, manifest, and node architecture before loading the image. The current bundle checksum detects accidental changes but does not authenticate its builder; kid bundle signing is not implemented yet.

## 10. Configure the sensor interface and listener

Inspect node links and identify the dedicated sensor port by interface name and MAC address:

```sh
ssh operator@<node-address> 'sudo billie network interfaces'
```

If necessary, assign a static address from the sensor network's approved address plan:

```sh
ssh operator@<node-address> \
  'sudo billie network configure --interface <sensor-interface> --address <node-ipv4>/<prefix>'
```

This creates a Billie-managed Netplan snippet without gateway or DNS. Billie refuses the default-route and active SSH interfaces. Confirm the address is present on the intended interface. An IPv4 CIDR prefix represents the subnet mask; for example, /24 corresponds to 255.255.255.0. Use your network plan, not an example address.

Configure a manifest-declared listener. Replace the listener name, transport, address, port, and source CIDR with the package and deployment values:

```sh
ssh operator@<node-address> \
  'sudo billie kid configure my-sensor --version 0.1.0 --listener tracks-udp --transport udp --bind-address <node-ipv4> --port 5100 --source-cidr <sensor-network>/<prefix>'
```

The bind address must already belong to the node. The host port may differ from the container port. When UFW is active, source CIDR limits which sensor addresses can reach the listener; use the actual source network.

## 11. Activate and verify

Activate the installed version and inspect the service:

```sh
ssh operator@<node-address> \
  'sudo billie kid activate my-sensor --version 0.1.0'
ssh operator@<node-address> 'sudo billie kid status my-sensor'
ssh operator@<node-address> 'sudo billie kid logs my-sensor --lines 100'
ssh operator@<node-address> 'sudo billie verify'
```

Send a known synthetic vector or the kid's own simulator. Verify each stage:

1. Traffic arrives on the intended interface, transport, and port.
2. Kid logs show successful decoding and mapping.
3. Translator logs show acceptance for each declared output.
4. The expected publication appears on its local Zenoh route.
5. The Open Billie bridge forwards it with no rejects.
6. An authorized downstream subscriber displays it.

Successful decoding or a local translator response alone does not prove remote delivery. Record which stages passed.

## 12. Troubleshooting and safe maintenance

| Symptom | Check |
| --- | --- |
| Build fails | Validate first; confirm the selected Containerfile and command exist, the engine is running, and the target architecture is supported. |
| Install says checksum missing | Transfer the neighboring .sha256 file to the same node directory. |
| Listener does not start | Check sudo billie kid status/logs, selected transport, port, image command, and declared environment. |
| No packets arrive | Confirm interface and address with sudo billie network interfaces; check sensor subnet, cable, transport, host port, UFW rule, and sender address. |
| Bytes arrive but no translator request | Check framing, length/CRC/version validation, schema interpretation, conversions, lookups, and test vectors. |
| Translator rejects a request | Validate against canonical-track-v2.schema.json; check required fields, units, timestamp, output name, and format. |
| Local output appears but remote output does not | Inspect Billie health, Zenoh island, fabric client, bridge, and certificate diagnostics. Never add fabric credentials to a kid. |

Stop a kid while retaining its installation with sudo billie kid deactivate my-sensor. Remove it with sudo billie kid remove my-sensor; --remove-config also deletes protected runtime configuration. Full platform removal is sudo billie teardown. Teardown requires explicit confirmation before deleting node identity and fabric credentials and leaves NetBird untouched.

## 13. Release the kid independently

Version the kid independently of Open Billie. Review schema and mapping changes together with decoder and test-vector changes. Transfer or publish bundles through the sensor owner's approved distribution process; GitHub Packages is not required. Keep proprietary source and release artifacts in the owner's repository, never in the Open Billie platform Debian release.

For each release, retain the source revision, selected implementation, target architecture, bundle checksum, conformance results, node installation result, listener configuration, and end-to-end publication result.

