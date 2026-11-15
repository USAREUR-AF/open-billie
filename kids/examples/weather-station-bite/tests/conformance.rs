//! The dictionary's vectors decode inside the kid, and every vector in
//! tests/vectors decodes and maps exactly as recorded.

use std::path::{Path, PathBuf};

use billie_bite_kid::{translation_request, Decoder, Mapper};
use serde_json::{json, Value};

fn package() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn decoder() -> Decoder {
    Decoder::load(&package().join("schemas/weather-station"), None).unwrap()
}

fn mapper() -> Mapper {
    Mapper::from_dirs(&package().join("mappings"), &package().join("lookups")).unwrap()
}

fn read(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn hex(text: &str) -> Vec<u8> {
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
        .collect()
}

/// Exact structural equality; integers and floats compare by value.
fn same(a: &Value, b: &Value, path: &str) {
    match (a, b) {
        (Value::Object(x), Value::Object(y)) => {
            let (kx, ky): (Vec<_>, Vec<_>) = (x.keys().collect(), y.keys().collect());
            assert_eq!(kx, ky, "{path}: keys differ");
            for (key, value) in x {
                same(value, &y[key], &format!("{path}.{key}"));
            }
        }
        (Value::Number(x), Value::Number(y)) => assert_eq!(x.as_f64(), y.as_f64(), "{path}"),
        _ => assert_eq!(a, b, "{path}"),
    }
}

#[test]
fn the_dictionary_vectors_decode_inside_the_kid() {
    assert_eq!(decoder().check_vectors(), Ok(5));
}

#[test]
fn the_dictionary_loads_without_warnings() {
    assert!(decoder().dictionary().issues().is_empty());
}

#[test]
fn only_the_position_message_is_mapped() {
    assert_eq!(mapper().mapped_messages(), ["Position"]);
}

#[test]
fn every_vector_decodes_and_maps_as_recorded() {
    let (decoder, mapper) = (decoder(), mapper());
    let mut paths: Vec<_> = std::fs::read_dir(package().join("tests/vectors"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension == "json")
        })
        .collect();
    paths.sort();
    assert_eq!(paths.len(), 9, "conformance vectors in tests/vectors");

    for path in paths {
        let vector = read(&path);
        let name = vector["name"].as_str().unwrap();
        let datagram = hex(vector["datagramHex"].as_str().unwrap());
        let received_at = vector["receivedAt"].as_str().unwrap();

        let record = match (decoder.decode(&datagram), vector.get("decodeError")) {
            (Err(error), Some(expected)) => {
                assert!(
                    error.contains(expected.as_str().unwrap()),
                    "{name}: {error}"
                );
                assert!(
                    vector["decoded"].is_null() && vector["track"].is_null(),
                    "{name}"
                );
                continue;
            }
            (Ok(record), None) => record,
            (outcome, _) => panic!("{name}: unexpected decode outcome {outcome:?}"),
        };
        assert_eq!(record.interface, vector["interface"], "{name}: interface");
        assert_eq!(
            record.message, vector["decoded"]["message"],
            "{name}: message"
        );
        same(
            &Value::Object(record.fields.clone()),
            &vector["decoded"]["fields"],
            &format!("{name}.decoded.fields"),
        );

        match mapper.translate(&record, received_at) {
            None => {
                assert!(vector["track"].is_null(), "{name}: a track was expected");
                assert_eq!(vector["missing"], json!([]), "{name}: missing");
            }
            Some(mapped) => {
                assert_eq!(json!(mapped.missing), vector["missing"], "{name}: missing");
                if mapped.missing.is_empty() {
                    same(&mapped.track, &vector["track"], &format!("{name}.track"));
                } else {
                    assert!(vector["track"].is_null(), "{name}: no track is sent");
                }
            }
        }
    }
}

#[test]
fn a_position_datagram_becomes_the_expected_translation_request() {
    let vector = read(&package().join("tests/vectors/position.json"));
    let record = decoder()
        .decode(&hex(vector["datagramHex"].as_str().unwrap()))
        .unwrap();
    let mapped = mapper()
        .translate(&record, "2026-01-01T00:00:00.000Z")
        .unwrap();
    let request = translation_request(
        "weather-station-bite",
        "request-1",
        "tracks-cot",
        "cot",
        &mapped.track,
    );
    same(
        &request,
        &json!({
            "apiVersion": "billie.dev/translation-v1",
            "kind": "TranslateRequest",
            "requestId": "request-1",
            "kid": "weather-station-bite",
            "target": { "outputName": "tracks-cot", "format": "cot" },
            "record": {
                "apiVersion": "billie.dev/track-v2",
                "kind": "Track",
                "trackId": "KX7",
                "sourceId": "WX",
                "trackGeneration": "1",
                "observedAt": "2026-01-01T00:00:00.000Z",
                "testData": true,
                "headerSimulated": false,
                "simulated": false,
                "position": {
                    "latitudeDeg": 64.8378,
                    "longitudeDeg": -147.7164,
                    "altitudeM": 136.5
                },
                "classification": "other"
            }
        }),
        "request",
    );
}

#[test]
fn the_checked_in_record_schema_is_what_the_dictionary_produces() {
    let produced = Value::Object(bite::jsonschema::dictionary_schemas(decoder().dictionary()));
    let checked_in = read(&package().join("schemas/weather-station.records.schema.json"));
    assert_eq!(
        produced, checked_in,
        "regenerate schemas/weather-station.records.schema.json with `bite schema schemas/weather-station`"
    );
}

#[test]
fn a_dictionary_with_errors_is_refused() {
    let directory = std::env::temp_dir().join(format!("bite-kid-bad-{}", std::process::id()));
    let messages = directory.join("BAD/messages");
    std::fs::create_dir_all(&messages).unwrap();
    std::fs::write(
        directory.join("BAD/metadata.json"),
        r#"{"message_type": {"start": 0, "stop": 8, "values": {"1": "M"}}}"#,
    )
    .unwrap();
    std::fs::write(
        messages.join("M.json"),
        r#"{"fields": {"wide": {"start": 0, "stop": 12, "type": "float"}}}"#,
    )
    .unwrap();
    let result = Decoder::load(&directory, None);
    std::fs::remove_dir_all(&directory).unwrap();
    let error = result.err().expect("a 12-bit float is an error");
    assert!(error.contains("has errors"), "{error}");
}
