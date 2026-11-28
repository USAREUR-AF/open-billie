# Mapping to Canonical Track v2

The mapping is code (`map` in `src/lib.rs`):

| Canonical Track v2 | Remote ID |
|---|---|
| `trackId` | DRIP DET when authenticated, else the first Basic ID, else the transmitter address |
| `sourceId` | `REMOTE_ID_SOURCE_ID` (default `remote-id`) |
| `trackGeneration` | when this kid first heard the transmitter (ms) |
| `position` | Location latitude, longitude, geodetic altitude |
| `velocity` | Location direction and horizontal speed, vertical speed |
| `classification` | `uas` |
| `confidence` | trust score, 0 (fake) to 1 (authenticated) |
| `confirmed` | `false` when the transmitter is graded suspicious |
| `identifiers` | `remote-id-trust` verdict, `remote-id-transmitter`, `remote-id-trust-reasons` |

A transmitter graded spoofed is not published.
