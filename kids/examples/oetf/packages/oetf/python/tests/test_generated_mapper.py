"""End-to-end compatibility checks for generated maps and the OETF mapper engine."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from billie_oetf import DecodedRecord, FrameHeader, Mapper, OetfDecoder, Track, build_track_report


def project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "deploy" / "bin" / "billie-mapper-generate.py").is_file():
            return parent
    raise RuntimeError("cannot locate the Open Billie repository root")


ROOT = project_root()
GENERATOR = Path(os.environ.get("BILLIE_MAPPER_GENERATOR", ROOT / "deploy" / "bin" / "billie-mapper-generate.py")).resolve()
SCHEMAS = ROOT / "kids/examples/oetf/packages/oetf/shared/schemas"
LOOKUPS = ROOT / "kids/examples/oetf/packages/oetf/shared/lookups"
PROTO_FIXTURE = Path(__file__).parent / "fixtures" / "mapper_codegen.proto"


def run_generator(
    schema: Path,
    output: Path,
    mappings: Path,
    protocol: str,
    input_format: str = "auto",
    enable_direct: bool = True,
) -> None:
    command = [
        sys.executable,
        str(GENERATOR),
        "--schema",
        str(schema),
        "--format",
        input_format,
        "--source-protocol",
        protocol,
        "--target",
        "cot",
        "--target-message",
        "CoTEvent",
        "--output",
        str(output),
        "--mappings-dir",
        str(mappings),
    ]
    if enable_direct:
        command.append("--enable-direct")
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )


def test_billie_json_generation_loads_and_translates(tmp_path: Path) -> None:
    plan_path = tmp_path / "mapper-plan.json"
    mappings_dir = tmp_path / "mappings"
    run_generator(SCHEMAS, plan_path, mappings_dir, "oetf", "billie-json")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["sourceProtocol"] == "oetf"
    assert [message["name"] for message in plan["messages"]] == ["Sensor Status", "Track Report"]
    track_map_path = next(mappings_dir.glob("msg_16_*_cot.json"))
    track_map = json.loads(track_map_path.read_text(encoding="utf-8"))
    assert track_map["source"]["messageId"] == 16
    assert track_map["source"]["message"] == "Track Report"
    assert any(binding["from"] == "Sensor ID" for binding in track_map["mappings"])

    mapper = Mapper(mappings_dir=mappings_dir, lookup_dirs=[LOOKUPS])
    frame = build_track_report(
        FrameHeader(42, 0x0107),
        1_761_739_200_123_456,
        [Track(
            id=311, classification=3, confidence_pct=87, lat_deg=0.0, lon_deg=0.0,
            alt_m=152.4, vel_east_ms=-12.5, vel_north_ms=4.25, vel_up_ms=1.5,
            pos_sigma_east_m=3.2, pos_sigma_north_m=2.8, alt_sigma_m=6.1,
            vel_sigma_east_ms=0.9, vel_sigma_north_ms=0.7, rcs_dbsm=-18.3, age_s=74,
        )],
    )
    record = OetfDecoder().feed(frame)[0]
    translated = mapper.translate("oetf", record, "cot")
    assert len(translated) == 1
    assert translated[0]["messageName"] == "CoTEvent"
    assert translated[0]["fields"]["Sensor ID"] == 0x0107
    assert translated[0]["fields"]["Track 0 ID"] == 311


def test_canonical_oetf_mapping_preserves_header_and_track_status_flags() -> None:
    shared = ROOT / "kids/examples/oetf/packages/oetf/shared"
    vectors = json.loads((shared / "conformance/vectors/track_report_two_tracks.json").read_text(encoding="utf-8"))
    frame = bytes.fromhex(vectors["chunks"][0])
    records = OetfDecoder().feed(frame)
    mapper = Mapper(mappings_dir=shared / "mappings", lookup_dirs=[LOOKUPS])
    first, second = mapper.translate("oetf", records[0], "billie-canonical")
    assert first["fields"]["confirmed"] is True
    assert first["fields"]["simulated"] is False
    assert second["fields"]["confirmed"] is False
    assert second["fields"]["coasting"] is True
    assert second["fields"]["finalUpdate"] is True
    assert second["fields"]["simulated"] is True
    assert second["fields"]["testData"] is False
    assert second["fields"]["headerSimulated"] is False


def test_unreviewed_generated_bindings_are_disabled(tmp_path: Path) -> None:
    plan_path = tmp_path / "unreviewed-plan.json"
    mappings_dir = tmp_path / "unreviewed-mappings"
    run_generator(SCHEMAS, plan_path, mappings_dir, "oetf", "billie-json", enable_direct=False)
    track_map = json.loads(next(mappings_dir.glob("msg_16_*_cot.json")).read_text(encoding="utf-8"))
    assert track_map["mappings"] == []
    assert len(track_map["unmapped"]) > 0

    mapper = Mapper(mappings_dir=mappings_dir, lookup_dirs=[LOOKUPS])
    record = DecodedRecord("Track Report", {"Timestamp": 123, "Track count": 0}, {})
    translated = mapper.translate("oetf", record, "cot")
    assert translated[0]["fields"] == {}


PROTO_AVAILABLE = shutil.which("protoc") is not None
try:
    import google.protobuf  # noqa: F401
except ImportError:
    PROTO_AVAILABLE = False


@pytest.mark.skipif(not PROTO_AVAILABLE, reason="protoc and python3-protobuf are optional")
def test_protobuf_generation_loads_and_translates(tmp_path: Path) -> None:
    plan_path = tmp_path / "proto-mapper-plan.json"
    mappings_dir = tmp_path / "proto-mappings"
    run_generator(PROTO_FIXTURE, plan_path, mappings_dir, "synthetic-proto", "protobuf")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    track_message = next(message for message in plan["messages"] if message["name"] == "synthetic.mapper.Track")
    enum_field = next(field for field in track_message["fields"] if field["sourcePath"] == "classification")
    assert enum_field["source"]["enumValues"] == {"0": "TRACK_CLASS_UNKNOWN", "1": "TRACK_CLASS_AIRCRAFT"}

    mapper = Mapper(mappings_dir=mappings_dir)
    record = DecodedRecord(
        "synthetic.mapper.Track",
        {"callsign": "EAGLE", "classification": "TRACK_CLASS_AIRCRAFT", "confidence_samples": [0.8, 0.9]},
        {},
    )
    translated = mapper.translate("synthetic-proto", record, "cot")
    assert translated[0]["messageName"] == "CoTEvent"
    assert translated[0]["fields"]["callsign"] == "EAGLE"
    assert translated[0]["fields"]["confidence_samples"] == [0.8, 0.9]


def test_oetf_mapper_emits_canonical_records_for_rust_translator() -> None:
    vector_path = SCHEMAS.parent / "conformance/vectors/track_report_two_tracks.json"
    vector = json.loads(vector_path.read_text(encoding="utf-8"))
    decoded = OetfDecoder().feed(bytes.fromhex(vector["chunks"][0]))
    assert len(decoded) == 1

    mapper = Mapper(mappings_dir=SCHEMAS.parent / "mappings", lookup_dirs=[LOOKUPS])
    tracks = mapper.translate("oetf", decoded[0], "billie-canonical")
    assert [item["messageName"] for item in tracks] == ["Track", "Track"]
    assert len(tracks) == 2
    first = tracks[0]["fields"]
    expected = json.loads((ROOT / "schemas/examples/oetf-canonical-track.json").read_text(encoding="utf-8"))
    assert first == expected
    assert "meta" not in tracks[0]  # Raw sensor frames stay inside the kid.
    assert first["apiVersion"] == "billie.dev/track-v2"
    assert first["kind"] == "Track"
    assert first["trackId"] == "311"
    assert first["sourceId"] == "263"
    assert first["trackGeneration"] == "fixture-1"
    assert first["observedAt"] == "2025-10-29T12:00:00.123Z"
    assert first["position"]["latitudeDeg"] == pytest.approx(0.0)
    assert first["position"]["longitudeDeg"] == pytest.approx(0.0)
    assert first["position"]["altitudeM"] == pytest.approx(152.4)
    assert first["velocity"] == {"eastMps": -12.5, "northMps": 4.25, "upMps": 1.5}
    assert first["classification"] == "uas"
    assert first["confidence"] == pytest.approx(0.87)
    assert first["identifiers"] == [{"scheme": "sapient-object-info", "value": "-18.3"}]
    assert first["positionUncertainty"]["sigmaEastM"] == pytest.approx(3.2)
    assert first["positionUncertainty"]["sigmaNorthM"] == pytest.approx(2.8)
    assert first["positionUncertainty"]["sigmaUpM"] == pytest.approx(6.1)
    assert tracks[1]["fields"]["trackId"] == "312"
    assert tracks[1]["fields"]["classification"] == "bird"
    assert tracks[1]["fields"]["identifiers"] == [{"scheme": "sapient-object-info", "value": "-18.3"}]

    request = {
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateRequest",
        "requestId": "oetf-vector-track-311",
        "kid": "oetf",
        "target": {"format": "cot"},
        "record": first,
    }
    assert "zenohKey" not in request["target"]
    assert request["record"] == expected
    assert set(request) == {"apiVersion", "kind", "requestId", "kid", "target", "record"}
    assert set(request["target"]) == {"format"}
