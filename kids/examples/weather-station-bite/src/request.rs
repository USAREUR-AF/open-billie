//! The translation request a kid sends to the shared translator, and the
//! timestamp format Canonical Track v2 uses.

use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

/// A `billie.dev/translation-v1` request for one canonical record and one
/// logical output.
pub fn translation_request(
    kid: &str,
    request_id: &str,
    output_name: &str,
    format: &str,
    record: &Value,
) -> Value {
    json!({
        "apiVersion": "billie.dev/translation-v1",
        "kind": "TranslateRequest",
        "requestId": request_id,
        "kid": kid,
        "target": { "outputName": output_name, "format": format },
        "record": record,
    })
}

/// `time` as `YYYY-MM-DDTHH:MM:SS.mmmZ`.
pub fn rfc3339_millis(time: SystemTime) -> String {
    let ms = time
        .duration_since(UNIX_EPOCH)
        .map_or(0, |duration| duration.as_millis() as i64);
    let (days, rem) = (ms.div_euclid(86_400_000), ms.rem_euclid(86_400_000));
    // Howard Hinnant's civil_from_days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!(
        "{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}.{:03}Z",
        rem / 3_600_000,
        rem / 60_000 % 60,
        rem / 1000 % 60,
        rem % 1000
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn timestamps_are_rfc3339_utc_with_milliseconds() {
        let at = |ms: u64| rfc3339_millis(UNIX_EPOCH + Duration::from_millis(ms));
        assert_eq!(at(0), "1970-01-01T00:00:00.000Z");
        assert_eq!(at(1_761_739_200_123), "2025-10-29T12:00:00.123Z");
        assert_eq!(at(1_709_251_199_999), "2024-02-29T23:59:59.999Z");
    }
}
