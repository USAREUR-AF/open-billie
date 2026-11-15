//! Executes this kid's mapping files (`mappings/**/*.json`).
//!
//! A mapping file binds the fields of one decoded message to Canonical Track
//! v2. This engine runs the part of the mapping-contract shape that a
//! fixed-layout message needs: literal `value`, `from` a decoded field or a
//! runtime value, dotted `to`, `enabled`, and the conversions in [`Conv`].
//! Repeats and conditional bindings are not implemented.
//!
//! `from` names a field of the dictionary message, or one of three values the
//! runtime supplies:
//!
//! | `from` | Value |
//! |---|---|
//! | `$receivedAt` | when the datagram arrived, RFC 3339 UTC |
//! | `$interface` | the dictionary interface name |
//! | `$message` | the message name |

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

use crate::decoder::Record;

/// The target protocol name of a map that produces Canonical Track v2.
pub const CANONICAL_TARGET: &str = "billie-canonical";

/// Fields the translator requires in every Canonical Track v2 record. A record
/// without one of them is not sent.
const REQUIRED: [&str; 11] = [
    "apiVersion",
    "kind",
    "trackId",
    "sourceId",
    "trackGeneration",
    "observedAt",
    "testData",
    "headerSimulated",
    "simulated",
    "position.latitudeDeg",
    "position.longitudeDeg",
];

type Lookups = HashMap<String, HashMap<String, Value>>;

#[derive(Debug, Clone, PartialEq)]
enum Conv {
    /// Multiply a number.
    Scale(f64),
    /// Add to a number.
    Offset(f64),
    /// Replace a value by its entry in a lookup table. A value with no entry
    /// drops the binding.
    Lookup(String),
    /// `0`/`1`/`false`/`true` to a JSON boolean; anything else drops the
    /// binding.
    ToBoolean,
    /// A number or boolean to its text.
    ToString,
}

#[derive(Debug)]
struct Binding {
    from: Option<String>,
    literal: Option<Value>,
    to: String,
    via: Vec<Conv>,
}

#[derive(Debug)]
struct MapDoc {
    bindings: Vec<Binding>,
}

/// The result of mapping one record.
#[derive(Debug, Clone, PartialEq)]
pub struct Mapped {
    /// The Canonical Track v2 record, as far as the bindings filled it.
    pub track: Value,
    /// Required canonical fields the mapping left empty. The record is sent
    /// only when this is empty.
    pub missing: Vec<&'static str>,
}

/// Loaded maps and lookup tables.
#[derive(Debug)]
pub struct Mapper {
    maps: HashMap<String, MapDoc>,
    lookups: Lookups,
}

fn json_files(directory: &Path, out: &mut Vec<PathBuf>) -> Result<(), String> {
    let entries =
        std::fs::read_dir(directory).map_err(|e| format!("{}: {e}", directory.display()))?;
    for entry in entries {
        let path = entry
            .map_err(|e| format!("{}: {e}", directory.display()))?
            .path();
        if path.is_dir() {
            json_files(&path, out)?;
        } else if path
            .extension()
            .is_some_and(|extension| extension == "json")
        {
            out.push(path);
        }
    }
    Ok(())
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn conversion(step: &Value) -> Result<Option<Conv>, String> {
    let name = match step {
        Value::String(name) => name.as_str(),
        Value::Object(step) => step
            .get("conversion")
            .and_then(Value::as_str)
            .ok_or("a via step needs a \"conversion\" name")?,
        _ => return Err("a via step must be a name or an object".to_owned()),
    };
    // The first value under `params`, whatever its key, as the OETF maps
    // write it: {"conversion": "scale", "params": {"factor": 0.01}}.
    let param = step
        .get("params")
        .and_then(Value::as_object)
        .and_then(|params| params.values().next());
    let number = || {
        param
            .and_then(Value::as_f64)
            .ok_or_else(|| format!("conversion {name} needs one numeric parameter"))
    };
    Ok(Some(match name {
        "none" => return Ok(None),
        "scale" => Conv::Scale(number()?),
        "offset" => Conv::Offset(number()?),
        "lookup" => Conv::Lookup(
            param
                .and_then(Value::as_str)
                .ok_or("conversion lookup needs a table name")?
                .to_owned(),
        ),
        "toBoolean" => Conv::ToBoolean,
        "toString" => Conv::ToString,
        other => return Err(format!("unsupported conversion: {other}")),
    }))
}

fn text(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.clone()),
        Value::Bool(flag) => Some(flag.to_string()),
        Value::Number(number) => Some(match (number.as_u64(), number.as_i64()) {
            (Some(unsigned), _) => unsigned.to_string(),
            (_, Some(signed)) => signed.to_string(),
            _ => number.as_f64()?.to_string(),
        }),
        _ => None,
    }
}

fn run(conv: &Conv, value: Value, lookups: &Lookups) -> Value {
    match conv {
        Conv::Scale(factor) => value
            .as_f64()
            .map_or(Value::Null, |x| Value::from(x * factor)),
        Conv::Offset(addend) => value
            .as_f64()
            .map_or(Value::Null, |x| Value::from(x + addend)),
        Conv::Lookup(table) => text(&value)
            .and_then(|key| lookups.get(table)?.get(&key).cloned())
            .unwrap_or(Value::Null),
        Conv::ToBoolean => match &value {
            Value::Bool(_) => value,
            _ if value.as_f64() == Some(0.0) => Value::Bool(false),
            _ if value.as_f64() == Some(1.0) => Value::Bool(true),
            _ => Value::Null,
        },
        Conv::ToString => text(&value).map_or(Value::Null, Value::from),
    }
}

fn write(object: &mut Map<String, Value>, path: &str, value: Value) {
    let mut parts: Vec<&str> = path.split('.').collect();
    let leaf = parts.pop().unwrap_or(path);
    let mut current = object;
    for part in parts {
        let slot = current
            .entry(part)
            .or_insert_with(|| Value::Object(Map::new()));
        if !slot.is_object() {
            *slot = Value::Object(Map::new());
        }
        current = slot.as_object_mut().expect("just made an object");
    }
    current.insert(leaf.to_owned(), value);
}

fn present(track: &Value, path: &str) -> bool {
    let mut current = track;
    for part in path.split('.') {
        match current.get(part) {
            Some(next) => current = next,
            None => return false,
        }
    }
    match current {
        Value::Null => false,
        Value::String(text) => !text.is_empty(),
        _ => true,
    }
}

impl Mapper {
    /// Load every `*.json` map under `mappings` whose target is
    /// [`CANONICAL_TARGET`], and every `*.json` table under `lookups`. A
    /// lookup table is named by its file stem.
    pub fn from_dirs(mappings: &Path, lookups: &Path) -> Result<Self, String> {
        let (mut map_files, mut table_files) = (Vec::new(), Vec::new());
        json_files(mappings, &mut map_files)?;
        if lookups.is_dir() {
            json_files(lookups, &mut table_files)?;
        }
        let mut tables = Lookups::new();
        for path in table_files {
            let table = read_json(&path)?
                .as_object()
                .ok_or_else(|| format!("{}: a lookup table is a JSON object", path.display()))?
                .clone()
                .into_iter()
                .collect();
            let name = path.file_stem().unwrap_or_default().to_string_lossy();
            tables.insert(name.into_owned(), table);
        }
        map_files.sort();
        let mut maps = HashMap::new();
        for path in map_files {
            let doc = read_json(&path)?;
            if doc["target"]["protocol"] != CANONICAL_TARGET || doc["enabled"] == false {
                continue;
            }
            let message = doc["source"]["message"]
                .as_str()
                .ok_or_else(|| format!("{}: source.message is missing", path.display()))?;
            let mut bindings = Vec::new();
            for entry in doc["mappings"].as_array().into_iter().flatten() {
                if entry["enabled"] == false {
                    continue;
                }
                let at = |problem: String| format!("{}: {problem}", path.display());
                let to = entry["to"]
                    .as_str()
                    .filter(|to| !to.is_empty())
                    .ok_or_else(|| at("a binding needs \"to\"".to_owned()))?;
                let from = entry["from"].as_str().map(str::to_owned);
                let literal = entry.get("value").cloned();
                if from.is_some() == literal.is_some() {
                    return Err(at(format!(
                        "binding to {to} needs exactly one of \"from\" and \"value\""
                    )));
                }
                let mut via = Vec::new();
                for step in entry["via"].as_array().into_iter().flatten() {
                    if let Some(conv) = conversion(step).map_err(at)? {
                        if let Conv::Lookup(table) = &conv {
                            if !tables.contains_key(table) {
                                return Err(at(format!("lookup table {table} is not in lookups/")));
                            }
                        }
                        via.push(conv);
                    }
                }
                bindings.push(Binding {
                    from,
                    literal,
                    to: to.to_owned(),
                    via,
                });
            }
            // A generated map whose bindings are all still disabled maps
            // nothing.
            if bindings.is_empty() {
                continue;
            }
            if maps
                .insert(message.to_owned(), MapDoc { bindings })
                .is_some()
            {
                return Err(format!(
                    "{}: a second map for message {message}",
                    path.display()
                ));
            }
        }
        Ok(Self {
            maps,
            lookups: tables,
        })
    }

    /// The messages that have a map.
    pub fn mapped_messages(&self) -> Vec<&str> {
        let mut names: Vec<&str> = self.maps.keys().map(String::as_str).collect();
        names.sort_unstable();
        names
    }

    /// Map one decoded record. `None` when its message has no map: the
    /// message is decoded and produces no track.
    pub fn translate(&self, record: &Record, received_at: &str) -> Option<Mapped> {
        let map = self.maps.get(&record.message)?;
        let mut out = Map::new();
        for binding in &map.bindings {
            let mut value = match (&binding.literal, binding.from.as_deref()) {
                (Some(literal), _) => literal.clone(),
                (None, Some("$receivedAt")) => Value::from(received_at),
                (None, Some("$interface")) => Value::from(record.interface.as_str()),
                (None, Some("$message")) => Value::from(record.message.as_str()),
                (None, Some(field)) => record.fields.get(field).cloned().unwrap_or(Value::Null),
                (None, None) => Value::Null,
            };
            for conv in &binding.via {
                if value.is_null() {
                    break;
                }
                value = run(conv, value, &self.lookups);
            }
            if !value.is_null() {
                write(&mut out, &binding.to, value);
            }
        }
        let track = Value::Object(out);
        let missing = REQUIRED
            .into_iter()
            .filter(|path| !present(&track, path))
            .collect();
        Some(Mapped { track, missing })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn lookups() -> Lookups {
        let table: HashMap<String, Value> = [("Sampling".to_owned(), json!("other"))].into();
        [("modes".to_owned(), table)].into()
    }

    #[test]
    fn conversions_follow_their_definitions() {
        let l = lookups();
        assert_eq!(run(&Conv::Scale(0.01), json!(87), &l), json!(0.87));
        assert_eq!(
            run(&Conv::Offset(-273.15), json!(300.0), &l),
            json!(300.0 - 273.15)
        );
        assert_eq!(run(&Conv::Scale(2.0), json!("text"), &l), Value::Null);
        assert_eq!(run(&Conv::ToBoolean, json!(1), &l), json!(true));
        assert_eq!(run(&Conv::ToBoolean, json!(false), &l), json!(false));
        assert_eq!(run(&Conv::ToBoolean, json!(2), &l), Value::Null);
        assert_eq!(run(&Conv::ToString, json!(311), &l), json!("311"));
        assert_eq!(run(&Conv::ToString, json!(-4), &l), json!("-4"));
        assert_eq!(run(&Conv::ToString, json!(1.5), &l), json!("1.5"));
        assert_eq!(run(&Conv::ToString, json!("KX7"), &l), json!("KX7"));
        assert_eq!(
            run(&Conv::Lookup("modes".into()), json!("Sampling"), &l),
            json!("other")
        );
        assert_eq!(
            run(&Conv::Lookup("modes".into()), json!("Idle"), &l),
            Value::Null
        );
    }

    #[test]
    fn via_steps_parse_in_both_written_forms() {
        let scale = json!({"conversion": "scale", "params": {"factor": 0.01}});
        assert_eq!(conversion(&scale), Ok(Some(Conv::Scale(0.01))));
        assert_eq!(conversion(&json!("toString")), Ok(Some(Conv::ToString)));
        assert_eq!(conversion(&json!("none")), Ok(None));
        assert!(conversion(&json!({"conversion": "epochMicrosToIso8601"})).is_err());
        assert!(conversion(&json!({"conversion": "scale"})).is_err());
    }

    #[test]
    fn an_empty_string_or_null_does_not_satisfy_a_required_field() {
        let track = json!({"trackId": "", "sourceId": "WX", "position": {"latitudeDeg": 0.0}});
        assert!(!present(&track, "trackId"));
        assert!(present(&track, "sourceId"));
        assert!(present(&track, "position.latitudeDeg"));
        assert!(!present(&track, "position.longitudeDeg"));
    }
}
