# @open-billie/mappings-oetf

This local package points at and executes the OETF maps for **ASTERIX CAT-062, CoT and SAPIENT**. The maps are language-neutral JSON in [`packages/oetf/shared/mappings`](../../shared/mappings/), and the Python, Rust, and TypeScript implementations consume the same files. It exports their paths, the OETF-to-canonical mapper used by the TypeScript runtime, and a field coverage test.

## Usage

```ts
import { MAPPINGS_PATH, LOOKUPS_PATH } from '@open-billie/mappings-oetf';

const translatorConfig = { mappingsDir: MAPPINGS_PATH, extraLookupDirs: [LOOKUPS_PATH] };
// Supply translatorConfig to the compatible Open Billie translator engine.
```

`LOOKUPS_PATH` must be passed to a translator engine, because each target looks up the OETF classification in its own table: `OETF_classification_callsign`, `_cot` and `_sapient`. Deployment fields come from encoder configuration, not the maps: CAT-062 SAC/SIC, CoT `how`/`stale`, and SAPIENT `node_id` plus the location `coordinate_system` and `datum`. The TypeScript runtime uses `mapOetfRecord` to execute the shared OETF-to-canonical map before it sends tracks to the Rust translator.

All three maps use `repeats` on `Track count`, which yields one output record per track. Each map's `unmapped` ledger lists every source field it deliberately leaves out, with the reason. Sensor Status (msg_1) has no maps.

## Track Report → ASTERIX CAT-062 (`asterix-cat062.json`)

| OETF field | CAT-062 | Conversion |
|---|---|---|
| Timestamp (µs epoch) | I062/070 Time Of Track Information | `epochMicrosToCat062TimeOfDay` |
| Track {n} ID | I062/040 Track Number | as-is |
| Latitude / Longitude (deg) | I062/105 | × 2^25/180 |
| Altitude (m HAE) | I062/130 Altitude | ÷ 1.905 (6.25 ft) |
| Velocity east / north (m/s) | I062/185 Vx / Vy | × 4 |
| Velocity up (m/s) | I062/220 Rate | × 31.496 (6.25 ft/min) |
| Mode 3/A code | I062/060 Mode 3/A code | as-is, only when `Flags.Mode 3/A valid` = 1 |
| Classification | I062/245 Target Identification | `lookup:OETF_classification_callsign` |
| Flags.Confirmed / Simulated / Final update | I062/080 CNF / SIM / TSE | CNF = `1 − x` (CAT-062 CNF 0 = confirmed) |
| Position sigma east / north | I062/500 APC X / Y | × 2 (0.5 m) |
| Altitude sigma | I062/500 AGA | ÷ 1.905 |
| Velocity sigma east / north | I062/500 ATV Vx / Vy | × 4 |

## Track Report → CoT (`cot.json`)

| OETF field | CoT | Conversion |
|---|---|---|
| Timestamp | `time` | `epochMicrosToIso8601` (ms precision) |
| Track {n} ID | `uid`, `detail.uid.tadilj` | `uintToString` |
| Classification | `type` | `lookup:OETF_classification_cot`, e.g. `a-u-A-M-F-Q` for Small UAS |
| Latitude / Longitude / Altitude | `lat` / `lon` / `hae` | as-is (OETF altitude is already HAE) |
| Velocity east + north | `detail.track.speed` | `speedMsFromVxy` |
| Velocity east + north | `detail.track.course` | `headingDegFromVxy`. OETF is ENU, so no NWU swap is needed. |
| Position sigma east + north | `ce` | `speedMsFromVxy` (√(σE² + σN²)) |
| Altitude sigma | `le` | as-is |
| Velocity sigma east + north | `detail.track.eSpeed` | `speedMsFromVxy` |

## Track Report → SAPIENT (`sapient.json`)

| OETF field | SAPIENT | Conversion |
|---|---|---|
| Timestamp | `timestamp` | `epochMicrosToProtoTimestamp` (seconds + nanos, full µs) |
| Track {n} ID | `detection_report.id` | `uintToString` |
| Classification | `detection_report.classification.type` | `lookup:OETF_classification_sapient` |
| Confidence (%) | `detection_report.detection_confidence` | × 0.01 (0..1) |
| Latitude / Longitude / Altitude | `detection_report.location.y` / `.x` / `.z` | as-is |
| Altitude sigma | `detection_report.location.z_error` | as-is (m) |
| Velocity east / north / up | `detection_report.enu_velocity.east_rate` / `north_rate` / `up_rate` | as-is (already ENU) |
| Velocity sigma east / north | `…enu_velocity.east_rate_error` / `north_rate_error` | as-is |
| RCS | Canonical `identifiers` entry `{scheme: "sapient-object-info", value}`; Rust translator emits `detection_report.object_info` `{type: "rcs_dbsm", value}` | `toCanonicalIdentifier` then shared encoder conversion |

Position sigma east/north are **intentionally not** mapped to `location.x_error`/`y_error`. Under `LAT_LNG_DEG_M`, those fields are in degrees, and converting metres to degrees needs a latitude-aware conversion that the translator doesn't have. (The RPS-42 maps currently put metres there.)

## Tests

`tests/coverage.test.ts` decodes a real frame and checks every map file against it:

- Every `from` / `availableIf` / `unmapped` name resolves.
- Every decoded field is either mapped, ledgered or the `repeats` driver.
- Every referenced lookup table exists.
- `source.message` matches the decoder's `messageName`.

Output values are pinned by `shared/conformance`.
