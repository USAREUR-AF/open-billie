//! Executes the shared OETF map files (`mappings/**/*.json`) in Rust.
//!
//! The subset of the Open Billie translator mapping contract the OETF maps (CAT-062,
//! CoT, SAPIENT) use: `repeats`, `availableIf`, dotted/piped `from`, brace
//! multi-`to`, literal `value`, and the conversions in [`Conv`]. Semantics —
//! presentation stripping, JS `Math.round`, JS `%`, JS `Date` truncation —
//! match the TS engine so the conformance vectors pass.

use std::collections::HashMap;
use std::path::Path;

use serde_json::{Map, Value};

use crate::bundled;
use crate::decoder::DecodedRecord;
use crate::parser::{js_str, num_value};

type Lookups = HashMap<String, HashMap<String, String>>;

#[derive(Debug, Clone)]
enum Conv {
    Scale(f64),
    Offset(f64),
    ScaleOffset(f64, f64),
    Lookup(String),
    ToCanonicalIdentifier(String),
    EpochMicrosToCat062Tod,
    EpochMicrosToIso8601,
    EpochMicrosToProtoTimestamp,
    UintToString,
    ToBoolean,
    NumberToString,
    Negate,
    SpeedMsFromVxy,
    HeadingDegFromVxy,
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn canonical_mapping_preserves_rcs_as_a_namespaced_identifier() {
        let record = DecodedRecord {
            message_name: "Track Report".to_owned(),
            fields: json!({
                "Track count": 1,
                "Track 0 RCS": "-18.3 dBsm"
            })
            .as_object()
            .unwrap()
            .clone(),
            msg_id: 16,
            raw_hex: String::new(),
            decoded_at_ms: 0,
        };
        let translated = Mapper::bundled().translate("oetf", &record, "billie-canonical");
        assert_eq!(
            translated[0].fields["identifiers"],
            json!([{ "scheme": "sapient-object-info", "value": "-18.3" }])
        );
    }

    #[test]
    fn canonical_mapping_preserves_header_and_track_status_flags() {
        let vector: Value = serde_json::from_str(include_str!("../../shared/conformance/vectors/track_report_two_tracks.json")).unwrap();
        let bytes: Vec<u8> = vector["chunks"][0].as_str().unwrap().as_bytes().chunks_exact(2)
            .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap()).collect();
        let records = crate::OetfDecoder::new().feed(&bytes);
        let mapped = Mapper::bundled().translate("oetf", &records[0], "billie-canonical");
        assert_eq!(mapped.len(), 2);
        assert_eq!(mapped[0].fields["confirmed"], true);
        assert_eq!(mapped[0].fields["sourceId"], "263");
        assert_eq!(mapped[0].fields["trackGeneration"], "fixture-1");
        assert_eq!(mapped[0].fields["testData"], false);
        assert_eq!(mapped[0].fields["headerSimulated"], false);
        assert_eq!(mapped[0].fields["simulated"], false);
        assert_eq!(mapped[1].fields["confirmed"], false);
        assert_eq!(mapped[1].fields["coasting"], true);
        assert_eq!(mapped[1].fields["finalUpdate"], true);
        assert_eq!(mapped[1].fields["simulated"], true);
    }
}

struct Binding {
    inputs: Vec<String>,
    literal: Option<Value>,
    outputs: Vec<String>,
    enabled: bool,
    available_if: Option<(String, Value)>,
    via: Vec<Conv>,
}

struct MapDoc {
    source_message: String,
    target_message: String,
    preserve_raw: bool,
    repeats: Option<(String, Option<i64>)>,
    bindings: Vec<Binding>,
}

/// One translated record: `{ messageName, fields, meta.raw? }` as the TS engine emits.
#[derive(Debug, Clone)]
pub struct Translated {
    pub message_name: String,
    pub fields: Value,
    /// `{ messageName, fields }` of the source record when the map sets `preserveRaw`.
    pub raw: Option<Value>,
}

/// Loaded maps + lookup tables.
pub struct Mapper {
    maps: HashMap<(String, String, String), MapDoc>,
    lookups: Lookups,
}

fn decimal(s: &str) -> bool {
    let s = s.strip_prefix('-').unwrap_or(s);
    let (int, frac) = s.split_once('.').map_or((s, None), |(a, b)| (a, Some(b)));
    !int.is_empty() && int.bytes().all(|b| b.is_ascii_digit()) && frac.is_none_or(|f| !f.is_empty() && f.bytes().all(|b| b.is_ascii_digit()))
}

/// `"Label (3)"` → 3, `"152.4 m"` → 152.4, anything else unchanged.
pub fn strip_presentation(v: &Value) -> Value {
    let Value::String(s) = v else { return v.clone() };
    let t = s.trim_end();
    if let Some(inner) = t.strip_suffix(')').and_then(|t| t.rsplit_once('(')).map(|(_, i)| i) {
        if decimal(inner) {
            return num_value(inner.parse().unwrap());
        }
    }
    if let Some((n, rest)) = s.split_once(char::is_whitespace) {
        let unit = rest.trim_start();
        if decimal(n) && !unit.is_empty() && !unit.contains(char::is_whitespace) {
            return num_value(n.parse().unwrap());
        }
    }
    v.clone()
}

fn spec_of(step: &Value) -> Option<String> {
    let name = match step {
        Value::String(s) => return Some(s.clone()),
        Value::Object(o) => o.get("conversion")?.as_str()?,
        _ => return None,
    };
    if name.contains(':') {
        return Some(name.into());
    }
    if let Some(Value::Object(p)) = step.get("params") {
        if p.len() == 1 {
            match p.values().next().unwrap() {
                Value::Number(n) => return Some(format!("{name}:{}", js_str(n.as_f64().unwrap()))),
                Value::String(s) => return Some(format!("{name}:{s}")),
                Value::Bool(b) => return Some(format!("{name}:{b}")),
                _ => {}
            }
        }
    }
    Some(name.into())
}

fn resolve(spec: &str) -> Result<Conv, String> {
    let named = match spec {
        "epochMicrosToCat062TimeOfDay" => Some(Conv::EpochMicrosToCat062Tod),
        "epochMicrosToIso8601" => Some(Conv::EpochMicrosToIso8601),
        "epochMicrosToProtoTimestamp" => Some(Conv::EpochMicrosToProtoTimestamp),
        "uintToString" => Some(Conv::UintToString),
        "toBoolean" => Some(Conv::ToBoolean),
        "numberToString" => Some(Conv::NumberToString),
        "negate" => Some(Conv::Negate),
        "speedMsFromVxy" => Some(Conv::SpeedMsFromVxy),
        "headingDegFromVxy" => Some(Conv::HeadingDegFromVxy),
        _ => None,
    };
    if let Some(c) = named {
        return Ok(c);
    }
    let mut parts = spec.split(':');
    let name = parts.next().unwrap_or_default();
    let args: Vec<&str> = parts.collect();
    let f = |i: usize| args[i].parse::<f64>().map_err(|_| format!("Bad number in conversion {spec}"));
    match (name, args.len()) {
        ("scale", 1) => Ok(Conv::Scale(f(0)?)),
        ("offset", 1) => Ok(Conv::Offset(f(0)?)),
        ("scaleOffset", 2) => Ok(Conv::ScaleOffset(f(0)?, f(1)?)),
        ("lookup", 1) => Ok(Conv::Lookup(args[0].into())),
        ("toCanonicalIdentifier", 1) => Ok(Conv::ToCanonicalIdentifier(args[0].into())),
        _ => Err(format!("Unsupported conversion: {spec}")),
    }
}

fn targets(to: &str) -> Vec<String> {
    let Some(brace) = to.find('{') else { return vec![to.into()] };
    let end = to.find('}').unwrap_or(to.len());
    to[brace + 1..end].split(',').map(|s| format!("{}{}", &to[..brace], s.trim())).collect()
}

fn read<'a>(obj: &'a Map<String, Value>, path: &str) -> Option<&'a Value> {
    if let Some(v) = obj.get(path) {
        return Some(v);
    }
    let mut parts = path.split('.');
    let mut cur = obj.get(parts.next()?)?;
    for p in parts {
        cur = cur.as_object()?.get(p)?;
    }
    Some(cur)
}

fn write(obj: &mut Map<String, Value>, path: &str, value: Value) {
    let mut parts: Vec<&str> = path.split('.').collect();
    let leaf = parts.pop().unwrap();
    let mut cur = obj;
    for p in parts {
        let slot = cur.entry(p).or_insert_with(|| Value::Object(Map::new()));
        if !slot.is_object() {
            *slot = Value::Object(Map::new());
        }
        cur = slot.as_object_mut().unwrap();
    }
    cur.insert(leaf.into(), value);
}

fn idx(name: &str, n: Option<usize>) -> String {
    n.map_or(name.into(), |n| name.replace("{n}", &n.to_string()))
}

fn same_number_or_value(a: &Value, b: &Value) -> bool {
    match (a.as_f64(), b.as_f64()) {
        (Some(x), Some(y)) => x == y,
        _ => a == b,
    }
}

/// JS `Number(v)` for the inputs the epoch conversions accept.
fn js_number(v: &Value) -> f64 {
    match v {
        Value::Number(n) => n.as_f64().unwrap_or(f64::NAN),
        Value::String(s) => s.trim().parse().unwrap_or(f64::NAN),
        _ => f64::NAN,
    }
}

/// JS `asNum`: numbers pass, strings yield their leading decimal, else NaN.
fn as_num(v: &Value) -> f64 {
    match v {
        Value::Number(n) => n.as_f64().unwrap_or(f64::NAN),
        Value::String(s) => {
            // Mirrors /^(-?\d+(?:\.\d+)?)/.
            let b = s.as_bytes();
            let digits = |from: usize| from + b[from..].iter().take_while(|c| c.is_ascii_digit()).count();
            let int_start = usize::from(b.first() == Some(&b'-'));
            let mut end = digits(int_start);
            if end == int_start {
                return f64::NAN;
            }
            if b.get(end) == Some(&b'.') && digits(end + 1) > end + 1 {
                end = digits(end + 1);
            }
            s[..end].parse().unwrap_or(f64::NAN)
        }
        _ => f64::NAN,
    }
}

fn pair(v: &Value) -> Option<(f64, f64)> {
    let a = v.as_array().filter(|a| a.len() == 2)?;
    let (x, y) = (as_num(&a[0]), as_num(&a[1]));
    (!x.is_nan() && !y.is_nan()).then_some((x, y))
}

/// `YYYY-MM-DDTHH:MM:SS.mmmZ` for whole milliseconds since the epoch, as JS `Date#toISOString`.
fn iso8601(ms: i64) -> String {
    let (days, rem) = (ms.div_euclid(86_400_000), ms.rem_euclid(86_400_000));
    // Howard Hinnant's civil_from_days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}.{:03}Z",
        rem / 3_600_000,
        rem / 60_000 % 60,
        rem / 1000 % 60,
        rem % 1000
    )
}

fn run(conv: &Conv, v: Value, lookups: &Lookups) -> Value {
    let num = v.as_f64();
    match conv {
        Conv::UintToString => match &v {
            Value::Number(n) => Value::from(js_str(n.as_f64().unwrap().trunc())),
            Value::String(_) => v,
            other => Value::from(other.to_string()),
        },
        Conv::ToBoolean => match &v {
            Value::Bool(_) => v,
            _ if num == Some(0.0) => Value::Bool(false),
            _ if num == Some(1.0) => Value::Bool(true),
            _ => Value::Null,
        },
        Conv::NumberToString => num.map_or(v, |x| Value::from(js_str(x))),
        Conv::Negate => num.map_or(v, |x| Value::from(-x)),
        Conv::SpeedMsFromVxy => pair(&v).map_or(v, |(x, y)| Value::from((x * x + y * y).sqrt())),
        Conv::HeadingDegFromVxy => match pair(&v) {
            None => v,
            Some((x, y)) if x == 0.0 && y == 0.0 => Value::from(0),
            Some((x, y)) => {
                let deg = (x.atan2(y) * (180.0 / std::f64::consts::PI) + 360.0) % 360.0;
                num_value((deg + 0.5).floor() % 360.0)
            }
        },
        Conv::EpochMicrosToIso8601 => {
            let us = js_number(&v);
            if !us.is_finite() {
                return v;
            }
            Value::from(iso8601((us / 1000.0).trunc() as i64)) // JS Date truncates to whole ms
        }
        Conv::EpochMicrosToProtoTimestamp => {
            let us = js_number(&v);
            if !us.is_finite() {
                return v;
            }
            let seconds = (us / 1_000_000.0).floor();
            serde_json::json!({ "seconds": num_value(seconds), "nanos": num_value((us - seconds * 1_000_000.0) * 1_000.0) })
        }
        Conv::Scale(n) => num.map_or(v, |x| Value::from(x * n)),
        Conv::Offset(n) => num.map_or(v, |x| Value::from(x + n)),
        Conv::ScaleOffset(s, o) => num.map_or(v, |x| Value::from(x * s + o)),
        Conv::ToCanonicalIdentifier(scheme) => {
            let value = match &v {
                Value::Number(number) => js_str(number.as_f64().unwrap_or_default()),
                Value::String(text) => text.clone(),
                _ => return Value::Null,
            };
            serde_json::json!([{ "scheme": scheme, "value": value }])
        }
        Conv::Lookup(table) => {
            let Some(t) = lookups.get(table) else { return v };
            let key = match &v {
                Value::String(s) => s.clone(),
                other => other.as_f64().map_or_else(|| other.to_string(), js_str),
            };
            let raw_key = key
                .trim_end()
                .strip_suffix(')')
                .and_then(|k| k.rsplit_once('('))
                .map(|(_, i)| i)
                .filter(|i| decimal(i) && !i.contains('.'))
                .unwrap_or(&key);
            t.get(raw_key).map_or(v.clone(), |l| Value::from(l.clone()))
        }
        Conv::EpochMicrosToCat062Tod => {
            let us = js_number(&v);
            if !us.is_finite() {
                return v;
            }
            let total_ms = us / 1000.0;
            let day_ms = ((total_ms % 86_400_000.0) + 86_400_000.0) % 86_400_000.0; // JS `%` == fmod
            num_value((day_ms * 0.128 + 0.5).floor()) // JS Math.round
        }
    }
}

impl Mapper {
    /// Mapper over the maps and lookups embedded at build time.
    pub fn bundled() -> Self {
        Self::from_texts(bundled::MAPS.iter().map(|(_, t)| *t), bundled::LOOKUPS.iter().copied())
            .expect("embedded maps are valid")
    }

    /// Mapper over map/lookup files on disk (e.g. a deployment overlay).
    pub fn from_dirs(mappings_dir: &Path, lookups_dir: &Path) -> Result<Self, String> {
        fn walk(dir: &Path, out: &mut Vec<std::path::PathBuf>) -> std::io::Result<()> {
            for e in std::fs::read_dir(dir)? {
                let p = e?.path();
                if p.is_dir() {
                    walk(&p, out)?;
                } else if p.extension().is_some_and(|x| x == "json") && !p.file_name().unwrap().to_string_lossy().starts_with('_') {
                    out.push(p);
                }
            }
            Ok(())
        }
        let (mut maps, mut tables) = (Vec::new(), Vec::new());
        walk(mappings_dir, &mut maps).map_err(|e| e.to_string())?;
        walk(lookups_dir, &mut tables).map_err(|e| e.to_string())?;
        let read = |p: &std::path::PathBuf| std::fs::read_to_string(p).map_err(|e| e.to_string());
        let map_texts = maps.iter().map(read).collect::<Result<Vec<_>, _>>()?;
        let table_texts = tables
            .iter()
            .map(|p| Ok((p.file_name().unwrap().to_string_lossy().into_owned(), read(p)?)))
            .collect::<Result<Vec<_>, String>>()?;
        Self::from_texts(map_texts.iter().map(String::as_str), table_texts.iter().map(|(n, t)| (n.as_str(), t.as_str())))
    }

    fn from_texts<'a>(
        maps: impl Iterator<Item = &'a str>,
        lookups: impl Iterator<Item = (&'a str, &'a str)>,
    ) -> Result<Self, String> {
        let lookups = lookups
            .map(|(file, text)| {
                let name = file.rsplit('/').next().unwrap().trim_end_matches(".json").to_owned();
                serde_json::from_str(text).map(|t| (name, t)).map_err(|e| format!("lookup {file}: {e}"))
            })
            .collect::<Result<Lookups, _>>()?;
        let mut out = HashMap::new();
        for text in maps {
            let doc: Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
            let s = |v: &Value| v.as_str().unwrap_or_default().to_owned();
            let mut bindings = Vec::new();
            for m in doc["mappings"].as_array().into_iter().flatten() {
                let inputs: Vec<String> = m["from"].as_str().unwrap_or_default().split('|').filter(|s| !s.is_empty()).map(Into::into).collect();
                let steps: Vec<Value> = match (&m["via"], &m["conversion"]) {
                    (Value::Array(a), _) => a.clone(),
                    (_, Value::String(c)) => vec![Value::from(c.clone())],
                    _ => vec![],
                };
                let via = steps
                    .iter()
                    .filter_map(spec_of)
                    .filter(|s| s != "none")
                    .map(|s| resolve(&s))
                    .collect::<Result<_, _>>()?;
                bindings.push(Binding {
                    literal: m.get("value").filter(|_| inputs.is_empty()).cloned(),
                    inputs,
                    outputs: targets(m["to"].as_str().unwrap_or_default()),
                    enabled: m["enabled"].as_bool().unwrap_or(true),
                    available_if: m.get("availableIf").map(|a| (s(&a["field"]), a["equals"].clone())),
                    via,
                });
            }
            let key = (s(&doc["source"]["protocol"]), s(&doc["source"]["message"]), s(&doc["target"]["protocol"]));
            out.insert(key, MapDoc {
                source_message: s(&doc["source"]["message"]),
                target_message: s(&doc["target"]["message"]),
                preserve_raw: doc["preserveRaw"].as_bool().unwrap_or(true),
                repeats: doc.get("repeats").map(|r| (s(&r["field"]), r["max"].as_i64())),
                bindings,
            });
        }
        Ok(Self { maps: out, lookups })
    }

    pub fn has_mapping(&self, protocol: &str, message: &str, target: &str) -> bool {
        self.maps.contains_key(&(protocol.into(), message.into(), target.into()))
    }

    /// One output per repeat index; empty when no map exists for the pair.
    pub fn translate(&self, protocol: &str, record: &DecodedRecord, target: &str) -> Vec<Translated> {
        let Some(m) = self.maps.get(&(protocol.into(), record.message_name.clone(), target.into())) else {
            return Vec::new();
        };
        match &m.repeats {
            None => vec![self.one(m, record, None)],
            Some((field, max)) => {
                let raw = read(&record.fields, field).map(strip_presentation);
                let mut n = match &raw {
                    Some(Value::Number(x)) => x.as_f64().unwrap_or(0.0).floor().max(0.0) as i64,
                    Some(Value::String(s)) => s.trim().parse::<i64>().unwrap_or(0).max(0),
                    _ => 0,
                };
                if let Some(max) = max {
                    n = n.min(*max);
                }
                (0..n as usize).map(|i| self.one(m, record, Some(i))).collect()
            }
        }
    }

    fn one(&self, m: &MapDoc, record: &DecodedRecord, n: Option<usize>) -> Translated {
        let mut out = Map::new();
        for b in m.bindings.iter().filter(|b| b.enabled) {
            if let Some((field, equals)) = &b.available_if {
                let got = read(&record.fields, &idx(field, n)).map(strip_presentation).unwrap_or(Value::Null);
                if !same_number_or_value(&got, equals) {
                    continue;
                }
            }
            let vals = if let Some(lit) = &b.literal {
                vec![lit.clone()]
            } else {
                let raws: Option<Vec<Value>> = b.inputs.iter().map(|i| read(&record.fields, &idx(i, n)).map(strip_presentation)).collect();
                let Some(mut raws) = raws else { continue };
                let mut cur = if raws.len() > 1 { Value::Array(raws) } else { raws.remove(0) };
                for step in &b.via {
                    cur = run(step, cur, &self.lookups);
                    if cur.is_null() {
                        break;
                    }
                }
                if cur.is_null() {
                    continue;
                }
                match (b.outputs.len() > 1, cur) {
                    (true, Value::Array(a)) => a,
                    (true, _) => continue,
                    (false, v) => vec![v],
                }
            };
            for (path, v) in b.outputs.iter().zip(vals) {
                if !v.is_null() {
                    write(&mut out, path, v);
                }
            }
        }
        Translated {
            message_name: m.target_message.clone(),
            fields: Value::Object(out),
            raw: m.preserve_raw.then(|| {
                serde_json::json!({ "messageName": m.source_message, "fields": record.fields })
            }),
        }
    }
}
