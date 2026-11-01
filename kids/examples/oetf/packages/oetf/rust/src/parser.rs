//! Schema-driven byte reader — a port of the TypeScript `parser.ts`.
//!
//! Reads the shared `schemas/*.json` and produces the same `fields` map,
//! including presentation strings, so numbers are stringified with
//! JavaScript's `Number#toString` rules ([`js_str`]).

use serde_json::{Map, Value};

/// Stringify a number exactly as JavaScript's `String(n)` does.
pub fn js_str(x: f64) -> String {
    if x.is_nan() {
        return "NaN".into();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity".into() } else { "-Infinity".into() };
    }
    if x == 0.0 {
        return "0".into();
    }
    let a = x.abs();
    if (1e-6..1e21).contains(&a) {
        // Rust's Display is shortest round-trip and positional — same digits as JS.
        return format!("{x}");
    }
    let s = format!("{x:e}");
    match s.split_once('e') {
        Some((m, e)) if !e.starts_with('-') => format!("{m}e+{e}"),
        _ => s,
    }
}

/// A number as JSON: integral values become JSON integers, others floats.
pub fn num_value(x: f64) -> Value {
    if x.fract() == 0.0 && x.abs() < 9_007_199_254_740_992.0 {
        Value::from(x as i64)
    } else {
        Value::from(x)
    }
}

enum Raw {
    Int(i64),
    Float(f64),
    Big(u64),
}

fn size_of(ty: &str) -> Option<usize> {
    Some(match ty {
        "uint8" | "int8" => 1,
        "uint16" | "int16" => 2,
        "uint32" | "int32" | "real32" => 4,
        "uint48" => 6,
        "uint64" | "real64" => 8,
        _ => return None,
    })
}

fn read(frame: &[u8], offset: usize, ty: &str, little: bool) -> Result<Raw, String> {
    let n = size_of(ty).ok_or_else(|| format!("Unknown type: {ty}"))?;
    let b = &frame[offset..offset + n];
    let mut buf = [0u8; 8];
    if little {
        buf[..n].copy_from_slice(b);
    } else {
        for (i, v) in b.iter().rev().enumerate() {
            buf[i] = *v;
        }
    }
    let u = u64::from_le_bytes(buf);
    Ok(match ty {
        "uint8" | "uint16" | "uint32" | "uint48" => Raw::Int(u as i64),
        "int8" => Raw::Int(u as u8 as i8 as i64),
        "int16" => Raw::Int(u as u16 as i16 as i64),
        "int32" => Raw::Int(u as u32 as i32 as i64),
        "real32" => Raw::Float(f32::from_bits(u as u32) as f64),
        "real64" => Raw::Float(f64::from_bits(u)),
        "uint64" => Raw::Big(u),
        _ => unreachable!(),
    })
}

fn label(values: Option<&Value>, key: &str) -> Option<String> {
    values?.get(key)?.as_str().map(str::to_owned)
}

/// Decode every field in `schema` from `frame`. Mirrors `MessageParser.parse`.
pub fn parse(frame: &[u8], schema: &Value, little: bool) -> Result<Map<String, Value>, String> {
    let mut result = Map::new();
    let mut raw_bits: std::collections::HashMap<String, std::collections::HashMap<String, i64>> = Default::default();
    let mut raw_fields: std::collections::HashMap<String, f64> = Default::default();
    let fields = schema["fields"].as_array().ok_or("schema has no fields")?;

    for field in fields {
        let name = field["name"].as_str().ok_or("field without name")?.to_owned();
        let ty = field["type"].as_str().ok_or("field without type")?;
        let offset = field["offset"].as_u64().ok_or("field without offset")? as usize;

        if let Some(v) = field.get("validIf") {
            let parent = v["field"].as_str().unwrap_or_default();
            if let Some(bit) = v.get("bit").and_then(Value::as_str) {
                if raw_bits.get(parent).and_then(|b| b.get(bit)) != Some(&1) {
                    result.insert(name, "(invalid)".into());
                    continue;
                }
            } else if let Some(min) = v.get("minCount").and_then(Value::as_f64) {
                if !raw_fields.get(parent).is_some_and(|c| *c >= min) {
                    result.insert(name, "(not present)".into());
                    continue;
                }
            }
        }

        let size = size_of(ty).ok_or_else(|| format!("Unknown type: {ty}"))?;
        if offset + size > frame.len() {
            result.insert(name, "(beyond message)".into());
            continue;
        }
        let raw = read(frame, offset, ty, little)?;

        if let Some(bits) = field.get("bits").and_then(Value::as_array).filter(|b| !b.is_empty()) {
            let whole: u64 = match raw {
                Raw::Int(i) => i as u64,
                Raw::Big(u) => u,
                Raw::Float(f) => f as u64,
            };
            let mut out = Map::new();
            let mut by_name = std::collections::HashMap::new();
            for b in bits {
                let bname = b["name"].as_str().unwrap_or_default().to_owned();
                let start = b["bitStart"].as_u64().unwrap_or(0);
                let len = b["length"].as_u64().unwrap_or(1);
                let mask = if len >= 64 { u64::MAX } else { (1u64 << len) - 1 };
                let v = ((whole >> start) & mask) as i64;
                by_name.insert(bname.clone(), v);
                let key = v.to_string();
                let mut resolved = Value::from(v);
                if let Some(l) = label(b.get("values"), &key) {
                    resolved = format!("{l} ({v})").into();
                } else if let Some(vb) = b.get("valuesBy") {
                    let names: Vec<&str> = match &vb["field"] {
                        Value::Array(a) => a.iter().filter_map(Value::as_str).collect(),
                        Value::String(s) => vec![s.as_str()],
                        _ => vec![],
                    };
                    let ctx = names
                        .iter()
                        .map(|n| by_name.get(*n).map_or("undefined".to_owned(), i64::to_string))
                        .collect::<Vec<_>>()
                        .join(".");
                    if let Some(l) = label(vb["map"].get(&ctx), &key) {
                        resolved = format!("{l} ({v})").into();
                    }
                }
                out.insert(bname, resolved);
            }
            out.insert("_raw".into(), num_value(whole as f64));
            raw_bits.insert(name.clone(), by_name);
            result.insert(name, Value::Object(out));
            continue;
        }

        // `num` is either a JS number or (for uint64) a decimal string.
        let x = match raw {
            Raw::Big(u) => {
                // uint64 stays a decimal string (JS bigint); never scaled or counted.
                let s = u.to_string();
                result.insert(name, present(field, Value::from(s.clone()), &s));
                continue;
            }
            Raw::Int(i) => i as f64,
            Raw::Float(f) => f,
        };
        raw_fields.insert(name.clone(), x);
        let x = field.get("scale").and_then(Value::as_f64).map_or(x, |s| x * s);
        result.insert(name, present(field, num_value(x), &js_str(x)));
    }
    Ok(result)
}

/// Apply the schema's `values` label or `units` suffix, as the TS parser does.
fn present(field: &Value, num: Value, key: &str) -> Value {
    if let Some(l) = label(field.get("values"), key) {
        format!("{l} ({key})").into()
    } else if let Some(units) = field.get("units").and_then(Value::as_str).filter(|u| !u.is_empty()) {
        format!("{key} {units}").into()
    } else {
        num
    }
}
