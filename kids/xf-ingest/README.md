# xf-ingest kid: standard-format feeds to tracks

A kid for a sensor whose output is already a standard format. It receives the sensor's messages, has [goat-transformers](https://github.com/USAREUR-AF/goat-transformers) convert each one to Canonical Track v2, and hands the track to the Open Billie translator, which publishes it as Cursor-on-Target, SAPIENT and ASTERIX CAT062. The input format is a setting, not code: one kid image serves every sensor that sends a format listed below. Why this is a kid and not a script: [XF_INGEST_KID](../../docs/architecture/XF_INGEST_KID.md).

```text
sensor --UDP or TCP--> xf-ingest
  -> goat-xf-pipe source and framer (goat-adapters-std)       the transport, one message at a time
  -> goat-transformers engine: <XF_FROM_FORMAT> -> canonical-track-v2   packs under goat-transformers/
  -> billie: output (src/translator.rs): one request per output on the translator socket
     tracks-cot, tracks-sapient, tracks-cat062
```

The kid is the `goat-xf-pipe` command line of goat-transformers with one more output scheme, `billie:`, the translator socket. `src/settings.rs` turns the kid's settings into that command line; the kid prints it at start-up.

## Input formats

| `XF_FROM_FORMAT` | One message is | Over UDP | Over TCP (`XF_IN_FRAME`) |
|---|---|---|---|
| `cot-xml` | one Cursor-on-Target XML event | one datagram | required, for example `newline` |
| `cot-protobuf` | one TAK protocol `TakMessage`, without a mesh or stream header | one datagram | required: the stream's framing |
| `geojson` | one GeoJSON Feature with an `id` | one datagram | required, for example `newline` |
| `canonical-track-v2` | one Canonical Track v2 JSON object | one datagram | required, for example `newline` |

The list is `lookups/input-formats.json`; the pack and model files are under `goat-transformers/`, copied from the goat-transformers commit the engine is built from. A message is converted only when it gives a track identity, a time (or the kid supplies the arrival time) and a position. ASTERIX CAT062 and CAT021 and SAPIENT are not offered yet: goat-transformers decodes them, but its packs do not derive the track identity (`uid`) from the track number or object id, so the conversion to Canonical Track v2 is refused (`no-kind`). They become input formats when goat-transformers derives it and the pin here moves.

## What the kid adds to a track

| Canonical field | When the message has no value |
|---|---|
| `sourceId` | `XF_SOURCE_ID`. CAT062 SAC/SIC is assigned per `sourceId` |
| `trackGeneration` | `XF_TRACK_GENERATION`, default `1` |
| `observedAt` | the time the kid received the message |

A value the message carries is never replaced. After the conversion, a `classification` that is not a Billie track class is removed (a CoT type with no Billie class, such as `a-f-G`, is written as it is by the pack, and the translator refuses it); each removed value is printed once. `mappings/canonical-track-v2.json` states the same.

CAT062 needs a decimal `trackId` from 0 to 4095 and an explicit `confirmed`. A CoT `uid` such as `J-5` is not a number, and CoT carries no confirmation state, so CAT062 refuses such tracks; Cursor-on-Target and SAPIENT carry them.

## Settings

Billie sets the listener from `billie kid configure`; an env file given to `billie kid activate --config` sets the rest. Every key is in `schemas/xf-ingest-settings.schema.json`.

| Key | |
|---|---|
| `XF_FROM_FORMAT` | required: the input format |
| `XF_SOURCE_ID` | required: the `sourceId` of every track |
| `XF_IN_FRAME` | how one message is delimited ([goat-xf-pipe framing](https://github.com/USAREUR-AF/goat-transformers/blob/main/docs/adapters.md#framing)); default `whole` (one datagram) on UDP, required on TCP |
| `XF_MULTICAST_GROUP`, `XF_MULTICAST_IFACE` | join an IPv4 multicast group on the listener port, on the interface with that local address |
| `XF_INPUT` | a goat-xf-pipe input endpoint that replaces the listener, such as `tcp://192.0.2.10:4000` to connect to a sensor that serves a stream |
| `XF_TRACK_GENERATION` | default `1` |
| `XF_ON_ERROR` | `skip` (default) or `stop` |

Listeners: `xf-udp` (UDP, container port 40540) and `xf-tcp` (TCP, container port 40541, accepts up to 64 connections).

```sh
billie kid install <bundle>.tar.gz --checksum <bundle>.tar.gz.sha256
billie kid configure xf-ingest --transport udp --bind-address <node-IP> --port <host-port> --source-cidr <sensor-CIDR> --listener xf-udp
billie cat062 source set xf-ingest <XF_SOURCE_ID> --sac <sac> --sic <sic>
billie kid activate xf-ingest --config <env-file>
```

**Multicast.** The kid joins the group, but Billie runs a kid in a container on Podman's bridge network with one published port, and multicast does not cross that bridge. A multicast feed reaches the kid only when the node relays it to the published port (or when Billie gains host networking for kids); the setting is in place for that.

## Failures and logging

`goat-xf-pipe` counts every message that does not convert or is not delivered, under its error name (`no-kind`, `malformed-wire`, `translator-io`, `translator-<code>`, ...). The first 10 failures of each name are printed with the message number and the full error; later ones are counted. A status line is printed every 10 seconds: `in=… converted=… failed=… [name=count]`. A translator refusal of one output does not stop the other outputs.

## Local checks

```sh
cargo fmt -- --check
cargo test --locked
python3 ../../tools/sync_goat_transformers_packs.py --target xf-ingest --check
```

`tests/conformance.rs` loads the shipped packs and runs every vector in `tests/vectors`: input messages taken from goat-transformers' own vectors (each file names its source), the kid's context, and the Canonical Track v2 record expected, or the error expected. `tests/runtime.rs` starts the built binary, sends a CoT datagram and a datagram that is not CoT, and reads the three translation requests from a socket stub.

## Origin and licence

Apache-2.0. The engine, the adapters and the files under `goat-transformers/` come from goat-transformers commit `d57d36118edf296d1f610893025631f97d955ded` (release `xf-pipe-v0.1.1`), Apache-2.0; see `licenses/NOTICE`. The translator client in `src/translator.rs` follows `kids/examples/weather-station-bite`.
