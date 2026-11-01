"""Every vector in shared/conformance/vectors must decode and map (to every target) exactly as the TS reference did."""

import json
from pathlib import Path

import pytest

from billie_oetf import FrameHeader, Mapper, OetfDecoder, Track, build_track_report, crc16

VECTORS = sorted((Path(__file__).resolve().parents[2] / "shared" / "conformance" / "vectors").glob("*.json"))
MAPPER = Mapper()


def same(a, b, path="$"):
    """Exact structural equality; ints and floats compare numerically (JS has one number type)."""
    if isinstance(a, dict) and isinstance(b, dict):
        assert a.keys() == b.keys(), f"{path}: keys {sorted(a.keys() ^ b.keys())}"
        for k in a:
            same(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            same(x, y, f"{path}[{i}]")
    else:
        numeric = (type(a) in (int, float), type(b) in (int, float))
        assert a == b and numeric[0] == numeric[1], f"{path}: {a!r} != {b!r}"


@pytest.mark.parametrize("path", VECTORS, ids=lambda p: p.stem)
def test_vector(path):
    v = json.loads(path.read_text("utf-8"))
    dec = OetfDecoder()
    records = [r for chunk in v["chunks"] for r in dec.feed(bytes.fromhex(chunk))]

    assert [e.reason for e in dec.get_recent_errors()] == v["errors"]
    assert len(records) == len(v["records"])
    for got, want in zip(records, v["records"]):
        assert got.message_name == want["messageName"]
        assert got.meta["msgId"] == want["msgId"]
        same(got.fields, want["fields"])
        for target, expected in want["translations"].items():
            if expected is None:
                assert not MAPPER.has_mapping("oetf", got.message_name, target), target
            else:
                out = [t["fields"] for t in MAPPER.translate("oetf", got, target)]
                same(out, expected, f"{path.stem}.{target}")


def test_vectors_present():
    assert len(VECTORS) >= 5


def test_crc_check_value():
    assert crc16(b"123456789") == 0x29B1


def test_builder_is_byte_identical_to_ts():
    base = dict(
        classification=3, confidence_pct=87, lat_deg=38.8977, lon_deg=-77.0365, alt_m=152.4,
        vel_east_ms=-12.5, vel_north_ms=4.25, vel_up_ms=1.5, pos_sigma_east_m=3.2, pos_sigma_north_m=2.8,
        alt_sigma_m=6.1, vel_sigma_east_ms=0.9, vel_sigma_north_ms=0.7, rcs_dbsm=-18.3, age_s=74,
    )
    frame = build_track_report(FrameHeader(42, 0x0107), 1_761_739_200_123_456, [
        Track(id=311, confirmed=True, mode3a="7000", **base),
        Track(id=312, coasting=True, final_update=True, simulated=True, **{**base, "classification": 5}),
    ])
    want = json.loads((VECTORS[0].parent / "track_report_two_tracks.json").read_text("utf-8"))["chunks"][0]
    assert frame.hex() == want
