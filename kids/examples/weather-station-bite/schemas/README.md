# Schemas

`weather-station/` is the dictionary the decoder reads. It is first-bite's `dictionaries/weather-station/`, copied unchanged from commit `b7bc25898a28bc449dd11bb1876a9645bde43cb3` of <https://github.com/USAREUR-AF/first-bite> (Apache-2.0; licence and notice in `../licenses/`). The format is described in first-bite's `docs/dictionary-format.md`. Its `vectors/` directory holds the dictionary's own decode vectors.

`weather-station.records.schema.json` is the JSON Schema (draft 2020-12) of the decoded records, keyed `interface/message`. It is the output of `bite schema weather-station` at the same commit, and `tests/conformance.rs` fails when it differs from what the dictionary produces. `billie mapper generate --format bite-schema` reads it.
