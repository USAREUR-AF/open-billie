//! The built runtime: a UDP datagram in, a translation request on the local
//! socket out. A stub stands in for the translator; no Zenoh is involved.

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

fn hex(text: &str) -> Vec<u8> {
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn a_udp_datagram_reaches_the_translator_socket_as_a_canonical_track() {
    let package = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let socket_path =
        std::env::temp_dir().join(format!("bite-kid-test-{}.sock", std::process::id()));
    let _ = std::fs::remove_file(&socket_path);
    let listener = UnixListener::bind(&socket_path).unwrap();

    // The translator stub: answer every request as published, pass it on.
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

    // A free UDP port for the kid to bind.
    let port = UdpSocket::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let _kid = Kid(Command::new(env!("CARGO_BIN_EXE_billie-bite-kid"))
        .env("BITE_KID_ID", "weather-station-bite")
        .env("BITE_KID_OUTPUTS", "tracks-cot:cot,tracks-sapient:sapient")
        .env(
            "BITE_KID_DICTIONARY",
            package.join("schemas/weather-station"),
        )
        .env("BITE_KID_MAPPINGS", package.join("mappings"))
        .env("BITE_KID_LOOKUPS", package.join("lookups"))
        .env("BILLIE_INPUT_BIND", "127.0.0.1")
        .env("BILLIE_INPUT_PORT", port.to_string())
        .env("BILLIE_INPUT_TRANSPORT", "udp")
        .env("BILLIE_TRANSLATOR_SOCKET", &socket_path)
        .stdout(Stdio::null())
        .spawn()
        .unwrap());

    // Heartbeat, truncated Position and unknown type produce no request; the
    // complete Position produces one per declared output. Resend until the
    // kid has bound its port.
    let sender = UdpSocket::bind("127.0.0.1:0").unwrap();
    let datagrams = [
        "01000c4b5837000001518060",
        "03001b4b5837004050359e83e425afc06276ecbf",
        "2a0003",
        "03001b4b5837004050359e83e425afc06276ecbfb15b5743088000",
    ];
    let mut first = None;
    for _ in 0..100 {
        for datagram in datagrams {
            let _ = sender.send_to(&hex(datagram), ("127.0.0.1", port));
        }
        if let Ok(request) = received.recv_timeout(Duration::from_millis(100)) {
            first = Some(request);
            break;
        }
    }
    let first = first.expect("the kid sent no translation request within ten seconds");
    let second = received.recv_timeout(Duration::from_secs(5)).unwrap();
    let _ = std::fs::remove_file(&socket_path);

    assert_eq!(
        first["target"],
        json!({"outputName": "tracks-cot", "format": "cot"})
    );
    assert_eq!(
        second["target"],
        json!({"outputName": "tracks-sapient", "format": "sapient"})
    );
    for request in [&first, &second] {
        assert_eq!(request["apiVersion"], "billie.dev/translation-v1");
        assert_eq!(request["kind"], "TranslateRequest");
        assert_eq!(request["kid"], "weather-station-bite");
        assert!(!request["requestId"].as_str().unwrap().is_empty());
        let record = &request["record"];
        assert_eq!(record["trackId"], "KX7");
        assert_eq!(record["sourceId"], "WX");
        assert_eq!(record["testData"], true);
        assert_eq!(record["classification"], "other");
        assert_eq!(
            record["position"],
            json!({"latitudeDeg": 64.8378, "longitudeDeg": -147.7164, "altitudeM": 136.5})
        );
        // RFC 3339 UTC with milliseconds, e.g. 2026-01-01T00:00:00.000Z.
        let observed = record["observedAt"].as_str().unwrap();
        assert_eq!(observed.len(), 24, "{observed}");
        assert!(observed.ends_with('Z') && observed.as_bytes()[10] == b'T');
    }
    assert_eq!(first["record"], second["record"]);
}
