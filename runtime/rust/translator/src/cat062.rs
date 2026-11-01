use chrono::{DateTime, Timelike, Utc};
use std::collections::HashMap;

use crate::CanonicalTrack;

const CATEGORY: u8 = 62;
const LAT_LON_SCALE: f64 = 33_554_432.0 / 180.0;
const GEOMETRIC_ALTITUDE_LSB_M: f64 = 1.905;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Cat062Options {
    /// System Area Code configured for this node.
    pub sac: u8,
    /// System Identification Code configured for this node.
    pub sic: u8,
    /// Optional per-kid, per-source I062/010 assignments.
    pub sources: HashMap<(String, String), Cat062SourceIdentifier>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct Cat062SourceIdentifier {
    pub sac: u8,
    pub sic: u8,
}

/// Parse the operator-maintained JSON source-ID file. Duplicate SAC/SIC pairs
/// are rejected because they would not disambiguate overlapping track numbers.
pub fn parse_source_identifiers_json(
    contents: &str,
) -> Result<HashMap<(String, String), Cat062SourceIdentifier>, String> {
    let root: serde_json::Value = serde_json::from_str(contents)
        .map_err(|error| format!("invalid CAT062 source map JSON: {error}"))?;
    let root = root
        .as_object()
        .ok_or_else(|| "CAT062 source map must be a JSON object".to_owned())?;
    if root.keys().any(|key| key != "kids" && key != "sources") {
        return Err("CAT062 source map accepts only the 'kids' property".to_owned());
    }
    if root.contains_key("sources") && root.contains_key("kids") {
        return Err(
            "CAT062 source map cannot mix legacy 'sources' and scoped 'kids' properties".to_owned(),
        );
    }
    // Platform releases before 0.3.0 stored source assignments globally.
    // Preserve that behavior as a fallback so an upgrade cannot prevent the
    // translator from starting; operators can move the map to a kid scope.
    if root.contains_key("sources") && !root.contains_key("kids") {
        let sources = root["sources"]
            .as_object()
            .ok_or_else(|| "legacy CAT062 source map 'sources' must be an object".to_owned())?;
        let mut assignments = HashMap::new();
        let mut used_pairs = HashMap::new();
        for (source_id, value) in sources {
            if source_id.trim().is_empty() || source_id.len() > 128 {
                return Err("CAT062 source IDs must contain 1 to 128 characters".to_owned());
            }
            let fields = value.as_object().ok_or_else(|| {
                format!("legacy CAT062 source '{source_id}' must contain sac and sic")
            })?;
            if fields.len() != 2 || fields.keys().any(|key| key != "sac" && key != "sic") {
                return Err(format!(
                    "legacy CAT062 source '{source_id}' accepts only sac and sic"
                ));
            }
            let read_code = |key: &str| -> Result<u8, String> {
                fields.get(key).and_then(serde_json::Value::as_u64)
                    .and_then(|code| u8::try_from(code).ok())
                    .ok_or_else(|| format!("legacy CAT062 source '{source_id}' {key} must be an integer from 0 to 255"))
            };
            let assignment = Cat062SourceIdentifier {
                sac: read_code("sac")?,
                sic: read_code("sic")?,
            };
            if used_pairs
                .insert((assignment.sac, assignment.sic), source_id)
                .is_some()
            {
                return Err(format!(
                    "legacy CAT062 map assigns duplicate SAC/SIC {}/{}",
                    assignment.sac, assignment.sic
                ));
            }
            assignments.insert(("*".to_owned(), source_id.clone()), assignment);
        }
        return Ok(assignments);
    }
    let kids = root
        .get("kids")
        .and_then(serde_json::Value::as_object)
        .ok_or_else(|| "CAT062 source map requires an object property named 'kids'".to_owned())?;
    let mut assignments = HashMap::new();
    let mut used_pairs = HashMap::new();
    for (kid, kid_value) in kids {
        if kid != "*" && (kid.is_empty() || kid.len() > 63 || !valid_kid_id(kid)) {
            return Err("CAT062 kid IDs must use lowercase letters, digits, and hyphens; 1 to 63 characters".to_owned());
        }
        let kid_fields = kid_value
            .as_object()
            .ok_or_else(|| format!("CAT062 kid '{kid}' must contain a sources object"))?;
        if kid_fields.len() != 1 || !kid_fields.contains_key("sources") {
            return Err(format!(
                "CAT062 kid '{kid}' accepts only a 'sources' property"
            ));
        }
        let sources = kid_fields["sources"]
            .as_object()
            .ok_or_else(|| format!("CAT062 kid '{kid}' sources must be an object"))?;
        for (source_id, value) in sources {
            if source_id.trim().is_empty() || source_id.len() > 128 {
                return Err("CAT062 source IDs must contain 1 to 128 characters".to_owned());
            }
            let fields = value.as_object().ok_or_else(|| {
                format!("CAT062 source '{kid}/{source_id}' must map to an object with sac and sic")
            })?;
            if fields.len() != 2 || fields.keys().any(|key| key != "sac" && key != "sic") {
                return Err(format!(
                    "CAT062 source '{kid}/{source_id}' accepts only sac and sic"
                ));
            }
            let read_code = |key: &str| -> Result<u8, String> {
                fields.get(key).and_then(serde_json::Value::as_u64).and_then(|code| u8::try_from(code).ok())
                    .ok_or_else(|| format!("CAT062 source '{kid}/{source_id}' {key} must be an integer from 0 to 255"))
            };
            let assignment = Cat062SourceIdentifier {
                sac: read_code("sac")?,
                sic: read_code("sic")?,
            };
            if let Some(previous) = used_pairs.insert(
                (assignment.sac, assignment.sic),
                format!("{kid}/{source_id}"),
            ) {
                return Err(format!(
                    "CAT062 sources '{previous}' and '{kid}/{source_id}' share SAC/SIC {}/{}",
                    assignment.sac, assignment.sic
                ));
            }
            assignments.insert((kid.clone(), source_id.clone()), assignment);
        }
    }
    Ok(assignments)
}

fn valid_kid_id(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes
        .first()
        .is_some_and(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        && bytes
            .iter()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || *byte == b'-')
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Cat062Encoder {
    options: Cat062Options,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Cat062EncodeError {
    pub code: &'static str,
    pub message: String,
}

impl Cat062Encoder {
    pub fn new(options: Cat062Options) -> Self {
        Self { options }
    }

    /// Encode one ASTERIX Category 062 Edition 1.21 block containing one track record.
    pub fn encode_for_kid(
        &self,
        track: &CanonicalTrack,
        kid: &str,
    ) -> Result<Vec<u8>, Cat062EncodeError> {
        let confirmed = track.confirmed.ok_or_else(|| Cat062EncodeError {
            code: "unknown_confirmation",
            message: "CAT062 I062/080 requires an explicit confirmation state".to_owned(),
        })?;
        let (sac, sic) = self.source_identifier(kid, &track.source_id)?;
        let track_number = track
            .track_id
            .parse::<u16>()
            .map_err(|_| Cat062EncodeError {
                code: "invalid_track_number",
                message: "CAT062 I062/040 requires a decimal trackId in 0..=4095".to_owned(),
            })?;
        if track_number > 4095 {
            return Err(Cat062EncodeError {
                code: "invalid_track_number",
                message: "CAT062 I062/040 trackId must be in 0..=4095".to_owned(),
            });
        }
        if track.position.longitude_deg >= 180.0 {
            return Err(Cat062EncodeError {
                code: "out_of_range",
                message: "CAT062 I062/105 longitude must be less than 180 degrees".to_owned(),
            });
        }

        let observed = DateTime::parse_from_rfc3339(&track.observed_at)
            .map_err(|e| Cat062EncodeError {
                code: "invalid_timestamp",
                message: format!("cannot encode observedAt as CAT062 time of day: {e}"),
            })?
            .with_timezone(&Utc);
        let time = observed.time();
        let seconds_since_midnight = f64::from(time.num_seconds_from_midnight())
            + f64::from(time.nanosecond()) / 1_000_000_000.0;
        let time_units = (seconds_since_midnight * 128.0).round() as u32 % (86_400 * 128);

        // I062/080 Track Status is mandatory in the CAT062 UAP (FRN 13).
        let mut frns = vec![1, 4, 5, 12, 13];
        if track.velocity.is_some() {
            frns.push(7);
        }
        if track.position.altitude_m.is_some() {
            frns.push(18);
        }
        let fspec = encode_fspec(&frns);

        let mut record = Vec::new();
        // UAP FRN 1: I062/010 Data Source Identifier.
        record.extend([sac, sic]);
        // UAP FRN 4: I062/070 Time Of Track Information, 1/128 s since UTC midnight.
        push_u24(&mut record, time_units);
        // UAP FRN 5: I062/105 WGS-84 latitude and longitude, signed 32-bit values.
        let latitude = (track.position.latitude_deg * LAT_LON_SCALE).round() as i32;
        let longitude = (track.position.longitude_deg * LAT_LON_SCALE).round() as i32;
        record.extend(latitude.to_be_bytes());
        record.extend(longitude.to_be_bytes());
        // UAP FRN 7: I062/185 east/north Cartesian velocity, 0.25 m/s per LSB.
        if let Some(velocity) = track.velocity {
            let vx = quantize_i16(velocity.east_mps, 0.25, "east velocity")?;
            let vy = quantize_i16(velocity.north_mps, 0.25, "north velocity")?;
            record.extend(vx.to_be_bytes());
            record.extend(vy.to_be_bytes());
        }
        // UAP FRN 12: I062/040 Track Number (12 low-order bits).
        record.extend(track_number.to_be_bytes());
        // UAP FRN 13: I062/080 Track Status (first part and three extents).
        let simulated = track.test_data || track.header_simulated || track.simulated;
        record.push(0x81 | if confirmed { 0 } else { 0x02 }); // MON, CNF, FX
        record.push(
            (if simulated { 0x80 } else { 0 }) | (if track.final_update { 0x40 } else { 0 }) | 0x01,
        ); // SIM, TSE, FX
        record.push(0x01); // FX points to third extent
        record.push(if track.coasting { 0x80 } else { 0 }); // CST
                                                            // UAP FRN 18: I062/130 geometric altitude, 6.25 ft (1.905 m) per LSB.
        if let Some(altitude_m) = track.position.altitude_m {
            if !(-457.2..=45_720.0).contains(&altitude_m) {
                return Err(Cat062EncodeError {
                    code: "out_of_range",
                    message: "CAT062 I062/130 altitude is outside -1500..150000 ft".to_owned(),
                });
            }
            let altitude =
                quantize_i16(altitude_m, GEOMETRIC_ALTITUDE_LSB_M, "geometric altitude")?;
            record.extend(altitude.to_be_bytes());
        }

        let block_length = 3 + fspec.len() + record.len();
        let block_length = u16::try_from(block_length).map_err(|_| Cat062EncodeError {
            code: "message_too_large",
            message: "encoded CAT062 block exceeds the 16-bit length field".to_owned(),
        })?;
        let mut block = Vec::with_capacity(usize::from(block_length));
        block.push(CATEGORY);
        block.extend(block_length.to_be_bytes());
        block.extend(fspec);
        block.extend(record);
        Ok(block)
    }

    fn source_identifier(&self, kid: &str, source_id: &str) -> Result<(u8, u8), Cat062EncodeError> {
        if self.options.sources.is_empty() {
            return Ok((self.options.sac, self.options.sic));
        }
        let assignment = self
            .options
            .sources
            .get(&(kid.to_owned(), source_id.to_owned()))
            .or_else(|| {
                self.options
                    .sources
                    .get(&("*".to_owned(), source_id.to_owned()))
            })
            .ok_or_else(|| Cat062EncodeError {
                code: "missing_source_identifier",
                message: format!(
                    "CAT062 has no SAC/SIC assignment for kid '{kid}' and sourceId '{source_id}'"
                ),
            })?;
        Ok((assignment.sac, assignment.sic))
    }
}

fn quantize_i16(value: f64, lsb: f64, name: &str) -> Result<i16, Cat062EncodeError> {
    let raw = (value / lsb).round();
    if !raw.is_finite() || raw < f64::from(i16::MIN) || raw > f64::from(i16::MAX) {
        return Err(Cat062EncodeError {
            code: "out_of_range",
            message: format!("{name} cannot be represented by the CAT062 signed 16-bit item"),
        });
    }
    Ok(raw as i16)
}

fn encode_fspec(frns: &[u8]) -> Vec<u8> {
    let max_frn = frns.iter().copied().max().unwrap_or(1);
    let mut fspec = vec![0u8; usize::from((max_frn + 6) / 7)];
    for frn in frns {
        let zero_based = frn - 1;
        let byte = usize::from(zero_based / 7);
        let bit = 7 - (zero_based % 7);
        fspec[byte] |= 1 << bit;
    }
    let continuation_octets = fspec.len().saturating_sub(1);
    for byte in fspec.iter_mut().take(continuation_octets) {
        *byte |= 1;
    }
    fspec
}

fn push_u24(out: &mut Vec<u8>, value: u32) {
    out.push((value >> 16) as u8);
    out.push((value >> 8) as u8);
    out.push(value as u8);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Classification, Position, PositionUncertainty, Velocity};

    fn sample() -> CanonicalTrack {
        CanonicalTrack {
            track_id: "311".to_owned(),
            source_id: "sensor-a".to_owned(),
            track_generation: "generation-1".to_owned(),
            observed_at: "2025-10-29T12:00:00.123Z".to_owned(),
            position: Position {
                latitude_deg: 38.8977,
                longitude_deg: -77.0365,
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
            identifiers: Vec::new(),
            test_data: false,
            header_simulated: false,
            simulated: false,
            confirmed: Some(true),
            coasting: false,
            final_update: false,
        }
    }

    #[test]
    fn encodes_minimal_cat062_uap_record_with_optional_items() {
        let block = Cat062Encoder::new(Cat062Options {
            sac: 1,
            sic: 7,
            sources: HashMap::new(),
        })
        .encode_for_kid(&sample(), "oetf")
        .unwrap();
        assert_eq!(block[0], 62);
        assert_eq!(
            u16::from_be_bytes([block[1], block[2]]) as usize,
            block.len()
        );
        assert_eq!(&block[3..6], &[0x9b, 0x0d, 0x10]);
        assert_eq!(&block[6..8], &[1, 7]);
        assert_eq!(
            &block[19..23],
            &[
                (-50i16).to_be_bytes()[0],
                (-50i16).to_be_bytes()[1],
                17i16.to_be_bytes()[0],
                17i16.to_be_bytes()[1]
            ]
        );
        assert_eq!(u16::from_be_bytes([block[23], block[24]]), 311);
        assert_eq!(&block[25..29], &[0x81, 0x01, 0x01, 0x00]);
        assert_eq!(i16::from_be_bytes([block[29], block[30]]), 80);
        let latitude = i32::from_be_bytes(block[11..15].try_into().unwrap()) as f64 / LAT_LON_SCALE;
        let longitude =
            i32::from_be_bytes(block[15..19].try_into().unwrap()) as f64 / LAT_LON_SCALE;
        assert!((latitude - 38.8977).abs() < 0.00001);
        assert!((longitude + 77.0365).abs() < 0.00001);
    }

    #[test]
    fn rejects_unrepresentable_track_id_and_longitude() {
        let encoder = Cat062Encoder::new(Cat062Options {
            sac: 1,
            sic: 7,
            sources: HashMap::new(),
        });
        let mut track = sample();
        track.track_id = "track-311".to_owned();
        assert_eq!(
            encoder.encode_for_kid(&track, "oetf").unwrap_err().code,
            "invalid_track_number"
        );
        let mut track = sample();
        track.position.longitude_deg = 180.0;
        assert_eq!(
            encoder.encode_for_kid(&track, "oetf").unwrap_err().code,
            "out_of_range"
        );
    }

    #[test]
    fn maps_simulation_confirmation_coasting_and_final_update_status_bits() {
        let mut track = sample();
        track.simulated = true;
        track.confirmed = Some(false);
        track.coasting = true;
        track.final_update = true;
        let block = Cat062Encoder::new(Cat062Options {
            sac: 1,
            sic: 7,
            sources: HashMap::new(),
        })
        .encode_for_kid(&track, "oetf")
        .unwrap();
        assert_eq!(&block[25..29], &[0x83, 0xc1, 0x01, 0x80]);
    }

    #[test]
    fn selects_source_specific_sac_sic_and_requires_every_configured_source() {
        let encoder = Cat062Encoder::new(Cat062Options {
            sac: 0,
            sic: 0,
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
        });
        let source_a = encoder.encode_for_kid(&sample(), "oetf").unwrap();
        assert_eq!(&source_a[6..8], &[1, 7]);

        let mut track_b = sample();
        track_b.source_id = "sensor-b".to_owned();
        let source_b = encoder.encode_for_kid(&track_b, "oetf").unwrap();
        assert_eq!(&source_b[6..8], &[1, 8]);
        assert_eq!(&source_a[23..25], &source_b[23..25]);

        let mut unknown = sample();
        unknown.source_id = "sensor-c".to_owned();
        assert_eq!(
            encoder.encode_for_kid(&unknown, "oetf").unwrap_err().code,
            "missing_source_identifier"
        );
    }

    #[test]
    fn validates_unique_source_identifier_assignments() {
        let parsed = parse_source_identifiers_json(
            r#"{"kids":{"oetf":{"sources":{"sensor-a":{"sac":1,"sic":7},"sensor-b":{"sac":1,"sic":8}}},"other":{"sources":{"sensor-c":{"sac":2,"sic":7}}}}}"#,
        )
        .unwrap();
        assert_eq!(parsed.len(), 3);
        assert!(parse_source_identifiers_json(
            r#"{"kids":{"oetf":{"sources":{"sensor-a":{"sac":1,"sic":7},"sensor-b":{"sac":1,"sic":7}}}}}"#,
        )
        .unwrap_err()
        .contains("share SAC/SIC"));
        assert!(parse_source_identifiers_json(
            r#"{"kids":{"oetf":{"sources":{"sensor-a":{"sac":256,"sic":7}}}}}"#
        )
        .is_err());
        assert_eq!(
            parsed
                .get(&("other".to_owned(), "sensor-c".to_owned()))
                .unwrap()
                .sac,
            2
        );
    }

    #[test]
    fn preserves_legacy_global_source_map_compatibility() {
        let parsed =
            parse_source_identifiers_json(r#"{"sources":{"sensor-a":{"sac":4,"sic":20}}}"#)
                .unwrap();
        let encoder = Cat062Encoder::new(Cat062Options {
            sac: 0,
            sic: 0,
            sources: parsed,
        });
        let encoded = encoder.encode_for_kid(&sample(), "oetf").unwrap();
        assert_eq!(&encoded[6..8], &[4, 20]);
    }

    #[test]
    fn rejects_invalid_kid_ids_in_scoped_source_map() {
        assert!(parse_source_identifiers_json(
            r#"{"kids":{"OETF":{"sources":{"sensor-a":{"sac":4,"sic":20}}}}}"#,
        )
        .unwrap_err()
        .contains("lowercase letters"));
    }
}
