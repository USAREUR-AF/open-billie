//! UDP ingress, `bite` decode, canonical mapping and the local Billie
//! translator request. Everything specific to a sensor is read from files.

use billie_bite_kid::{rfc3339_millis, translation_request, Decoder, Mapper};
use serde_json::Value;
use std::env;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, UdpSocket};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const MAX_RESPONSE_BYTES: usize = 64 * 1024;
static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Config {
    kid: String,
    outputs: Vec<(String, String)>,
    dictionary: PathBuf,
    interface: Option<String>,
    mappings: PathBuf,
    lookups: PathBuf,
    bind: Ipv4Addr,
    port: u16,
    socket: PathBuf,
}

fn setting(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_owned())
}

fn required(name: &str) -> Result<String, String> {
    env::var(name)
        .ok()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| format!("{name} must be set"))
}

fn config() -> Result<Config, String> {
    let transport = setting("BILLIE_INPUT_TRANSPORT", "udp").to_ascii_lowercase();
    if transport != "udp" {
        return Err(format!(
            "unsupported input transport '{transport}': a dictionary describes datagrams, so this runtime listens on udp only"
        ));
    }
    // "name:format,name:format", matching interfaces.outputs in billie-kid.yaml.
    let outputs = required("BITE_KID_OUTPUTS")?
        .split(',')
        .map(|pair| {
            pair.trim()
                .split_once(':')
                .filter(|(name, format)| !name.is_empty() && !format.is_empty())
                .map(|(name, format)| (name.to_owned(), format.to_owned()))
                .ok_or_else(|| format!("BITE_KID_OUTPUTS entry '{pair}' is not name:format"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Config {
        kid: required("BITE_KID_ID")?,
        outputs,
        dictionary: PathBuf::from(required("BITE_KID_DICTIONARY")?),
        interface: env::var("BITE_KID_INTERFACE")
            .ok()
            .filter(|v| !v.is_empty()),
        mappings: PathBuf::from(setting("BITE_KID_MAPPINGS", "/app/mappings")),
        lookups: PathBuf::from(setting("BITE_KID_LOOKUPS", "/app/lookups")),
        bind: setting("BILLIE_INPUT_BIND", "0.0.0.0")
            .parse()
            .map_err(|_| "BILLIE_INPUT_BIND must be an IPv4 address".to_owned())?,
        port: required("BILLIE_INPUT_PORT")?
            .parse::<u16>()
            .ok()
            .filter(|port| *port > 0)
            .ok_or_else(|| "BILLIE_INPUT_PORT must be between 1 and 65535".to_owned())?,
        socket: PathBuf::from(setting(
            "BILLIE_TRANSLATOR_SOCKET",
            "/run/billie/translator.sock",
        )),
    })
}

fn request_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let sequence = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("{}-{}-{sequence}", std::process::id(), nanos)
}

fn translate(
    socket_path: &Path,
    kid: &str,
    output_name: &str,
    format: &str,
    record: &Value,
) -> io::Result<()> {
    let id = request_id();
    let request = translation_request(kid, &id, output_name, format, record);
    let mut bytes = serde_json::to_vec(&request)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    bytes.push(b'\n');

    let mut stream = UnixStream::connect(socket_path)?;
    stream.set_read_timeout(Some(Duration::from_secs(10)))?;
    stream.set_write_timeout(Some(Duration::from_secs(10)))?;
    stream.write_all(&bytes)?;
    stream.flush()?;

    let mut response = Vec::new();
    let read = BufReader::new(stream)
        .take((MAX_RESPONSE_BYTES + 1) as u64)
        .read_until(b'\n', &mut response)?;
    if read == 0 || read > MAX_RESPONSE_BYTES || response.last() != Some(&b'\n') {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "translator returned an empty, oversized, or unterminated response",
        ));
    }
    let result: Value = serde_json::from_slice(&response[..response.len() - 1])
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    if result["requestId"] != id.as_str() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "translator requestId did not match",
        ));
    }
    if result["status"] != "published" {
        let code = result["error"]["code"].as_str().unwrap_or("unknown");
        let message = result["error"]["message"]
            .as_str()
            .unwrap_or("no error detail provided");
        return Err(io::Error::other(format!(
            "translator rejected output ({code}): {message}"
        )));
    }
    if result["outputName"] != output_name || result["format"] != format {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "translator output selection did not match",
        ));
    }
    println!(
        "translator accepted output={output_name} format={format} bytes={}",
        result["bytesPublished"].as_u64().unwrap_or(0)
    );
    Ok(())
}

fn process_datagram(config: &Config, decoder: &Decoder, mapper: &Mapper, datagram: &[u8]) {
    let received_at = rfc3339_millis(SystemTime::now());
    let record = match decoder.decode(datagram) {
        Ok(record) => record,
        Err(error) => {
            eprintln!("datagram of {} bytes not decoded: {error}", datagram.len());
            return;
        }
    };
    let Some(mapped) = mapper.translate(&record, &received_at) else {
        return;
    };
    if !mapped.missing.is_empty() {
        eprintln!(
            "{} message not sent: no value for {}",
            record.message,
            mapped.missing.join(", ")
        );
        return;
    }
    for (output_name, format) in &config.outputs {
        if let Err(error) = translate(
            &config.socket,
            &config.kid,
            output_name,
            format,
            &mapped.track,
        ) {
            eprintln!("output {output_name} failed: {error}");
        }
    }
}

fn run() -> Result<(), String> {
    let config = config()?;
    let decoder = Decoder::load(&config.dictionary, config.interface.as_deref())?;
    let vectors = decoder.check_vectors()?;
    let mapper = Mapper::from_dirs(&config.mappings, &config.lookups)?;
    if mapper.mapped_messages().is_empty() {
        return Err(format!(
            "no enabled map to billie-canonical under {}",
            config.mappings.display()
        ));
    }
    let spec = &decoder.dictionary().spec;
    println!(
        "dictionary {} {}: interface {}, {} dictionary vectors passed; mapped messages: {}",
        spec.name.as_deref().unwrap_or("(unnamed)"),
        spec.version.as_deref().unwrap_or("(no version)"),
        decoder.interface(),
        vectors,
        mapper.mapped_messages().join(", ")
    );

    let address = SocketAddrV4::new(config.bind, config.port);
    let ingress = UdpSocket::bind(address).map_err(|error| format!("bind {address}: {error}"))?;
    ingress
        .set_read_timeout(Some(Duration::from_millis(500)))
        .map_err(|error| error.to_string())?;
    println!(
        "UDP listening on {address}; translator socket {}",
        config.socket.display()
    );
    let mut packet = [0u8; 65_535];
    loop {
        match ingress.recv_from(&mut packet) {
            Ok((length, _peer)) => process_datagram(&config, &decoder, &mapper, &packet[..length]),
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::WouldBlock
                        | io::ErrorKind::TimedOut
                        | io::ErrorKind::Interrupted
                ) => {}
            Err(error) => return Err(error.to_string()),
        }
    }
}

fn main() {
    if let Err(error) = run() {
        eprintln!("billie-bite-kid failed: {error}");
        std::process::exit(1);
    }
}
