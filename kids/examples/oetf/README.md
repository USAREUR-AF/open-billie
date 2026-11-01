# OETF synthetic kid example

This is a local, synthetic example kid included to demonstrate how a decoder repository can carry its own framing code, schemas, mappings, lookup tables, and conformance vectors. OETF is a fictional format described by [the wire specification](docs/WIRE_FORMAT.md); its source project states that it is not derived from a real sensor interface.

This synthetic example is maintained inside the Open Billie checkout for development. It is not a GitHub package, is not part of the core Debian release, and is not installed automatically on nodes. The standard kid build, transfer, install, configure, and activation flow supports it.

## Included implementations

- `packages/oetf/typescript/decoder`: streaming decoder, parser, frame builder, and decoder tests.
- `packages/oetf/typescript/mappings`: map/lookup path adapter and field coverage tests.
- `packages/oetf/typescript/runtime`: deployable TypeScript UDP/TCP ingress, canonical mapping, and translator-socket adapter.
- `packages/oetf/rust`: decoder, mapper, and deployable Rust UDP/TCP ingress with translator-socket adapter.
- `packages/oetf/python`: decoder, reference builder, map executor, and conformance tests.
- The Python and Rust implementations include reference frame builders, shared-map execution, and conformance tests against the same vectors.
- `packages/oetf/shared`: the single copy of the OETF schemas, maps, lookup data, and golden vectors used by all three implementations.

The shared maps translate the synthetic OETF track record to ASTERIX CAT-062, CoT, and SAPIENT field structures. Those files remain with this example kid rather than entering the sensor-neutral core package. The canonical map feeds the shared Rust translator, which applies the selected encoder.

The Python, TypeScript, and Rust runtimes support UDP datagrams and TCP byte streams. The OETF frame length makes TCP streams self-delimiting, so the decoders handle fragmented reads and multiple frames per connection. Choose the package-declared `oetf-udp` or `oetf-tcp` listener in the kid wizard. Each runtime decodes frames, applies the shared canonical mapping and lookup JSON, and sends selected logical outputs to the shared Rust translator socket. None configures Zenoh or handles fabric certificates. The Open Billie platform maps logical outputs to local transport and owns the mTLS bridge. The source image references in `billie-kid.yaml` are placeholders; `billie kid build` resolves them in the bundle without editing the source manifest. Both listeners use container port 5100; activation passes the selected TCP or UDP transport to the runtime. Python UDP/TCP, TypeScript TCP, and Rust UDP/TCP paths have all been exercised on the test Pi. An authorized subscriber confirmed prior CoT/CAT062 output runs; independent SAPIENT receiver interoperability remains unverified. A later listener reconfiguration exposed a stale Netavark DNAT rule after activation; platform 0.2.0 includes cleanup-before-start and active-forward verification, and fresh Pi acceptance is pending.

## Local checks

From this directory:

```sh
pnpm install --frozen-lockfile
pnpm build
pnpm typecheck
pnpm test
pnpm test:py
pnpm test:rs
```

Python and Rust checks require `pytest` and `cargo` respectively. The checked-in vectors are the conformance baseline. The original vector-generation script depended on a separate translator checkout, so it is not carried into this standalone example.

The synthetic translator-boundary test runs without Zenoh or certificates:

```sh
python -m pytest -q packages/oetf/python/tests/test_translator_socket_integration.py
```

It uses a local socket stub to verify OETF decoding, canonical mapping, logical output selection, and request/response framing. The platform separately tests the local Zenoh route, vendor-prefix bridge, and fabric mTLS.

## Import and licensing note

The source workspace identifies its TypeScript, Python, and Rust packages as ISC-licensed, but it had no `LICENSE` file or Git metadata when imported. See [the import record](../../../docs/provenance/OETF_IMPORT.md). This copy is not a public package release; confirm the copyright holder and include the proper ISC notice before redistributing it publicly.
