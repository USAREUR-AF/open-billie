# Weather-station kid decoded by a bite dictionary

This synthetic example kid has no decoder code for its message set. Its decoder is the [`bite`](https://github.com/USAREUR-AF/first-bite/tree/main/bite) library from first-bite, which reads a dictionary: a directory of JSON files that gives the bit range, type, scale and value labels of every field. The dictionary, the mapping to Canonical Track v2 and the list of outputs are data files in this package. A kid for another fixed-layout message set is made by replacing those files; the Rust source does not change.

The same dictionary directory is what a first-bite tap loads to decode captured traffic, so one field table serves both.

## What runs

```text
UDP datagram on the declared listener
  -> bite decodes it against schemas/weather-station/        (src/decoder.rs)
  -> mappings/WX_Position/canonical-track-v2.json binds the
     decoded fields to Canonical Track v2                    (src/mapper.rs)
  -> one translation request per declared output on the
     translator socket                                       (src/bin/billie-bite-kid.rs)
```

The dictionary is first-bite's `weather-station` example: a fictional station that sends `Heartbeat`, `Observation` and `Position` messages over UDP on port 40100. Only `Position` carries a latitude and longitude, so only `Position` has a map and produces a track. The other two messages are decoded and produce nothing. The package declares two outputs, `tracks-cot` and `tracks-sapient`. It does not declare CAT062, because that encoder needs a numeric track number and the station identifier is text.

| Path | Holds |
|---|---|
| `schemas/weather-station/` | the dictionary, copied unchanged from first-bite; format in first-bite's [`docs/dictionary-format.md`](https://github.com/USAREUR-AF/first-bite/blob/main/docs/dictionary-format.md) |
| `schemas/weather-station.records.schema.json` | JSON Schema of the decoded records, as `bite schema schemas/weather-station` prints it |
| `mappings/WX_Position/canonical-track-v2.json` | the map from a decoded `Position` to Canonical Track v2 |
| `lookups/` | lookup tables for mappings: one, giving the Billie track class of a `Position` report |
| `tests/vectors/` | datagrams and the decoded record and track expected from each |
| `src/` | the runtime: listener, `bite` call, map executor, translator request. No field layout |
| `Containerfile` | builds the runtime and copies the data files to `/app`; its `ENV` lines name the kid, the dictionary and the outputs |
| `licenses/` | the Open Billie licence, the first-bite licence and notice, this kid's notice, and the licences of the crates its decoder is built from (`THIRD_PARTY_CRATES.txt`, written by `tools/crate_notices.py`) |

At start-up the runtime refuses a dictionary that `bite` reports errors in, runs the vectors the dictionary carries, and refuses to start if one fails. A datagram that cannot be decoded, or a record whose map leaves a required canonical field empty, is logged by size or field name and dropped; the process keeps running.

## The mapping file

A map names one dictionary message and lists bindings. Each binding writes one canonical field from a literal `value` or `from` a source, optionally through `via` conversions:

```json
{ "from": "latitude", "to": "position.latitudeDeg" },
{ "from": "$receivedAt", "to": "observedAt" },
{ "value": true, "to": "testData" },
{ "from": "confidence_pct", "to": "confidence",
  "via": [{ "conversion": "scale", "params": { "factor": 0.01 } }] }
```

| `from` | Value |
|---|---|
| a field name of the message | the decoded value: the dictionary's label where the raw value has one, the typed value otherwise |
| `$receivedAt` | when the datagram arrived, RFC 3339 UTC with milliseconds |
| `$interface` | the dictionary interface name (`WX`) |
| `$message` | the message name |

| Conversion | Does |
|---|---|
| `scale` | multiplies a number by its parameter |
| `offset` | adds its parameter to a number |
| `lookup` | replaces the value by its entry in `lookups/<table>.json`; no entry leaves the field out |
| `toBoolean` | `0`, `1`, `false`, `true` to a JSON boolean; anything else leaves the field out |
| `toString` | a number or boolean to text |

The dictionary already applies each field's `scale` and `offset`, so a map converts only between the dictionary's unit and the canonical unit. A binding whose source is absent (a field beyond the end of a short datagram, a NaN) writes nothing. A record is sent only when `apiVersion`, `kind`, `trackId`, `sourceId`, `trackGeneration`, `observedAt`, `testData`, `headerSimulated`, `simulated`, `position.latitudeDeg` and `position.longitudeDeg` all have a value. The shape is the mapping-contract shape the OETF example uses; `repeats`, `availableIf` and multi-field bindings are not implemented.

The weather-station map takes `classification` from `lookups/WX_message_classification.json`, keyed by message name, because the message set has no classification field. It sets `testData` to `true` for every record because the message set is synthetic and has no status flags. A map for a real message set binds these three flags to the fields that state them.

## Make a kid from another dictionary

1. Copy this directory into its own repository and remove `schemas/weather-station*`.
2. Put the dictionary under `schemas/<name>/`. Check it with first-bite's command, `bite check schemas/<name>`, which also runs the dictionary's vectors.
3. Write `schemas/<name>.records.schema.json` with `bite schema schemas/<name>`, then list every field for review:

   ```sh
   billie mapper generate --schema schemas/<name>.records.schema.json --format bite-schema \
     --source-protocol <kid-id> --target billie-canonical \
     --output mappings/mapper-plan.json --mappings-dir mappings/generated
   ```

4. Write one map under `mappings/` for each message that carries a position, deciding every field: bound, or listed under `unmapped` with a reason. Put the tables the maps use under `lookups/`. `billie kid build` refuses a package whose `schemas/`, `mappings/`, `lookups/` or `tests/vectors/` holds no JSON file.
5. In `billie-kid.yaml` set the id, the listener port and the outputs. In `Containerfile` set `BITE_KID_ID`, `BITE_KID_DICTIONARY`, `BITE_KID_OUTPUTS`, `BILLIE_INPUT_PORT` and the `COPY` of the dictionary to match. Set `BITE_KID_INTERFACE` when the dictionary has more than one interface.
6. Replace `tests/vectors/` with synthetic datagrams for the new message set and update the names and counts in `tests/`.

## Limits

- **Fixed-layout messages only.** A dictionary gives every field a fixed bit range. Messages with repeated groups, optional sections or variable-length fields need a coded decoder, as in the OETF example.
- **Tracks only where the message set carries a position.** Canonical Track v2 requires latitude and longitude. A message without them can be decoded and has nothing to send to the translator.
- **One datagram is one message, over UDP.** The runtime does not frame a TCP byte stream and does not check a checksum; a dictionary describes neither.
- **One interface per kid**, and one message per datagram identified by a field of the payload.
- **Time comes from the message only if the dictionary can express it.** A dictionary decodes a timestamp field to a number; this map engine has no conversion from a numeric epoch to RFC 3339, so the weather-station map uses the arrival time.

## Local checks

From this directory, with Rust 1.85 or later (`bite` declares `rust-version = "1.85"`; the `Containerfile` pins `rust:1.85.1-slim-bookworm`):

```sh
cargo fmt -- --check
cargo test --locked
```

From the repository root:

```sh
python -m unittest tools/test_weather_station_bite_kid.py
bash deploy/bin/billie kid validate kids/examples/weather-station-bite
bash deploy/bin/billie kid build kids/examples/weather-station-bite --platform linux/amd64 --decoder-language rust
```

`tests/runtime.rs` starts the built binary, sends UDP datagrams and reads the translation requests from a socket stub. Send the Position vector to a running kid with:

```sh
python3 -c "import socket,sys; socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(bytes.fromhex('03001b4b5837004050359e83e425afc06276ecbfb15b5743088000'), (sys.argv[1], int(sys.argv[2])))" <node-address> 40100
```

## Origin and licence

The dictionary and the `bite` library come from [first-bite](https://github.com/USAREUR-AF/first-bite) (Apache-2.0) at commit `b7bc25898a28bc449dd11bb1876a9645bde43cb3`. `Cargo.toml` pins the library to that commit with `default-features = false`, which leaves out its command line. See the [import record](../../../docs/provenance/WEATHER_STATION_DICTIONARY_IMPORT.md). Everything else here was written for Open Billie under Apache-2.0.
