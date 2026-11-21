//! Reads one translation request (JSON, stdin) and prints, as JSON, what the real
//! Billie translator encodes for it in CoT and in ASTERIX CAT062. The CAT062 source
//! identifier (SAC 1, SIC 2) is the example node default the page states.
use billie_translator::{encode_request, parse_request, Cat062SourceIdentifier, EncodeOptions};
use serde_json::{json, Value};

fn main() {
    let mut request: Value = serde_json::from_reader(std::io::stdin()).expect("request JSON");
    let mut options = EncodeOptions::default();
    options.cat062.default_source = Some(Cat062SourceIdentifier { sac: 1, sic: 2 });
    let mut out = Vec::new();
    for format in ["cot", "asterix-cat062"] {
        request["target"]["format"] = Value::String(format.into());
        let parsed = parse_request(&request).expect("valid request");
        let payload = encode_request(&parsed, &options).expect("encoded");
        out.push(json!({
            "format": format,
            "contentType": payload.content_type,
            "length": payload.bytes.len(),
            "text": if format == "cot" { Value::String(String::from_utf8(payload.bytes.clone()).unwrap()) } else { Value::Null },
            "hex": payload.bytes.iter().map(|b| format!("{b:02x}")).collect::<String>(),
        }));
    }
    println!("{}", serde_json::to_string(&out).unwrap());
}
