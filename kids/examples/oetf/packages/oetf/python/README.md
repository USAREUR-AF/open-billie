# billie-oetf (Python)

This is the Python implementation of the OETF decoder, frame builder, and sensor-to-canonical mapper. Its runtime accepts UDP datagrams or TCP streams and sends versioned canonical requests to the shared Billie Rust translator over a local Unix socket. It does not connect to Zenoh or carry fabric credentials; the Open Billie platform owns local output routing and fabric mTLS. It passes the shared conformance suite, so decoder and mapper output is interchangeable with TypeScript and Rust packages.

## Usage

```python
from billie_oetf import Mapper, OetfDecoder

decoder, mapper = OetfDecoder(), Mapper()
for rec in decoder.feed(datagram):
    for target in ("asterix-cat062", "cot", "sapient"):
        for out in mapper.translate("oetf", rec, target):
            print(target, out["fields"])   # one record per track
errors = decoder.get_recent_errors()
```

```sh
python -m billie_oetf 4f455446011046...             # hex in, one JSON line per record, every target
python -m billie_oetf --to cot 4f455446011046...    # or one target
```

To generate traffic, use `build_track_report(FrameHeader(seq, sensor_id), timestamp_us, [Track(...)])`. Its frames are byte-identical to the TypeScript builder's.

## Shared artifacts

The package reads the **same** `schemas/`, `mappings/` and `lookups/` JSON as the TypeScript and Rust packages, straight from [`packages/oetf/shared`](../shared/). It doesn't keep a copy of its own. Set `OETF_SHARED_DIR` to a `shared` directory when the package is installed outside the repo.

`Mapper` executes the subset of the Open Billie translator mapping contract used by OETF. That covers `repeats`, `availableIf`, piped `from`, brace `to`, literal `value`, the parametric conversions `scale`, `offset`, `scaleOffset` and `lookup`, and the named conversions `epochMicrosToCat062TimeOfDay`, `epochMicrosToIso8601`, `epochMicrosToProtoTimestamp`, `uintToString`, `numberToString`, `negate`, `speedMsFromVxy` and `headingDegFromVxy`. An unsupported conversion raises an error when the map loads, rather than passing data through silently.

## Tests

```sh
pip install -e .[test]   # or just: python -m pytest  (pythonpath is configured)
python -m pytest -q
```
