#[cfg(unix)]
fn main() {
    use billie_translator::{
        parse_source_identifiers_json, publish_to_local_zenoh, serve_unix, EncodeOptions,
    };
    use std::path::PathBuf;

    let socket_path = std::env::var_os("BILLIE_TRANSLATOR_SOCKET")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/run/billie/translator.sock"));
    let registry_path = std::env::var_os("BILLIE_TRANSLATOR_REGISTRY")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/etc/billie/translator/kids.json"));
    let group_name = std::env::var("BILLIE_TRANSLATOR_SOCKET_GROUP")
        .unwrap_or_else(|_| "billie-kids".to_owned());
    let socket_gid = match std::fs::read_to_string("/etc/group")
        .ok()
        .and_then(|groups| {
            groups.lines().find_map(|line| {
                let mut fields = line.split(':');
                (fields.next() == Some(group_name.as_str()))
                    .then(|| fields.nth(1)?.parse::<u32>().ok())
                    .flatten()
            })
        }) {
        Some(gid) => gid,
        None => {
            eprintln!("billie-translator: group '{group_name}' is missing from /etc/group");
            std::process::exit(2);
        }
    };
    let mut encode_options = EncodeOptions::default();
    let source_map_path = std::env::var_os("BILLIE_CAT062_SOURCE_MAP")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/etc/billie/translator/cat062-sources.json"));
    if source_map_path.exists() {
        let source_map_json = match std::fs::read_to_string(&source_map_path) {
            Ok(contents) => contents,
            Err(error) => {
                eprintln!(
                    "billie-translator: cannot read {}: {error}",
                    source_map_path.display()
                );
                std::process::exit(2);
            }
        };
        encode_options.cat062.sources = match parse_source_identifiers_json(&source_map_json) {
            Ok(sources) => sources,
            Err(error) => {
                eprintln!("billie-translator: {}: {error}", source_map_path.display());
                std::process::exit(2);
            }
        };
    }
    if let Err(error) = serve_unix(
        socket_path,
        registry_path,
        socket_gid,
        encode_options,
        publish_to_local_zenoh,
    ) {
        eprintln!("billie-translator: service stopped: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(unix))]
fn main() {
    eprintln!("billie-translator currently requires a Unix platform");
    std::process::exit(2);
}
