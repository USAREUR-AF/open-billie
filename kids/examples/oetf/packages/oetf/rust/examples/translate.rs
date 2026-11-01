//! Decode OETF hex and print translated records, one JSON line per output record.
//!
//!     cargo run --example translate -- 4f455446011046...               # every target with a map
//!     cargo run --example translate -- --to cot 4f455446011046...      # one target
//!     echo 4f455446... | cargo run --example translate -- --to sapient

use std::io::BufRead;

use billie_oetf::{Mapper, OetfDecoder};

const TARGETS: [&str; 3] = ["asterix-cat062", "cot", "sapient"];

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let mut targets: Vec<&str> = TARGETS.to_vec();
    if let Some(i) = args.iter().position(|a| a == "--to") {
        let t = args.get(i + 1).cloned().unwrap_or_default();
        if t != "all" {
            let Some(found) = TARGETS.iter().find(|x| **x == t) else {
                eprintln!("--to must be one of {TARGETS:?} or all");
                std::process::exit(2);
            };
            targets = vec![*found];
        }
        args.drain(i..(i + 2).min(args.len()));
    }
    if args.is_empty() {
        args = std::io::stdin().lock().lines().map_while(Result::ok).filter(|l| !l.trim().is_empty()).collect();
    }

    let (mut decoder, mapper) = (OetfDecoder::new(), Mapper::bundled());
    for h in args {
        let h = h.trim();
        let bytes: Vec<u8> = (0..h.len()).step_by(2).map(|i| u8::from_str_radix(&h[i..i + 2], 16).expect("hex")).collect();
        for rec in decoder.feed(&bytes) {
            for target in &targets {
                for out in mapper.translate("oetf", &rec, target) {
                    println!("{}", serde_json::json!({ "source": rec.message_name, "target": target, "fields": out.fields }));
                }
            }
        }
    }
    for e in decoder.take_recent_errors() {
        eprintln!("framing: {}: {}", e.reason, e.detail);
    }
}
