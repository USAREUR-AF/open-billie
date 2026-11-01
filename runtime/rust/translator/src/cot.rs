use chrono::{DateTime, Duration, SecondsFormat, Utc};

use crate::{CanonicalTrack, Classification};

const UNKNOWN_ERROR_METRES: f64 = 9_999_999.0;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CotOptions {
    /// Seconds after the observation time when the CoT event expires.
    pub stale_after_seconds: i64,
    /// CoT `how` attribute supplied by Billie node configuration.
    pub how: String,
}

impl Default for CotOptions {
    fn default() -> Self {
        Self {
            stale_after_seconds: 180,
            how: "m-p".to_owned(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CotEncodeError {
    pub code: &'static str,
    pub message: String,
}

/// Serialize a canonical track as one Cursor on Target Event XML payload.
#[derive(Clone, Debug, Default)]
pub struct CotEncoder {
    options: CotOptions,
}

impl CotEncoder {
    pub fn new(options: CotOptions) -> Self {
        Self { options }
    }

    pub fn encode(&self, track: &CanonicalTrack) -> Result<Vec<u8>, CotEncodeError> {
        self.encode_for_kid(track, "local")
    }

    pub fn encode_for_kid(
        &self,
        track: &CanonicalTrack,
        kid: &str,
    ) -> Result<Vec<u8>, CotEncodeError> {
        if self.options.stale_after_seconds <= 0 {
            return Err(CotEncodeError {
                code: "invalid_configuration",
                message: "CoT stale-after duration must be positive".to_owned(),
            });
        }
        if self.options.how.is_empty() {
            return Err(CotEncodeError {
                code: "invalid_configuration",
                message: "CoT how value must not be empty".to_owned(),
            });
        }
        let observed =
            DateTime::parse_from_rfc3339(&track.observed_at).map_err(|e| CotEncodeError {
                code: "invalid_timestamp",
                message: format!("cannot encode observedAt as CoT time: {e}"),
            })?;
        let observed = observed.with_timezone(&Utc);
        let stale = observed + Duration::seconds(self.options.stale_after_seconds);
        let timestamp = observed.to_rfc3339_opts(SecondsFormat::AutoSi, true);
        let stale = stale.to_rfc3339_opts(SecondsFormat::AutoSi, true);

        let class = track.classification.unwrap_or(Classification::Unknown);
        let hae = track.position.altitude_m.unwrap_or(UNKNOWN_ERROR_METRES);
        let ce = track
            .position_uncertainty
            .and_then(|u| Some((u.sigma_east_m?, u.sigma_north_m?)))
            .map(|(east, north)| east.hypot(north))
            .unwrap_or(UNKNOWN_ERROR_METRES);
        let le = track
            .position_uncertainty
            .and_then(|u| u.sigma_up_m)
            .unwrap_or(UNKNOWN_ERROR_METRES);

        let simulated = track.test_data || track.header_simulated || track.simulated;
        let opex = if simulated { " opex=\"s\"" } else { "" };
        let mut xml = format!(
            "<event version=\"2.0\" uid=\"{}\" type=\"{}\" time=\"{}\" start=\"{}\" stale=\"{}\" how=\"{}\"{}><point lat=\"{}\" lon=\"{}\" hae=\"{}\" ce=\"{}\" le=\"{}\"/><detail>",
            escape_attr(&track.scoped_identity(kid)),
            class.cot_type(),
            timestamp,
            timestamp,
            stale,
            escape_attr(&self.options.how),
            opex,
            track.position.latitude_deg,
            track.position.longitude_deg,
            hae,
            ce,
            le,
        );
        if let Some(velocity) = track.velocity {
            let course = if velocity.east_mps == 0.0 && velocity.north_mps == 0.0 {
                0.0
            } else {
                velocity
                    .east_mps
                    .atan2(velocity.north_mps)
                    .to_degrees()
                    .rem_euclid(360.0)
            };
            let speed = velocity.east_mps.hypot(velocity.north_mps);
            xml.push_str(&format!("<track course=\"{course}\" speed=\"{speed}\"/>"));
        }
        let mut status = Vec::new();
        if track.test_data {
            status.push("test-data");
        }
        if track.test_data || track.header_simulated || track.simulated {
            status.push("simulated");
        }
        if track.confirmed == Some(false) {
            status.push("tentative");
        }
        if track.coasting {
            status.push("coasting");
        }
        if track.final_update {
            status.push("final-update");
        }
        if !status.is_empty() {
            xml.push_str("<remarks>");
            xml.push_str(&status.join(","));
            xml.push_str("</remarks>");
        }
        xml.push_str("</detail></event>");
        Ok(xml.into_bytes())
    }
}

fn escape_attr(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{Position, PositionUncertainty, Velocity};

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
    fn encodes_canonical_oetf_track_as_cot_xml() {
        let bytes = CotEncoder::default().encode(&sample()).unwrap();
        let xml = String::from_utf8(bytes).unwrap();
        assert!(xml.contains(
            "version=\"2.0\" uid=\"local/sensor-a/311/generation-1\" type=\"a-u-A-M-F-Q\""
        ));
        assert!(xml.contains("time=\"2025-10-29T12:00:00.123Z\""));
        assert!(xml.contains("stale=\"2025-10-29T12:03:00.123Z\""));
        assert!(xml.contains("lat=\"38.8977\" lon=\"-77.0365\" hae=\"152.4\""));
        assert!(xml.contains("ce=\"4.25205832509386\" le=\"6.1\""));
        assert!(xml.contains("<track course=\"288."));
        assert!(xml.contains(" speed=\"13.202"));
    }

    #[test]
    fn unknown_optional_point_fields_use_cot_unknown_sentinel() {
        let mut track = sample();
        track.position.altitude_m = None;
        track.velocity = None;
        track.position_uncertainty = None;
        track.classification = None;
        let xml = String::from_utf8(CotEncoder::default().encode(&track).unwrap()).unwrap();
        assert!(xml.contains("type=\"a-u-X\""));
        assert!(xml.contains("hae=\"9999999\" ce=\"9999999\" le=\"9999999\""));
        assert!(!xml.contains("<track "));
    }

    #[test]
    fn escapes_user_values_and_rejects_invalid_ttl() {
        let mut track = sample();
        track.track_id = "A<&\"".to_owned();
        let options = CotOptions {
            stale_after_seconds: 30,
            how: "m-&p".to_owned(),
        };
        let xml = String::from_utf8(CotEncoder::new(options).encode(&track).unwrap()).unwrap();
        assert!(xml.contains("uid=\"local/sensor-a/A%3C%26%22/generation-1\""));
        assert!(xml.contains("how=\"m-&amp;p\""));
        let err = CotEncoder::new(CotOptions {
            stale_after_seconds: 0,
            how: "m-p".to_owned(),
        })
        .encode(&sample())
        .unwrap_err();
        assert_eq!(err.code, "invalid_configuration");
    }

    #[test]
    fn represents_simulation_and_track_status_in_cot() {
        let mut track = sample();
        track.test_data = true;
        track.confirmed = Some(false);
        track.coasting = true;
        track.final_update = true;
        let xml = String::from_utf8(CotEncoder::default().encode(&track).unwrap()).unwrap();
        assert!(xml.contains("opex=\"s\""));
        assert!(
            xml.contains("<remarks>test-data,simulated,tentative,coasting,final-update</remarks>")
        );
    }
}
