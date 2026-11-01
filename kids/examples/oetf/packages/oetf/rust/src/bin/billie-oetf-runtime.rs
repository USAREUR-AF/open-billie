//! OETF TCP/UDP ingress and local Billie translator adapter.

use billie_oetf::{Mapper, OetfDecoder};
use serde_json::{json, Value};
use std::env;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream, UdpSocket};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const OUTPUTS: [(&str, &str); 3] = [
    ("tracks-cot", "cot"),
    ("tracks-cat062", "asterix-cat062"),
    ("tracks-sapient", "sapient"),
];
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn setting(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_owned())
}

fn config() -> Result<(Ipv4Addr, u16, String, PathBuf), String> {
    let bind = setting("BILLIE_INPUT_BIND", "0.0.0.0")
        .parse::<Ipv4Addr>()
        .map_err(|_| "BILLIE_INPUT_BIND must be an IPv4 address".to_owned())?;
    let port = setting("BILLIE_INPUT_PORT", "5100")
        .parse::<u16>()
        .ok()
        .filter(|port| *port > 0)
        .ok_or_else(|| "BILLIE_INPUT_PORT must be between 1 and 65535".to_owned())?;
    let transport = setting("BILLIE_INPUT_TRANSPORT", "udp").to_ascii_lowercase();
    if transport != "udp" && transport != "tcp" {
        return Err(format!("unsupported input transport '{transport}' (use udp or tcp)"));
    }
    let socket = PathBuf::from(setting(
        "BILLIE_TRANSLATOR_SOCKET",
        "/run/billie/translator.sock",
    ));
    Ok((bind, port, transport, socket))
}

fn request_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_nanos());
    let sequence = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    format!("{}-{}-{sequence}", std::process::id(), nanos)
}

fn translate(socket_path: &PathBuf, output_name: &str, format: &str, record: &Value) -> io::Result<()> {
    let id = request_id();
    let request = json!({
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateRequest",
        "requestId": id,
        "kid": "oetf",
        "target": { "outputName": output_name, "format": format },
        "record": record,
    });
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
    if result["requestId"] != id {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "translator requestId did not match"));
    }
    if result["status"] != "published" {
        let code = result["error"]["code"].as_str().unwrap_or("unknown");
        let message = result["error"]["message"].as_str().unwrap_or("no error detail provided");
        return Err(io::Error::other(format!("translator rejected output ({code}): {message}")));
    }
    if result["outputName"] != output_name || result["format"] != format {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "translator output selection did not match"));
    }
    println!(
        "translator accepted output={output_name} format={format} bytes={}",
        result["bytesPublished"].as_u64().unwrap_or(0)
    );
    Ok(())
}

fn process_records(decoder: &mut OetfDecoder, mapper: &Mapper, socket_path: &PathBuf, data: &[u8]) {
    for decoded in decoder.feed(data) {
        for canonical in mapper.translate("oetf", &decoded, "billie-canonical") {
            for (output_name, format) in OUTPUTS {
                if let Err(error) = translate(socket_path, output_name, format, &canonical.fields) {
                    eprintln!("OETF output {output_name} failed: {error}");
                }
            }
        }
    }
    for error in decoder.take_recent_errors() {
        eprintln!("OETF framing {}: {}", error.reason, error.detail);
    }
}

fn run_udp(bind: Ipv4Addr, port: u16, socket_path: &PathBuf, mapper: &Mapper) -> io::Result<()> {
    let address = SocketAddrV4::new(bind, port);
    let ingress = UdpSocket::bind(address)?;
    ingress.set_read_timeout(Some(Duration::from_millis(500)))?;
    println!("OETF UDP listening on {address}; translator socket {}", socket_path.display());
    let mut decoder = OetfDecoder::new();
    let mut packet = [0u8; 65_535];
    loop {
        match ingress.recv_from(&mut packet) {
            Ok((length, _peer)) => process_records(&mut decoder, mapper, socket_path, &packet[..length]),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock || error.kind() == io::ErrorKind::TimedOut => {}
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
}

fn serve_tcp_client(mut client: TcpStream, mapper: &Mapper, socket_path: &PathBuf) -> io::Result<()> {
    client.set_read_timeout(Some(Duration::from_secs(1)))?;
    let peer = client.peer_addr()?;
    println!("OETF TCP connected from {peer}");
    let mut decoder = OetfDecoder::new();
    let mut chunk = [0u8; 4096];
    loop {
        match client.read(&mut chunk) {
            Ok(0) => break,
            Ok(length) => process_records(&mut decoder, mapper, socket_path, &chunk[..length]),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock || error.kind() == io::ErrorKind::TimedOut => continue,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    decoder.reset();
    println!("OETF TCP disconnected from {peer}");
    Ok(())
}

fn run_tcp(bind: Ipv4Addr, port: u16, socket_path: &PathBuf, mapper: &Mapper) -> io::Result<()> {
    let address = SocketAddrV4::new(bind, port);
    let listener = TcpListener::bind(address)?;
    println!("OETF TCP listening on {address}; translator socket {}", socket_path.display());
    for incoming in listener.incoming() {
        match incoming {
            Ok(client) => {
                if let Err(error) = serve_tcp_client(client, mapper, socket_path) {
                    eprintln!("OETF TCP connection ended with an error: {error}");
                }
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let (bind, port, transport, socket_path) = config().map_err(io::Error::other)?;
    let mapper = Mapper::bundled();
    match transport.as_str() {
        "udp" => run_udp(bind, port, &socket_path, &mapper)?,
        "tcp" => run_tcp(bind, port, &socket_path, &mapper)?,
        _ => unreachable!(),
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("OETF runtime failed: {error}");
        std::process::exit(1);
    }
}
