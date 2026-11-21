//! The kid's settings, read from its environment, as a `goat-xf-pipe`
//! command line.
//!
//! Billie sets `BILLIE_INPUT_TRANSPORT` and `BILLIE_INPUT_PORT` from
//! `billie kid configure`; the env file given to `billie kid activate
//! --config` sets the `XF_*` values. The image sets `XF_PACKS`, `XF_MODELS`
//! and `XF_OUTPUTS`.

use std::collections::BTreeMap;

/// The settings an operator gives in the env file, with what each does.
pub const OPERATOR_SETTINGS: [(&str, &str); 8] = [
    ("XF_FROM_FORMAT", "required: the pack name of the input format, for example cot-xml"),
    ("XF_SOURCE_ID", "required: the sourceId of every track; CAT062 SAC/SIC is assigned per sourceId"),
    ("XF_IN_FRAME", "how one message is delimited; default whole (one datagram) for udp, required for tcp"),
    ("XF_MULTICAST_GROUP", "join this IPv4 multicast group on the listener port"),
    ("XF_MULTICAST_IFACE", "the local address of the interface to join the group on (with XF_MULTICAST_GROUP)"),
    ("XF_INPUT", "a goat-xf-pipe input endpoint that replaces the listener, for example tcp://192.0.2.10:4000"),
    ("XF_TRACK_GENERATION", "the trackGeneration of every track whose message has none; default 1"),
    ("XF_ON_ERROR", "skip (default) or stop"),
];

fn get<'a>(env: &'a BTreeMap<String, String>, key: &str) -> Option<&'a str> {
    env.get(key).map(|v| v.trim()).filter(|v| !v.is_empty())
}

fn need<'a>(env: &'a BTreeMap<String, String>, key: &str) -> Result<&'a str, String> {
    get(env, key).ok_or_else(|| format!("{key} must be set"))
}

/// A pack name, a source id: letters, digits and `-_.`, so that nothing an
/// operator writes becomes a second option.
fn plain(key: &str, value: &str) -> Result<(), String> {
    if value.len() <= 128
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
    {
        Ok(())
    } else {
        Err(format!(
            "{key} may hold only letters, digits, '-', '_' and '.' (at most 128)"
        ))
    }
}

/// The input endpoint: `XF_INPUT` when given, otherwise the Billie listener
/// (UDP, joined to a multicast group when one is named, or a TCP listener).
fn input(env: &BTreeMap<String, String>) -> Result<String, String> {
    if let Some(uri) = get(env, "XF_INPUT") {
        return Ok(uri.to_owned());
    }
    let transport = get(env, "BILLIE_INPUT_TRANSPORT")
        .unwrap_or("udp")
        .to_ascii_lowercase();
    let port: u16 = need(env, "BILLIE_INPUT_PORT")?
        .parse()
        .ok()
        .filter(|p| *p > 0)
        .ok_or("BILLIE_INPUT_PORT must be between 1 and 65535")?;
    match (transport.as_str(), get(env, "XF_MULTICAST_GROUP")) {
        ("udp", None) => Ok(format!("udp://:{port}")),
        ("udp", Some(group)) => {
            let group: std::net::Ipv4Addr = group
                .parse()
                .map_err(|_| "XF_MULTICAST_GROUP must be an IPv4 address")?;
            if !group.is_multicast() {
                return Err("XF_MULTICAST_GROUP must be a multicast address (224.0.0.0/4)".into());
            }
            let iface: std::net::Ipv4Addr = get(env, "XF_MULTICAST_IFACE")
                .unwrap_or("0.0.0.0")
                .parse()
                .map_err(|_| "XF_MULTICAST_IFACE must be an IPv4 address")?;
            Ok(format!("udp://{group}:{port}?iface={iface}"))
        }
        ("tcp", None) => Ok(format!("tcp-listen://:{port}")),
        ("tcp", Some(_)) => Err("XF_MULTICAST_GROUP needs the udp transport".into()),
        (other, _) => Err(format!("unsupported BILLIE_INPUT_TRANSPORT '{other}'")),
    }
}

/// The `goat-xf-pipe` arguments for these settings. The output is always
/// Canonical Track v2 on the `billie:` endpoint.
pub fn pipe_args(env: &BTreeMap<String, String>) -> Result<Vec<String>, String> {
    let from = need(env, "XF_FROM_FORMAT")?;
    plain("XF_FROM_FORMAT", from)?;
    let source_id = need(env, "XF_SOURCE_ID")?;
    plain("XF_SOURCE_ID", source_id)?;
    let generation = get(env, "XF_TRACK_GENERATION").unwrap_or("1");
    plain("XF_TRACK_GENERATION", generation)?;
    let on_error = get(env, "XF_ON_ERROR").unwrap_or("skip");
    if !matches!(on_error, "skip" | "stop") {
        return Err("XF_ON_ERROR must be skip or stop".into());
    }
    let input = input(env)?;
    let stream = input.starts_with("tcp");
    let frame = match (get(env, "XF_IN_FRAME"), stream) {
        (Some(frame), _) => Some(frame.to_owned()),
        (None, false) => None,
        (None, true) => return Err(
            "XF_IN_FRAME must be set for a tcp input (newline, len:<N>:<be|le>, start:..., ...)"
                .into(),
        ),
    };

    let mut args: Vec<String> = vec![
        "--packs".into(),
        need(env, "XF_PACKS")?.into(),
        "--models".into(),
        need(env, "XF_MODELS")?.into(),
        "--packs-only".into(),
        "--max-distribution".into(),
        "public".into(),
        "--from-format".into(),
        from.into(),
        "--in".into(),
        input,
    ];
    if let Some(frame) = frame {
        args.extend(["--in-frame".into(), frame]);
    }
    args.extend([
        "--set".into(),
        format!("track.source_id={source_id}"),
        "--set".into(),
        format!("track.generation={generation}"),
        "--set-receive-time".into(),
        "time_ms".into(),
        "--on-error".into(),
        on_error.into(),
        "--out".into(),
        "billie:".into(),
        "--to-format".into(),
        "canonical-track-v2".into(),
    ]);
    Ok(args)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
        let mut map: BTreeMap<String, String> = [
            ("XF_PACKS", "/app/goat-transformers/packs"),
            ("XF_MODELS", "/app/goat-transformers/model"),
            ("BILLIE_INPUT_TRANSPORT", "udp"),
            ("BILLIE_INPUT_PORT", "40540"),
            ("XF_FROM_FORMAT", "cot-xml"),
            ("XF_SOURCE_ID", "sensor-a"),
        ]
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
        for (k, v) in pairs {
            map.insert(k.to_string(), v.to_string());
        }
        map
    }

    fn value(args: &[String], flag: &str) -> Option<String> {
        args.iter()
            .position(|a| a == flag)
            .map(|i| args[i + 1].clone())
    }

    #[test]
    fn udp_listener_is_the_default_input() {
        let args = pipe_args(&env(&[])).unwrap();
        assert_eq!(value(&args, "--in").unwrap(), "udp://:40540");
        assert_eq!(value(&args, "--from-format").unwrap(), "cot-xml");
        assert_eq!(value(&args, "--to-format").unwrap(), "canonical-track-v2");
        assert_eq!(value(&args, "--out").unwrap(), "billie:");
        assert!(args.contains(&"track.source_id=sensor-a".to_string()));
        assert!(args.contains(&"track.generation=1".to_string()));
        assert_eq!(value(&args, "--set-receive-time").unwrap(), "time_ms");
        assert_eq!(value(&args, "--max-distribution").unwrap(), "public");
        assert!(value(&args, "--in-frame").is_none());
    }

    #[test]
    fn a_multicast_group_is_joined_on_the_listener_port() {
        let args = pipe_args(&env(&[
            ("XF_MULTICAST_GROUP", "239.2.3.1"),
            ("XF_MULTICAST_IFACE", "192.0.2.20"),
        ]))
        .unwrap();
        assert_eq!(
            value(&args, "--in").unwrap(),
            "udp://239.2.3.1:40540?iface=192.0.2.20"
        );
        assert!(pipe_args(&env(&[("XF_MULTICAST_GROUP", "192.0.2.1")])).is_err());
    }

    #[test]
    fn tcp_needs_a_framing() {
        assert!(pipe_args(&env(&[("BILLIE_INPUT_TRANSPORT", "tcp")])).is_err());
        let args = pipe_args(&env(&[
            ("BILLIE_INPUT_TRANSPORT", "tcp"),
            ("XF_IN_FRAME", "newline"),
        ]))
        .unwrap();
        assert_eq!(value(&args, "--in").unwrap(), "tcp-listen://:40540");
        assert_eq!(value(&args, "--in-frame").unwrap(), "newline");
    }

    #[test]
    fn an_explicit_input_replaces_the_listener() {
        let args = pipe_args(&env(&[
            ("XF_INPUT", "tcp://192.0.2.10:4000"),
            ("XF_IN_FRAME", "newline"),
        ]))
        .unwrap();
        assert_eq!(value(&args, "--in").unwrap(), "tcp://192.0.2.10:4000");
    }

    #[test]
    fn required_and_unsafe_values_are_refused() {
        let mut e = env(&[]);
        e.remove("XF_FROM_FORMAT");
        assert!(pipe_args(&e).unwrap_err().contains("XF_FROM_FORMAT"));
        let mut e = env(&[]);
        e.remove("XF_SOURCE_ID");
        assert!(pipe_args(&e).unwrap_err().contains("XF_SOURCE_ID"));
        assert!(pipe_args(&env(&[("XF_SOURCE_ID", "a --out stdout:")])).is_err());
        assert!(pipe_args(&env(&[("XF_ON_ERROR", "retry")])).is_err());
    }
}
