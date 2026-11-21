//! The built kid: a CoT XML datagram in, one translation request per output
//! out. A stub stands in for the translator.

use std::io::{BufRead, BufReader, Write};
use std::net::UdpSocket;
use std::os::unix::net::UnixListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::Duration;

use serde_json::{json, Value};

struct Kid(Child);

impl Drop for Kid {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
fn a_cot_datagram_reaches_the_translator_once_per_output() {
    let package = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let socket_path =
        std::env::temp_dir().join(format!("xf-ingest-test-{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path).unwrap();

    let (requests, received) = mpsc::channel::<Value>();
    std::thread::spawn(move || {
        for connection in listener.incoming() {
            let mut connection = connection.unwrap();
            let mut line = String::new();
            BufReader::new(connection.try_clone().unwrap())
                .read_line(&mut line)
                .unwrap();
            let request: Value = serde_json::from_str(&line).unwrap();
            let response = json!({
                "apiVersion": "billie.dev/translation-v1",
                "kind": "TranslateResult",
                "requestId": request["requestId"],
                "status": "published",
                "outputName": request["target"]["outputName"],
                "format": request["target"]["format"],
                "bytesPublished": 128,
            });
            connection
                .write_all(format!("{response}\n").as_bytes())
                .unwrap();
            if requests.send(request).is_err() {
                break;
            }
        }
    });

    let port = UdpSocket::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let _kid = Kid(Command::new(env!("CARGO_BIN_EXE_billie-xf-ingest"))
        .env("XF_KID_ID", "xf-ingest")
        .env(
            "XF_OUTPUTS",
            "tracks-cot:cot,tracks-sapient:sapient,tracks-cat062:asterix-cat062",
        )
        .env("XF_PACKS", package.join("goat-transformers/packs"))
        .env("XF_MODELS", package.join("goat-transformers/model"))
        .env("XF_FROM_FORMAT", "cot-xml")
        .env("XF_SOURCE_ID", "sensor-a")
        .env("BILLIE_INPUT_TRANSPORT", "udp")
        .env("BILLIE_INPUT_PORT", port.to_string())
        .env("BILLIE_TRANSLATOR_SOCKET", &socket_path)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap());

    // tests/vectors/cot-xml--15-course-and-speed-give-velocity.json; a
    // datagram that is not CoT is counted and skipped. Resend until the kid
    // has bound its port.
    let event = r#"<event version="2.0" uid="J-5" type="a-f-G" time="2021-02-27T20:00:00.000Z" start="2021-02-27T20:00:00.000Z"><point lat="1" lon="2" hae="3" ce="4" le="5"/><detail><track course="30" speed="10"/></detail></event>"#;
    let sender = UdpSocket::bind("127.0.0.1:0").unwrap();
    let mut first = None;
    for _ in 0..100 {
        let _ = sender.send_to(b"not a cot event", ("127.0.0.1", port));
        let _ = sender.send_to(event.as_bytes(), ("127.0.0.1", port));
        if let Ok(request) = received.recv_timeout(Duration::from_millis(100)) {
            first = Some(request);
            break;
        }
    }
    let first = first.expect("the kid sent no translation request within ten seconds");
    let second = received.recv_timeout(Duration::from_secs(5)).unwrap();
    let third = received.recv_timeout(Duration::from_secs(5)).unwrap();
    let _ = std::fs::remove_file(&socket_path);

    let targets: Vec<&Value> = [&first, &second, &third]
        .iter()
        .map(|r| &r["target"])
        .collect();
    assert_eq!(
        targets,
        [
            &json!({"outputName": "tracks-cot", "format": "cot"}),
            &json!({"outputName": "tracks-sapient", "format": "sapient"}),
            &json!({"outputName": "tracks-cat062", "format": "asterix-cat062"}),
        ]
    );
    for request in [&first, &second, &third] {
        assert_eq!(request["kind"], "TranslateRequest");
        assert_eq!(request["kid"], "xf-ingest");
        let record = &request["record"];
        assert_eq!(record["trackId"], "J-5");
        assert_eq!(record["sourceId"], "sensor-a");
        assert_eq!(record["trackGeneration"], "1");
        assert_eq!(record["observedAt"], "2021-02-27T20:00:00.000Z");
        assert_eq!(
            record["position"],
            json!({"latitudeDeg": 1, "longitudeDeg": 2, "altitudeM": 3})
        );
        // `a-f-G` is a CoT type with no Billie class: removed, not sent.
        assert!(record.get("classification").is_none());
    }
}
