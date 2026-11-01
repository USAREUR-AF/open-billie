//! Reference OETF frame builder — a port of the TypeScript `builder.ts`.
//!
//! Produces byte-identical frames to the TS and Python builders (rounding
//! follows JS `Math.round`).

use crate::decoder::{crc16, FORMAT_VERSION, MAGIC};

pub const MSG_SENSOR_STATUS: u8 = 1;
pub const MSG_TRACK_REPORT: u8 = 16;
pub const MAX_TRACKS: usize = 8;

/// JS `Math.round`: half rounds toward +∞.
fn round(x: f64) -> i64 {
    (x + 0.5).floor() as i64
}

fn flags(bits: &[bool]) -> u16 {
    bits.iter().enumerate().filter(|(_, on)| **on).map(|(i, _)| 1u16 << i).sum()
}

#[derive(Debug, Clone, Default)]
pub struct FrameHeader {
    pub sequence: u32,
    pub sensor_id: u16,
    pub test_data: bool,
    pub simulated: bool,
}

#[derive(Debug, Clone, Default)]
pub struct SensorStatus {
    pub timestamp_us: u64,
    pub lat_deg: f64,
    pub lon_deg: f64,
    pub alt_m: f64,
    pub boresight_deg: f64,
    /// 0 Off, 1 Standby, 2 Scanning, 3 Degraded, 4 Fault
    pub state: u8,
    pub active_tracks: u8,
    pub transmitting: bool,
    pub time_sync_valid: bool,
    pub position_valid: bool,
    pub over_temperature: bool,
}

#[derive(Debug, Clone, Default)]
pub struct Track {
    pub id: u16,
    /// 0 Unknown … 7 Clutter, see docs/WIRE_FORMAT.md
    pub classification: u8,
    pub confidence_pct: u8,
    pub confirmed: bool,
    pub coasting: bool,
    pub final_update: bool,
    pub simulated: bool,
    /// Octal Mode 3/A, e.g. `Some("7000")`.
    pub mode3a: Option<String>,
    pub lat_deg: f64,
    pub lon_deg: f64,
    pub alt_m: f64,
    pub vel_east_ms: f64,
    pub vel_north_ms: f64,
    pub vel_up_ms: f64,
    pub pos_sigma_east_m: f64,
    pub pos_sigma_north_m: f64,
    pub alt_sigma_m: f64,
    pub vel_sigma_east_ms: f64,
    pub vel_sigma_north_ms: f64,
    pub rcs_dbsm: f64,
    pub age_s: u32,
}

/// Wrap a body into a complete frame with header and CRC.
pub fn build_frame(msg_type: u8, h: &FrameHeader, body: &[u8]) -> Vec<u8> {
    let len = (16 + body.len() + 2) as u16;
    let mut f = Vec::with_capacity(len as usize);
    f.extend_from_slice(MAGIC);
    f.push(FORMAT_VERSION);
    f.push(msg_type);
    f.extend_from_slice(&len.to_le_bytes());
    f.extend_from_slice(&h.sequence.to_le_bytes());
    f.extend_from_slice(&h.sensor_id.to_le_bytes());
    f.extend_from_slice(&flags(&[h.test_data, h.simulated]).to_le_bytes());
    f.extend_from_slice(body);
    let crc = crc16(&f);
    f.extend_from_slice(&crc.to_le_bytes());
    f
}

pub fn build_sensor_status(h: &FrameHeader, s: &SensorStatus) -> Vec<u8> {
    let mut b = Vec::with_capacity(28);
    b.extend_from_slice(&s.timestamp_us.to_le_bytes());
    b.extend_from_slice(&(round(s.lat_deg * 1e7) as i32).to_le_bytes());
    b.extend_from_slice(&(round(s.lon_deg * 1e7) as i32).to_le_bytes());
    b.extend_from_slice(&(round(s.alt_m * 100.0) as i32).to_le_bytes());
    b.extend_from_slice(&(round(s.boresight_deg * 100.0) as u16).to_le_bytes());
    b.push(s.state);
    b.push(s.active_tracks);
    b.extend_from_slice(&flags(&[s.transmitting, s.time_sync_valid, s.position_valid, s.over_temperature]).to_le_bytes());
    b.extend_from_slice(&0u16.to_le_bytes());
    build_frame(MSG_SENSOR_STATUS, h, &b)
}

pub fn build_track_report(h: &FrameHeader, timestamp_us: u64, tracks: &[Track]) -> Result<Vec<u8>, String> {
    if tracks.len() > MAX_TRACKS {
        return Err(format!("OETF Track Report carries at most {MAX_TRACKS} tracks"));
    }
    let mut b = Vec::with_capacity(12 + tracks.len() * 40);
    b.extend_from_slice(&timestamp_us.to_le_bytes());
    b.push(tracks.len() as u8);
    b.extend_from_slice(&[0, 0, 0]);
    for t in tracks {
        let mode3a = match &t.mode3a {
            Some(code) => u16::from_str_radix(code, 8).map_err(|e| format!("Mode 3/A {code:?}: {e}"))?,
            None => 0,
        };
        b.extend_from_slice(&t.id.to_le_bytes());
        b.push(t.classification);
        b.push(t.confidence_pct);
        b.extend_from_slice(&flags(&[t.confirmed, t.coasting, t.final_update, t.simulated, t.mode3a.is_some()]).to_le_bytes());
        b.extend_from_slice(&mode3a.to_le_bytes());
        for v in [t.lat_deg * 1e7, t.lon_deg * 1e7, t.alt_m * 100.0] {
            b.extend_from_slice(&(round(v) as i32).to_le_bytes());
        }
        for v in [t.vel_east_ms, t.vel_north_ms, t.vel_up_ms] {
            b.extend_from_slice(&(round(v * 100.0) as i16).to_le_bytes());
        }
        for v in [t.pos_sigma_east_m, t.pos_sigma_north_m, t.alt_sigma_m, t.vel_sigma_east_ms, t.vel_sigma_north_ms] {
            b.extend_from_slice(&(round(v * 100.0) as u16).to_le_bytes());
        }
        b.extend_from_slice(&(round(t.rcs_dbsm * 10.0) as i16).to_le_bytes());
        b.extend_from_slice(&(t.age_s.min(0xFFFF) as u16).to_le_bytes());
    }
    Ok(build_frame(MSG_TRACK_REPORT, h, &b))
}
