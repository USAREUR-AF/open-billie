//! Every vector in tests/vectors converts as recorded, with the packs and
//! model files this kid ships, and every converted track is one the
//! translator accepts.

use std::path::{Path, PathBuf};

use billie_xf_ingest::translator::{drop_unknown_class, TRACK_CLASSES};
use goat_adapters_core::pipeline::{parse_distribution, Formats};
use serde_json::Value;

fn package() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn read(path: &Path) -> Value {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

/// The input formats this kid offers, from lookups/input-formats.json.
fn input_formats() -> Vec<String> {
    read(&package().join("lookups/input-formats.json"))["formats"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["name"].as_str().unwrap().to_owned())
        .collect()
}

fn formats() -> Formats {
    let mut names = input_formats();
    names.push("canonical-track-v2".into());
    names.sort();
    names.dedup();
    Formats::load(
        &package().join("goat-transformers/model"),
        &package().join("goat-transformers/packs"),
        Some(&names),
        parse_distribution("public"),
    )
    .unwrap()
}

/// Exact structural equality; numbers compare by value.
fn same(a: &Value, b: &Value, path: &str) {
    match (a, b) {
        (Value::Object(x), Value::Object(y)) => {
            let (kx, ky): (Vec<_>, Vec<_>) = (x.keys().collect(), y.keys().collect());
            assert_eq!(kx, ky, "{path}: keys differ");
            for (key, value) in x {
                same(value, &y[key], &format!("{path}.{key}"));
            }
        }
        (Value::Array(x), Value::Array(y)) => {
            assert_eq!(x.len(), y.len(), "{path}: lengths differ");
            for (i, (p, q)) in x.iter().zip(y).enumerate() {
                same(p, q, &format!("{path}[{i}]"));
            }
        }
        (Value::Number(x), Value::Number(y)) => assert_eq!(x.as_f64(), y.as_f64(), "{path}"),
        _ => assert_eq!(a, b, "{path}"),
    }
}

#[test]
fn every_offered_input_format_and_the_target_load_from_the_shipped_files() {
    let formats = formats();
    for name in input_formats() {
        assert!(
            formats.is_binary(&name).is_some(),
            "no pack loaded for {name}"
        );
    }
    assert_eq!(formats.is_binary("canonical-track-v2"), Some(false));
}

#[test]
fn the_offered_formats_are_the_shipped_packs() {
    let mut shipped: Vec<String> = std::fs::read_dir(package().join("goat-transformers/packs"))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    shipped.sort();
    let mut offered = input_formats();
    offered.sort();
    assert_eq!(
        offered, shipped,
        "lookups/input-formats.json and goat-transformers/packs differ"
    );
}

#[test]
fn every_vector_converts_as_recorded() {
    let formats = formats();
    let mut paths: Vec<_> = std::fs::read_dir(package().join("tests/vectors"))
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "json"))
        .collect();
    paths.sort();
    assert_eq!(paths.len(), 13, "vectors in tests/vectors");
    let offered = input_formats();
    let mut converted = 0;
    for path in paths {
        let vector = read(&path);
        let name = vector["name"].as_str().unwrap();
        let from = vector["from"].as_str().unwrap();
        assert!(
            offered.iter().any(|f| f == from),
            "{name}: {from} is not offered"
        );
        // The order the pipeline gives context: receive time, then the
        // kid's --set values. The engine keeps the first value of a key and
        // never replaces a decoded one.
        let context: Vec<(String, String)> = ["time_ms", "track.source_id", "track.generation"]
            .iter()
            .map(|k| {
                (
                    k.to_string(),
                    vector["context"][k].as_str().unwrap().to_owned(),
                )
            })
            .collect();
        let result = formats.engine().convert_text(
            from,
            "canonical-track-v2",
            vector["input"].as_str().unwrap(),
            Some(&context),
        );
        match (result, vector.get("expect"), vector.get("expectError")) {
            (Ok(text), Some(expect), None) => {
                let mut track: Value = serde_json::from_str(&text).unwrap();
                same(&track, expect, name);
                // What the translator receives.
                drop_unknown_class(&mut track);
                for key in [
                    "apiVersion",
                    "kind",
                    "trackId",
                    "sourceId",
                    "trackGeneration",
                    "observedAt",
                ] {
                    assert!(track[key].is_string(), "{name}: {key}");
                }
                assert!(track["position"]["latitudeDeg"].is_number(), "{name}");
                assert!(track["position"]["longitudeDeg"].is_number(), "{name}");
                if let Some(class) = track.get("classification") {
                    assert!(TRACK_CLASSES.contains(&class.as_str().unwrap()), "{name}");
                }
                converted += 1;
            }
            (Err(error), None, Some(kind)) => {
                assert!(
                    error.msg.starts_with(kind.as_str().unwrap()),
                    "{name}: {}",
                    error.msg
                );
            }
            (outcome, _, _) => panic!("{name}: unexpected outcome {outcome:?}"),
        }
    }
    assert_eq!(converted, 10);
}

#[test]
fn the_settings_schema_and_the_manifest_name_the_settings_the_kid_reads() {
    use billie_xf_ingest::settings::OPERATOR_SETTINGS;
    let schema = read(&package().join("schemas/xf-ingest-settings.schema.json"));
    let mut documented: Vec<&str> = schema["properties"]
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    documented.sort_unstable();
    let mut read_by_kid: Vec<&str> = OPERATOR_SETTINGS.iter().map(|(key, _)| *key).collect();
    read_by_kid.sort_unstable();
    assert_eq!(documented, read_by_kid);
    let manifest = std::fs::read_to_string(package().join("billie-kid.yaml")).unwrap();
    for key in read_by_kid {
        assert!(
            manifest.contains(&format!("    - {key}\n")),
            "billie-kid.yaml runtime.environment lacks {key}"
        );
    }
    let offered = input_formats();
    let enumerated: Vec<String> = schema["properties"]["XF_FROM_FORMAT"]["enum"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_owned())
        .collect();
    assert_eq!(enumerated, offered);
}
