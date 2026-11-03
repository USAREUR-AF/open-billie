//! SAPIENT BSI Flex 335 v2.0 protobuf DetectionReport encoder.
//!
//! The Zenoh adapter publishes one serialized SapientMessage as one Zenoh sample.
//! It does not add a TCP stream length prefix: Zenoh already preserves sample
//! boundaries. The node UUID is persisted in protected platform identity and is
//! injected into the service environment.

use chrono::{DateTime, Utc};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::{CanonicalTrack, Classification};

const WGS84_A: f64 = 6_378_137.0;
const WGS84_E2: f64 = 6.694_379_990_14e-3;
static OBJECT_ID_STORE_LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SapientOptions {
    /// SAPIENT node UUID supplied by the node identity or platform service.
    pub node_id: String,
    /// Persistent map from canonical track IDs to their SAPIENT object ULIDs.
    pub object_id_store: PathBuf,
}

impl Default for SapientOptions {
    fn default() -> Self {
        Self {
            node_id: std::env::var("BILLIE_SAPIENT_NODE_ID").unwrap_or_default(),
            object_id_store: std::env::var_os("BILLIE_SAPIENT_OBJECT_ID_STORE")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("/var/lib/billie/sapient-object-ids.json")),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SapientEncodeError {
    pub code: &'static str,
    pub message: String,
}

/// Encode one canonical track as a SAPIENT v2 SapientMessage protobuf.
#[derive(Clone, Debug, Default)]
pub struct SapientEncoder {
    options: SapientOptions,
}

impl SapientEncoder {
    pub fn new(options: SapientOptions) -> Self {
        Self { options }
    }

    pub fn encode(&self, track: &CanonicalTrack) -> Result<Vec<u8>, SapientEncodeError> {
        self.encode_for_kid(track, "local")
    }

    pub fn encode_for_kid(
        &self,
        track: &CanonicalTrack,
        kid: &str,
    ) -> Result<Vec<u8>, SapientEncodeError> {
        if self.options.node_id.is_empty() {
            return Err(error(
                "invalid_configuration",
                "SAPIENT node UUID is missing; configure the node identity or set BILLIE_SAPIENT_NODE_ID",
            ));
        }
        if !valid_uuid(&self.options.node_id) {
            return Err(error(
                "invalid_configuration",
                "SAPIENT node_id must be a UUID",
            ));
        }

        let observed = DateTime::parse_from_rfc3339(&track.observed_at)
            .map_err(|e| {
                error(
                    "invalid_timestamp",
                    format!("cannot encode SAPIENT timestamp: {e}"),
                )
            })?
            .with_timezone(&Utc);
        let seconds = observed.timestamp();
        let nanos = observed.timestamp_subsec_nanos();

        let report_id = new_ulid()?;
        let scoped_identity = track.scoped_identity(kid);
        let object_id = self.object_id_for(&scoped_identity)?;
        let mut report = Vec::new();
        put_string(&mut report, 1, &report_id);
        put_string(&mut report, 2, &object_id);
        put_string(&mut report, 23, &scoped_identity);
        let mut state = Vec::new();
        if track.test_data {
            state.push("test-data");
        }
        if track.test_data || track.header_simulated || track.simulated {
            state.push("simulated");
        }
        if track.confirmed == Some(false) {
            state.push("tentative");
        }
        if track.coasting {
            state.push("coasting");
        }
        if track.final_update {
            state.push("final-update");
        }
        if !state.is_empty() {
            // BSI Flex 335 has a free-form state string; these tokens are
            // Open Billie conventions, not standardized SAPIENT enum values.
            put_string(&mut report, 4, &state.join(","));
        }

        let mut location = Vec::new();
        put_double(&mut location, 1, track.position.longitude_deg);
        put_double(&mut location, 2, track.position.latitude_deg);
        if let Some(altitude) = track.position.altitude_m {
            put_double(&mut location, 3, altitude);
        }
        if let Some(uncertainty) = track.position_uncertainty {
            let (latitude_sigma_deg, longitude_sigma_deg) = position_sigma_degrees(
                track.position.latitude_deg,
                uncertainty.sigma_north_m,
                uncertainty.sigma_east_m,
            );
            if let Some(sigma) = longitude_sigma_deg {
                put_double(&mut location, 4, sigma);
            }
            if let Some(sigma) = latitude_sigma_deg {
                put_double(&mut location, 5, sigma);
            }
            if let Some(sigma) = uncertainty.sigma_up_m {
                put_double(&mut location, 6, sigma);
            }
        }
        // LAT_LNG_DEG_M and WGS84 ellipsoid, as defined by BSI Flex 335 v2.0.
        put_varint_field(&mut location, 7, 1);
        put_varint_field(&mut location, 8, 1);
        put_message(&mut report, 6, &location);

        if let Some(confidence) = track.confidence {
            put_float(&mut report, 7, confidence as f32);
        }
        if let Some(classification) = track.classification {
            let mut class = Vec::new();
            put_string(&mut class, 1, sapient_class(classification));
            if let Some(confidence) = track.confidence {
                put_float(&mut class, 2, confidence as f32);
            }
            put_message(&mut report, 11, &class);
        }
        for identifier in &track.identifiers {
            if identifier.scheme == "sapient-object-info" {
                let mut info = Vec::new();
                put_string(&mut info, 1, "rcs_dbsm");
                put_string(&mut info, 2, &identifier.value);
                put_message(&mut report, 10, &info);
            }
        }
        if let Some(velocity) = track.velocity {
            let mut enu = Vec::new();
            put_double(&mut enu, 1, velocity.east_mps);
            put_double(&mut enu, 2, velocity.north_mps);
            if let Some(up) = velocity.up_mps {
                put_double(&mut enu, 3, up);
            }
            put_message(&mut report, 19, &enu);
        }

        let mut timestamp = Vec::new();
        put_varint_field(&mut timestamp, 1, seconds as u64);
        if nanos != 0 {
            put_varint_field(&mut timestamp, 2, u64::from(nanos));
        }
        let mut envelope = Vec::new();
        put_message(&mut envelope, 1, &timestamp);
        put_string(&mut envelope, 2, &self.options.node_id.to_ascii_lowercase());
        put_message(&mut envelope, 7, &report);
        Ok(envelope)
    }

    fn object_id_for(&self, track_id: &str) -> Result<String, SapientEncodeError> {
        let _guard = OBJECT_ID_STORE_LOCK
            .lock()
            .map_err(|_| error("state_io", "SAPIENT object ID store lock is poisoned"))?;
        let path = &self.options.object_id_store;
        let mut ids: BTreeMap<String, String> = match fs::read(path) {
            Ok(bytes) => serde_json::from_slice(&bytes).map_err(|e| {
                error(
                    "invalid_state",
                    format!("cannot read SAPIENT object ID store: {e}"),
                )
            })?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => BTreeMap::new(),
            Err(e) => {
                return Err(error(
                    "state_io",
                    format!("cannot read SAPIENT object ID store: {e}"),
                ))
            }
        };
        if let Some(id) = ids.get(track_id) {
            return Ok(id.clone());
        }
        let id = new_ulid()?;
        ids.insert(track_id.to_owned(), id.clone());
        let bytes = serde_json::to_vec(&ids).map_err(|e| {
            error(
                "state_io",
                format!("cannot serialize SAPIENT object ID store: {e}"),
            )
        })?;
        let temporary = path.with_extension(format!("json.tmp.{}", std::process::id()));
        fs::write(&temporary, bytes).map_err(|e| {
            error(
                "state_io",
                format!("cannot write SAPIENT object ID store: {e}"),
            )
        })?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600)).map_err(|e| {
                error(
                    "state_io",
                    format!("cannot protect SAPIENT object ID store: {e}"),
                )
            })?;
        }
        fs::rename(&temporary, path).map_err(|e| {
            error(
                "state_io",
                format!("cannot persist SAPIENT object ID store: {e}"),
            )
        })?;
        Ok(id)
    }
}

fn error(code: &'static str, message: impl Into<String>) -> SapientEncodeError {
    SapientEncodeError {
        code,
        message: message.into(),
    }
}

fn sapient_class(class: Classification) -> &'static str {
    match class {
        Classification::Unknown | Classification::Other => "UNKNOWN",
        Classification::FixedWingAircraft => "AIRCRAFT_FIXEDWING",
        Classification::RotaryWingAircraft => "AIRCRAFT_ROTARYWING",
        Classification::Uas => "UAV",
        Classification::Balloon => "BALLOON",
        Classification::Bird => "BIRD",
        Classification::Vehicle => "VEHICLE",
        Classification::Clutter => "CLUTTER",
    }
}

fn valid_uuid(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 36
        && [8, 13, 18, 23].iter().all(|index| bytes[*index] == b'-')
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| [8, 13, 18, 23].contains(&index) || byte.is_ascii_hexdigit())
}

fn new_ulid() -> Result<String, SapientEncodeError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| {
            error(
                "clock_error",
                format!("system clock predates Unix epoch: {e}"),
            )
        })?
        .as_millis() as u64;
    if millis >= (1u64 << 48) {
        return Err(error(
            "clock_error",
            "system clock is outside the ULID timestamp range",
        ));
    }
    let mut bytes = [0u8; 16];
    bytes[..6].copy_from_slice(&millis.to_be_bytes()[2..]);
    getrandom::getrandom(&mut bytes[6..]).map_err(|e| {
        error(
            "random_source_unavailable",
            format!("cannot generate ULID randomness: {e}"),
        )
    })?;
    Ok(encode_ulid(bytes))
}

fn encode_ulid(bytes: [u8; 16]) -> String {
    const ALPHABET: &[u8; 32] = b"0123456789ABCDEFGHJKMNPQRSTVWXYZ";
    let mut encoded = String::with_capacity(26);
    for symbol in 0..26 {
        let mut value = 0usize;
        for offset in 0..5 {
            let bit_index = symbol * 5 + offset;
            value <<= 1;
            if bit_index >= 2 {
                let source_bit = bit_index - 2;
                value |= usize::from((bytes[source_bit / 8] >> (7 - (source_bit % 8))) & 1);
            }
        }
        encoded.push(ALPHABET[value] as char);
    }
    encoded
}

fn position_sigma_degrees(
    latitude_deg: f64,
    north_m: Option<f64>,
    east_m: Option<f64>,
) -> (Option<f64>, Option<f64>) {
    let latitude = latitude_deg.to_radians();
    let sin_lat = latitude.sin();
    let denom = 1.0 - WGS84_E2 * sin_lat * sin_lat;
    let meridional_radius = WGS84_A * (1.0 - WGS84_E2) / denom.powf(1.5);
    let prime_vertical_radius = WGS84_A / denom.sqrt();
    let latitude_sigma = north_m.map(|m| (m / meridional_radius).to_degrees());
    let cosine = latitude.cos().abs();
    let longitude_sigma = east_m.and_then(|m| {
        (cosine > 1e-12).then(|| (m / (prime_vertical_radius * cosine)).to_degrees())
    });
    (latitude_sigma, longitude_sigma)
}

fn put_varint_field(out: &mut Vec<u8>, field: u32, value: u64) {
    put_varint(out, u64::from(field) << 3);
    put_varint(out, value);
}

fn put_string(out: &mut Vec<u8>, field: u32, value: &str) {
    put_bytes(out, field, value.as_bytes());
}

fn put_message(out: &mut Vec<u8>, field: u32, value: &[u8]) {
    put_bytes(out, field, value);
}

fn put_bytes(out: &mut Vec<u8>, field: u32, value: &[u8]) {
    put_varint(out, (u64::from(field) << 3) | 2);
    put_varint(out, value.len() as u64);
    out.extend_from_slice(value);
}

fn put_double(out: &mut Vec<u8>, field: u32, value: f64) {
    put_varint(out, (u64::from(field) << 3) | 1);
    out.extend_from_slice(&value.to_le_bytes());
}

fn put_float(out: &mut Vec<u8>, field: u32, value: f32) {
    put_varint(out, (u64::from(field) << 3) | 5);
    out.extend_from_slice(&value.to_le_bytes());
}

fn put_varint(out: &mut Vec<u8>, mut value: u64) {
    while value >= 0x80 {
        out.push((value as u8) | 0x80);
        value >>= 7;
    }
    out.push(value as u8);
}

#[cfg(test)]
mod tests {
    use super::*;
    use prost::Message;
    use std::sync::atomic::{AtomicU64, Ordering};

    // Minimal independent Prost decoder matching the official SAPIENT v2
    // message field numbers and wire types. See Dstl's BSI Flex 335 v2.0
    // definitions: sapient_message.proto and detection_report.proto.
    // https://github.com/dstl/SAPIENT-Proto-Files/tree/main/bsi_flex_335_v2_0
    #[derive(Clone, PartialEq, Message)]
    struct SapientMessage {
        #[prost(message, optional, tag = "1")]
        timestamp: Option<Timestamp>,
        #[prost(string, optional, tag = "2")]
        node_id: Option<String>,
        #[prost(oneof = "sapient_message::Content", tags = "7")]
        content: Option<sapient_message::Content>,
    }

    mod sapient_message {
        #[derive(Clone, PartialEq, prost::Oneof)]
        pub enum Content {
            #[prost(message, tag = "7")]
            DetectionReport(super::DetectionReport),
        }
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

    fn sample_track() -> CanonicalTrack {
        use crate::{Identifier, Position, PositionUncertainty, Velocity};
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
            identifiers: vec![Identifier {
                scheme: "sapient-object-info".to_owned(),
                value: "-18.3".to_owned(),
            }],
            test_data: false,
            header_simulated: false,
            simulated: false,
            confirmed: Some(true),
            coasting: false,
            final_update: false,
        }
    }

    #[test]
    fn output_decodes_with_bsi_flex_v2_fields_and_stable_object_identity() {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let store = std::env::temp_dir().join(format!(
            "billie-sapient-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let encoder = SapientEncoder::new(SapientOptions {
            node_id: "00000000-0000-4000-8000-000000000001".to_owned(),
            object_id_store: store.clone(),
        });

        let first_bytes = encoder.encode(&sample_track()).unwrap();
        let first = SapientMessage::decode(first_bytes.as_slice()).unwrap();
        assert_eq!(
            first.node_id.as_deref(),
            Some("00000000-0000-4000-8000-000000000001")
        );
        assert_eq!(
            first.timestamp.as_ref().unwrap().seconds,
            Some(1_761_739_200)
        );
        assert_eq!(first.timestamp.as_ref().unwrap().nanos, Some(123_000_000));

        let sapient_message::Content::DetectionReport(report) = first.content.unwrap();
        assert_eq!(
            report.id.as_deref(),
            Some("local/sensor-a/311/generation-1")
        );
        assert_eq!(report.state, None);
        assert_eq!(report.report_id.as_ref().unwrap().len(), 26);
        let first_report_id = report.report_id.clone();
        assert_eq!(report.object_id.as_ref().unwrap().len(), 26);
        assert_eq!(report.detection_confidence, Some(0.87));
        let location = report.location.unwrap();
        assert_eq!(location.x, Some(0.0));
        assert_eq!(location.y, Some(0.0));
        assert_eq!(location.z, Some(152.4));
        assert_eq!(location.coordinate_system, Some(1));
        assert_eq!(location.datum, Some(1));
        assert!(location.x_error.unwrap() > 0.0);
        assert!(location.y_error.unwrap() > 0.0);
        assert_eq!(location.z_error, Some(6.1));
        assert_eq!(report.classification[0].r#type.as_deref(), Some("UAV"));
        assert_eq!(report.object_info[0].r#type.as_deref(), Some("rcs_dbsm"));
        assert_eq!(report.object_info[0].value.as_deref(), Some("-18.3"));
        let velocity = report.enu_velocity.unwrap();
        assert_eq!(velocity.east_rate, Some(-12.5));
        assert_eq!(velocity.north_rate, Some(4.25));
        assert_eq!(velocity.up_rate, Some(1.5));
        let first_object_id = report.object_id.unwrap();

        let mut later_track = sample_track();
        later_track.observed_at = "2025-10-29T12:00:01Z".to_owned();
        let second =
            SapientMessage::decode(encoder.encode(&later_track).unwrap().as_slice()).unwrap();
        let sapient_message::Content::DetectionReport(second_report) = second.content.unwrap();
        assert_eq!(
            second_report.object_id.as_deref(),
            Some(first_object_id.as_str())
        );
        assert_ne!(second_report.report_id, first_report_id);

        let mut recycled_track = sample_track();
        recycled_track.track_generation = "generation-2".to_owned();
        let recycled =
            SapientMessage::decode(encoder.encode(&recycled_track).unwrap().as_slice()).unwrap();
        let sapient_message::Content::DetectionReport(recycled_report) = recycled.content.unwrap();
        assert_ne!(
            recycled_report.object_id.as_deref(),
            Some(first_object_id.as_str())
        );

        let other_kid = SapientMessage::decode(
            encoder
                .encode_for_kid(&sample_track(), "other-kid")
                .unwrap()
                .as_slice(),
        )
        .unwrap();
        let sapient_message::Content::DetectionReport(other_report) = other_kid.content.unwrap();
        assert_ne!(
            other_report.object_id.as_deref(),
            Some(first_object_id.as_str())
        );

        let _ = fs::remove_file(store);
    }

    #[test]
    fn preserves_track_status_in_sapient_state_convention() {
        static NEXT: AtomicU64 = AtomicU64::new(1000);
        let store = std::env::temp_dir().join(format!(
            "billie-sapient-status-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let encoder = SapientEncoder::new(SapientOptions {
            node_id: "00000000-0000-4000-8000-000000000001".to_owned(),
            object_id_store: store.clone(),
        });
        let mut track = sample_track();
        track.test_data = true;
        track.header_simulated = true;
        track.confirmed = Some(false);
        track.coasting = true;
        track.final_update = true;
        let decoded = SapientMessage::decode(encoder.encode(&track).unwrap().as_slice()).unwrap();
        let sapient_message::Content::DetectionReport(report) = decoded.content.unwrap();
        assert_eq!(
            report.state.as_deref(),
            Some("test-data,simulated,tentative,coasting,final-update")
        );
        let _ = fs::remove_file(store);
    }

    #[test]
    fn concurrent_object_id_requests_preserve_one_stable_mapping() {
        use std::sync::Arc;
        use std::thread;

        static NEXT: AtomicU64 = AtomicU64::new(2000);
        let store = std::env::temp_dir().join(format!(
            "billie-sapient-concurrent-{}-{}.json",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        let encoder = Arc::new(SapientEncoder::new(SapientOptions {
            node_id: "00000000-0000-4000-8000-000000000001".to_owned(),
            object_id_store: store.clone(),
        }));
        let handles: Vec<_> = (0..32)
            .map(|_| {
                let encoder = Arc::clone(&encoder);
                thread::spawn(move || {
                    encoder
                        .object_id_for("kid/source/track/generation")
                        .unwrap()
                })
            })
            .collect();
        let ids: Vec<_> = handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect();
        assert!(ids.iter().all(|id| id == &ids[0]));
        let persisted: BTreeMap<String, String> =
            serde_json::from_slice(&fs::read(&store).unwrap()).unwrap();
        assert_eq!(persisted.len(), 1);
        assert_eq!(persisted.values().next(), Some(&ids[0]));
        let _ = fs::remove_file(store);
    }
}
