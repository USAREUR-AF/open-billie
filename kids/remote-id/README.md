# remote-id kid

Drone Remote ID to `uas` tracks. Remote ID (ASTM F3411-22a, ASD-STAN EN
4709-002) is an open broadcast standard, and an unsigned one: any serial
number and position can be typed into a cheap board. This kid decodes the
frames with the [`remoteid`](https://crates.io/crates/remoteid) crate, keeps
one entry per transmitter, and grades each one before it becomes a track:

| Verdict | Published as |
|---|---|
| authenticated (DRIP signature) | confirmed track |
| plausible | confirmed track |
| suspicious | tentative track (`confirmed: false`, CoT remark `tentative`) |
| spoofed | not published |

The verdict and its reasons travel in `identifiers`; the field mapping is in
[mappings/README.md](mappings/README.md).

## Input

One frame per UDP datagram on `BILLIE_INPUT_PORT` (40110):

- `REMOTE_ID_LINK=wifi` (default): an 802.11 Beacon or NAN action frame, with
  or without a radiotap header, as a monitor-mode interface gives it.
- `REMOTE_ID_LINK=ble`: the 6-byte advertiser address, then the advertising
  data (Bluetooth 4 legacy or Bluetooth 5 extended).

## Test

```bash
cargo fmt --manifest-path kids/remote-id/Cargo.toml -- --check
cargo test --locked --manifest-path kids/remote-id/Cargo.toml
```

The tests build synthetic broadcasts with the crate's encoder: a plausible
aircraft becomes a `uas` track, and a transmitter that jumps about 1,100 km a
second is withheld.
