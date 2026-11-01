use serde_json::{Map, Value};
use std::fmt;

use crate::{API_VERSION, TRACK_VERSION};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum EncoderFormat {
    Cot,
    AsterixCat062,
    Sapient,
}

impl EncoderFormat {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Cot => "cot",
            Self::AsterixCat062 => "asterix-cat062",
            Self::Sapient => "sapient",
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct TranslateRequest {
    pub request_id: String,
    pub kid: String,
    pub format: EncoderFormat,
    pub output_name: String,
    pub profile: Option<String>,
    pub record: CanonicalTrack,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CanonicalTrack {
    pub track_id: String,
    pub source_id: String,
    pub track_generation: String,
    pub observed_at: String,
    pub position: Position,
    pub velocity: Option<Velocity>,
    pub classification: Option<Classification>,
    pub confidence: Option<f64>,
    pub position_uncertainty: Option<PositionUncertainty>,
    pub identifiers: Vec<Identifier>,
    pub test_data: bool,
    pub header_simulated: bool,
    pub simulated: bool,
    pub confirmed: Option<bool>,
    pub coasting: bool,
    pub final_update: bool,
}

impl CanonicalTrack {
    /// Stable identity for one track lifetime within its authenticated kid and source.
    pub fn scoped_identity(&self, kid: &str) -> String {
        [
            kid,
            self.source_id.as_str(),
            self.track_id.as_str(),
            self.track_generation.as_str(),
        ]
        .into_iter()
        .map(escape_identity_component)
        .collect::<Vec<_>>()
        .join("/")
    }
}

fn escape_identity_component(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.') {
            escaped.push(char::from(byte));
        } else {
            escaped.push('%');
            escaped.push(char::from(b"0123456789ABCDEF"[(byte >> 4) as usize]));
            escaped.push(char::from(b"0123456789ABCDEF"[(byte & 0x0f) as usize]));
        }
    }
    escaped
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Position {
    pub latitude_deg: f64,
    pub longitude_deg: f64,
    pub altitude_m: Option<f64>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Velocity {
    pub east_mps: f64,
    pub north_mps: f64,
    pub up_mps: Option<f64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Classification {
    Unknown,
    FixedWingAircraft,
    RotaryWingAircraft,
    Uas,
    Balloon,
    Bird,
    Vehicle,
    Clutter,
    Other,
}

impl Classification {
    fn parse(value: &str) -> Option<Self> {
        Some(match value {
            "unknown" => Self::Unknown,
            "fixed-wing-aircraft" => Self::FixedWingAircraft,
            "rotary-wing-aircraft" => Self::RotaryWingAircraft,
            "uas" => Self::Uas,
            "balloon" => Self::Balloon,
            "bird" => Self::Bird,
            "vehicle" => Self::Vehicle,
            "clutter" => Self::Clutter,
            "other" => Self::Other,
            _ => return None,
        })
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::FixedWingAircraft => "fixed-wing-aircraft",
            Self::RotaryWingAircraft => "rotary-wing-aircraft",
            Self::Uas => "uas",
            Self::Balloon => "balloon",
            Self::Bird => "bird",
            Self::Vehicle => "vehicle",
            Self::Clutter => "clutter",
            Self::Other => "other",
        }
    }

    /// Return the CoT type code for this canonical category.
    pub fn cot_type(self) -> &'static str {
        match self {
            Self::FixedWingAircraft => "a-u-A-M-F",
            Self::RotaryWingAircraft => "a-u-A-M-H",
            Self::Uas => "a-u-A-M-F-Q",
            Self::Balloon => "a-u-A-M-L",
            Self::Bird => "a-u-A",
            Self::Vehicle => "a-u-G-E-V",
            Self::Unknown | Self::Clutter | Self::Other => "a-u-X",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PositionUncertainty {
    pub sigma_east_m: Option<f64>,
    pub sigma_north_m: Option<f64>,
    pub sigma_up_m: Option<f64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Identifier {
    pub scheme: String,
    pub value: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContractError {
    pub code: &'static str,
    pub path: String,
    pub message: String,
}

impl fmt::Display for ContractError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} at {}: {}", self.code, self.path, self.message)
    }
}

impl std::error::Error for ContractError {}

fn invalid(
    code: &'static str,
    path: impl Into<String>,
    message: impl Into<String>,
) -> ContractError {
    ContractError {
        code,
        path: path.into(),
        message: message.into(),
    }
}

fn object<'a>(value: &'a Value, path: &str) -> Result<&'a Map<String, Value>, ContractError> {
    value
        .as_object()
        .ok_or_else(|| invalid("invalid_type", path, "expected an object"))
}

fn check_keys(obj: &Map<String, Value>, allowed: &[&str], path: &str) -> Result<(), ContractError> {
    if let Some(key) = obj.keys().find(|key| !allowed.contains(&key.as_str())) {
        return Err(invalid(
            "unknown_field",
            format!("{path}.{key}"),
            "field is not allowed by this contract version",
        ));
    }
    Ok(())
}

fn required<'a>(
    obj: &'a Map<String, Value>,
    key: &str,
    path: &str,
) -> Result<&'a Value, ContractError> {
    obj.get(key).ok_or_else(|| {
        invalid(
            "missing_required_field",
            format!("{path}.{key}"),
            "required field is missing",
        )
    })
}

fn string(value: &Value, path: &str, max: usize) -> Result<String, ContractError> {
    let s = value
        .as_str()
        .ok_or_else(|| invalid("invalid_type", path, "expected a string"))?;
    if s.is_empty() || s.len() > max {
        return Err(invalid(
            "invalid_value",
            path,
            format!("string length must be 1..={max}"),
        ));
    }
    Ok(s.to_owned())
}

fn required_string(
    obj: &Map<String, Value>,
    key: &str,
    path: &str,
    max: usize,
) -> Result<String, ContractError> {
    string(required(obj, key, path)?, &format!("{path}.{key}"), max)
}

fn number(value: &Value, path: &str) -> Result<f64, ContractError> {
    value
        .as_f64()
        .filter(|n| n.is_finite())
        .ok_or_else(|| invalid("invalid_number", path, "expected a finite JSON number"))
}

fn optional_number(
    obj: &Map<String, Value>,
    key: &str,
    path: &str,
) -> Result<Option<f64>, ContractError> {
    obj.get(key)
        .map(|v| number(v, &format!("{path}.{key}")))
        .transpose()
}

fn nonnegative(value: f64, path: &str) -> Result<f64, ContractError> {
    if value < 0.0 {
        Err(invalid("out_of_range", path, "value must be non-negative"))
    } else {
        Ok(value)
    }
}

/// Validate and parse one request according to translation-request-v1 and canonical-track-v2.
pub fn parse_request(value: &Value) -> Result<TranslateRequest, ContractError> {
    let root = object(value, "$")?;
    check_keys(
        root,
        &["apiVersion", "kind", "requestId", "kid", "target", "record"],
        "$",
    )?;
    if required_string(root, "apiVersion", "$", 64)? != API_VERSION {
        return Err(invalid(
            "unsupported_api_version",
            "$.apiVersion",
            "expected billie.dev/translation-v1",
        ));
    }
    if required_string(root, "kind", "$", 64)? != "TranslateRequest" {
        return Err(invalid(
            "invalid_kind",
            "$.kind",
            "expected TranslateRequest",
        ));
    }
    let request_id = required_string(root, "requestId", "$", 128)?;
    let kid = required_string(root, "kid", "$", 63)?;
    if !valid_kid(&kid) {
        return Err(invalid(
            "invalid_value",
            "$.kid",
            "kid ID must use lowercase letters, digits, and hyphens",
        ));
    }

    let target_path = "$.target";
    let target = object(required(root, "target", "$")?, target_path)?;
    check_keys(target, &["outputName", "format", "profile"], target_path)?;
    let output_name = required_string(target, "outputName", target_path, 32)?;
    if !valid_output_name(&output_name) {
        return Err(invalid(
            "invalid_value",
            "$.target.outputName",
            "output name must use lowercase letters, digits, and hyphens and start with a letter",
        ));
    }
    let format_text = required_string(target, "format", target_path, 32)?;
    let format = match format_text.as_str() {
        "cot" => EncoderFormat::Cot,
        "asterix-cat062" => EncoderFormat::AsterixCat062,
        "sapient" => EncoderFormat::Sapient,
        _ => {
            return Err(invalid(
                "unsupported_format",
                "$.target.format",
                "supported formats are cot, asterix-cat062, and sapient",
            ))
        }
    };
    let profile = target
        .get("profile")
        .map(|v| string(v, "$.target.profile", 128))
        .transpose()?;

    let record_path = "$.record";
    let record = parse_track(required(root, "record", "$")?, record_path)?;
    Ok(TranslateRequest {
        request_id,
        kid,
        format,
        output_name,
        profile,
        record,
    })
}

fn parse_track(value: &Value, path: &str) -> Result<CanonicalTrack, ContractError> {
    let obj = object(value, path)?;
    check_keys(
        obj,
        &[
            "apiVersion",
            "kind",
            "trackId",
            "sourceId",
            "trackGeneration",
            "observedAt",
            "position",
            "velocity",
            "classification",
            "confidence",
            "positionUncertainty",
            "identifiers",
            "testData",
            "headerSimulated",
            "simulated",
            "confirmed",
            "coasting",
            "finalUpdate",
        ],
        path,
    )?;
    if required_string(obj, "apiVersion", path, 64)? != TRACK_VERSION {
        return Err(invalid(
            "unsupported_record_version",
            format!("{path}.apiVersion"),
            "expected billie.dev/track-v2",
        ));
    }
    if required_string(obj, "kind", path, 32)? != "Track" {
        return Err(invalid(
            "invalid_kind",
            format!("{path}.kind"),
            "expected Track",
        ));
    }
    let track_id = required_string(obj, "trackId", path, 128)?;
    let source_id = required_string(obj, "sourceId", path, 128)?;
    let track_generation = required_string(obj, "trackGeneration", path, 128)?;
    let observed_at = required_string(obj, "observedAt", path, 64)?;
    if !valid_rfc3339(&observed_at) {
        return Err(invalid(
            "invalid_timestamp",
            format!("{path}.observedAt"),
            "expected an RFC 3339 date-time",
        ));
    }
    let position_path = format!("{path}.position");
    let position_obj = object(required(obj, "position", path)?, &position_path)?;
    check_keys(
        position_obj,
        &["latitudeDeg", "longitudeDeg", "altitudeM"],
        &position_path,
    )?;
    let lat = number(
        required(position_obj, "latitudeDeg", &position_path)?,
        &format!("{position_path}.latitudeDeg"),
    )?;
    if !(-90.0..=90.0).contains(&lat) {
        return Err(invalid(
            "out_of_range",
            format!("{position_path}.latitudeDeg"),
            "latitude must be in [-90,90] degrees",
        ));
    }
    let lon = number(
        required(position_obj, "longitudeDeg", &position_path)?,
        &format!("{position_path}.longitudeDeg"),
    )?;
    if !(-180.0..=180.0).contains(&lon) {
        return Err(invalid(
            "out_of_range",
            format!("{position_path}.longitudeDeg"),
            "longitude must be in [-180,180] degrees",
        ));
    }
    let position = Position {
        latitude_deg: lat,
        longitude_deg: lon,
        altitude_m: optional_number(position_obj, "altitudeM", &position_path)?,
    };

    let velocity = if let Some(value) = obj.get("velocity") {
        let velocity_path = format!("{path}.velocity");
        let v = object(value, &velocity_path)?;
        check_keys(v, &["eastMps", "northMps", "upMps"], &velocity_path)?;
        let east = number(
            required(v, "eastMps", &velocity_path)?,
            &format!("{velocity_path}.eastMps"),
        )?;
        let north = number(
            required(v, "northMps", &velocity_path)?,
            &format!("{velocity_path}.northMps"),
        )?;
        Some(Velocity {
            east_mps: east,
            north_mps: north,
            up_mps: optional_number(v, "upMps", &velocity_path)?,
        })
    } else {
        None
    };

    let classification = if let Some(value) = obj.get("classification") {
        let p = format!("{path}.classification");
        let category = string(value, &p, 64)?;
        Some(Classification::parse(&category).ok_or_else(|| {
            invalid(
                "unsupported_classification",
                &p,
                "category is not in the Billie track-class v1 vocabulary",
            )
        })?)
    } else {
        None
    };

    let confidence = optional_number(obj, "confidence", path)?;
    if confidence.is_some_and(|n| !(0.0..=1.0).contains(&n)) {
        return Err(invalid(
            "out_of_range",
            format!("{path}.confidence"),
            "confidence must be in [0,1]",
        ));
    }

    let position_uncertainty = if let Some(value) = obj.get("positionUncertainty") {
        let p = format!("{path}.positionUncertainty");
        let u = object(value, &p)?;
        check_keys(u, &["sigmaEastM", "sigmaNorthM", "sigmaUpM"], &p)?;
        if u.is_empty() {
            return Err(invalid(
                "invalid_value",
                &p,
                "at least one uncertainty axis is required",
            ));
        }
        let east = optional_number(u, "sigmaEastM", &p)?
            .map(|n| nonnegative(n, &format!("{p}.sigmaEastM")))
            .transpose()?;
        let north = optional_number(u, "sigmaNorthM", &p)?
            .map(|n| nonnegative(n, &format!("{p}.sigmaNorthM")))
            .transpose()?;
        let up = optional_number(u, "sigmaUpM", &p)?
            .map(|n| nonnegative(n, &format!("{p}.sigmaUpM")))
            .transpose()?;
        Some(PositionUncertainty {
            sigma_east_m: east,
            sigma_north_m: north,
            sigma_up_m: up,
        })
    } else {
        None
    };

    let identifiers = if let Some(value) = obj.get("identifiers") {
        let array = value.as_array().ok_or_else(|| {
            invalid(
                "invalid_type",
                format!("{path}.identifiers"),
                "expected an array",
            )
        })?;
        array
            .iter()
            .enumerate()
            .map(|(index, item)| {
                let p = format!("{path}.identifiers[{index}]");
                let id = object(item, &p)?;
                check_keys(id, &["scheme", "value"], &p)?;
                Ok(Identifier {
                    scheme: required_string(id, "scheme", &p, 256)?,
                    value: required_string(id, "value", &p, 256)?,
                })
            })
            .collect::<Result<Vec<_>, ContractError>>()?
    } else {
        Vec::new()
    };

    Ok(CanonicalTrack {
        track_id,
        source_id,
        track_generation,
        observed_at,
        position,
        velocity,
        classification,
        confidence,
        position_uncertainty,
        identifiers,
        test_data: optional_bool(obj, "testData", path)?.unwrap_or(false),
        header_simulated: optional_bool(obj, "headerSimulated", path)?.unwrap_or(false),
        simulated: optional_bool(obj, "simulated", path)?.unwrap_or(false),
        confirmed: optional_bool(obj, "confirmed", path)?,
        coasting: optional_bool(obj, "coasting", path)?.unwrap_or(false),
        final_update: optional_bool(obj, "finalUpdate", path)?.unwrap_or(false),
    })
}

fn optional_bool(
    obj: &Map<String, Value>,
    key: &str,
    path: &str,
) -> Result<Option<bool>, ContractError> {
    obj.get(key)
        .map(|value| {
            value.as_bool().ok_or_else(|| {
                invalid(
                    "invalid_type",
                    format!("{path}.{key}"),
                    "expected a boolean",
                )
            })
        })
        .transpose()
}

fn valid_kid(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 63
        && (s.as_bytes()[0].is_ascii_lowercase() || s.as_bytes()[0].is_ascii_digit())
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

fn valid_output_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 32
        && s.as_bytes()[0].is_ascii_lowercase()
        && s.bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

fn digits(s: &str, start: usize, end: usize) -> Option<u32> {
    let bytes = s.as_bytes().get(start..end)?;
    if !bytes.iter().all(u8::is_ascii_digit) {
        return None;
    }
    std::str::from_utf8(bytes).ok()?.parse().ok()
}

fn valid_rfc3339(s: &str) -> bool {
    let bytes = s.as_bytes();
    if bytes.len() < 20
        || !matches!(bytes.get(4), Some(b'-'))
        || !matches!(bytes.get(7), Some(b'-'))
        || !matches!(bytes.get(10), Some(b'T' | b't'))
    {
        return false;
    }
    if !matches!(bytes.get(13), Some(b':')) || !matches!(bytes.get(16), Some(b':')) {
        return false;
    }
    let (Some(year), Some(month), Some(day), Some(hour), Some(minute), Some(second)) = (
        digits(s, 0, 4),
        digits(s, 5, 7),
        digits(s, 8, 10),
        digits(s, 11, 13),
        digits(s, 14, 16),
        digits(s, 17, 19),
    ) else {
        return false;
    };
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let month_days = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => return false,
    };
    if day == 0 || day > month_days || hour > 23 || minute > 59 || second > 60 {
        return false;
    }
    let mut i = 19;
    if bytes.get(i) == Some(&b'.') {
        i += 1;
        let start = i;
        while bytes.get(i).is_some_and(u8::is_ascii_digit) {
            i += 1;
        }
        if i == start {
            return false;
        }
    }
    match bytes.get(i) {
        Some(b'Z' | b'z') => i + 1 == bytes.len(),
        Some(b'+' | b'-') if i + 6 == bytes.len() && bytes.get(i + 3) == Some(&b':') => {
            let Some(oh) = digits(s, i + 1, i + 3) else {
                return false;
            };
            let Some(om) = digits(s, i + 4, i + 6) else {
                return false;
            };
            oh <= 23 && om <= 59
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn valid() -> Value {
        json!({
            "apiVersion":"billie.dev/translation-v1", "kind":"TranslateRequest", "requestId":"test-1", "kid":"oetf",
            "target":{"outputName":"tracks-cot","format":"cot"},
            "record":{
                "apiVersion":"billie.dev/track-v2", "kind":"Track", "trackId":"311", "sourceId":"sensor-a", "trackGeneration":"generation-1", "observedAt":"2025-10-29T12:00:00.123Z",
                "position":{"latitudeDeg":38.8977,"longitudeDeg":-77.0365,"altitudeM":152.4},
                "velocity":{"eastMps":-12.5,"northMps":4.25,"upMps":1.5},
                "classification":"uas", "confidence":0.87,
                "positionUncertainty":{"sigmaEastM":3.2,"sigmaNorthM":2.8,"sigmaUpM":6.1}
            }
        })
    }

    #[test]
    fn parses_canonical_track_and_output_format() {
        let parsed = parse_request(&valid()).unwrap();
        assert_eq!(parsed.format, EncoderFormat::Cot);
        assert_eq!(parsed.output_name, "tracks-cot");
        assert_eq!(parsed.record.track_id, "311");
        assert_eq!(parsed.record.source_id, "sensor-a");
        assert_eq!(parsed.record.track_generation, "generation-1");
        assert_eq!(parsed.record.velocity.unwrap().east_mps, -12.5);
    }

    #[test]
    fn scoped_identity_separates_kids_sources_reused_ids_and_delimiters() {
        let mut input = valid();
        let record = parse_request(&input).unwrap().record;
        assert_eq!(
            record.scoped_identity("oetf"),
            "oetf/sensor-a/311/generation-1"
        );
        input["record"]["sourceId"] = json!("sensor/b");
        assert_eq!(
            parse_request(&input)
                .unwrap()
                .record
                .scoped_identity("oetf"),
            "oetf/sensor%2Fb/311/generation-1"
        );
        input["record"]["sourceId"] = json!("sensor-a");
        input["record"]["trackGeneration"] = json!("generation-2");
        assert_eq!(
            parse_request(&input)
                .unwrap()
                .record
                .scoped_identity("oetf"),
            "oetf/sensor-a/311/generation-2"
        );
        assert_eq!(
            record.scoped_identity("other-kid"),
            "other-kid/sensor-a/311/generation-1"
        );
    }

    #[test]
    fn requires_nonempty_source_and_generation_identity_fields() {
        let mut input = valid();
        input["record"].as_object_mut().unwrap().remove("sourceId");
        assert_eq!(
            parse_request(&input).unwrap_err().code,
            "missing_required_field"
        );
        input = valid();
        input["record"]["trackGeneration"] = json!("");
        assert_eq!(parse_request(&input).unwrap_err().code, "invalid_value");
    }

    #[test]
    fn parses_optional_track_status_flags_and_rejects_non_boolean_values() {
        let mut input = valid();
        input["record"]["testData"] = json!(true);
        input["record"]["headerSimulated"] = json!(true);
        input["record"]["simulated"] = json!(true);
        input["record"]["confirmed"] = json!(false);
        input["record"]["coasting"] = json!(true);
        input["record"]["finalUpdate"] = json!(true);
        let record = parse_request(&input).unwrap().record;
        assert!(record.test_data && record.header_simulated && record.simulated);
        assert_eq!(record.confirmed, Some(false));
        assert!(record.coasting && record.final_update);
        input["record"]["coasting"] = json!("yes");
        let error = parse_request(&input).unwrap_err();
        assert_eq!(error.code, "invalid_type");
        assert_eq!(error.path, "$.record.coasting");
    }

    #[test]
    fn translates_canonical_classes_to_cot_codes() {
        assert_eq!(Classification::Uas.cot_type(), "a-u-A-M-F-Q");
        assert_eq!(Classification::Bird.cot_type(), "a-u-A");
        assert_eq!(Classification::Other.cot_type(), "a-u-X");
    }

    #[test]
    fn rejects_unknown_canonical_class() {
        let mut input = valid();
        input["record"]["classification"] = json!("oetf-small-uas");
        assert_eq!(
            parse_request(&input).unwrap_err().code,
            "unsupported_classification"
        );
    }

    #[test]
    fn rejects_invalid_logical_output_name() {
        let mut input = valid();
        input["target"]["outputName"] = json!("fabric/vendor/track");
        let error = parse_request(&input).unwrap_err();
        assert_eq!(error.code, "invalid_value");
        assert_eq!(error.path, "$.target.outputName");
    }

    #[test]
    fn rejects_out_of_range_coordinates() {
        let mut input = valid();
        input["record"]["position"]["latitudeDeg"] = json!(91.0);
        let error = parse_request(&input).unwrap_err();
        assert_eq!(error.code, "out_of_range");
        assert_eq!(error.path, "$.record.position.latitudeDeg");
    }

    #[test]
    fn rejects_zenoh_routing_in_kid_request() {
        let mut input = valid();
        input["target"]["zenohKey"] = json!("unauthorized/topic");
        assert_eq!(parse_request(&input).unwrap_err().code, "unknown_field");
    }

    #[test]
    fn rejects_bad_timestamp_and_missing_position() {
        let mut input = valid();
        input["record"]["observedAt"] = json!("not-a-time");
        assert_eq!(parse_request(&input).unwrap_err().code, "invalid_timestamp");
        let mut input = valid();
        input["record"].as_object_mut().unwrap().remove("position");
        assert_eq!(
            parse_request(&input).unwrap_err().code,
            "missing_required_field"
        );
    }

    #[test]
    fn supports_each_registered_format_selector() {
        for (name, expected) in [
            ("cot", EncoderFormat::Cot),
            ("asterix-cat062", EncoderFormat::AsterixCat062),
            ("sapient", EncoderFormat::Sapient),
        ] {
            let mut input = valid();
            input["target"]["format"] = json!(name);
            assert_eq!(parse_request(&input).unwrap().format, expected);
        }
    }
}
