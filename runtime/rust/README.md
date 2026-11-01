# Billie Rust translator

This crate is the shared Rust boundary for kid translation requests. It parses and validates the versioned request, maps canonical tracks to CoT XML, ASTERIX CAT062 Edition 1.21 records, or SAPIENT BSI Flex 335 v2.0 protobuf messages. Runtime options provide CoT TTL and `how`, CAT062 SAC/SIC, and the SAPIENT node UUID.

It rejects unknown fields (including kid-supplied Zenoh routes), unsupported format names, malformed timestamps, out-of-range coordinates/confidence, and incomplete velocity or uncertainty groups. It accepts only the versioned contracts documented in [`schemas/`](../../schemas/).

## Build and test

From this directory:

```sh
cargo test
```

The integration test reads the synthetic OETF translation-request fixture from the repository schema examples. The OETF mapper test separately proves that decoding and user-defined mapping produce that canonical track shape.

## Current scope

A first ASTERIX CAT062 Edition 1.21 encoder writes a minimal UAP record with source identifier, UTC time, WGS-84 position, numeric track number, and optional velocity/geometric altitude. It resolves SAC/SIC by exact kid and `sourceId`, then a migrated legacy wildcard assignment, then the optional node default. Configure a single-source default with `sudo billie cat062 default set --sac <0-255> --sic <0-255>`; configure source-specific pairs with `sudo billie cat062 source set <kid> <sourceId> --sac <0-255> --sic <0-255>`. Without a matching assignment or node default, CAT062 requests are rejected. The map is stored in `/etc/billie/translator/cat062-sources.json`; the CLI restarts the translator after changes. SAPIENT encodes a BSI Flex 335 v2.0 `SapientMessage` with a DetectionReport, WGS-84 geodetic location, optional ENU velocity, confidence, and canonical classification. `BILLIE_SAPIENT_NODE_ID` must contain a valid deployment UUID; normal node initialization stores a generated UUID in the protected node identity and passes it to the translator service. Each `report_id` is a fresh ULID. A generated `object_id` is cached by authenticated kid plus canonical `sourceId`, `trackId`, and `trackGeneration` in `/var/lib/billie/sapient-object-ids.json`, so a track lifetime retains its identity across reports and service restarts without aliasing another source, kid, or reused ID. Teardown removes this cache with Billie state. CoT uses the same scoped identity in `uid`. A Zenoh sample carries exactly one protobuf message, with no additional TCP stream prefix. SAPIENT classification labels follow the OETF sample lookup table. The shared dispatcher returns encoded bytes with a media type. The SAPIENT unit test decodes output with a Prost model matching the official field numbers, but interoperability with an independently generated official receiver remains to be verified. CAT062 field layout also still needs independent interoperability vectors. For the SAPIENT schema, see the [official Dstl SAPIENT v2.0 protobuf definitions](https://github.com/dstl/SAPIENT-Proto-Files/tree/main/bsi_flex_335_v2_0); for CAT062, see the [EUROCONTROL Category 062 Edition 1.21 specification](https://www.eurocontrol.int/sites/default/files/2025-06/asterix-cat062-system-track-data-p9-ed1-21.pdf).

On Unix platforms, `serve_unix` provides the first local IPC service. It accepts one UTF-8 JSON request per connection, terminated by a newline, with a 1 MiB maximum request size and a 10 second I/O timeout. It creates the socket with mode `0600`, removes an existing path only when it is already a socket, and returns one JSON `TranslateResult` line. Each encoded payload carries the kid ID, logical output name, output format, media type, and bytes, allowing the platform adapter to route without exposing a Zenoh key expression to the kid. A platform-supplied publisher callback must report success before the response says `published`; the Rust translator has no Zenoh client or certificate dependency.

The Open Billie platform owns Zenoh and fabric mTLS. It provisions the local Zenoh island, the separate fabric client and its certificate/key files, and the one-way island-to-fabric bridge that applies the configured prefix. The translator publishes encoded output through the local Zenoh integration and has no fabric certificate or remote endpoint configuration. The listener processes connections serially in this initial version. Independent end-to-end SAPIENT interoperability validation remains open.
