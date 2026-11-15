//! Decoding with the `bite` library and a dictionary.
//!
//! Nothing about a message set is compiled in. The dictionary directory names
//! the messages of an interface and gives the bit range, type, scale and value
//! labels of every field; `bite` reads it and decodes a datagram against it.

use std::path::Path;

use bite::{Dictionary, Severity};
use serde_json::{Map, Value};

/// One decoded datagram.
#[derive(Debug, Clone, PartialEq)]
pub struct Record {
    /// The dictionary interface the datagram was decoded against.
    pub interface: String,
    /// The message name, or the type code in decimal when the interface has
    /// no name for it.
    pub message: String,
    /// Field name to value: the dictionary's label where the raw value has
    /// one, the typed value otherwise, `null` for a field beyond the end of
    /// the datagram. Empty when the dictionary does not define the message.
    pub fields: Map<String, Value>,
}

/// A loaded dictionary and the interface this kid listens for.
pub struct Decoder {
    dictionary: Dictionary,
    interface: String,
}

impl Decoder {
    /// Load the dictionary at `directory`.
    ///
    /// `interface` selects one of its interfaces by name; it may be omitted
    /// when the dictionary has exactly one. A dictionary that `bite` reports
    /// errors in is refused, so a kid never runs on a partly loaded field
    /// table.
    pub fn load(directory: &Path, interface: Option<&str>) -> Result<Self, String> {
        let dictionary = Dictionary::load(directory)
            .map_err(|error| format!("dictionary {}: {error}", directory.display()))?;
        let errors: Vec<String> = dictionary
            .issues()
            .iter()
            .filter(|issue| issue.severity == Severity::Error)
            .map(ToString::to_string)
            .collect();
        if !errors.is_empty() {
            return Err(format!(
                "dictionary {} has errors: {}",
                directory.display(),
                errors.join("; ")
            ));
        }
        let names: Vec<&str> = dictionary
            .interfaces()
            .iter()
            .map(|interface| interface.name.as_str())
            .collect();
        let interface = match (interface, names.as_slice()) {
            (Some(wanted), _) if names.contains(&wanted) => wanted.to_owned(),
            (Some(wanted), _) => {
                return Err(format!(
                    "dictionary has no interface named '{wanted}' (it has: {})",
                    names.join(", ")
                ))
            }
            (None, [only]) => (*only).to_owned(),
            (None, []) => return Err("dictionary defines no interface".to_owned()),
            (None, _) => {
                return Err(format!(
                    "dictionary has several interfaces ({}); name one",
                    names.join(", ")
                ))
            }
        };
        Ok(Self {
            dictionary,
            interface,
        })
    }

    pub fn dictionary(&self) -> &Dictionary {
        &self.dictionary
    }

    pub fn interface(&self) -> &str {
        &self.interface
    }

    /// Decode one datagram. The only failure is a datagram too short to hold
    /// the message type.
    pub fn decode(&self, datagram: &[u8]) -> Result<Record, String> {
        let interface = self
            .dictionary
            .interface(&self.interface)
            .expect("the interface was checked when the dictionary was loaded");
        let decoded = interface
            .decode(datagram)
            .map_err(|error| error.to_string())?;
        let fields = match serde_json::to_value(&decoded) {
            Ok(Value::Object(fields)) => fields,
            Ok(_) => Map::new(),
            Err(error) => return Err(error.to_string()),
        };
        Ok(Record {
            interface: self.interface.clone(),
            message: decoded.message_type(),
            fields,
        })
    }

    /// Run the vectors the dictionary carries. Returns how many there are, or
    /// every failure.
    pub fn check_vectors(&self) -> Result<usize, String> {
        let results = bite::vectors::run_vectors(&self.dictionary)
            .map_err(|error| format!("dictionary vectors: {error}"))?;
        let failures: Vec<String> = results
            .iter()
            .filter(|result| !result.passed())
            .map(|result| format!("{}: {}", result.name, result.failures.join(", ")))
            .collect();
        if failures.is_empty() {
            Ok(results.len())
        } else {
            Err(format!(
                "dictionary vectors failed: {}",
                failures.join("; ")
            ))
        }
    }
}
