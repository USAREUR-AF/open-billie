# goat-transformers encoder option

Status: Built, off by default, not deployed. The numbers below are measured by `runtime/rust/translator/tests/goat_transformers_compare.rs`.

The translator can write an output format with the [goat-transformers](https://github.com/USAREUR-AF/goat-transformers) library instead of its native encoder. goat-transformers converts between message formats from data files called packs: one pack states how one format maps to a shared model. An operator selects the encoder for each output format separately and can switch back. A translator built without the cargo feature `goat-transformers` contains none of this code, and its output does not change.

## What the option does

For a format set to `goat-transformers`, the translator writes the validated record back out as Canonical Track v2 JSON and asks the library to convert it from the pack `canonical-track-v2` to `cot-xml`, `asterix-cat062` or `sapient`. Request parsing, kid authentication, output authorization and publishing are the same on both paths.

A record does not carry every value an output needs. The translator computes the values the node owns with the code the native encoders use and gives them to the library as conversion context:

| Format | Value | Context key | Computed by |
|---|---|---|---|
| CoT | scoped identity (kid, `sourceId`, `trackId`, `trackGeneration`) | `track.scoped_id` | `CanonicalTrack::scoped_identity` |
| CoT | stale time | `stale_ms` | `CotEncoder::event_times` |
| CoT | `how` | `how` | `CotOptions` |
| CAT062 | SAC and SIC | `cat062.sac`, `cat062.sic` | `Cat062Encoder::source_identifier` |
| SAPIENT | node UUID | `sapient.node_id` | `SapientEncoder::node_id` |
| SAPIENT | message timestamp (the node stamps the message with the observation time) | `sapient.timestamp_seconds`, `sapient.timestamp_nanos` | `SapientEncoder::message_time` |
| SAPIENT | report ULID, object ULID, scoped identity | `sapient.detection_report_report_id`, `sapient.detection_report_object_id`, `sapient.detection_report_id` | `SapientEncoder::identifiers` |

The object ULID comes from the same store on both paths (`BILLIE_SAPIENT_OBJECT_ID_STORE`), so a track keeps its `object_id` when the encoder is switched. A node configuration error (no SAC/SIC assignment, no node UUID, a stale duration that is not positive) is reported with the native error code. A conversion the library refuses is rejected with the code `library_conversion_failed`.

## How to switch

Build the translator with the feature:

```sh
cargo build --locked --release --features goat-transformers --manifest-path runtime/rust/translator/Cargo.toml
```

`tools/build-platform-release.sh` builds without the feature, so a platform package does not contain the library path.

Select the encoder of each format in the translator service environment. Each variable takes `native` (the default) or `goat-transformers`:

| Variable | Output format |
|---|---|
| `BILLIE_COT_ENCODER` | `cot` |
| `BILLIE_CAT062_ENCODER` | `asterix-cat062` |
| `BILLIE_SAPIENT_ENCODER` | `sapient` |

To switch one format on a node, add a systemd drop-in for the translator unit with, for example, `Environment=BILLIE_CAT062_ENCODER=goat-transformers`, then restart the unit. To switch back, remove the line or set `native`, then restart. The translator reads the variables once at start. It exits with status 2 when a value is not one of the two names, when `goat-transformers` is selected in a build without the feature, or when an embedded definition does not load.

## What is identical and what differs

The comparison test encodes 33 inputs through both encoders for each format: the schema examples, the example request of the runtime contract, the tracks of the translator's unit tests, and the ten tracks the OETF example produces from its conformance vectors. It parses both outputs and compares them field by field. Two numbers no more than two units in the last place apart count as equal: the native encoders compute the CoT `ce` and `speed` with the platform `hypot`, the library computes `sqrt(a*a + b*b)`, and on Linux the two differ in the last digit on 3 of the 594 CoT fields (`ce` on 2 inputs, `speed` on 1). Those inputs are not among the 17 byte-identical ones.

| Format | Encoded by both | Refused by both | One path refuses | Byte-identical | Fields equal |
|---|---|---|---|---|---|
| ASTERIX CAT062 | 25 | 7 | 1 | 25 of 25 | 397 of 397 |
| CoT | 33 | 0 | 0 | 28 of 33 | 588 of 594 |
| SAPIENT | 33 | 0 | 0 | 0 of 33 | 685 of 719 |

A SAPIENT report ULID is new for every message on both paths, so two SAPIENT messages are never the same octets. On 2 of the 33 inputs every SAPIENT field is equal.

### ASTERIX CAT062

Every block both encoders write is the same, octet for octet. Both refuse a record without `confirmed` (5 inputs) and a `trackId` that is not a decimal number (2 inputs). Both set the I062/080 MRH bit when they write I062/130, the geometric altitude, which is then the more reliable height (goat-transformers spec 0.12, #105). SRC comes from the context key `cat062.src`, 0 when absent; the translator does not pass it, so both paths write 0.

| Difference | Inputs | Cause |
|---|---|---|
| The library encodes a record the native encoder refuses | 1 | The native encoder refuses a longitude of 180 degrees, a track number above 4095 and an altitude outside -1500 to 150000 ft. The pack writes any value the field holds; a longitude of 180 is written as 2^25. |

### CoT

| Field | Inputs | Difference | Cause |
|---|---|---|---|
| `event/@time`, `@start`, `@stale` | 2 | same instant, different text | The native encoder omits a zero fraction of a second (`2026-01-01T00:00:00Z`); the library always writes milliseconds (`2026-01-01T00:00:00.000Z`). |

The `uid` (the scoped identity), type, position, altitude, circular and linear error, the unknown-value sentinels, `how`, the stale instant, course and speed are equal on all 33 inputs. `opex="s"`, the status remarks and the `detail` element are equal too: goat-transformers derives them from the track flags and writes `<detail>` always (track 0.2.0 and cot-xml 0.6.0, goat-transformers#166, spec 0.18). The 28 inputs that have none of the differences in the table are the same octets on both paths. The pack reads `9999999` in `hae`, `ce` and `le` as no value when it decodes CoT; it still writes `9999999` when it encodes a record without the value.

A receiver sees the same track identity, `opex` and status remarks on both paths. The time text differs only at a whole second: the library writes `.000Z`, which chrono's `AutoSi` leaves out. goat-transformers' `iso8601_short` would drop it but writes `.25Z` where `AutoSi` writes `.250Z`, so the pack keeps milliseconds.

### SAPIENT

| Field | Inputs | Difference | Cause |
|---|---|---|---|
| `timestamp.nanos` | 2 | written by the library only | At a whole second the native encoder omits `nanos`; the library writes the 0 it derives from the track time. `Timestamp.nanos` is a proto3 field without presence, so 0 and absent are the same value. |
| `object_info[].type`, `object_info[].value` | 16 | not written by the library | The pack does not map `sapient-object-info` identifiers to `object_info`. |

The message timestamp (seconds, and nanos off a whole second), the x and y error, node UUID, report and object identifiers, the scoped identity in `id`, location, vertical error, coordinate system and datum, detection confidence, classification type and its confidence, `state` and ENU velocity are equal on all 33 inputs. The test counts two valid report ULIDs as equal.

A SAPIENT message from the library path has no `object_info`.

### The recorded baseline

`runtime/rust/translator/tests/fixtures/goat-transformers-baseline.json` holds the counts above and one row per differing field with its cause. The test fails when a difference appears, disappears or changes its input count. After a deliberate change, run the test with `BILLIE_COMPARE_UPDATE=1`, write the cause of each new row, and update this page.

## How the library and its packs are pinned

The crate is a git dependency pinned by `rev` in `runtime/rust/translator/Cargo.toml`, and `Cargo.lock` records the same commit. The library uses the Rust standard library only and adds no other crate. Cargo fetches the goat-transformers repository when it resolves the workspace, in a build without the feature too.

The translator stays one binary with no file to read at run time: the four model modules and four packs it uses are copied into `runtime/rust/translator/goat-transformers/` and embedded with `include_str!`. `COMMIT` in that directory names the commit they were copied from, and `SHA256SUMS` lists their digests.

| Check | Command | Needs |
|---|---|---|
| `rev`, `Cargo.lock` and `COMMIT` name one commit; the files match `SHA256SUMS`; no unlisted file is embedded | `python -m unittest discover --start-directory tools --pattern 'test_*.py'` | nothing |
| The copied files equal the files of the pinned commit | `python3 tools/sync_goat_transformers_packs.py --check` | the checkout Cargo makes of the pinned commit |

To move to a newer library commit: change `rev`, run `cargo update -p goat-transformers` in `runtime/rust`, run `python3 tools/sync_goat_transformers_packs.py`, then run the comparison test and update the baseline and this page.
