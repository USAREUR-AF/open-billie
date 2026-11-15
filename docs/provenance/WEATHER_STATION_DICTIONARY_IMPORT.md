# Weather-station dictionary import record

## Source and disposition

- Source repository: <https://github.com/USAREUR-AF/first-bite>, public.
- Source revision: `b7bc25898a28bc449dd11bb1876a9645bde43cb3`.
- Source path: `dictionaries/weather-station/`.
- Source declaration: the dictionary's own `dictionary.json` describes it as a synthetic example of a weather station that reports over UDP. It is not transcribed from an interface document and contains no sensor data.
- License: Apache-2.0. first-bite's `LICENSE` and `NOTICE` are kept as `kids/examples/weather-station-bite/licenses/FIRST-BITE-LICENSE` and `FIRST-BITE-NOTICE`; the kid's `licenses/NOTICE` names the copied files and the revision.
- Destination: `kids/examples/weather-station-bite/schemas/weather-station/`, a synthetic example kid excluded from the core platform release allowlist.

## Imported components

- `dictionary.json`, `WX/metadata.json`, `WX/messages/{Heartbeat,Observation,Position}.json`: the field tables.
- `vectors/*.json`: five decode vectors that belong to the dictionary.

The files are byte-for-byte copies. `schemas/weather-station.records.schema.json` is generated from them with first-bite's `bite schema` at the same revision.

## Linked code

The kid runtime depends on first-bite's `bite` crate as a Cargo git dependency pinned to the same revision, with `default-features = false`. No first-bite source is copied into this repository. `kids/examples/weather-station-bite/Cargo.lock` records the revision and the crates it brings: `hex`, `serde`, `serde_json`, `thiserror` and their dependencies.

## Verification

`cargo test --locked` in the kid directory runs the dictionary's vectors through the linked library and compares the checked-in record schema with what the library produces from the dictionary.
