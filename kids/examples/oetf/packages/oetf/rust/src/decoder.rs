//! Streaming OETF decoder — a port of the TypeScript `decoder.ts`.
//!
//! Framing: 4-byte magic `OETF`, `Frame length` (u16 LE) at offset 6,
//! CRC-16/CCITT-FALSE trailer. On any fault the decoder steps past the magic
//! and rescans, so one corrupt frame costs only that frame.

use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

use crate::bundled;
use crate::parser::parse;

pub const MAGIC: &[u8; 4] = b"OETF";
pub const FORMAT_VERSION: u8 = 1;
const HEADER_BYTES: usize = 16;
const CRC_BYTES: usize = 2;
const MIN_FRAME_SIZE: usize = HEADER_BYTES + CRC_BYTES;
const MAX_FRAME_SIZE: usize = 4096;

/// Same shape as the TS `DecodedRecord`: `messageName` + flat `fields` + meta.
#[derive(Debug, Clone)]
pub struct DecodedRecord {
    pub message_name: String,
    pub fields: Map<String, Value>,
    pub msg_id: u8,
    pub raw_hex: String,
    pub decoded_at_ms: u128,
}

#[derive(Debug, Clone)]
pub struct FramingError {
    pub at_ms: u128,
    /// sync-lost | bad-length | bad-version | crc-mismatch | unknown-type | decode-failed
    pub reason: &'static str,
    pub recovered_bytes: Option<usize>,
    pub detail: String,
}

/// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). `crc16(b"123456789") == 0x29B1`.
pub fn crc16(data: &[u8]) -> u16 {
    let mut crc: u16 = 0xFFFF;
    for &byte in data {
        crc ^= (byte as u16) << 8;
        for _ in 0..8 {
            crc = if crc & 0x8000 != 0 { (crc << 1) ^ 0x1021 } else { crc << 1 };
        }
    }
    crc
}

fn now_ms() -> u128 {
    SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_millis())
}

/// Stateful streaming decoder. One instance per stream; not thread-safe.
pub struct OetfDecoder {
    buffer: Vec<u8>,
    errors: Vec<FramingError>,
    schemas: HashMap<String, Value>,
}

impl Default for OetfDecoder {
    fn default() -> Self {
        Self::new()
    }
}

impl OetfDecoder {
    /// Decoder using the schemas embedded at build time.
    pub fn new() -> Self {
        let schemas = bundled::SCHEMAS
            .iter()
            .map(|(name, text)| (name.to_string(), serde_json::from_str(text).expect("embedded schema is valid JSON")))
            .collect();
        Self { buffer: Vec::new(), errors: Vec::new(), schemas }
    }

    /// Feed any number of bytes; return the complete records now available.
    pub fn feed(&mut self, chunk: &[u8]) -> Vec<DecodedRecord> {
        self.buffer.extend_from_slice(chunk);
        let mut records = Vec::new();

        while self.buffer.len() >= HEADER_BYTES {
            let sync_at = self.buffer.windows(MAGIC.len()).position(|w| w == MAGIC);
            if sync_at != Some(0) {
                // Keep a possible partial magic at the tail so it can complete on the next feed.
                let drop = sync_at.unwrap_or(self.buffer.len() - (MAGIC.len() - 1));
                self.err("sync-lost", format!("Skipped {drop} byte(s) looking for magic 'OETF'."), Some(drop));
                self.buffer.drain(..drop);
                continue;
            }

            let version = self.buffer[4];
            let size = u16::from_le_bytes([self.buffer[6], self.buffer[7]]) as usize;
            if version != FORMAT_VERSION {
                self.skip_bad_frame("bad-version", format!("Format version {version}, expected {FORMAT_VERSION}."));
                continue;
            }
            if !(MIN_FRAME_SIZE..=MAX_FRAME_SIZE).contains(&size) {
                self.skip_bad_frame("bad-length", format!("Declared length {size} outside {MIN_FRAME_SIZE}..{MAX_FRAME_SIZE}."));
                continue;
            }
            if self.buffer.len() < size {
                break; // need more data
            }

            let expected = u16::from_le_bytes([self.buffer[size - 2], self.buffer[size - 1]]);
            let actual = crc16(&self.buffer[..size - CRC_BYTES]);
            if expected != actual {
                // The length may itself be corrupt, so resync from the next magic.
                self.skip_bad_frame("crc-mismatch", format!("CRC 0x{actual:04x} != trailer 0x{expected:04x}."));
                continue;
            }

            let frame: Vec<u8> = self.buffer.drain(..size).collect();
            if let Some(r) = self.decode_frame(&frame) {
                records.push(r);
            }
        }
        records
    }

    /// Clear the accumulator (call on disconnect).
    pub fn reset(&mut self) {
        self.buffer.clear();
    }

    /// Drain the errors observed since the last call.
    pub fn take_recent_errors(&mut self) -> Vec<FramingError> {
        std::mem::take(&mut self.errors)
    }

    /// Decode one already-framed, CRC-checked buffer.
    pub fn decode_frame(&mut self, frame: &[u8]) -> Option<DecodedRecord> {
        let header = match parse(frame, &self.schemas["header.json"], true) {
            Ok(h) => h,
            Err(e) => {
                self.err("decode-failed", format!("Header decode threw: {e}"), None);
                return None;
            }
        };
        let msg_id = frame[5];
        let mut rec = DecodedRecord {
            message_name: format!("unknown-{msg_id}"),
            fields: header,
            msg_id,
            raw_hex: frame.iter().map(|b| format!("{b:02x}")).collect(),
            decoded_at_ms: now_ms(),
        };
        let Some(schema) = self.schemas.get(&format!("msg_{msg_id}.json")).cloned() else {
            self.err("unknown-type", format!("No schema for message type {msg_id}."), None);
            return Some(rec);
        };
        match parse(frame, &schema, true) {
            Ok(body) => rec.fields.extend(body),
            Err(e) => self.err("decode-failed", format!("Body decode for msg_{msg_id} threw: {e}"), None),
        }
        rec.message_name = schema["messageName"].as_str().unwrap_or_default().to_owned();
        Some(rec)
    }

    fn skip_bad_frame(&mut self, reason: &'static str, detail: String) {
        self.err(reason, detail, Some(MAGIC.len()));
        self.buffer.drain(..MAGIC.len());
    }

    fn err(&mut self, reason: &'static str, detail: String, recovered_bytes: Option<usize>) {
        self.errors.push(FramingError { at_ms: now_ms(), reason, recovered_bytes, detail });
    }
}
