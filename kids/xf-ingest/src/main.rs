//! billie-xf-ingest: the kid's entry point.

use std::collections::BTreeMap;
use std::path::PathBuf;

use billie_xf_ingest::settings::pipe_args;
use billie_xf_ingest::translator::{parse_outputs, Translator};

fn main() {
    let env: BTreeMap<String, String> = std::env::vars().collect();
    let setting = |key: &str| {
        env.get(key)
            .map(|v| v.trim().to_owned())
            .filter(|v| !v.is_empty())
    };
    let configured = (|| -> Result<(Vec<String>, Translator), String> {
        let args = pipe_args(&env)?;
        let translator = Translator {
            kid: setting("XF_KID_ID").ok_or("XF_KID_ID must be set")?,
            socket: PathBuf::from(
                setting("BILLIE_TRANSLATOR_SOCKET")
                    .unwrap_or_else(|| "/run/billie/translator.sock".into()),
            ),
            outputs: parse_outputs(&setting("XF_OUTPUTS").ok_or("XF_OUTPUTS must be set")?)?,
        };
        Ok((args, translator))
    })();
    let (args, translator) = match configured {
        Ok(done) => done,
        Err(error) => {
            eprintln!("billie-xf-ingest: {error}");
            std::process::exit(2);
        }
    };
    eprintln!("billie-xf-ingest: goat-xf-pipe {}", args.join(" "));
    std::process::exit(goat_adapters_std::cli::run(
        "billie-xf-ingest",
        &args,
        &[&translator],
    ));
}
