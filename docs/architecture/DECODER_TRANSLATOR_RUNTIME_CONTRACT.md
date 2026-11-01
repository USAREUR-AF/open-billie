# Decoder-to-Translator Runtime Contract

## Purpose

This document defines the boundary between a sensor-specific kid and the shared Rust translation/encoding path, and the handoff to the Open Billie platform transport. The platform lifecycle and Python/TypeScript OETF adapters implement the first slice. The Rust OETF streaming adapter is included and has passed an arm64 Pi TCP acceptance run.

## Ownership

| Component | Owner | Responsibility |
| --- | --- | --- |
| Sensor connection and framing | Kid | Open the configured TCP or UDP input, frame messages, and handle sensor-specific connection behavior. |
| Decoder | Kid | Convert sensor bytes into decoded source fields. Any suitable language may be used. |
| Mapper | Kid/user | Apply user-authored source-field-to-canonical-field mappings, conversions, and lookup tables. Do not infer sensor semantics in Billie core. |
| Translator | Billie Rust runtime | Select the requested output format and populate its format-specific structure from the canonical mapped record. Reject missing required values and report actionable validation errors. |
| Encoder | Billie Rust runtime | Serialize the translated structure into the selected wire representation. CoT, ASTERIX CAT062, and SAPIENT BSI Flex 335 v2.0 are shared Rust encoders. |
| Output transport | Open Billie platform | Map a logical output to its configured local Zenoh key expression, accept encoded output, and report local delivery. |
| Zenoh island and fabric egress | Open Billie platform | Provision the local Zenoh router, separate fabric client, mTLS certificates, vendor-prefix bridge, service lifecycle, health checks, and connectivity troubleshooting. |

The processing path is:

```text
TCP/UDP sensor input
  -> kid decoder (polyglot)
  -> kid mapper (user-defined fields and conversions)
  -> local versioned interface
  -> Rust translator
  -> Rust encoder (CoT / ASTERIX CAT062 / SAPIENT)
  -> Open Billie platform output transport
  -> local Zenoh island
  -> Open Billie platform mTLS fabric client and prefix bridge
  -> Downstream data fabric
```

## Local interface

The initial Linux node contract uses a Unix domain socket, which is reachable only on the local host and does not require a network listener. The socket path and permissions are managed by Billie. A future Windows development adapter may use a named pipe while preserving the same message schema.

Use UTF-8 JSON with newline-delimited framing for the first implementation. Each request and response is one JSON object per line. The schema is versioned independently of kid packages. Protobuf may be added as a negotiated transport later without changing the field semantics.

A mapper request carries a complete canonical record, logical output name, and requested output format. It must not contain raw credentials, Zenoh key expressions/session keys, or private endpoints.

Example request:

```json
{
  "apiVersion": "billie.dev/translation-v1",
  "kind": "TranslateRequest",
  "requestId": "01JEXAMPLE",
  "kid": "oetf",
  "target": { "outputName": "tracks-cot", "format": "cot" },
  "record": {
    "apiVersion": "billie.dev/track-v2",
    "kind": "Track",
    "trackId": "synthetic-001",
    "sourceId": "sensor-a",
    "trackGeneration": "fixture-1",
    "observedAt": "2026-01-01T00:00:00Z",
    "position": { "latitudeDeg": 45.0, "longitudeDeg": -73.0 }
  }
}
```
Example successful response:

```json
{
  "apiVersion": "billie.dev/translation-v1",
  "kind": "TranslateResult",
  "requestId": "01JEXAMPLE",
  "status": "published",
  "outputName": "tracks-cot",
  "format": "cot",
  "bytesPublished": 312
}
```
Example failure response:

```json
{
  "apiVersion": "billie.dev/translation-v1",
  "kind": "TranslateResult",
  "requestId": "01JEXAMPLE",
  "status": "rejected",
  "error": {
    "code": "missing_required_field",
    "message": "CoT output requires record.position.latitudeDeg",
    "path": "record.position.latitudeDeg"
  }
}
```

The contracts are [canonical-track-v2.schema.json](../../schemas/canonical-track-v2.schema.json), [translation-request-v1.schema.json](../../schemas/translation-request-v1.schema.json), and [translation-result-v1.schema.json](../../schemas/translation-result-v1.schema.json). Field units and mapper conversions are described in [CANONICAL_TRACK_V2.md](../../schemas/CANONICAL_TRACK_V2.md). `requestId` is used for log correlation; secrets and full sensor payloads must not be copied into routine logs.

## Translation and encoding behavior

- `target.format` selects a registered Rust translator and encoder. Unsupported formats are rejected with a stable error code.
- The translator may supply protocol-defined structure and defaults, but must not invent sensor-specific values or silently substitute for missing required mapped fields.
- The mapper owns units and semantic conversions. The translator validates the canonical units declared by the interface.
- Canonical identity is `(authenticated kid, sourceId, trackId, trackGeneration)`. The kid namespace comes from the translator's authenticated local socket peer, while the mapper supplies a stable source ID and a generation token that advances when its source reuses a track ID. Do not use `observedAt` as the generation.
- The encoder receives a validated output structure and returns bytes with a declared media type/encoding.
- Canonical Track v2 carries optional `testData`, `headerSimulated`, `simulated`, `confirmed`, `coasting`, and `finalUpdate` booleans. OETF maps its numeric 0/1 frame and per-track bits to JSON booleans through the shared `toBoolean` mapping conversion. Omitted status values remain unknown; CAT062 rejects an omitted `confirmed` value because its status item requires an explicit state.
- The CoT encoder marks simulated/test data with `opex="s"` and preserves the complete status set as comma-separated tokens in `<remarks>` (`test-data`, `simulated`, `tentative`, `coasting`, `final-update`). These remark tokens are Open Billie conventions.
- The CAT062 encoder emits mandatory I062/080 Track Status (FRN 13), including SIM, CNF, TSE, and CST where represented by the canonical fields. Header test/simulation and per-track simulation map to SIM; `confirmed=false` maps to CNF; `finalUpdate` maps to TSE; and `coasting` maps to CST. CAT062 encodings should be checked against independent interoperability vectors before release.
- CoT and SAPIENT use the scoped canonical identity for track/object identity. CAT062 encodes its configured SAC/SIC with numeric 12-bit `trackId`. Resolve SAC/SIC in this order: exact authenticated kid and `sourceId` mapping, legacy wildcard mapping while migrating, then the optional node default configured with `billie cat062 default set`. Without an applicable assignment or default, the translator rejects CAT062 output for that track. Exact source mappings should be used whenever sources need distinct identities.
- SAPIENT BSI Flex 335 DetectionReport field `state` is a free-form string. When status flags are set, Open Billie emits comma-separated tokens (`test-data`, `simulated`, `tentative`, `coasting`, `final-update`). These tokens are an Open Billie convention, not standardized SAPIENT enum values; receivers may ignore them.
- A successful result means the Open Billie local transport accepted the encoded sample. End-to-end delivery is verified separately by the Open Billie local-router, bridge, and fabric tests.
- The interface must support bounded message size, request timeouts, backpressure behavior, and per-record error reporting. One invalid record must not silently terminate the kid process.

## Configuration and secrets

Per-node configuration is injected when a kid is activated; it is not committed in a kid package or sent in each translation request. Open Billie platform owns Zenoh and fabric connectivity configuration, including endpoint, mTLS bundle, certificate validation, vendor prefix, bridge, and service health. The kid receives only its local translator socket and logical output name. The translator maps that name to a local key expression; sensor decoders and mappers never receive fabric private keys or remote credentials.

Configuration is divided into:

- **Sensor input:** transport (`tcp` or `udp`), bind/connect mode, address, port, and framing options. These are kid runtime settings, not mapper semantics.
- **Output selection:** logical output name, encoder format, and optional profile. The Open Billie platform binds the logical output to its local route/key expression and publisher.
- **Zenoh and fabric connection:** owned and configured by Open Billie platform. The island router never federates; a separate client-mode session connects to the remote fabric.
- **Credentials:** Open Billie platform installs administrator-provided certificate material into a protected node directory. CLI configuration accepts file paths and non-secret endpoint/prefix values; it never prints or embeds private key contents in manifests, logs, or release artifacts.

The CLI should prompt for non-secret values discovered from the selected kid manifest and encoder capabilities. Open Billie platform also configures the Zenoh fabric endpoint, vendor prefix, and certificate file paths, validates them, and applies the protected service configuration before activation.

## Language independence

A kid may implement its decoder and mapper in Python, TypeScript, Rust, Go, or another supported language. Language-specific code ends at the local translation request. The kid author implements a small adapter that emits the versioned JSON request; the shared Rust runtime owns output translation and encoding. Open Billie platform owns output routing and Zenoh. A kid must not need to reimplement the shared CoT, ASTERIX CAT062, or SAPIENT encoders, or platform publishing.

## Conformance checklist

Use the synthetic OETF kid to exercise and repeat the following checks across the kid-to-translator and Open Billie platform boundaries:

1. Send a synthetic UDP datagram into the kid.
2. Decode it and apply a fixture mapper with explicit conversions.
3. Send the canonical record through the local socket contract.
4. Request each supported output format and validate generated bytes against synthetic fixtures/specification tests.
5. Pass one encoded format through the Open Billie local output transport and assert it arrives on the configured local Zenoh route; separately verify the bridge applies the configured vendor prefix and forwards it through the mTLS fabric client.
6. Exercise missing-field, unsupported-format, malformed-message, timeout, reconnect, and secret-redaction cases.
7. Repeat the same socket-contract conformance test with at least two decoder language adapters to demonstrate the polyglot boundary.

## Implementation and remaining acceptance

The shared Rust translator provides a strict request parser, canonical-class translator, CoT XML encoder, CAT062 Edition 1.21 subset encoder, SAPIENT BSI Flex 335 v2.0 protobuf encoder, format dispatcher, Unix socket service, and loopback Zenoh publisher in [`runtime/rust/translator`](../../runtime/rust/README.md). The socket enforces local-only access through `0600` permissions and bounded newline-delimited JSON requests. Python, TypeScript, and Rust OETF ingress adapters have been exercised on the test Pi. Prior UDP/TCP OETF runs delivered CoT/CAT062 output visible to an authorized subscriber; the translator accepted SAPIENT requests, but an independent SAPIENT receiver check remains open. CoT conformance against the selected MIL-STD-6090 profile and CAT062 conformance against independent interoperability vectors also remain open.

Open Billie platform owns and provisions the local Zenoh island, separate mTLS fabric client, certificate/key validation and installation, vendor-prefix bridge, service lifecycle, and diagnostics. A later listener reconfiguration exposed stale Netavark forwarding. Platform 0.2.1 includes cleanup-before-start and exact DNAT verification; a clean ARM64 TCP Pi run exercised that path successfully. A second independent kid package is still needed to demonstrate plug-and-play package interoperability. Independent remote health receipt, fresh NetBird enrollment, and the published GitHub signing workflow remain separate acceptance items. `KID_PACKAGE_CONTRACT.md` and `kid-manifest.schema.json` define logical output intent while the Open Billie platform supplies routes and transport.
# Local translator trust boundary

The translator socket is a local Unix socket shared by active kids. The socket
is owned by root and the `billie-kids` group; each kid container runs with a
stable, unprivileged host UID and that group as its primary GID. The translator
authenticates the connecting process with Linux `SO_PEERCRED`, resolves that
UID through the root-owned `/etc/billie/translator/kids.json` registry, and
checks the request's kid ID and `(output name, format, profile)` against the
outputs copied from that installed kid's manifest at activation. The submitted
`kid` field remains for compatibility but is not an identity claim. The
registry is read on every request, so activation, deactivation, and removal
take effect without restarting the translator. Deactivation removes the
authorization entry before stopping the kid service.

The kid container uses `--userns=host` so the kernel peer UID is the same
stable host UID registered by the platform. The container drops all Linux
capabilities, uses a read-only root filesystem, and receives only the shared
translator socket. Container images must therefore make runtime code and
decoder assets readable by the assigned unprivileged UID; runtimes may write
only to explicitly allocated temporary storage.

The translator accepts up to 64 concurrent local clients. Its systemd runtime
directory is preserved across automatic service restarts. Kid systemd units
are `PartOf` the translator service, so a translator restart stops and starts
the kids as well; each restarted container then mounts the newly created
socket inode. The socket is recreated with root ownership and the shared kid
group on process startup.
