# Platform validation log

This document records completed development checks. It contains no operator workstation paths, node addresses, machine names, or credential locations. Historical deployment checks do not imply that a currently connected node has Billie installed or is publishing health.

## Workstation-to-node and platform checks

The following checks have been completed in development environments:

- Added branch-push and pull-request CI for platform Python, OETF Python and Rust, CLI/shell syntax, Ansible syntax, translator Rust, TypeScript, image pins, provenance, release payload parity, and public-boundary checks. On 2026-11-01, the local platform Python suite passed (42 tests), OETF Python passed 15 tests, OETF Rust passed 6 tests including conformance, and translator Rust passed formatting plus 38 tests. TypeScript passed typecheck and 30 decoder/mapping tests. All four Ansible playbooks passed syntax checks. The arm64 platform package and tarball built; the payload audit found 31 matching allowlisted files, no kid or credential paths, and confirmed `arm64`. The operator reported GitHub Actions CI passed. On 2026-11-03, current-source, reachable-history, and release-hygiene scans passed with no high-confidence public-boundary findings. These scans cover the local checkout and refs available to it; verify any additional published refs before a tagged release.

- Built the allowlisted Debian package and matching tarball; verified checksums and test-key signatures.
- Exercised the SSH installer against an Ubuntu 24.04 test environment, including host-key checking, transfer, remote checksum verification, apt installation, and `billie install`.
- On 2026-11-01, upgraded an Ubuntu 24.04 WSL2 test guest with the current amd64 development artifact. Checksum verification, `billie install`, a temporary isolated `billie init`, `check`, `apply`, `verify`, local Zenoh health publication, and a repeat `check` with zero changes passed. This did not bootstrap or enroll NetBird.
- Built and installed the synthetic OETF Rust kid 0.1.4 for linux/amd64 in that guest. Loopback UDP and a fragmented two-frame TCP stream were accepted for CoT (311 bytes), CAT062 (27 bytes), and SAPIENT (241 bytes). The guest uses Podman CNI; activation now verifies the exact CNI or Netavark DNAT target. This exercises virtual loopback only, not physical sensor networking.
- Exercised `billie bootstrap`, `init`, a mocked `join`, `check`, `apply`, `verify`, and `status`. The mocked join did not enroll with a live NetBird management service.
- Validated the generic kid template and synthetic OETF example. Placeholder image references were correctly rejected in strict mode.
- Exercised kid scanning and mapper generation using synthetic JSON and protobuf fixtures.
- Ran the synthetic OETF decoder-to-translator path over a local Unix socket. This did not connect to Zenoh or a fabric.
- Ran the imported TypeScript, Python, and Rust OETF component checks, plus translator and schema checks.
- Applied the generic Zenoh island, local health publication, mTLS client, and one-way bridge on a test Ubuntu arm64 node. Billie health was published locally, and the bridge accepted writes. This did not confirm delivery to an independent remote subscriber.
- On 2026-11-01, completed a clean ARM64 Pi acceptance run with platform 0.2.1 and OETF 0.1.4. The guided setup installed and configured the platform, imported the local fabric bundle, assigned the sensor interface, built and installed the ARM64 kid, and configured/activated its TCP listener. `sudo billie verify` passed all 12 checks; the five platform/kid services were active. The kid logged translator acceptance for CoT, CAT062, and SAPIENT, and the operator confirmed an OETF publication through an authorized fabric subscriber. This exercised the 0.2.1 listener-forwarding cleanup and verification on the Pi.
- SSH to the Pi and non-interactive sudo worked with the configured SSH key; no password prompt was needed. An independent command-line subscriber was not part of this acceptance; the operator confirmed the downstream OETF publication in the fabric viewer.
- Confirmed that the Debian release contains only allowlisted platform files and does not embed kid or OETF assets.
- The operator reports that a kid package from a separate folder, for a different sensor, was selected in the wizard, built, installed, activated, and exercised successfully. The proprietary/external package and sensor payload are intentionally not included in this repository. This is operator-reported acceptance; the repository does not contain its package or a reproducible test fixture.

## Known validation gaps

- The macOS platform builder runs the Debian release build inside a Rust 1.75 Linux container. It has not yet been exercised on Apple Silicon or Intel macOS.
- The GitHub Actions OIDC release signing workflow has not been exercised against a published release.
- A live NetBird management enrollment has not been validated by the repository's automated exercise.
- Independent receipt of a bridged health publication by a remote subscriber remains unverified.
- The OETF Python UDP/TCP runtime and TypeScript TCP runtime were deployed on a test Pi. A two-frame fragmented TypeScript TCP stream was accepted by the translator and published through the CoT and CAT062 outputs. The shared Rust SAPIENT encoder has a round-trip test that decodes protobuf bytes with a Prost model matching official BSI Flex 335 v2 field numbers. OETF RCS maps to canonical `sapient-object-info` identifiers in Python, TypeScript, and Rust.
- In an earlier run, the OETF Rust 0.1.4 kid was built for arm64, installed, and activated on the test Pi. Synthetic frames were sent over TCP and UDP, and the Rust runtime logged translator acceptance for CoT, CAT062, and SAPIENT. A later clean platform 0.2.1 acceptance used the Python OETF runtime over TCP and exercised stale Netavark forward cleanup and active DNAT verification. Independent SAPIENT receiver interoperability remains unverified.

- Focused kid activation regression checks cover cleanup-before-start ordering and exact Netavark/CNI DNAT verification. The Pi acceptance exercised the Netavark path. The CNI stale-rule cleanup case is not yet exercised.

See [the project plan](PROJECT_PLAN.md) and [troubleshooting](../deploy/TROUBLESHOOTING.md) for implementation status and operator guidance.

## Synthetic OETF UDP smoke test

Use the repository's sample generator to exercise the OETF decoder, mapper, Rust translator, encoders, and local Zenoh routes. It sends a synthetic frame marked as both test data and simulated. The default track ID is valid for the CAT-062 example encoder.

From Windows PowerShell:

```powershell
py -3 .\tools\generate-oetf-sample.py --udp-host <node-address> --udp-port 5100
```

From macOS or Linux:

```sh
python3 tools/generate-oetf-sample.py --udp-host <node-address> --udp-port 5100
```

Replace `<node-address>` with an address that can reach the node's UDP listener. To save the binary frame without sending it, add `--output sample.oetf`. The local output routes are `billie/oetf/tracks-cot/cot`, `billie/oetf/tracks-cat062/asterix-cat062`, and `billie/oetf/tracks-sapient/sapient`. A successful local result does not establish delivery to a remote fabric subscriber.

## Synthetic OETF TCP smoke test

Select the declared TCP listener in the kid wizard, using the node sensor address and port. The command below sends two back-to-back frames over one connection in 7-byte writes; this exercises frame reassembly without relying on TCP read boundaries.

From Windows PowerShell:

```powershell
py -3 .\tools\generate-oetf-sample.py --tcp-host <node-address> --tcp-port 5100 --tcp-source <workstation-sensor-address> --tcp-repeat 2 --tcp-chunk-size 7
```

From macOS or Linux:

```sh
python3 tools/generate-oetf-sample.py --tcp-host <node-address> --tcp-port 5100 --tcp-source <workstation-sensor-address> --tcp-repeat 2 --tcp-chunk-size 7
```

The OETF runtime accepts one TCP sensor connection at a time and accepts another after the current connection closes. For two frames and three encoders, expect six translator accepted log lines; then check the CoT, CAT062, and SAPIENT routes in an authorized subscriber. SAPIENT payloads are BSI Flex 335 v2.0 protobuf messages and require the node identity UUID created during Billie initialization. Independent SAPIENT receiver interoperability remains to be confirmed.
