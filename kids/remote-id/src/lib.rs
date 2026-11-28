//! billie-remote-id-kid: drone Remote ID (ASTM F3411-22a, ASD-STAN EN
//! 4709-002) to Canonical Track v2.
//!
//! Remote ID is a broadcast, not a proof: any serial number and any position
//! can be typed into a cheap board. The `remoteid` crate decodes the frames,
//! keeps one entry per transmitter and grades each one (authenticated,
//! plausible, suspicious or spoofed). A spoofed transmitter is withheld, a
//! suspicious one is published as tentative (`confirmed: false`), and every
//! record carries its verdict as an identifier.

pub mod request;

pub use request::{rfc3339_millis, translation_request};

use remoteid::{ble, wifi, TrackedUas, Tracker, TrackerConfig, Transmitter, Verdict};
use serde_json::{json, Value};

/// How the receiver forwards what it heard, one frame per UDP datagram.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Link {
    /// An 802.11 frame (Beacon or NAN action), with or without a radiotap
    /// header, as a monitor-mode capture gives it.
    Wifi,
    /// The 6-byte advertiser address, then the Bluetooth advertising data.
    Ble,
}

impl Link {
    pub fn from_name(name: &str) -> Option<Link> {
        match name.to_ascii_lowercase().as_str() {
            "wifi" => Some(Link::Wifi),
            "ble" => Some(Link::Ble),
            _ => None,
        }
    }
}

/// What one datagram produced.
#[derive(Debug, Clone, PartialEq)]
pub enum Update {
    /// A Canonical Track v2 record to send to the translator.
    Track(Value),
    /// The transmitter is graded spoofed; nothing is published.
    Withheld {
        transmitter: String,
        reasons: String,
    },
    /// The transmitter has not sent a usable position yet.
    NoPosition,
}

/// Remote ID decoder and per-transmitter tracker.
pub struct Kid {
    link: Link,
    source_id: String,
    tracker: Tracker,
}

impl Kid {
    pub fn new(link: Link, source_id: &str) -> Kid {
        Kid {
            link,
            source_id: source_id.to_owned(),
            tracker: Tracker::new(TrackerConfig::default()),
        }
    }

    /// Decodes one datagram heard at `now_ms` (Unix milliseconds) and maps the
    /// transmitter's state to a record observed at `observed_at` (RFC 3339).
    pub fn ingest(
        &mut self,
        datagram: &[u8],
        now_ms: u64,
        observed_at: &str,
    ) -> Result<Update, String> {
        self.tracker.expire(now_ms);
        let from = match self.link {
            Link::Wifi => {
                let rid = wifi::parse_frame(datagram)
                    .or_else(|_| wifi::strip_radiotap(datagram).and_then(wifi::parse_frame))
                    .map_err(|error| format!("no Remote ID in 802.11 frame: {error}"))?;
                self.tracker.ingest_wifi(&rid, now_ms);
                Transmitter::Wifi(rid.source)
            }
            Link::Ble => {
                if datagram.len() < 6 {
                    return Err("BLE datagram shorter than its 6-byte address".to_owned());
                }
                let mut address = [0u8; 6];
                address.copy_from_slice(&datagram[..6]);
                let rid = ble::find_in_advertising_data(&datagram[6..])
                    .ok_or("no Remote ID service data in advertising data")?;
                self.tracker.ingest_ble(address, &rid, now_ms);
                Transmitter::Ble(address)
            }
        };
        let uas = self.tracker.get(&from).ok_or("transmitter not tracked")?;
        Ok(map(uas, &from, &self.source_id, observed_at))
    }
}

fn address(from: &Transmitter) -> String {
    match from {
        Transmitter::Ble(a) | Transmitter::Wifi(a) => a
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<Vec<_>>()
            .join(":"),
        Transmitter::Other(id) => id.to_string(),
    }
}

fn map(uas: &TrackedUas, from: &Transmitter, source_id: &str, observed_at: &str) -> Update {
    let assessment = uas.assessment;
    let reasons = assessment
        .reasons
        .iter()
        .map(|r| r.name())
        .collect::<Vec<_>>()
        .join(",");
    if assessment.verdict == Verdict::Spoofed {
        return Update::Withheld {
            transmitter: address(from),
            reasons,
        };
    }
    let Some(location) = uas.data.location.as_ref().filter(|l| l.is_plausible()) else {
        return Update::NoPosition;
    };
    let Some((latitude, longitude)) = location.position() else {
        return Update::NoPosition;
    };
    let track_id = uas.uas_id().unwrap_or_else(|| address(from));
    let mut position = json!({ "latitudeDeg": latitude, "longitudeDeg": longitude });
    if let Some(altitude) = location.altitude_geo {
        position["altitudeM"] = json!(altitude);
    }
    let mut identifiers = vec![
        json!({ "scheme": "remote-id-trust", "value": assessment.verdict.name() }),
        json!({ "scheme": "remote-id-transmitter", "value": address(from) }),
    ];
    if !reasons.is_empty() {
        identifiers.push(json!({ "scheme": "remote-id-trust-reasons", "value": reasons }));
    }
    let mut record = json!({
        "trackId": track_id,
        "sourceId": source_id,
        "trackGeneration": uas.first_seen.to_string(),
        "observedAt": observed_at,
        "position": position,
        "classification": "uas",
        "confidence": assessment.score.clamp(0.0, 1.0),
        "confirmed": assessment.verdict != Verdict::Suspicious,
        "identifiers": identifiers,
    });
    if let (Some(direction), Some(speed)) = (location.direction, location.speed_horizontal) {
        let (sin, cos) = f64::from(direction).to_radians().sin_cos();
        let speed = f64::from(speed);
        let mut velocity = json!({ "eastMps": speed * sin, "northMps": speed * cos });
        if let Some(up) = location.speed_vertical {
            velocity["upMps"] = json!(up);
        }
        record["velocity"] = velocity;
    }
    Update::Track(record)
}

#[cfg(test)]
mod tests {
    use super::*;
    use remoteid::{BasicId, IdType, Location, Message, MessagePackBuilder, UaType};

    const ADDRESS: [u8; 6] = [0x02, 0x00, 0x00, 0x00, 0x00, 0x01];

    /// A synthetic Bluetooth 5 datagram: address, then one service data AD
    /// structure (UUID 0xFFFA, app code 0x0D, counter) holding a pack.
    fn datagram(counter: u8, latitude: f64, longitude: f64) -> Vec<u8> {
        let mut pack = MessagePackBuilder::new();
        let id = BasicId::new(
            IdType::SerialNumber,
            UaType::HelicopterOrMultirotor,
            "SYNTH0000001",
        )
        .unwrap();
        pack.push(&Message::BasicId(id)).unwrap();
        let location = Location {
            latitude,
            longitude,
            altitude_geo: Some(120.0),
            direction: Some(90.0),
            speed_horizontal: Some(10.0),
            speed_vertical: Some(0.5),
            ..Location::default()
        };
        pack.push(&Message::Location(location)).unwrap();
        let mut service = vec![0xFA, 0xFF, 0x0D, counter];
        service.extend_from_slice(pack.as_bytes());
        let mut out = ADDRESS.to_vec();
        out.push(service.len() as u8 + 1);
        out.push(0x16);
        out.extend_from_slice(&service);
        out
    }

    #[test]
    fn plausible_broadcast_becomes_a_uas_track() {
        let mut kid = Kid::new(Link::Ble, "remote-id");
        let update = kid
            .ingest(&datagram(1, 10.0, 20.0), 1_000, "2026-01-01T00:00:01.000Z")
            .unwrap();
        let Update::Track(record) = update else {
            panic!("{update:?}")
        };
        assert_eq!(record["trackId"], "SYNTH0000001");
        assert_eq!(record["classification"], "uas");
        assert_eq!(record["confirmed"], true);
        assert_eq!(record["position"]["altitudeM"], 120.0);
        assert!((record["velocity"]["eastMps"].as_f64().unwrap() - 10.0).abs() < 1e-6);
        assert_eq!(record["identifiers"][0]["value"], "plausible");
    }

    #[test]
    fn teleporting_transmitter_is_not_published_as_a_clean_track() {
        let mut kid = Kid::new(Link::Ble, "remote-id");
        let mut last = None;
        // Jumps of about 1,100 km a second: no aircraft flies like that.
        for step in 0..8u8 {
            let latitude = if step % 2 == 0 { 10.0 } else { 20.0 };
            let now = 1_000 + u64::from(step) * 1_000;
            last = Some(
                kid.ingest(
                    &datagram(step + 1, latitude, 20.0),
                    now,
                    "2026-01-01T00:00:01.000Z",
                )
                .unwrap(),
            );
        }
        assert!(matches!(last, Some(Update::Withheld { .. })), "{last:?}");
    }

    #[test]
    fn datagram_without_remote_id_is_rejected() {
        let mut kid = Kid::new(Link::Ble, "remote-id");
        assert!(kid.ingest(&ADDRESS, 0, "2026-01-01T00:00:00.000Z").is_err());
        let mut kid = Kid::new(Link::Wifi, "remote-id");
        assert!(kid
            .ingest(&[0u8; 40], 0, "2026-01-01T00:00:00.000Z")
            .is_err());
    }
}
