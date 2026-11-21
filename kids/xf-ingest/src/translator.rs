//! The `billie:` output endpoint: each converted Canonical Track v2 record
//! becomes one translation request per declared output, sent to the Open
//! Billie translator's local socket.

use std::io::{BufRead, BufReader, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use goat_adapters_core::frame::Framing;
use goat_adapters_core::{AdapterError, Meta, Sink, Source};
use goat_adapters_std::uri::{Scheme, Uri};
use serde_json::{json, Value};

const MAX_RESPONSE_BYTES: usize = 64 * 1024;

/// The Billie track-class v1 vocabulary (`schemas/canonical-track-v2.schema.json`,
/// `classification`). The translator refuses any other value.
pub const TRACK_CLASSES: [&str; 9] = [
    "unknown",
    "fixed-wing-aircraft",
    "rotary-wing-aircraft",
    "uas",
    "balloon",
    "bird",
    "vehicle",
    "clutter",
    "other",
];

/// Remove a `classification` outside [`TRACK_CLASSES`], returning the value
/// removed. A conversion from CoT writes a CoT type that has no Billie class
/// (`a-f-G`) as it is; the rest of the track is still valid.
pub fn drop_unknown_class(record: &mut Value) -> Option<String> {
    let class = record.get("classification")?.as_str().map(str::to_owned);
    match class {
        Some(class) if TRACK_CLASSES.contains(&class.as_str()) => None,
        other => {
            record.as_object_mut()?.remove("classification");
            Some(other.unwrap_or_else(|| "(not text)".into()))
        }
    }
}
static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

/// Where the translator is and what this kid publishes through it.
#[derive(Debug, Clone)]
pub struct Translator {
    pub kid: String,
    pub socket: PathBuf,
    /// `(output name, format)`, as declared in `interfaces.outputs`.
    pub outputs: Vec<(String, String)>,
}

/// Parse `name:format,name:format`.
pub fn parse_outputs(text: &str) -> Result<Vec<(String, String)>, String> {
    let outputs: Vec<(String, String)> = text
        .split(',')
        .map(|pair| {
            pair.trim()
                .split_once(':')
                .filter(|(name, format)| !name.is_empty() && !format.is_empty())
                .map(|(name, format)| (name.to_owned(), format.to_owned()))
                .ok_or_else(|| format!("output '{pair}' is not name:format"))
        })
        .collect::<Result<_, _>>()?;
    if outputs.is_empty() {
        return Err("no output declared".into());
    }
    Ok(outputs)
}

/// The request the translator expects for one record and one output.
pub fn translation_request(
    kid: &str,
    request_id: &str,
    output_name: &str,
    format: &str,
    record: &Value,
) -> Value {
    json!({
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateRequest",
        "requestId": request_id,
        "kid": kid,
        "target": { "outputName": output_name, "format": format },
        "record": record,
    })
}

fn request_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let sequence = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("{}-{nanos}-{sequence}", std::process::id())
}

fn fail(kind: &str, msg: impl Into<String>) -> AdapterError {
    AdapterError::new(kind, msg)
}

impl Translator {
    /// Send one record for one output and check the translator published it.
    fn send_one(&self, output: &str, format: &str, record: &Value) -> Result<(), AdapterError> {
        let id = request_id();
        let mut bytes =
            serde_json::to_vec(&translation_request(&self.kid, &id, output, format, record))
                .map_err(|e| fail("translator-request", e.to_string()))?;
        bytes.push(b'\n');
        let io =
            |e: std::io::Error| fail("translator-io", format!("{}: {e}", self.socket.display()));
        let mut stream = UnixStream::connect(&self.socket).map_err(io)?;
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .map_err(io)?;
        stream
            .set_write_timeout(Some(Duration::from_secs(10)))
            .map_err(io)?;
        stream.write_all(&bytes).map_err(io)?;
        stream.flush().map_err(io)?;
        let mut response = Vec::new();
        let read = BufReader::new(stream)
            .take((MAX_RESPONSE_BYTES + 1) as u64)
            .read_until(b'\n', &mut response)
            .map_err(io)?;
        if read == 0 || read > MAX_RESPONSE_BYTES || response.last() != Some(&b'\n') {
            return Err(fail(
                "translator-response",
                "empty, oversized or unterminated response",
            ));
        }
        let result: Value = serde_json::from_slice(&response[..response.len() - 1])
            .map_err(|e| fail("translator-response", e.to_string()))?;
        if result["requestId"] != id.as_str() {
            return Err(fail("translator-response", "requestId did not match"));
        }
        if result["status"] != "published" {
            let code = result["error"]["code"].as_str().unwrap_or("unknown");
            let message = result["error"]["message"].as_str().unwrap_or("no detail");
            return Err(fail(
                &format!("translator-{code}"),
                format!("output {output}: {message}"),
            ));
        }
        Ok(())
    }
}

/// The sink: one record in, one request per output.
struct TranslatorSink {
    translator: Translator,
    /// Classifications already reported as removed, so each is printed once.
    dropped: std::collections::BTreeSet<String>,
}

impl Sink for TranslatorSink {
    fn send(&mut self, bytes: &[u8], _meta: &Meta) -> Result<(), AdapterError> {
        let mut record: Value =
            serde_json::from_slice(bytes).map_err(|e| fail("not-canonical-json", e.to_string()))?;
        if let Some(class) = drop_unknown_class(&mut record) {
            if self.dropped.len() < 64 && self.dropped.insert(class.clone()) {
                eprintln!(
                    "billie-xf-ingest: classification '{class}' is not a Billie track class; sent without classification (reported once per value)"
                );
            }
        }
        // Every output is tried; the first refusal is reported.
        let mut first_error = None;
        for (output, format) in &self.translator.outputs {
            if let Err(error) = self.translator.send_one(output, format, &record) {
                first_error.get_or_insert(error);
            }
        }
        first_error.map_or(Ok(()), Err)
    }

    fn describe(&self) -> String {
        format!("billie:{}", self.translator.socket.display())
    }
}

impl Scheme for Translator {
    fn name(&self) -> &'static str {
        "billie"
    }

    fn help(&self) -> &'static str {
        "billie:   the Open Billie translator socket, one request per declared output (output only)"
    }

    fn source(&self, uri: &Uri, _frame: Option<&Framing>) -> Result<Box<dyn Source>, AdapterError> {
        Err(uri.err("billie: is an output only"))
    }

    fn sink(&self, uri: &Uri, _frame: Option<&Framing>) -> Result<Box<dyn Sink>, AdapterError> {
        uri.allow(&[])?;
        Ok(Box::new(TranslatorSink {
            translator: self.clone(),
            dropped: Default::default(),
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn outputs_parse_as_name_format_pairs() {
        assert_eq!(
            parse_outputs("tracks-cot:cot, tracks-cat062:asterix-cat062").unwrap(),
            [
                ("tracks-cot".to_string(), "cot".to_string()),
                ("tracks-cat062".to_string(), "asterix-cat062".to_string())
            ]
        );
        assert!(parse_outputs("tracks-cot").is_err());
        assert!(parse_outputs(":cot").is_err());
    }

    #[test]
    fn only_a_class_outside_the_vocabulary_is_removed() {
        let mut record = json!({"trackId": "7", "classification": "a-f-G"});
        assert_eq!(drop_unknown_class(&mut record).as_deref(), Some("a-f-G"));
        assert_eq!(record, json!({"trackId": "7"}));
        let mut record = json!({"trackId": "7", "classification": "uas"});
        assert_eq!(drop_unknown_class(&mut record), None);
        assert_eq!(record["classification"], "uas");
        let mut record = json!({"trackId": "7"});
        assert_eq!(drop_unknown_class(&mut record), None);
    }

    #[test]
    fn a_request_carries_the_record_unchanged() {
        let record = json!({"trackId": "7"});
        let request = translation_request("xf-ingest", "r1", "tracks-cot", "cot", &record);
        assert_eq!(request["record"], record);
        assert_eq!(request["target"]["format"], "cot");
        assert_eq!(request["kid"], "xf-ingest");
    }
}
