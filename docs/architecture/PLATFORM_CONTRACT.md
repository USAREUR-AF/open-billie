# Initial Platform Contract

## First deployment target

- Flow: Billie Modular Golden Path A, self-hosted single node.
- Host: Ubuntu Server 24.04 on arm64 or amd64.
- Build and delivery: build a versioned Debian package on the workstation, verify release signatures and checksums, transfer over SSH, and install with apt.
- Node execution: the node runs Ansible locally. The source repository is not cloned onto the node.
- Container runtime: Podman; no Docker daemon is part of the production contract.
- UI: out of scope.

## CLI boundary

- billie is the platform operator CLI.
- Kid package operations are implemented as `billie kid` subcommands. A separate billie-builder application or UI is deferred.
- Open Billie implements the platform flow based on the Billie Modular Golden Path and provisions the local Zenoh island, an optional client-mode fabric session with mTLS, and the one-way output bridge. It owns their configuration, service lifecycle, health checks, and troubleshooting.
- Open Billie manages the generic host baseline, can bootstrap the NetBird agent, and includes stateless kid bundle build/install/configure/activation/removal commands. The workstation setup wizard provisions the platform, configures node identity/fabric, then offers local kid discovery, build, transfer, listener selection, and activation.

## State locations

- Versioned platform software: /opt/billie/platform/releases/<version>
- Active platform release: /opt/billie/platform/current
- Persistent node identity: /etc/billie/identity/node.yml, mode 0600
- Persistent platform state: /var/lib/billie
- Ephemeral health report: /run/billie/health.json; the same JSON is published every minute to local Zenoh at `ops/<node-handle>/health`. It reports degraded status when the local Zenoh router, translator service/socket, or configured fabric client/bridge is unavailable. Kid health is reported separately by its systemd service and status command.
- Zenoh and fabric configuration: /etc/billie/zenoh; site values are excluded from release artifacts and source control
- Fabric certificate material: /etc/billie/zenoh/tls; private key mode 0600

Platform upgrades must not replace identity or persistent state.

The local Zenoh router is an island and never federates. Fabric connectivity uses a separate client-mode Zenoh session with routing and multicast scouting disabled. A one-way bridge copies local publications to the fabric under the configured vendor prefix. The router cannot expose its local storage to the fabric.

## Initial commands

- billie install verifies dependencies and prepares the protected identity directory.
- billie bootstrap installs and starts NetBird from its signed APT repository; it does not enroll the node.
- billie init writes a node handle and supply mode through Ansible.
- billie join accepts a setup-key file and HTTPS management URL for connected nodes after bootstrap; it never prints the key value. Offline nodes use billie init with supply mode airgap.
- billie check runs Ansible in check/diff mode.
- billie apply converges the generic platform baseline.
- billie verify checks the health timer and sample, local Zenoh island, translator publisher, and configured fabric client/bridge services.

## Provisioning flow alignment and current acceptance

The implemented platform follows the Billie Modular Golden Path and OctoPod handoff:

1. Prepare the Ubuntu host and SSH access outside this repository.
2. Build a versioned, allowlisted platform artifact on the workstation.
3. Transfer the artifact to the host over SSH and install it with apt.
4. Initialize or join the node after the platform package is installed.
5. Run `billie check`, `billie apply`, and `billie verify` on the node; Ansible converges locally and the node does not clone the source repository.

The signed SSH platform installation, bootstrap/init flow, local platform verification, and synthetic OETF translator path have been exercised in development environments. A clean ARM64 Pi deployment with platform 0.2.1 completed platform setup and OETF TCP kid activation; `billie verify` passed and the operator confirmed an OETF publication through an authorized fabric subscriber. The Pi run exercised listener-forward cleanup and active-forward verification. Independent remote health receipt, the GitHub keyless workflow, and a fresh live NetBird enrollment still need separate validation. See the [validation log](../TESTING.md).

Deferred: simultaneous multi-listener kid support, persistent kid storage, fleet management, and Ubuntu 26.04 support. Stateless kid upgrade and rollback are implemented; their upgrade/rollback sequence still needs Pi acceptance.

The OETF example proves that synthetic decode and mapping reach the shared translator contract. The clean platform 0.2.1 TCP run delivered OETF output visible through an authorized fabric subscriber and exercised the listener-forwarding fix. This data publication does not by itself prove independent remote health-topic receipt.
## Deferred

The kid bundle lifecycle, listener configuration, runtime activation, package removal, stateless upgrade/rollback, and full platform teardown are implemented for packages with one selected listener at a time. Simultaneous multiple listeners, persistent paths, fleet management, and support for Ubuntu 26.04 are later slices. Zenoh, mTLS, routing, and the bridge are part of the Open Billie platform implementation, not an external prerequisite.
