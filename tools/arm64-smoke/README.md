# ARM64 platform smoke test

This disposable Docker test runs the ARM64 `billie-translator` binary from a built platform `.deb` under Docker Desktop ARM64 emulation. It checks that the translator starts and creates its Unix socket with mode `0660` and group `billie-kids`.

From PowerShell at the repository root:

```powershell
docker compose -f tools/arm64-smoke/compose.yaml run --build --rm arm64-platform-smoke
```

The test selects the newest `dist/billie-platform_*_arm64.deb`. Build a fresh package first when validating current source changes:

```bash
BILLIE_TARGET_TRIPLE=aarch64-unknown-linux-gnu bash tools/build-platform-release.sh
```

This smoke test does not simulate Ubuntu host `systemd`, Podman, Netplan, UFW, NetBird, or end-to-end sensor-to-Zenoh provisioning. Containers share the Docker VM kernel; use a dedicated Ubuntu 24.04 VM for those behaviors.
