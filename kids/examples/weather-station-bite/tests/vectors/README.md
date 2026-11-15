# Conformance vectors

Synthetic datagrams for the `weather-station` dictionary and what this kid must make of each. `tests/conformance.rs` runs every file.

| Key | Meaning |
|---|---|
| `datagramHex` | the UDP payload |
| `receivedAt` | the arrival time given to the mapper (`$receivedAt`) |
| `decodeError` | present when the datagram cannot be decoded: text the error contains |
| `decoded` | the message name and the decoded fields; `null` for a field beyond the end of the datagram |
| `track` | the Canonical Track v2 record sent to the translator, or `null` when none is sent |
| `missing` | required canonical fields the mapping could not fill; a track is sent only when this is empty |

Numbers are compared by value; everything else must match exactly.

| Vector | Exercises |
|---|---|
| `position` | a complete Position message to one track |
| `position_boundary` | latitude -90, longitude 180, negative altitude |
| `position_truncated` | a datagram cut short: fields beyond it are `null`, no track |
| `position_not_a_number` | a NaN latitude, no track |
| `position_no_station` | an empty station identifier, no track |
| `heartbeat`, `observation` | messages with no map: decoded, no track |
| `unknown_type` | a type code the interface does not name |
| `empty` | a datagram too short to hold the message type |

The dictionary carries its own decode vectors in `schemas/weather-station/vectors/`. The runtime runs those at start-up and the test suite runs them too.
