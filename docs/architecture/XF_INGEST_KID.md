# xf-ingest: one kid for standard-format feeds

Status: Proposed (decision record draft). The kid is built and tested in this repository (`kids/xf-ingest`); not deployed.

## Decision

A sensor whose output is already a standard format is connected with one generic kid, `kids/xf-ingest`, configured per sensor. No sensor gets its own script or its own kid. The kid receives the sensor's messages over UDP or TCP. goat-transformers converts each message from the format named by `XF_FROM_FORMAT` to Canonical Track v2, and the kid hands the track to the translator. The translator publishes it on the same outputs as every other kid: `tracks-cot`, `tracks-sapient`, `tracks-cat062`.

## Context

Open Billie has two ways to build a kid. A coded decoder, as in `kids/examples/oetf`, is written for each message set. A first-bite dictionary, as in `kids/examples/weather-station-bite`, covers a fixed-layout binary message set described as data. Neither fits a sensor that already sends Cursor-on-Target, TAK protobuf, GeoJSON or Canonical Track v2. Those formats have public specifications, and goat-transformers already holds a pack for each. Without a generic kid, each such sensor ends up behind a one-off conversion script on the node. Such a script sits outside Billie's install, upgrade, rollback, firewall and logging, and outside any repository.

## Why a kid and not a script

| Need | Kid | Script on the node |
|---|---|---|
| Install, upgrade and rollback with a checksummed bundle | `billie kid install / upgrade / rollback` | by hand |
| Listener and firewall rule scoped to the sensor | `billie kid configure --source-cidr` | by hand |
| Runs as a service, restarts, logs in one place | systemd unit made by `billie kid activate` | by hand |
| Same outputs, CAT062 SAC/SIC per `sourceId`, same fabric keys as other kids | the translator | re-implemented or skipped |
| Tested and reviewed code | this repository's CI | none |

## What the kid is

The kid reuses the `goat-xf-pipe` command line of goat-transformers (`goat-adapters-std`). That command line already holds the UDP, multicast and TCP transports, the framers, failure counting and the status line. The kid adds one output scheme, `billie:`, which sends each converted track to the translator socket once per declared output. The kid holds no code for any format. Its settings (`XF_*` in the env file given to `billie kid activate --config`) become the command line. The pack and model files are copied from the goat-transformers commit the engine is built from, with `tools/sync_goat_transformers_packs.py --target xf-ingest`. The translator's own copy uses the same tool.

## Cross-repository check

| Existing piece | Relation |
|---|---|
| goat-transformers `adapters/` (`goat-xf-pipe`, `goat-xf-pipe-zenoh`) | Reused as a library, unchanged. `goat-xf-pipe-zenoh` could put converted messages on the fabric directly. That would bypass the translator, so the outputs, CAT062 SAC/SIC assignment, kid identity and fabric keys would differ from every other Billie kid. |
| goat-transformers packs | The format knowledge. A format is added to the kid by adding its pack to the copied set when it converts to Canonical Track v2. |
| translator goat-transformers encoder option (`GOAT_TRANSFORMERS_ENCODER_OPTION.md`) | The output side uses the same library and pack set. The kid does the input side. |
| `kids/examples/weather-station-bite` and kids built like it in other repositories, such as a first-bite dictionary kid for a fixed-layout ICD | Those cover fixed-layout message sets that have no pack. xf-ingest covers formats that have one. Both use the same translator request. |

No new repository and no new platform component: the kid is a package under `kids/`, like the examples.

## Consequences

- One image serves every standard-format sensor. Per sensor, an operator writes a two-line env file (`XF_FROM_FORMAT`, `XF_SOURCE_ID`) and sets a SAC/SIC.
- The input formats in this version are `cot-xml`, `cot-protobuf`, `geojson` and `canonical-track-v2`. ASTERIX CAT062, CAT021 and SAPIENT are not included yet: goat-transformers decodes them, but does not derive the track identity (`uid`) when decoding, so the conversion is refused. When goat-transformers derives it, they are added by moving the pin and the copied set.
- A CoT type that has no Billie class is removed from `classification` before the track is sent; the translator refuses values outside the vocabulary. The proper fix is in the goat-transformers `canonical-track-v2` pack.
- The kid can join a multicast group, but a multicast feed does not reach a kid container on Podman's bridge network. Host networking for kids, or a relay on the node, is a separate platform decision.
- CAT062 still needs a numeric `trackId` (0-4095) and a `confirmed` state; a CoT feed provides neither, so its tracks reach CoT and SAPIENT only.
