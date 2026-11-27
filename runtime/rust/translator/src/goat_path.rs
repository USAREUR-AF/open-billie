//! Encoder path through the goat-transformers library.
//!
//! Built only with the cargo feature `goat-transformers` and used only for an
//! output format whose encoder selection is `goat-transformers`. A request is
//! written back out as Canonical Track v2 JSON and converted by the library
//! from the pack `canonical-track-v2` to `cot-xml`, `sapient` or
//! `asterix-cat062`.
//!
//! The pack and model definitions are embedded from `../goat-transformers/`,
//! copied from the commit the crate is pinned to, so the translator reads no
//! file at run time. `tools/sync_goat_transformers_packs.py` copies and checks
//! them.
//!
//! The record does not carry every value an output needs. The values the node
//! owns are computed by the same code the native encoders use and passed to
//! the library as conversion context. This path applies no other rule of its
//! own: what it writes beyond the context is what the packs state.

use std::sync::OnceLock;

use goat_transformers::Engine;
use serde_json::{json, Map, Value};

use crate::dispatch::{EncodeDispatchError, EncodeOptions, EncodedPayload, LibraryEncodeError};
use crate::{
    CanonicalTrack, Cat062Encoder, CotEncoder, EncoderFormat, SapientEncoder, TranslateRequest,
    TRACK_VERSION,
};

/// The goat-transformers commit the crate and the embedded definitions are from.
pub const GOAT_TRANSFORMERS_COMMIT: &str = include_str!("../goat-transformers/COMMIT");

const SOURCE_FORMAT: &str = "canonical-track-v2";

// MODEL and PACKS: every model module and pack of goat-transformers/SHA256SUMS, from build.rs.
include!(concat!(env!("OUT_DIR"), "/goat_transformers_embedded.rs"));

fn error(code: &'static str, message: impl Into<String>) -> LibraryEncodeError {
    LibraryEncodeError {
        code,
        message: message.into(),
    }
}

fn load() -> Result<Engine, String> {
    let mut engine = Engine::new();
    for (name, text) in MODEL {
        engine
            .load_model(text)
            .map_err(|e| format!("embedded goat-transformers {name}: {e}"))?;
    }
    for (name, text) in PACKS {
        engine
            .load_def(text)
            .map_err(|e| format!("embedded goat-transformers {name}: {e}"))?;
    }
    Ok(engine)
}

/// The engine with the embedded modules and packs, loaded once per process.
fn engine() -> Result<&'static Engine, LibraryEncodeError> {
    static ENGINE: OnceLock<Result<Engine, String>> = OnceLock::new();
    ENGINE
        .get_or_init(load)
        .as_ref()
        .map_err(|message| error("invalid_configuration", message.clone()))
}

/// Confirm the embedded definitions load. Run at service start, so a bad
/// definition stops the translator instead of rejecting every request.
pub(crate) fn check() -> Result<(), LibraryEncodeError> {
    engine().map(|_| ())
}

/// Encode one request through the library.
pub(crate) fn encode_request(
    request: &TranslateRequest,
    options: &EncodeOptions,
) -> Result<EncodedPayload, EncodeDispatchError> {
    let track = &request.record;
    let kid = &request.kid;
    let (target, content_type, context) = match request.format {
        EncoderFormat::Cot => {
            let encoder = CotEncoder::new(options.cot.clone());
            let (_, stale) = encoder
                .event_times(track)
                .map_err(EncodeDispatchError::Cot)?;
            (
                "cot-xml",
                "application/xml",
                vec![
                    ("track.scoped_id", track.scoped_identity(kid)),
                    ("stale_ms", stale.timestamp_millis().to_string()),
                    ("how", encoder.how().to_owned()),
                ],
            )
        }
        EncoderFormat::AsterixCat062 => {
            let (sac, sic) = Cat062Encoder::new(options.cat062.clone())
                .source_identifier(kid, &track.source_id)
                .map_err(EncodeDispatchError::Cat062)?;
            (
                "asterix-cat062",
                "application/vnd.asterix.category-062",
                vec![
                    ("cat062.sac", sac.to_string()),
                    ("cat062.sic", sic.to_string()),
                ],
            )
        }
        EncoderFormat::Sapient => {
            let encoder = SapientEncoder::new(options.sapient.clone());
            let node_id = encoder.node_id().map_err(EncodeDispatchError::Sapient)?;
            let (seconds, nanos) = encoder
                .message_time(track)
                .map_err(EncodeDispatchError::Sapient)?;
            let (report_id, object_id, scoped_identity) = encoder
                .identifiers(track, kid)
                .map_err(EncodeDispatchError::Sapient)?;
            let mut context = vec![
                ("sapient.node_id", node_id),
                ("sapient.timestamp_seconds", seconds.to_string()),
                ("sapient.detection_report_report_id", report_id),
                ("sapient.detection_report_object_id", object_id),
                ("sapient.detection_report_id", scoped_identity),
            ];
            // As the native encoder: no nanos member for a whole second.
            if nanos != 0 {
                context.push(("sapient.timestamp_nanos", nanos.to_string()));
            }
            ("sapient", "application/vnd.sapient.protobuf", context)
        }
    };
    let context: Vec<(String, String)> = context
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value))
        .collect();
    let output = engine()
        .map_err(EncodeDispatchError::Library)?
        .convert_text(
            SOURCE_FORMAT,
            target,
            &canonical_track_json(track),
            Some(&context),
        )
        .map_err(|e| {
            EncodeDispatchError::Library(error("library_conversion_failed", e.to_string()))
        })?;
    let bytes = match request.format {
        EncoderFormat::Cot => output.into_bytes(),
        // The library writes binary formats as hex text.
        EncoderFormat::AsterixCat062 | EncoderFormat::Sapient => {
            unhex(&output).map_err(EncodeDispatchError::Library)?
        }
    };
    Ok(EncodedPayload {
        kid: request.kid.clone(),
        output_name: request.output_name.clone(),
        format: request.format,
        content_type,
        bytes,
    })
}

fn unhex(hex: &str) -> Result<Vec<u8>, LibraryEncodeError> {
    let hex = hex.trim().as_bytes();
    if hex.len() % 2 != 0 {
        return Err(error(
            "library_output_invalid",
            "odd-length hex from the library",
        ));
    }
    hex.chunks(2)
        .map(|pair| {
            std::str::from_utf8(pair)
                .ok()
                .and_then(|s| u8::from_str_radix(s, 16).ok())
                .ok_or_else(|| error("library_output_invalid", "non-hex output from the library"))
        })
        .collect()
}

/// The Canonical Track v2 JSON object for a parsed record, member for member.
///
/// `coasting` and `finalUpdate` are written as parsed: the request parser
/// turns an absent member into `false`, so the record no longer says which.
fn canonical_track_json(track: &CanonicalTrack) -> String {
    let mut root = Map::new();
    root.insert("apiVersion".into(), json!(TRACK_VERSION));
    root.insert("kind".into(), json!("Track"));
    root.insert("trackId".into(), json!(track.track_id));
    root.insert("sourceId".into(), json!(track.source_id));
    root.insert("trackGeneration".into(), json!(track.track_generation));
    root.insert("observedAt".into(), json!(track.observed_at));
    root.insert("testData".into(), json!(track.test_data));
    root.insert("headerSimulated".into(), json!(track.header_simulated));
    root.insert("simulated".into(), json!(track.simulated));
    if let Some(confirmed) = track.confirmed {
        root.insert("confirmed".into(), json!(confirmed));
    }
    root.insert("coasting".into(), json!(track.coasting));
    root.insert("finalUpdate".into(), json!(track.final_update));

    let mut position = Map::new();
    position.insert("latitudeDeg".into(), json!(track.position.latitude_deg));
    position.insert("longitudeDeg".into(), json!(track.position.longitude_deg));
    if let Some(altitude) = track.position.altitude_m {
        position.insert("altitudeM".into(), json!(altitude));
    }
    root.insert("position".into(), Value::Object(position));

    if let Some(velocity) = track.velocity {
        let mut v = Map::new();
        v.insert("eastMps".into(), json!(velocity.east_mps));
        v.insert("northMps".into(), json!(velocity.north_mps));
        if let Some(up) = velocity.up_mps {
            v.insert("upMps".into(), json!(up));
        }
        root.insert("velocity".into(), Value::Object(v));
    }
    if let Some(class) = track.classification {
        root.insert("classification".into(), json!(class.as_str()));
    }
    if let Some(confidence) = track.confidence {
        root.insert("confidence".into(), json!(confidence));
    }
    if let Some(uncertainty) = track.position_uncertainty {
        let mut u = Map::new();
        if let Some(sigma) = uncertainty.sigma_east_m {
            u.insert("sigmaEastM".into(), json!(sigma));
        }
        if let Some(sigma) = uncertainty.sigma_north_m {
            u.insert("sigmaNorthM".into(), json!(sigma));
        }
        if let Some(sigma) = uncertainty.sigma_up_m {
            u.insert("sigmaUpM".into(), json!(sigma));
        }
        root.insert("positionUncertainty".into(), Value::Object(u));
    }
    if !track.identifiers.is_empty() {
        let identifiers: Vec<Value> = track
            .identifiers
            .iter()
            .map(|id| json!({"scheme": id.scheme, "value": id.value}))
            .collect();
        root.insert("identifiers".into(), Value::Array(identifiers));
    }
    Value::Object(root).to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::dispatch::{encode_request as dispatch, EncoderPath, EncoderSelection};
    use crate::parse_request;

    fn request_for(format: &str) -> TranslateRequest {
        let mut input: Value = serde_json::from_str(include_str!(
            "../../../../schemas/examples/oetf-translation-request.json"
        ))
        .unwrap();
        input["target"]["format"] = json!(format);
        input["record"]["confirmed"] = json!(true);
        parse_request(&input).unwrap()
    }

    fn library_for_every_format() -> EncodeOptions {
        EncodeOptions {
            cat062: crate::Cat062Options {
                default_source: Some(crate::Cat062SourceIdentifier { sac: 4, sic: 22 }),
                sources: Default::default(),
            },
            encoders: EncoderSelection {
                cot: EncoderPath::GoatTransformers,
                cat062: EncoderPath::GoatTransformers,
                sapient: EncoderPath::GoatTransformers,
            },
            ..EncodeOptions::default()
        }
    }

    #[test]
    fn embedded_definitions_load_and_name_their_commit() {
        check().unwrap();
        let commit = GOAT_TRANSFORMERS_COMMIT.trim();
        assert_eq!(commit.len(), 40);
        assert!(commit.bytes().all(|b| b.is_ascii_hexdigit()));
        EncoderSelection::from_lookup(|_| Some("goat-transformers".to_owned())).unwrap();
    }

    #[test]
    fn selected_formats_are_encoded_by_the_library_with_node_values_as_context() {
        let options = library_for_every_format();
        let cot = dispatch(&request_for("cot"), &options).unwrap();
        assert_eq!(cot.content_type, "application/xml");
        let xml = String::from_utf8(cot.bytes).unwrap();
        assert!(xml.contains("uid=\"oetf/263/311/fixture-1\""), "{xml}");
        assert!(xml.contains("how=\"m-p\""), "{xml}");
        assert!(xml.contains("stale=\""), "{xml}");

        let cat062 = dispatch(&request_for("asterix-cat062"), &options).unwrap();
        assert_eq!(cat062.content_type, "application/vnd.asterix.category-062");
        assert_eq!(cat062.bytes[0], 62);
        assert_eq!(&cat062.bytes[6..8], &[4, 22]);
    }

    #[test]
    fn node_configuration_errors_are_the_native_errors() {
        let options = EncodeOptions {
            encoders: library_for_every_format().encoders,
            ..EncodeOptions::default()
        };
        assert!(matches!(
            dispatch(&request_for("asterix-cat062"), &options).unwrap_err(),
            EncodeDispatchError::Cat062(error) if error.code == "missing_source_identifier"
        ));
        let options = EncodeOptions {
            sapient: crate::SapientOptions {
                node_id: String::new(),
                object_id_store: std::env::temp_dir().join("billie-goat-path-unused.json"),
            },
            ..options
        };
        assert!(matches!(
            dispatch(&request_for("sapient"), &options).unwrap_err(),
            EncodeDispatchError::Sapient(error) if error.code == "invalid_configuration"
        ));
    }

    #[test]
    fn a_format_left_native_is_not_touched_by_the_selection_of_another() {
        let mut options = library_for_every_format();
        options.encoders.cot = EncoderPath::Native;
        let native = dispatch(&request_for("cot"), &EncodeOptions::default()).unwrap();
        assert_eq!(dispatch(&request_for("cot"), &options).unwrap(), native);
    }
}
