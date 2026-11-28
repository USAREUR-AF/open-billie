//! Every track input the translator's tests, fixtures and examples hold,
//! encoded by the native encoders and by the goat-transformers encoder path,
//! for CoT, ASTERIX CAT062 and SAPIENT.
//!
//! Outputs are parsed and compared field by field; CAT062 is also compared
//! byte for byte. The result must equal the recorded baseline,
//! `tests/fixtures/goat-transformers-baseline.json`: per output format the
//! counts, and one row per differing field with its cause. The test fails
//! when a difference appears, disappears or changes its input count.
//!
//! Run:
//!   cargo test --locked -p billie-translator --features goat-transformers \
//!     --test goat_transformers_compare -- --nocapture
//!
//! After a deliberate change (a new library pin, a changed encoder), set
//! `BILLIE_COMPARE_UPDATE=1` to rewrite the baseline, then write the cause of
//! every row the run marks `TODO` and update
//! docs/architecture/GOAT_TRANSFORMERS_ENCODER_OPTION.md.
//! `BILLIE_COMPARE_DETAIL=<file>` writes every per-input difference.

use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::fmt::Write as _;
use std::path::PathBuf;

use billie_translator::{
    encode_request, parse_request, CanonicalTrack, Cat062Options, Cat062SourceIdentifier,
    Classification, CotOptions, EncodeDispatchError, EncodeOptions, EncoderFormat, EncoderPath,
    EncoderSelection, Identifier, Position, PositionUncertainty, SapientOptions, TranslateRequest,
    Velocity,
};
use prost::Message;
use serde_json::{json, Map, Value};

const NODE_ID: &str = "00000000-0000-4000-8000-000000000001";
const BASELINE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/goat-transformers-baseline.json"
);
const FORMATS: [EncoderFormat; 3] = [
    EncoderFormat::Cot,
    EncoderFormat::AsterixCat062,
    EncoderFormat::Sapient,
];

// ---------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------

struct Case {
    name: String,
    kid: String,
    track: CanonicalTrack,
    cot: CotOptions,
}

fn case(name: &str, kid: &str, track: CanonicalTrack) -> Case {
    Case {
        name: name.to_owned(),
        kid: kid.to_owned(),
        track,
        cot: CotOptions::default(),
    }
}

fn from_request(name: &str, request: &Value) -> Case {
    let parsed = parse_request(request).unwrap_or_else(|e| panic!("{name}: {e}"));
    case(name, &parsed.kid.clone(), parsed.record)
}

fn wrap(kid: &str, record: Value) -> Value {
    json!({
        "apiVersion": "billie.dev/translation-v1", "kind": "TranslateRequest",
        "requestId": "compare", "kid": kid,
        "target": {"outputName": "tracks-cot", "format": "cot"},
        "record": record
    })
}

/// `valid()` of src/request.rs tests.
fn request_rs_valid() -> Value {
    json!({
        "apiVersion":"billie.dev/translation-v1", "kind":"TranslateRequest", "requestId":"test-1", "kid":"oetf",
        "target":{"outputName":"tracks-cot","format":"cot"},
        "record":{
            "apiVersion":"billie.dev/track-v2", "kind":"Track", "trackId":"311", "sourceId":"sensor-a", "trackGeneration":"generation-1", "observedAt":"2025-10-29T12:00:00.123Z",
            "position":{"latitudeDeg":0.0,"longitudeDeg":0.0,"altitudeM":152.4},
            "testData":false, "headerSimulated":false, "simulated":false,
            "velocity":{"eastMps":-12.5,"northMps":4.25,"upMps":1.5},
            "classification":"uas", "confidence":0.87,
            "positionUncertainty":{"sigmaEastM":3.2,"sigmaNorthM":2.8,"sigmaUpM":6.1}
        }
    })
}

/// `sample()` of src/cot.rs and src/cat062.rs tests; `sample_track()` of
/// src/sapient.rs tests is the same with one identifier.
fn sample(identifiers: Vec<Identifier>) -> CanonicalTrack {
    CanonicalTrack {
        track_id: "311".to_owned(),
        source_id: "sensor-a".to_owned(),
        track_generation: "generation-1".to_owned(),
        observed_at: "2025-10-29T12:00:00.123Z".to_owned(),
        position: Position {
            latitude_deg: 0.0,
            longitude_deg: 0.0,
            altitude_m: Some(152.4),
        },
        velocity: Some(Velocity {
            east_mps: -12.5,
            north_mps: 4.25,
            up_mps: Some(1.5),
        }),
        classification: Some(Classification::Uas),
        confidence: Some(0.87),
        position_uncertainty: Some(PositionUncertainty {
            sigma_east_m: Some(3.2),
            sigma_north_m: Some(2.8),
            sigma_up_m: Some(6.1),
        }),
        identifiers,
        test_data: false,
        header_simulated: false,
        simulated: false,
        confirmed: Some(true),
        coasting: false,
        final_update: false,
    }
}

fn rcs() -> Vec<Identifier> {
    vec![Identifier {
        scheme: "sapient-object-info".to_owned(),
        value: "-18.3".to_owned(),
    }]
}

fn cases() -> Vec<Case> {
    let mut out = Vec::new();

    // schemas/examples
    let example: Value = serde_json::from_str(include_str!(
        "../../../../schemas/examples/oetf-translation-request.json"
    ))
    .unwrap();
    out.push(from_request(
        "schemas/examples/oetf-translation-request.json",
        &example,
    ));
    let example_track: Value = serde_json::from_str(include_str!(
        "../../../../schemas/examples/oetf-canonical-track.json"
    ))
    .unwrap();
    out.push(from_request(
        "schemas/examples/oetf-canonical-track.json",
        &wrap("oetf", example_track),
    ));

    // docs/architecture/DECODER_TRANSLATOR_RUNTIME_CONTRACT.md, example request
    out.push(from_request(
        "DECODER_TRANSLATOR_RUNTIME_CONTRACT.md example request",
        &json!({
            "apiVersion": "billie.dev/translation-v1", "kind": "TranslateRequest",
            "requestId": "01JEXAMPLE", "kid": "oetf",
            "target": { "outputName": "tracks-cot", "format": "cot" },
            "record": {
                "apiVersion": "billie.dev/track-v2", "kind": "Track",
                "trackId": "synthetic-001", "sourceId": "sensor-a", "trackGeneration": "fixture-1",
                "observedAt": "2026-01-01T00:00:00Z",
                "testData": false, "headerSimulated": false, "simulated": false,
                "position": { "latitudeDeg": 45.0, "longitudeDeg": -73.0 }
            }
        }),
    ));

    // src/request.rs tests
    out.push(from_request("request.rs valid()", &request_rs_valid()));
    let mut v = request_rs_valid();
    v["record"]["sourceId"] = json!("sensor/b");
    out.push(from_request("request.rs sourceId sensor/b", &v));
    let mut v = request_rs_valid();
    v["record"]["trackGeneration"] = json!("generation-2");
    out.push(from_request("request.rs trackGeneration generation-2", &v));
    let mut v = request_rs_valid();
    for flag in [
        "testData",
        "headerSimulated",
        "simulated",
        "coasting",
        "finalUpdate",
    ] {
        v["record"][flag] = json!(true);
    }
    v["record"]["confirmed"] = json!(false);
    out.push(from_request("request.rs all status flags set", &v));
    out.push(case(
        "request.rs scoped identity, kid other-kid",
        "other-kid",
        parse_request(&request_rs_valid()).unwrap().record,
    ));

    // src/dispatch.rs tests: request_for("asterix-cat062") sets confirmed=true
    let mut v = example.clone();
    v["record"]["confirmed"] = json!(true);
    out.push(from_request("dispatch.rs request_for (confirmed=true)", &v));

    // src/cot.rs tests
    out.push(case("cot.rs sample()", "local", sample(Vec::new())));
    let mut t = sample(Vec::new());
    t.position.altitude_m = None;
    t.velocity = None;
    t.position_uncertainty = None;
    t.classification = None;
    out.push(case("cot.rs no optional point fields", "local", t));
    let mut t = sample(Vec::new());
    t.track_id = "A<&\"".to_owned();
    out.push(Case {
        name: "cot.rs trackId A<&\" with how m-&p, stale 30 s".to_owned(),
        kid: "local".to_owned(),
        track: t,
        cot: CotOptions {
            stale_after_seconds: 30,
            how: "m-&p".to_owned(),
        },
    });
    let mut t = sample(Vec::new());
    t.test_data = true;
    t.confirmed = Some(false);
    t.coasting = true;
    t.final_update = true;
    out.push(case("cot.rs simulation and track status", "local", t));

    // src/sapient.rs tests
    out.push(case("sapient.rs sample_track()", "local", sample(rcs())));
    let mut t = sample(rcs());
    t.observed_at = "2025-10-29T12:00:01Z".to_owned();
    out.push(case(
        "sapient.rs later observedAt (no fraction)",
        "local",
        t,
    ));
    let mut t = sample(rcs());
    t.track_generation = "generation-2".to_owned();
    out.push(case("sapient.rs generation-2", "local", t));
    out.push(case("sapient.rs kid other-kid", "other-kid", sample(rcs())));
    let mut t = sample(rcs());
    t.test_data = true;
    t.header_simulated = true;
    t.confirmed = Some(false);
    t.coasting = true;
    t.final_update = true;
    out.push(case("sapient.rs status in state convention", "local", t));

    // src/cat062.rs tests (the same tracks, sent to CoT and SAPIENT)
    let mut t = sample(Vec::new());
    t.simulated = true;
    t.confirmed = Some(false);
    t.coasting = true;
    t.final_update = true;
    out.push(case("cat062.rs status bits", "oetf", t));
    for source in ["sensor-b", "sensor-c"] {
        let mut t = sample(Vec::new());
        t.source_id = source.to_owned();
        out.push(case(&format!("cat062.rs sourceId {source}"), "oetf", t));
    }
    let mut t = sample(Vec::new());
    t.track_id = "track-311".to_owned();
    out.push(case("cat062.rs trackId track-311", "oetf", t));
    let mut t = sample(Vec::new());
    t.position.longitude_deg = 180.0;
    out.push(case("cat062.rs longitude 180", "oetf", t));

    // The OETF conformance vectors run through the example decoder and mapper
    // (tools/generate-oetf-mapper-tracks.py).
    let mapped: BTreeMap<String, Value> =
        serde_json::from_str(include_str!("fixtures/oetf-mapper-tracks.json")).unwrap();
    for (name, record) in mapped {
        out.push(from_request(&name, &wrap("oetf", record)));
    }
    out
}

// ---------------------------------------------------------------------------
// Parsing: one map of field path -> value per encoded message
// ---------------------------------------------------------------------------

type Fields = BTreeMap<String, String>;

fn flatten_xml(xml: &str) -> Fields {
    fn walk(node: roxmltree::Node, path: &str, out: &mut Fields) {
        for attr in node.attributes() {
            out.insert(format!("{path}/@{}", attr.name()), attr.value().to_owned());
        }
        let text: String = node
            .children()
            .filter(|c| c.is_text())
            .filter_map(|c| c.text())
            .collect();
        if !text.trim().is_empty() {
            out.insert(format!("{path}/#text"), text);
        }
        for child in node.children().filter(|c| c.is_element()) {
            let child_path = format!("{path}/{}", child.tag_name().name());
            out.insert(child_path.clone(), "(element)".to_owned());
            walk(child, &child_path, out);
        }
    }
    let doc = roxmltree::Document::parse(xml).unwrap_or_else(|e| panic!("bad XML {xml}: {e}"));
    let root = doc.root_element();
    let mut out = Fields::new();
    walk(root, root.tag_name().name(), &mut out);
    out
}

// Prost types for SAPIENT BSI Flex 335 v2.0, the same shapes as the decoder
// in src/sapient.rs tests (field numbers and wire types of the official
// sapient_message.proto and detection_report.proto).
#[derive(Clone, PartialEq, Message)]
struct SapientMessage {
    #[prost(message, optional, tag = "1")]
    timestamp: Option<Timestamp>,
    #[prost(string, optional, tag = "2")]
    node_id: Option<String>,
    #[prost(string, optional, tag = "3")]
    destination_id: Option<String>,
    #[prost(message, optional, tag = "7")]
    detection_report: Option<DetectionReport>,
}
#[derive(Clone, PartialEq, Message)]
struct Timestamp {
    #[prost(int64, optional, tag = "1")]
    seconds: Option<i64>,
    #[prost(int32, optional, tag = "2")]
    nanos: Option<i32>,
}
#[derive(Clone, PartialEq, Message)]
struct DetectionReport {
    #[prost(string, optional, tag = "1")]
    report_id: Option<String>,
    #[prost(string, optional, tag = "2")]
    object_id: Option<String>,
    #[prost(string, optional, tag = "3")]
    task_id: Option<String>,
    #[prost(string, optional, tag = "4")]
    state: Option<String>,
    #[prost(message, optional, tag = "6")]
    location: Option<Location>,
    #[prost(float, optional, tag = "7")]
    detection_confidence: Option<f32>,
    #[prost(message, repeated, tag = "10")]
    object_info: Vec<ObjectInfo>,
    #[prost(message, repeated, tag = "11")]
    classification: Vec<ClassificationMessage>,
    #[prost(message, optional, tag = "19")]
    enu_velocity: Option<EnuVelocity>,
    #[prost(string, optional, tag = "23")]
    id: Option<String>,
}
#[derive(Clone, PartialEq, Message)]
struct Location {
    #[prost(double, optional, tag = "1")]
    x: Option<f64>,
    #[prost(double, optional, tag = "2")]
    y: Option<f64>,
    #[prost(double, optional, tag = "3")]
    z: Option<f64>,
    #[prost(double, optional, tag = "4")]
    x_error: Option<f64>,
    #[prost(double, optional, tag = "5")]
    y_error: Option<f64>,
    #[prost(double, optional, tag = "6")]
    z_error: Option<f64>,
    #[prost(int32, optional, tag = "7")]
    coordinate_system: Option<i32>,
    #[prost(int32, optional, tag = "8")]
    datum: Option<i32>,
}
#[derive(Clone, PartialEq, Message)]
struct ClassificationMessage {
    #[prost(string, optional, tag = "1")]
    r#type: Option<String>,
    #[prost(float, optional, tag = "2")]
    confidence: Option<f32>,
}
#[derive(Clone, PartialEq, Message)]
struct ObjectInfo {
    #[prost(string, optional, tag = "1")]
    r#type: Option<String>,
    #[prost(string, optional, tag = "2")]
    value: Option<String>,
}
#[derive(Clone, PartialEq, Message)]
struct EnuVelocity {
    #[prost(double, optional, tag = "1")]
    east_rate: Option<f64>,
    #[prost(double, optional, tag = "2")]
    north_rate: Option<f64>,
    #[prost(double, optional, tag = "3")]
    up_rate: Option<f64>,
}

fn flatten_sapient(bytes: &[u8]) -> Fields {
    let message = SapientMessage::decode(bytes).expect("SAPIENT output decodes");
    let mut out = Fields::new();
    // Prost drops fields these types do not declare. A shorter re-encoding
    // means the output held one.
    if message.encoded_len() != bytes.len() {
        out.insert(
            "(undeclared fields)".to_owned(),
            format!("{} bytes", bytes.len() - message.encoded_len()),
        );
    }
    macro_rules! put {
        ($key:expr, $value:expr) => {
            if let Some(v) = $value {
                out.insert($key.to_owned(), format!("{:?}", v));
            }
        };
    }
    if let Some(t) = &message.timestamp {
        put!("timestamp.seconds", t.seconds);
        put!("timestamp.nanos", t.nanos);
    }
    put!("node_id", &message.node_id);
    put!("destination_id", &message.destination_id);
    if let Some(r) = &message.detection_report {
        out.insert("detection_report".to_owned(), "(message)".to_owned());
        put!("detection_report.report_id", &r.report_id);
        put!("detection_report.object_id", &r.object_id);
        put!("detection_report.task_id", &r.task_id);
        put!("detection_report.state", &r.state);
        put!(
            "detection_report.detection_confidence",
            r.detection_confidence
        );
        put!("detection_report.id", &r.id);
        if let Some(l) = &r.location {
            put!("detection_report.location.x", l.x);
            put!("detection_report.location.y", l.y);
            put!("detection_report.location.z", l.z);
            put!("detection_report.location.x_error", l.x_error);
            put!("detection_report.location.y_error", l.y_error);
            put!("detection_report.location.z_error", l.z_error);
            put!(
                "detection_report.location.coordinate_system",
                l.coordinate_system
            );
            put!("detection_report.location.datum", l.datum);
        }
        for (i, c) in r.classification.iter().enumerate() {
            put!(
                format!("detection_report.classification[{i}].type"),
                &c.r#type
            );
            put!(
                format!("detection_report.classification[{i}].confidence"),
                c.confidence
            );
        }
        for (i, o) in r.object_info.iter().enumerate() {
            put!(format!("detection_report.object_info[{i}].type"), &o.r#type);
            put!(format!("detection_report.object_info[{i}].value"), &o.value);
        }
        if let Some(v) = &r.enu_velocity {
            put!("detection_report.enu_velocity.east_rate", v.east_rate);
            put!("detection_report.enu_velocity.north_rate", v.north_rate);
            put!("detection_report.enu_velocity.up_rate", v.up_rate);
        }
    }
    out
}

/// One ASTERIX CAT062 data block with one record of the items the native
/// encoder writes (I062/010, 070, 105, 185, 040, 080, 130), read without the
/// library. Anything else is reported under `(unparsed)`.
fn flatten_cat062(block: &[u8]) -> Fields {
    let mut out = Fields::new();
    if block.len() < 4 {
        out.insert("(unparsed)".to_owned(), format!("{} octets", block.len()));
        return out;
    }
    out.insert("CAT".to_owned(), block[0].to_string());
    out.insert(
        "LEN".to_owned(),
        u16::from_be_bytes([block[1], block[2]]).to_string(),
    );
    let mut at = 3;
    let mut frns = BTreeSet::new();
    let mut octet = 0usize;
    while let Some(&byte) = block.get(at) {
        at += 1;
        for bit in 0..7 {
            if byte & (0x80 >> bit) != 0 {
                frns.insert(octet * 7 + bit + 1);
            }
        }
        octet += 1;
        if byte & 1 == 0 {
            break;
        }
    }
    let fspec: Vec<String> = frns.iter().map(usize::to_string).collect();
    out.insert("FSPEC".to_owned(), fspec.join(","));
    for frn in &frns {
        let width = match frn {
            1 | 12 | 18 => 2,
            4 => 3,
            5 => 8,
            7 => 4,
            // I062/080: a first part and extents, each ending in an FX bit
            13 => {
                let mut width = 0;
                while let Some(&byte) = block.get(at + width) {
                    width += 1;
                    if byte & 1 == 0 {
                        break;
                    }
                }
                width
            }
            _ => {
                out.insert("(unparsed)".to_owned(), format!("from FRN {frn}"));
                return out;
            }
        };
        let Some(b) = block.get(at..at + width) else {
            out.insert("(unparsed)".to_owned(), format!("FRN {frn} is cut short"));
            return out;
        };
        at += width;
        let i16_at = |i: usize| i16::from_be_bytes([b[i], b[i + 1]]).to_string();
        let i32_at =
            |i: usize| i32::from_be_bytes([b[i], b[i + 1], b[i + 2], b[i + 3]]).to_string();
        let mut put = |key: &str, value: String| {
            out.insert(key.to_owned(), value);
        };
        match frn {
            1 => {
                put("I062/010 SAC", b[0].to_string());
                put("I062/010 SIC", b[1].to_string());
            }
            4 => put(
                "I062/070 time of day (1/128 s)",
                u32::from_be_bytes([0, b[0], b[1], b[2]]).to_string(),
            ),
            5 => {
                put("I062/105 latitude (180/2^25 deg)", i32_at(0));
                put("I062/105 longitude (180/2^25 deg)", i32_at(4));
            }
            7 => {
                put("I062/185 Vx (0.25 m/s)", i16_at(0));
                put("I062/185 Vy (0.25 m/s)", i16_at(2));
            }
            12 => put(
                "I062/040 track number",
                u16::from_be_bytes([b[0], b[1]]).to_string(),
            ),
            13 => {
                for (index, extent) in b.iter().enumerate() {
                    put(
                        &format!("I062/080 octet {}", index + 1),
                        format!("{extent:#04x}"),
                    );
                }
            }
            _ => put("I062/130 altitude (6.25 ft)", i16_at(0)),
        }
    }
    if at != block.len() {
        out.insert(
            "(unparsed)".to_owned(),
            format!("{} trailing octets", block.len() - at),
        );
    }
    out
}

// ---------------------------------------------------------------------------
// Comparison
// ---------------------------------------------------------------------------

fn is_ulid(text: &str) -> bool {
    let t = text.trim_matches('"');
    t.len() == 26
        && t.bytes()
            .all(|b| b"0123456789ABCDEFGHJKMNPQRSTVWXYZ".contains(&b))
}

fn same_value(a: &str, b: &str) -> bool {
    if let (Ok(x), Ok(y)) = (a.parse::<f64>(), b.parse::<f64>()) {
        return x == y;
    }
    match (
        chrono::DateTime::parse_from_rfc3339(a),
        chrono::DateTime::parse_from_rfc3339(b),
    ) {
        (Ok(x), Ok(y)) => x == y,
        _ => false,
    }
}

/// Two finite numbers no more than two units in the last place apart.
fn last_digit_apart(a: &str, b: &str) -> bool {
    match (a.parse::<f64>(), b.parse::<f64>()) {
        (Ok(x), Ok(y)) if x.is_finite() && y.is_finite() => {
            (x - y).abs() <= 2.0 * f64::EPSILON * x.abs().max(y.abs())
        }
        _ => false,
    }
}

/// (field, kind of difference, native value, library value)
type Diff = (String, &'static str, String, String);

fn compare(native: &Fields, library: &Fields) -> Vec<Diff> {
    let keys: BTreeSet<&String> = native.keys().chain(library.keys()).collect();
    let mut out = Vec::new();
    for key in keys {
        let kind = match (native.get(key), library.get(key)) {
            (Some(n), Some(l)) if n == l => continue,
            // A SAPIENT report_id is a fresh ULID per message: two valid
            // ULIDs count as equal.
            (Some(n), Some(l)) if key.ends_with(".report_id") && is_ulid(n) && is_ulid(l) => {
                continue
            }
            // The native encoders call the platform `hypot`; the library
            // computes sqrt(a*a + b*b). The two can differ in the last digit,
            // on some platforms only, so such a pair counts as equal.
            (Some(n), Some(l)) if last_digit_apart(n, l) => continue,
            (Some(n), Some(l)) if same_value(n, l) => "same value, different text",
            (Some(_), Some(_)) => "different value",
            (Some(_), None) => "not written by the library",
            (None, Some(_)) => "written by the library only",
            (None, None) => unreachable!(),
        };
        let show = |v: Option<&String>| v.cloned().unwrap_or_else(|| "(absent)".to_owned());
        out.push((
            strip_index(key),
            kind,
            show(native.get(key)),
            show(library.get(key)),
        ));
    }
    out
}

fn strip_index(key: &str) -> String {
    let mut out = String::new();
    let mut skip = false;
    for ch in key.chars() {
        match ch {
            '[' => {
                skip = true;
                out.push_str("[]");
            }
            ']' => skip = false,
            _ if skip => {}
            _ => out.push(ch),
        }
    }
    out
}

fn error_code(error: &EncodeDispatchError) -> &'static str {
    match error {
        EncodeDispatchError::Cot(e) => e.code,
        EncodeDispatchError::Cat062(e) => e.code,
        EncodeDispatchError::Sapient(e) => e.code,
        EncodeDispatchError::UnsupportedFormat(_) => "unsupported_format",
        EncodeDispatchError::Library(e) => e.code,
    }
}

fn flatten(format: EncoderFormat, bytes: &[u8]) -> Fields {
    match format {
        EncoderFormat::Cot => flatten_xml(std::str::from_utf8(bytes).expect("CoT is UTF-8")),
        EncoderFormat::AsterixCat062 => flatten_cat062(bytes),
        EncoderFormat::Sapient => flatten_sapient(bytes),
    }
}

#[derive(Default)]
struct Tally {
    inputs: usize,
    encoded_by_both: usize,
    refused_by_both: usize,
    bytes_identical: usize,
    fields_identical: usize,
    fields_compared: usize,
    fields_equal: usize,
    /// (field, kind) -> (inputs, first example)
    differences: BTreeMap<(String, &'static str), (usize, String)>,
}

fn options(case: &Case, store: &std::path::Path, path: EncoderPath) -> EncodeOptions {
    EncodeOptions {
        cot: case.cot.clone(),
        // The assignments of the CAT062 encoder's source tests.
        cat062: Cat062Options {
            default_source: Some(Cat062SourceIdentifier { sac: 9, sic: 9 }),
            sources: HashMap::from([
                (
                    ("oetf".to_owned(), "sensor-a".to_owned()),
                    Cat062SourceIdentifier { sac: 1, sic: 7 },
                ),
                (
                    ("oetf".to_owned(), "sensor-b".to_owned()),
                    Cat062SourceIdentifier { sac: 1, sic: 8 },
                ),
            ]),
        },
        // One store for both paths: the object ULID of a scoped identity is
        // allocated by the first path and read by the second.
        sapient: SapientOptions {
            node_id: NODE_ID.to_owned(),
            object_id_store: store.to_path_buf(),
        },
        encoders: EncoderSelection {
            cot: path,
            cat062: path,
            sapient: path,
        },
    }
}

fn measure(detail: &mut String) -> BTreeMap<&'static str, Tally> {
    let store: PathBuf = std::env::temp_dir().join(format!(
        "billie-compare-sapient-{}.json",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&store);
    let mut tallies = BTreeMap::new();
    for format in FORMATS {
        let tally: &mut Tally = tallies.entry(format.as_str()).or_default();
        for case in cases() {
            let request = TranslateRequest {
                request_id: "compare".to_owned(),
                kid: case.kid.clone(),
                format,
                output_name: "tracks".to_owned(),
                profile: None,
                record: case.track.clone(),
            };
            let native = encode_request(&request, &options(&case, &store, EncoderPath::Native));
            let library = encode_request(
                &request,
                &options(&case, &store, EncoderPath::GoatTransformers),
            );
            tally.inputs += 1;
            writeln!(detail, "## {} / {}", format.as_str(), case.name).unwrap();
            let diffs: Vec<Diff> = match (&native, &library) {
                (Ok(native), Ok(library)) => {
                    assert_eq!(native.content_type, library.content_type);
                    tally.encoded_by_both += 1;
                    if native.bytes == library.bytes {
                        tally.bytes_identical += 1;
                    }
                    let (n, l) = (
                        flatten(format, &native.bytes),
                        flatten(format, &library.bytes),
                    );
                    let diffs = compare(&n, &l);
                    let union: BTreeSet<&String> = n.keys().chain(l.keys()).collect();
                    tally.fields_compared += union.len();
                    tally.fields_equal += union.len() - diffs.len();
                    if diffs.is_empty() {
                        tally.fields_identical += 1;
                    }
                    if format == EncoderFormat::Cot {
                        let text = |bytes: &[u8]| String::from_utf8_lossy(bytes).into_owned();
                        writeln!(detail, "native:  {}", text(&native.bytes)).unwrap();
                        writeln!(detail, "library: {}", text(&library.bytes)).unwrap();
                    }
                    diffs
                }
                (Err(native), Err(library)) => {
                    tally.refused_by_both += 1;
                    writeln!(
                        detail,
                        "  both refuse: native {} / library {}",
                        error_code(native),
                        error_code(library)
                    )
                    .unwrap();
                    Vec::new()
                }
                (native, library) => {
                    let show = |r: &Result<_, EncodeDispatchError>| match r {
                        Ok(_) => "encoded".to_owned(),
                        Err(e) => format!("refused: {}", error_code(e)),
                    };
                    vec![(
                        "(outcome)".to_owned(),
                        "one path refuses",
                        show(native),
                        show(library),
                    )]
                }
            };
            for (field, kind, native, library) in diffs {
                writeln!(
                    detail,
                    "  {field:<48} {kind}: native={native} library={library}"
                )
                .unwrap();
                let entry = tally.differences.entry((field, kind)).or_default();
                entry.0 += 1;
                if entry.1.is_empty() {
                    entry.1 = format!("{native} | {library}");
                }
            }
        }
    }
    let _ = std::fs::remove_file(&store);
    tallies
}

/// The measurement in the shape of the baseline file. Causes come from
/// `known`; a row with no recorded cause gets `TODO`.
fn render(tallies: &BTreeMap<&'static str, Tally>, known: &Value) -> Value {
    let mut root = Map::new();
    for (format, tally) in tallies {
        let rows: Vec<Value> = tally
            .differences
            .iter()
            .map(|((field, kind), (inputs, example))| {
                let cause = known[*format]["differences"]
                    .as_array()
                    .and_then(|rows| {
                        rows.iter()
                            .find(|row| row["field"] == **field && row["difference"] == **kind)
                    })
                    .and_then(|row| row["cause"].as_str())
                    .unwrap_or("TODO");
                json!({
                    "field": field,
                    "difference": kind,
                    "inputs": inputs,
                    "example": example,
                    "cause": cause,
                })
            })
            .collect();
        let mut target = json!({
            "inputs": tally.inputs,
            "encodedByBoth": tally.encoded_by_both,
            "refusedByBoth": tally.refused_by_both,
            "bytesIdentical": tally.bytes_identical,
            "fieldsIdentical": tally.fields_identical,
            "fieldsCompared": tally.fields_compared,
            "fieldsEqual": tally.fields_equal,
            "differences": rows,
        });
        // A count recorded for this architecture goes back to its own entry;
        // `bytesIdentical` keeps the count recorded on x86_64.
        if let Some(by_arch) = known[*format]["bytesIdenticalByArch"].as_object() {
            let mut by_arch = by_arch.clone();
            if by_arch.contains_key(std::env::consts::ARCH) {
                by_arch.insert(
                    std::env::consts::ARCH.to_owned(),
                    json!(tally.bytes_identical),
                );
                target["bytesIdentical"] = known[*format]["bytesIdentical"].clone();
            }
            target["bytesIdenticalByArch"] = Value::Object(by_arch);
        }
        root.insert((*format).to_owned(), target);
    }
    Value::Object(root)
}

/// The baseline without the columns that are not asserted: an example holds
/// the first input's values, and a cause is prose. Where the baseline records
/// a byte-identical count for the architecture the test runs on
/// (`bytesIdenticalByArch`), that count is the one asserted.
fn asserted(baseline: &Value) -> Value {
    let mut copy = baseline.clone();
    for (_, target) in copy.as_object_mut().into_iter().flatten() {
        if let Some(by_arch) = target
            .as_object_mut()
            .unwrap()
            .remove("bytesIdenticalByArch")
        {
            if let Some(count) = by_arch.get(std::env::consts::ARCH) {
                target["bytesIdentical"] = count.clone();
            }
        }
        for row in target["differences"].as_array_mut().into_iter().flatten() {
            let row = row.as_object_mut().unwrap();
            row.remove("example");
            row.remove("cause");
        }
    }
    copy
}

#[test]
fn library_encoder_differs_from_native_exactly_as_recorded() {
    let mut detail = String::new();
    let tallies = measure(&mut detail);
    if let Some(path) = std::env::var_os("BILLIE_COMPARE_DETAIL") {
        std::fs::write(path, &detail).unwrap();
    }
    let recorded: Value = std::fs::read_to_string(BASELINE)
        .ok()
        .map(|text| serde_json::from_str(&text).expect("the baseline is JSON"))
        .unwrap_or(Value::Null);
    let measured = render(&tallies, &recorded);
    let text = serde_json::to_string_pretty(&measured).unwrap() + "\n";
    println!("{text}");
    if std::env::var_os("BILLIE_COMPARE_UPDATE").is_some() {
        std::fs::write(BASELINE, &text).unwrap();
    } else {
        assert_eq!(
            asserted(&measured),
            asserted(&recorded),
            "the measured differences (left) are not the recorded baseline (right); \
             see the header of this file"
        );
    }
    assert!(
        !text.contains("\"cause\": \"TODO\""),
        "a difference has no recorded cause in {BASELINE}"
    );
}

#[test]
fn switching_a_format_back_to_native_restores_the_native_bytes() {
    // An input the two encoders still write differently (at a whole second
    // the library writes `.000Z` and the native encoder no fraction), so the
    // first assertion shows the selection took effect.
    let case = cases()
        .into_iter()
        .find(|case| case.name == "DECODER_TRANSLATOR_RUNTIME_CONTRACT.md example request")
        .unwrap();
    let request = TranslateRequest {
        request_id: "compare".to_owned(),
        kid: case.kid,
        format: EncoderFormat::Cot,
        output_name: "tracks".to_owned(),
        profile: None,
        record: case.track,
    };
    let mut options = EncodeOptions::default();
    options.encoders.cot = EncoderPath::Native;
    let native = encode_request(&request, &options).unwrap();
    options.encoders.cot = EncoderPath::GoatTransformers;
    let library = encode_request(&request, &options).unwrap();
    assert_ne!(library.bytes, native.bytes);
    options.encoders.cot = EncoderPath::Native;
    assert_eq!(encode_request(&request, &options).unwrap(), native);
}
