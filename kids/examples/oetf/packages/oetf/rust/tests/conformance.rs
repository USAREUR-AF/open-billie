//! Every vector in shared/conformance/vectors must decode and map (to every target) exactly as the TS reference did.

use std::path::PathBuf;

use billie_oetf::{build_track_report, crc16, FrameHeader, Mapper, OetfDecoder, Track};
use serde_json::Value;

fn vectors_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../shared/conformance/vectors")
}

fn hex(s: &str) -> Vec<u8> {
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
}

/// Exact structural equality; ints and floats compare numerically (JS has one number type).
fn same(a: &Value, b: &Value, path: &str) {
    match (a, b) {
        (Value::Object(x), Value::Object(y)) => {
            let (kx, ky): (Vec<_>, Vec<_>) = (x.keys().collect(), y.keys().collect());
            assert_eq!(kx, ky, "{path}: keys differ");
            for (k, v) in x {
                same(v, &y[k], &format!("{path}.{k}"));
            }
        }
        (Value::Array(x), Value::Array(y)) => {
            assert_eq!(x.len(), y.len(), "{path}: length");
            for (i, (p, q)) in x.iter().zip(y).enumerate() {
                same(p, q, &format!("{path}[{i}]"));
            }
        }
        (Value::Number(x), Value::Number(y)) => assert_eq!(x.as_f64(), y.as_f64(), "{path}"),
        _ => assert_eq!(a, b, "{path}"),
    }
}

#[test]
fn every_vector_matches_the_reference() {
    let mapper = Mapper::bundled();
    let mut paths: Vec<_> = std::fs::read_dir(vectors_dir()).unwrap().map(|e| e.unwrap().path()).collect();
    paths.sort();
    assert!(paths.len() >= 5, "expected conformance vectors in {}", vectors_dir().display());

    for p in paths {
        let name = p.file_stem().unwrap().to_string_lossy().into_owned();
        let v: Value = serde_json::from_str(&std::fs::read_to_string(&p).unwrap()).unwrap();
        let mut dec = OetfDecoder::new();
        let records: Vec<_> = v["chunks"].as_array().unwrap().iter().flat_map(|c| dec.feed(&hex(c.as_str().unwrap()))).collect();

        let errors: Vec<Value> = dec.take_recent_errors().iter().map(|e| Value::from(e.reason)).collect();
        assert_eq!(Value::Array(errors), v["errors"], "{name}: errors");
        let want = v["records"].as_array().unwrap();
        assert_eq!(records.len(), want.len(), "{name}: record count");

        for (i, (got, want)) in records.iter().zip(want).enumerate() {
            let at = format!("{name}[{i}]");
            assert_eq!(got.message_name, want["messageName"], "{at}");
            assert_eq!(Value::from(got.msg_id), want["msgId"], "{at}");
            same(&Value::Object(got.fields.clone()), &want["fields"], &format!("{at}.fields"));
            for (target, expected) in want["translations"].as_object().unwrap() {
                if expected.is_null() {
                    assert!(!mapper.has_mapping("oetf", &got.message_name, target), "{at}.{target}");
                } else {
                    let out: Vec<Value> = mapper.translate("oetf", got, target).into_iter().map(|t| t.fields).collect();
                    same(&Value::Array(out), expected, &format!("{at}.{target}"));
                }
            }
        }
    }
}

#[test]
fn crc_check_value() {
    assert_eq!(crc16(b"123456789"), 0x29B1);
}

#[test]
fn builder_is_byte_identical_to_ts() {
    let base = Track {
        classification: 3, confidence_pct: 87, lat_deg: 0.0, lon_deg: 0.0, alt_m: 152.4,
        vel_east_ms: -12.5, vel_north_ms: 4.25, vel_up_ms: 1.5, pos_sigma_east_m: 3.2, pos_sigma_north_m: 2.8,
        alt_sigma_m: 6.1, vel_sigma_east_ms: 0.9, vel_sigma_north_ms: 0.7, rcs_dbsm: -18.3, age_s: 74,
        ..Default::default()
    };
    let frame = build_track_report(
        &FrameHeader { sequence: 42, sensor_id: 0x0107, ..Default::default() },
        1_761_739_200_123_456,
        &[
            Track { id: 311, confirmed: true, mode3a: Some("7000".into()), ..base.clone() },
            Track { id: 312, classification: 5, coasting: true, final_update: true, simulated: true, ..base },
        ],
    )
    .unwrap();
    let v: Value = serde_json::from_str(&std::fs::read_to_string(vectors_dir().join("track_report_two_tracks.json")).unwrap()).unwrap();
    let got: String = frame.iter().map(|b| format!("{b:02x}")).collect();
    assert_eq!(got, v["chunks"][0].as_str().unwrap());
}
