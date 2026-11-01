# OETF TypeScript runtime

This runtime connects the OETF TypeScript decoder and mapper to the Open Billie translator. It accepts one selected input transport (`udp` or `tcp`), applies the shared OETF-to-canonical map, and sends each canonical track to the Rust translator over the local Unix socket. The runtime requests the package-declared CoT, ASTERIX CAT062, and SAPIENT outputs from the shared Rust translator, which publishes through Open Billie platform.

## Runtime configuration

The kid service sets these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `BILLIE_INPUT_BIND` | `0.0.0.0` | Address inside the container to listen on |
| `BILLIE_INPUT_PORT` | `5100` | Container listener port |
| `BILLIE_INPUT_TRANSPORT` | `udp` | `udp` datagrams or `tcp` byte stream |
| `BILLIE_TRANSLATOR_SOCKET` | `/run/billie/translator.sock` | Billie local translator socket |

The network interface and host-side port are selected with `billie kid configure`. The runtime does not manage Zenoh or credentials. TCP has independent framing state per connection, supports fragmented and back-to-back frames, and reports incomplete frames when a peer disconnects. It accepts up to eight simultaneous TCP connections.

## Build

From the Open Billie repository root, build the package with the normal kid builder:

```sh
bash deploy/bin/billie kid build kids/examples/oetf --decoder-language typescript --platform linux/arm64
```

`Containerfile.typescript` compiles the TypeScript decoder, map executor, and runtime in the package workspace. The source schemas, maps, and lookup tables stay in the shared OETF data directories.
