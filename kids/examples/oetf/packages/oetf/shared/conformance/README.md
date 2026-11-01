# OETF conformance vectors

These golden cases define what "an OETF implementation" means, for decoding and for every mapping target (ASTERIX CAT-062, CoT and SAPIENT). The TypeScript, Python and Rust packages all run them in their own test suites, and all three must reproduce every vector **exactly**. Strings, integers and floats are compared value for value, with no tolerance.

| Vector | Exercises |
|---|---|
| `track_report_two_tracks` | Mode 3/A present and absent (`availableIf`), CNF polarity flip, TSE/SIM flags, CoT course/speed, SAPIENT proto timestamp |
| `track_report_eight_tracks` | A full frame: every classification, near-zero lat/lon (`3e-7`), negative altitude, saturated age, the `I062/070` day rollover |
| `track_report_empty` | `Track count` 0 → zero records for every target |
| `sensor_status` | A message with no maps (every translation is `null`) |
| `stream_recovery` | Garbage, a CRC-corrupt frame, an unknown type and a bad version, fed in 7-byte chunks, then a good frame |

## Shape

```jsonc
{
  "name": "…", "description": "…",
  "chunks": ["4f455446…", …],        // feed these to one decoder instance, in order
  "errors": ["sync-lost", …],         // framing error reasons, in order
  "records": [{
    "messageName": "Track Report",
    "msgId": 16,
    "fields": { … },                  // decoder output, presentation strings included
    "translations": {                 // translator output per repeat, or null if no map
      "asterix-cat062": [ { "I062/040": … } ],
      "cot":            [ { "uid": "311", "type": "a-u-A-M-F-Q", … } ],
      "sapient":        [ { "timestamp": { "seconds": …, "nanos": … }, … } ]
    }
  }]
}
```

## Where the answers come from

`pnpm gen:vectors` (`tools/gen-vectors.ts`) generates the vectors in two steps:

1. It builds frames with the TypeScript builder and decodes them with the TypeScript decoder.
2. It translates the decoded records to every target with the OETF reference mapping engine used when these vectors were generated.

The original vector generator used an external translator checkout and is not included in this standalone example. Treat these checked-in vectors as the reviewed baseline; regenerate them only after the Open Billie translator integration can reproduce them.

## Parity details the ports had to get right

- **Number → string:** presentation strings such as `"152.4 m"` and lookup keys follow JavaScript's `Number#toString`. That means `80`, not `80.0`, and `3e-7`, not `3e-07` or `0.0000003`.
- **Rounding:** `Math.round` rounds half toward +∞, so it's `floor(x + 0.5)`. That isn't Python's `round` (banker's rounding) or Rust's `round` (half away from zero).
- **Modulo:** JavaScript's `%` on floats is `fmod`, which keeps the sign of the dividend. That isn't Python's `%`.
- **Time:** JavaScript's `Date` truncates to whole milliseconds, so the CoT `time` is `…00.123Z` even though the source is `…00.123456`. SAPIENT keeps the full µs as `nanos`.
- **JSON float parsing:** Rust's `serde_json` needs its `float_roundtrip` feature. Without it, `1e-07` can parse one ULP off.
