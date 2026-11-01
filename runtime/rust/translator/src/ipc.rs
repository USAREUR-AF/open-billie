//! Newline-delimited JSON request service for local kid-to-translator IPC.

use std::fs;
use std::io::{self, BufRead, BufReader, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{chown, FileTypeExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use serde_json::{json, Value};

use crate::{encode_request, parse_request, EncodeDispatchError, EncodeOptions, EncodedPayload};

pub const MAX_REQUEST_BYTES: usize = 1024 * 1024;
const SOCKET_MODE: u32 = 0o660;
const IO_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_CONCURRENT_CLIENTS: usize = 64;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishError {
    pub code: String,
    pub message: String,
}

impl PublishError {
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

/// Serve one versioned request per local Unix socket connection.
///
/// The caller supplies the publisher so this boundary can be tested without a
/// Zenoh router. A request reports `published` only after that callback succeeds.
#[cfg(unix)]
pub fn serve_unix<F>(
    socket_path: impl AsRef<Path>,
    registry_path: impl AsRef<Path>,
    socket_gid: u32,
    options: EncodeOptions,
    publish: F,
) -> io::Result<()>
where
    F: Fn(&EncodedPayload) -> Result<(), PublishError> + Send + Sync + 'static,
{
    let socket_path = socket_path.as_ref();
    if let Ok(metadata) = fs::symlink_metadata(socket_path) {
        if !metadata.file_type().is_socket() {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "refusing to replace a non-socket path",
            ));
        }
        fs::remove_file(socket_path)?;
    }

    let listener = UnixListener::bind(socket_path)?;
    fs::set_permissions(socket_path, fs::Permissions::from_mode(SOCKET_MODE))?;
    chown(socket_path, Some(0), Some(socket_gid))?;
    let options = Arc::new(options);
    let publish = Arc::new(publish);
    let active_clients = Arc::new(AtomicUsize::new(0));

    for connection in listener.incoming() {
        match connection {
            Ok(stream) => {
                if active_clients.fetch_add(1, Ordering::AcqRel) >= MAX_CONCURRENT_CLIENTS {
                    active_clients.fetch_sub(1, Ordering::AcqRel);
                    let _ = write_response(
                        stream,
                        &rejected(
                            "unknown",
                            "translator_busy",
                            "translator reached its concurrent client limit; retry shortly",
                            None,
                        ),
                    );
                    continue;
                }
                let options = Arc::clone(&options);
                let publish = Arc::clone(&publish);
                let active_clients = Arc::clone(&active_clients);
                let registry_path = registry_path.as_ref().to_path_buf();
                std::thread::spawn(move || {
                    if let Err(error) =
                        handle_connection(stream, &registry_path, &options, publish.as_ref())
                    {
                        eprintln!("billie translator socket connection failed: {error}");
                    }
                    active_clients.fetch_sub(1, Ordering::AcqRel);
                });
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

fn handle_connection<F>(
    stream: UnixStream,
    registry_path: &Path,
    options: &EncodeOptions,
    publish: &F,
) -> io::Result<()>
where
    F: Fn(&EncodedPayload) -> Result<(), PublishError>,
{
    stream.set_read_timeout(Some(IO_TIMEOUT))?;
    stream.set_write_timeout(Some(IO_TIMEOUT))?;
    let reader = BufReader::new(stream.try_clone()?);
    let mut line = Vec::new();
    let response = match reader
        .take((MAX_REQUEST_BYTES + 2) as u64)
        .read_until(b'\n', &mut line)
    {
        Ok(0) => rejected(
            "unknown",
            "empty_request",
            "expected one JSON request line",
            None,
        ),
        Ok(read) if read > MAX_REQUEST_BYTES => rejected(
            "unknown",
            "request_too_large",
            "request exceeds the 1 MiB limit",
            None,
        ),
        Ok(_) if line.last() != Some(&b'\n') => rejected(
            "unknown",
            "invalid_framing",
            "request must end with a newline",
            None,
        ),
        Ok(_) => process_authenticated_request(
            &line[..line.len() - 1],
            peer_uid(&stream)?,
            registry_path,
            options,
            publish,
        ),
        Err(error) => return Err(error),
    };
    write_response(stream, &response)
}

fn write_response(mut stream: UnixStream, response: &Value) -> io::Result<()> {
    let mut encoded = serde_json::to_vec(response)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    encoded.push(b'\n');
    stream.write_all(&encoded)?;
    stream.flush()
}

#[cfg(target_os = "linux")]
fn peer_uid(stream: &UnixStream) -> io::Result<u32> {
    let mut credentials = std::mem::MaybeUninit::<libc::ucred>::uninit();
    let mut length = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let result = unsafe {
        libc::getsockopt(
            stream.as_raw_fd(),
            libc::SOL_SOCKET,
            libc::SO_PEERCRED,
            credentials.as_mut_ptr().cast(),
            &mut length,
        )
    };
    if result != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { credentials.assume_init() }.uid)
}

#[cfg(not(target_os = "linux"))]
fn peer_uid(_stream: &UnixStream) -> io::Result<u32> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "translator peer identity currently requires Linux SO_PEERCRED",
    ))
}

fn process_authenticated_request<F>(
    line: &[u8],
    uid: u32,
    registry_path: &Path,
    options: &EncodeOptions,
    publish: &F,
) -> Value
where
    F: Fn(&EncodedPayload) -> Result<(), PublishError>,
{
    let registry: Value = match fs::read(registry_path)
        .ok()
        .and_then(|data| serde_json::from_slice(&data).ok())
    {
        Some(value) => value,
        None => {
            return rejected(
                "unknown",
                "registry_unavailable",
                "kid authorization registry is unavailable",
                None,
            )
        }
    };
    let kids = match registry.get("kids").and_then(Value::as_object) {
        Some(kids) => kids,
        None => {
            return rejected(
                "unknown",
                "registry_invalid",
                "kid authorization registry is invalid",
                None,
            )
        }
    };
    if registry.get("schema").and_then(Value::as_str) != Some("billie.translator.registry.v1") {
        return rejected(
            "unknown",
            "registry_invalid",
            "kid authorization registry has an unsupported schema",
            None,
        );
    }
    let authorized_kid = kids.iter().find_map(|(kid, policy)| {
        (policy.get("uid").and_then(Value::as_u64) == Some(uid as u64)).then_some((kid, policy))
    });
    let Some((authorized_kid, policy)) = authorized_kid else {
        return rejected(
            "unknown",
            "unauthorized_peer",
            "local process UID is not registered to an active kid",
            None,
        );
    };
    let value: Value = match serde_json::from_slice(line) {
        Ok(value) => value,
        Err(error) => {
            return rejected(
                "unknown",
                "invalid_json",
                &format!("request is not valid JSON: {error}"),
                None,
            )
        }
    };
    let request_id = value
        .get("requestId")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty() && id.len() <= 128)
        .unwrap_or("unknown");
    if value.get("kid").and_then(Value::as_str) != Some(authorized_kid.as_str()) {
        return rejected(
            request_id,
            "kid_identity_mismatch",
            "request kid does not match the authenticated local process",
            None,
        );
    }
    let request = match parse_request(&value) {
        Ok(request) => request,
        Err(error) => {
            return rejected(
                request_id,
                error.code,
                &error.message,
                Some(error.path.as_str()),
            )
        }
    };
    let allowed = policy
        .get("outputs")
        .and_then(Value::as_array)
        .is_some_and(|outputs| {
            outputs.iter().any(|output| {
                output.get("name").and_then(Value::as_str) == Some(request.output_name.as_str())
                    && output.get("format").and_then(Value::as_str) == Some(request.format.as_str())
                    && output.get("profile").and_then(Value::as_str) == request.profile.as_deref()
            })
        });
    if !allowed {
        return rejected(
            request_id,
            "output_not_declared",
            "requested output is not declared by this kid's installed manifest",
            Some("$.target"),
        );
    }
    let payload = match encode_request(&request, options) {
        Ok(payload) => payload,
        Err(error) => {
            let (code, message) = dispatch_error(&error);
            return rejected(request_id, code, message, None);
        }
    };
    if let Err(error) = publish(&payload) {
        return rejected(request_id, &error.code, &error.message, None);
    }
    json!({
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateResult",
        "requestId": request_id,
        "status": "published",
        "outputName": payload.output_name,
        "format": payload.format.as_str(),
        "bytesPublished": payload.bytes.len()
    })
}

#[cfg(test)]
fn process_request<F>(line: &[u8], options: &EncodeOptions, publish: &F) -> Value
where
    F: Fn(&EncodedPayload) -> Result<(), PublishError>,
{
    let value: Value = match serde_json::from_slice(line) {
        Ok(value) => value,
        Err(error) => {
            return rejected(
                "unknown",
                "invalid_json",
                &format!("request is not valid JSON: {error}"),
                None,
            )
        }
    };
    let request_id = value
        .get("requestId")
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty() && id.len() <= 128)
        .unwrap_or("unknown");
    let request = match parse_request(&value) {
        Ok(request) => request,
        Err(error) => {
            return rejected(
                request_id,
                error.code,
                &error.message,
                Some(error.path.as_str()),
            )
        }
    };
    let payload = match encode_request(&request, options) {
        Ok(payload) => payload,
        Err(error) => {
            let (code, message) = dispatch_error(&error);
            return rejected(request_id, code, message, None);
        }
    };
    if let Err(error) = publish(&payload) {
        return rejected(request_id, &error.code, &error.message, None);
    }
    json!({
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateResult",
        "requestId": request_id,
        "status": "published",
        "outputName": payload.output_name,
        "format": payload.format.as_str(),
        "bytesPublished": payload.bytes.len()
    })
}

fn dispatch_error(error: &EncodeDispatchError) -> (&'static str, &str) {
    match error {
        EncodeDispatchError::Cot(error) => (error.code, &error.message),
        EncodeDispatchError::Cat062(error) => (error.code, &error.message),
        EncodeDispatchError::Sapient(error) => (error.code, &error.message),
        EncodeDispatchError::UnsupportedFormat(_) => (
            "unsupported_format",
            "requested encoder format is registered but not implemented",
        ),
    }
}

fn rejected(request_id: &str, code: &str, message: &str, path: Option<&str>) -> Value {
    let mut error = json!({"code": code, "message": message});
    if let Some(path) = path {
        error["path"] = json!(path);
    }
    json!({
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateResult",
        "requestId": request_id,
        "status": "rejected",
        "error": error
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    const REQUEST: &str =
        include_str!("../../../../schemas/examples/oetf-translation-request.json");

    fn compact_request() -> Vec<u8> {
        serde_json::to_vec(&serde_json::from_str::<Value>(REQUEST).unwrap()).unwrap()
    }

    fn test_registry() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "billie-translator-test-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let request: Value = serde_json::from_str(REQUEST).unwrap();
        let output = request["target"].clone();
        fs::write(
            &path,
            json!({"schema":"billie.translator.registry.v1","kids":{"oetf":{
                "uid": unsafe { libc::geteuid() },
                "outputs":[{"name":output["outputName"],"format":output["format"],"profile":null}]
            }}})
            .to_string(),
        )
        .unwrap();
        path
    }

    #[test]
    fn request_is_encoded_then_acknowledged_only_after_publish_succeeds() {
        let captured = Mutex::new(Vec::new());
        let response = process_request(REQUEST.as_bytes(), &EncodeOptions::default(), &|payload| {
            captured.lock().unwrap().push(payload.clone());
            Ok(())
        });
        assert_eq!(response["status"], "published");
        assert_eq!(response["format"], "cot");
        assert_eq!(
            response["bytesPublished"],
            captured.lock().unwrap()[0].bytes.len()
        );
        assert_eq!(captured.lock().unwrap()[0].content_type, "application/xml");
    }

    #[test]
    fn invalid_request_returns_schema_shaped_error_without_publishing() {
        let result = process_request(b"{\"bad\":true}", &EncodeOptions::default(), &|_| {
            panic!("invalid request must not reach publisher")
        });
        assert_eq!(result["status"], "rejected");
        assert_eq!(result["error"]["code"], "unknown_field");
        assert_eq!(result["error"]["path"], "$.bad");
    }

    #[test]
    fn publisher_failure_returns_rejected_response() {
        let response = process_request(REQUEST.as_bytes(), &EncodeOptions::default(), &|_| {
            Err(PublishError::new("publish_failed", "router unavailable"))
        });
        assert_eq!(response["status"], "rejected");
        assert_eq!(response["error"]["code"], "publish_failed");
    }

    #[test]
    fn authenticated_peer_is_bound_to_manifest_outputs() {
        let registry = test_registry();
        let uid = unsafe { libc::geteuid() };
        let allowed = process_authenticated_request(
            REQUEST.as_bytes(),
            uid,
            &registry,
            &EncodeOptions::default(),
            &|_| Ok(()),
        );
        assert_eq!(allowed["status"], "published");

        let mut request: Value = serde_json::from_str(REQUEST).unwrap();
        request["target"]["outputName"] = json!("tracks-sapient");
        request["target"]["format"] = json!("sapient");
        let denied = process_authenticated_request(
            &serde_json::to_vec(&request).unwrap(),
            uid,
            &registry,
            &EncodeOptions::default(),
            &|_| panic!("undeclared output must not reach publisher"),
        );
        assert_eq!(denied["error"]["code"], "output_not_declared");

        let denied_peer = process_authenticated_request(
            REQUEST.as_bytes(),
            uid.wrapping_add(1),
            &registry,
            &EncodeOptions::default(),
            &|_| panic!("unregistered UID must not reach publisher"),
        );
        assert_eq!(denied_peer["error"]["code"], "unauthorized_peer");
        fs::remove_file(registry).unwrap();
    }

    #[test]
    fn request_cannot_claim_another_kid_identity() {
        let registry = test_registry();
        let mut request: Value = serde_json::from_str(REQUEST).unwrap();
        request["kid"] = json!("other-kid");
        let response = process_authenticated_request(
            &serde_json::to_vec(&request).unwrap(),
            unsafe { libc::geteuid() },
            &registry,
            &EncodeOptions::default(),
            &|_| panic!("mismatched kid claim must not reach publisher"),
        );
        assert_eq!(response["error"]["code"], "kid_identity_mismatch");
        fs::remove_file(registry).unwrap();
    }

    #[test]
    fn invalid_json_and_oversized_lines_are_rejected() {
        let invalid = process_request(
            b"{",
            &EncodeOptions::default(),
            &|_: &EncodedPayload| -> Result<(), PublishError> {
                panic!("invalid input must not reach publisher")
            },
        );
        assert_eq!(invalid["error"]["code"], "invalid_json");
        let oversized = rejected("unknown", "request_too_large", "limit", None);
        assert_eq!(oversized["error"]["code"], "request_too_large");
    }

    #[test]
    fn unix_connection_requires_newline_and_returns_one_json_line() {
        let registry = test_registry();
        let (mut client, server) = UnixStream::pair().unwrap();
        let mut request = compact_request();
        request.push(b'\n');
        client.write_all(&request).unwrap();
        client.shutdown(std::net::Shutdown::Write).unwrap();
        handle_connection(server, &registry, &EncodeOptions::default(), &|_| Ok(())).unwrap();
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        let response: Value = serde_json::from_str(response.trim()).unwrap();
        assert_eq!(response["status"], "published");
        fs::remove_file(registry).unwrap();
    }

    #[test]
    fn unix_connection_rejects_missing_newline() {
        let registry = test_registry();
        let (mut client, server) = UnixStream::pair().unwrap();
        client.write_all(&compact_request()).unwrap();
        client.shutdown(std::net::Shutdown::Write).unwrap();
        handle_connection(server, &registry, &EncodeOptions::default(), &|_| {
            panic!("bad framing must not reach publisher")
        })
        .unwrap();
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        let response: Value = serde_json::from_str(response.trim()).unwrap();
        assert_eq!(response["error"]["code"], "invalid_framing");
        fs::remove_file(registry).unwrap();
    }

    #[test]
    fn unix_connection_rejects_oversized_request() {
        let registry = test_registry();
        let (mut client, server) = UnixStream::pair().unwrap();
        let handler = std::thread::spawn(move || {
            handle_connection(server, &registry, &EncodeOptions::default(), &|_| {
                panic!("oversized input must not reach publisher")
            })
            .unwrap();
        });
        client
            .write_all(&vec![b'a'; MAX_REQUEST_BYTES + 1])
            .unwrap();
        client.shutdown(std::net::Shutdown::Write).unwrap();
        handler.join().unwrap();
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        let response: Value = serde_json::from_str(response.trim()).unwrap();
        assert_eq!(response["error"]["code"], "request_too_large");
    }
}
