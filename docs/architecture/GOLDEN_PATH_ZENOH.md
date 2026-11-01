# Open Billie platform: Zenoh and fabric security

Open Billie owns the whole output transport path. A node runs a local Zenoh
island for kids and a separate client-mode Zenoh session for the remote fabric.
The local router never joins the fabric. A one-way bridge moves local
publications through the client session and adds the configured vendor prefix.

## Topology and trust boundary

```
polyglot kid
  -> local Billie translator and encoder
  -> local Zenoh island (REST 127.0.0.1:8000)
  -> one-way prefix bridge
  -> Zenoh client session (REST 127.0.0.1:8001)
  -> mTLS fabric endpoint
```

The router island binds its REST and peer ports to loopback and has local
memory storage. It has no fabric endpoint. The second Zenoh process runs in
client mode with multicast scouting and routing disabled. It receives only the
fabric-client config and TLS directory. The bridge reads the island's REST
event stream and writes samples through the client session; it never subscribes
to or forwards fabric data back to the node.

The platform health timer also publishes its current JSON record locally at
`ops/<node-handle>/health`. The island bridge forwards that key to the fabric as
`<vendor-prefix>/ops/<node-handle>/health`; consumers can subscribe to that
exact expression to observe node health.

Local sensor keys are expected to be scoped by the translator as:

```
billie/<kid-id>/<logical-output>/<format>
```

The bridge places these keys under the configured fabric prefix. A key already
inside that prefix passes through unchanged. Empty or wildcard prefixes are
rejected so the bridge cannot publish unscoped output.

## Configure fabric access

First install and initialize Open Billie, then apply once to start the local
Zenoh island:

```
sudo billie install
sudo billie init <node-handle> --supply connected
sudo billie apply
```

Obtain the fabric CA certificate, client certificate, private key, endpoint,
and authorized prefix from the fabric administrator. Keep the credential files
in a protected temporary directory. Do not copy them into this repository,
the kid package, a release artifact, or a shell command.

Configure the node by passing file paths and non-secret values:

```
sudo billie zenoh configure \
  --endpoint tls/<fabric-host>:<port> \
  --prefix <authorized-prefix> \
  --ca-file /path/to/ca.pem \
  --client-cert-file /path/to/client.pem \
  --client-key-file /path/to/client-key.pem
```

Open Billie validates that the endpoint is TLS, the prefix is literal and
scoped, the certificate inputs are regular files, the certificates parse and
are currently valid, the client certificate chains to the supplied CA, and the
client certificate matches the private key. It copies the CA and certificate
into `/etc/billie/zenoh/tls` and protects the private key as mode `0600`.
Configuration is stored in `/etc/billie/zenoh/fabric.json` with mode
`0600`; it contains only the endpoint and prefix, not the certificate contents or
original input paths.

Apply and verify:

```
sudo billie check
sudo billie apply
sudo billie verify
systemctl status billie-zenohd billie-fabric-client billie-island-bridge
```

## Single-install node lifecycle

Open Billie supports one Billie platform installation per node. Use the standard SSH installer to install or upgrade it. For a clean reprovision, use the standard sudo billie teardown flow; NetBird remains untouched.

## Diagnostics

`billie verify` checks the local router health endpoint. When fabric
configuration exists, it also checks that the client and bridge services are
active. This proves local service health only; it does not prove that the fabric
accepted a message.

Inspect service logs:

```
sudo journalctl -u billie-zenohd -n 80 --no-pager
sudo journalctl -u billie-fabric-client -n 80 --no-pager
sudo journalctl -u billie-island-bridge -n 80 --no-pager
```

The bridge heartbeat reports accepted local-client REST writes, rejected writes,
transport errors, skipped keys, and malformed events. A successful local REST
write is not proof of remote delivery. Confirm delivery with a fabric-side
subscriber authorized for the configured prefix.

If the fabric name cannot resolve in the Zenoh container, first check host
resolution and network reachability. Do not disable Zenoh TLS name checking.
Configure the node/container resolver so that the endpoint hostname resolves
to the fabric address while preserving the hostname used for TLS verification.

## Current implementation limits

The local island, separate mTLS client, prefix bridge, and Rust translator-to-island publisher are implemented. On a clean ARM64 Pi run with platform 0.2.1, systemd and Podman/Quadlet services ran with the provisioned fabric bundle, and the operator confirmed OETF output through an authorized fabric subscriber. This verifies sample data delivery through the configured fabric, but it is not independent validation of the bridge health topic or a second subscriber. Unit checks cover bridge key scoping, event handling, and configuration validation. Platform 0.2.1 cleans stale listener DNAT rules before kid startup and verifies the active forward; the clean Pi run exercised this fix.
