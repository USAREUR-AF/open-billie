# ADR 0002: every Open Billie node taps its sensor link by default with first-bite

Status: Proposed (2026-11-27)

## TL;DR (for a layperson)

When a sensor's tracks look wrong, the first question is what the sensor
actually sent. Today the answer means logging into the node and recording
traffic by hand, after the problem has passed. This record makes every Open
Billie node record each sensor's link all the time with
[first-bite](https://github.com/USAREUR-AF/first-bite), keep the last hour on
its own disk, and publish each finished minute so that a named list of readers
can save the exact bytes and check the work. Open Billie adds no capture code
of its own.

## Context

A kid connects to its sensor and turns the sensor's messages into standard
formats. When the output is wrong, the cause can be the sensor, the link, the
kid or the encoder. Telling them apart needs the bytes on the link at the time.
first-bite's `mind --tap-only` already captures a link passively into rotating
pcap files, keeps a bounded ring, and publishes each finished file to a Zenoh
key through a local REST port (`deployment/tap`, the `first-bite-tap@<name>`
systemd unit). Its `mind goat watch <key> --save <dir>` saves what it receives
unchanged.

The fabric side is goatcore ADR 1270 (Proposed): capture keys live at
`volatile/<anchor>/stream/@pcap/<sensor>/<node>`, routed and never stored, read
only by subjects on a named reader list, never released to partners.

## Decision

1. **One tap per sensor, on by default.** `billie apply` installs first-bite
   from its attested release and enables one `first-bite-tap@<kid-id>` instance
   for each kid that has a network sensor, filtered to that sensor's address and
   port from the kid's configuration. The tap only listens. It never opens a
   connection to the sensor, so a sensor that accepts one client keeps the
   kid's connection.
2. **One-minute slices, a one-hour ring.** `TAP_SLICE_SECONDS=60`,
   `--pcap-slice-mb 1`, `TAP_KEEP=60`: at most 60 MiB per sensor. A slice that
   fails to publish stays in the ring.
3. **Published on the island, forwarded by the bridge.** The tap publishes each
   slice to the local island at `billie/<kid-id>/capture/pcap` (the translator key shape `billie/<kid-id>/<logical-output>/<format>`). The
   one-way bridge forwards it to the fabric at
   `volatile/<vendor-prefix>/stream/@pcap/<kid-id>/<node-handle>` with content
   type `application/vnd.tcpdump.pcap`, unchanged.
4. **Raw is shed before decoded.** The bridge forwards captures in the bulk
   class (congestion control drop, lowest priority) and decoded outputs ahead of
   them. A node short of uplink stops forwarding captures and keeps its ring.
5. **Off is a declared exception.** A node that must not tap a sensor sets
   `capture: off` on that kid with a reason; `billie status` shows it.
6. **No captures in this repository.** Captures stay on the node, on the
   fabric for named readers, and in the sensor owner's private repository.
   Release scans keep refusing packet-capture files.

## Built and not built

| Piece | State |
|---|---|
| `mind --tap-only`, ring, publish to a local REST port, `first-bite-tap@` unit | built in first-bite; in its release candidate 1.2.0-rc.2 |
| `mind goat watch <key> --save <dir>` | built in first-bite, in review |
| A first-bite tap on an Open Billie node, published to its island | running on one node, installed by hand |
| `billie apply` installing first-bite and one tap per kid | not built |
| Bridge mapping of `billie/<kid-id>/capture/pcap` to the `@pcap` fabric key, in the bulk class | not built |
| `capture: off` per kid and its line in `billie status` | not built |
| Fabric write and read rules for `@pcap` keys | goatcore ADR 1270, not built |

## Consequences

**Positive.** The bytes behind any track from the last hour are on the node,
and the last minute is on the fabric for named readers, without anyone logging
in. A kid, encoder or sensor fault can be told apart from a saved slice with
`mind --pcap-file` or `mind discover`.

**Negative.** Each node spends up to 60 MiB of disk and one capture process per
sensor. Captures use uplink when it is available; the bulk class and the
per-kid switch bound that.

## Alternatives considered

- **A capture service inside Open Billie.** Rejected: first-bite already
  captures, rotates, publishes and decodes; a second copy splits where an
  operator looks.
- **Capture only when asked.** Rejected: the traffic that explains a fault has
  passed by the time someone asks.
- **Let the kid record what it reads.** Rejected: the kid sees its parsed
  stream, not the link; a link or framing fault is exactly what it cannot show.
