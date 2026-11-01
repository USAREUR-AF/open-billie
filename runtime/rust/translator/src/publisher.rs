//! Local Zenoh REST publisher used by the Golden Path translator service.
//!
//! The translator talks only to the loopback island. Fabric endpoints,
//! certificates, and vendor prefixes are owned by the separate platform
//! client and one-way bridge.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

use crate::{EncodedPayload, PublishError};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
const IO_TIMEOUT: Duration = Duration::from_secs(10);
const DEFAULT_REST_ADDR: &str = "127.0.0.1:8000";

/// Publish a translated payload to the node-local Zenoh REST plugin.
pub fn publish_to_local_zenoh(payload: &EncodedPayload) -> Result<(), PublishError> {
    let endpoint = std::env::var("BILLIE_LOCAL_ZENOH_REST_ADDR")
        .unwrap_or_else(|_| DEFAULT_REST_ADDR.to_string());
    publish_to_rest(payload, &endpoint)
}

/// Publish to a loopback Zenoh REST endpoint.
///
/// The endpoint is restricted to loopback so kid messages cannot be directed
/// to an arbitrary host or bypass the Golden Path fabric client.
pub fn publish_to_rest(payload: &EncodedPayload, endpoint: &str) -> Result<(), PublishError> {
    let address: SocketAddr = endpoint.parse().map_err(|_| {
        PublishError::new(
            "invalid_local_transport",
            "local Zenoh REST address must be a loopback socket address",
        )
    })?;
    if !address.ip().is_loopback() {
        return Err(PublishError::new(
            "invalid_local_transport",
            "local Zenoh REST publisher refuses non-loopback addresses",
        ));
    }

    let key = format!(
        "billie/{}/{}/{}",
        payload.kid,
        payload.output_name,
        payload.format.as_str()
    );
    let mut stream = TcpStream::connect_timeout(&address, CONNECT_TIMEOUT).map_err(|_| {
        PublishError::new(
            "local_zenoh_unavailable",
            "local Zenoh island is unavailable",
        )
    })?;
    stream.set_read_timeout(Some(IO_TIMEOUT)).map_err(|_| {
        PublishError::new(
            "local_zenoh_io",
            "could not configure local Zenoh connection",
        )
    })?;
    stream.set_write_timeout(Some(IO_TIMEOUT)).map_err(|_| {
        PublishError::new(
            "local_zenoh_io",
            "could not configure local Zenoh connection",
        )
    })?;

    write!(
        stream,
        "PUT /{} HTTP/1.1\r\nHost: {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        key,
        address,
        payload.content_type,
        payload.bytes.len()
    )
    .and_then(|_| stream.write_all(&payload.bytes))
    .map_err(|_| PublishError::new("local_zenoh_io", "failed to send encoded payload to local Zenoh"))?;

    let mut reader = BufReader::new(stream);
    let mut status = String::new();
    reader
        .read_line(&mut status)
        .map_err(|_| PublishError::new("local_zenoh_io", "failed to read local Zenoh response"))?;
    let status_code = status
        .split_whitespace()
        .nth(1)
        .and_then(|value| value.parse::<u16>().ok())
        .ok_or_else(|| {
            PublishError::new(
                "local_zenoh_protocol",
                "local Zenoh returned an invalid HTTP status",
            )
        })?;
    if !(200..300).contains(&status_code) {
        return Err(PublishError::new(
            "local_zenoh_rejected",
            "local Zenoh rejected the encoded payload",
        ));
    }
    let mut drain = [0_u8; 1024];
    let _ = reader.read(&mut drain);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::EncoderFormat;
    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::TcpListener;
    use std::thread;

    fn payload() -> EncodedPayload {
        EncodedPayload {
            kid: "synthetic-kid".to_string(),
            output_name: "tracks-cot".to_string(),
            format: EncoderFormat::Cot,
            content_type: "application/xml",
            bytes: b"<event/>".to_vec(),
        }
    }

    #[test]
    fn publishes_to_logical_output_route_on_loopback() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut headers = String::new();
            let mut content_length = 0;
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                if line == "\r\n" || line.is_empty() {
                    break;
                }
                if line.to_ascii_lowercase().starts_with("content-length:") {
                    content_length = line.split(':').nth(1).unwrap().trim().parse().unwrap();
                }
                headers.push_str(&line);
            }
            let mut body = vec![0; content_length];
            reader.read_exact(&mut body).unwrap();
            assert!(headers.starts_with("PUT /billie/synthetic-kid/tracks-cot/cot HTTP/1.1"));
            assert!(headers
                .to_ascii_lowercase()
                .contains("content-type: application/xml"));
            assert_eq!(body, b"<event/>");
            stream
                .write_all(
                    b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .unwrap();
        });

        publish_to_rest(&payload(), &address.to_string()).unwrap();
        server.join().unwrap();
    }

    #[test]
    fn refuses_non_loopback_transport_address() {
        let error = publish_to_rest(&payload(), "192.0.2.10:8000").unwrap_err();
        assert_eq!(error.code, "invalid_local_transport");
    }
}
