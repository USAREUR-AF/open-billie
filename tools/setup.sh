#!/usr/bin/env bash
# Guided workstation flow: build or select a release, install it, then configure the node.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { printf '\nOpen Billie setup: %s\n' "$*" >&2; exit 2; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing prerequisite '$1'. See deploy/README.md for platform setup."; }
ask() { local prompt="$1" default="${2:-}" value; if [ -n "$default" ]; then read -r -p "$prompt (default: $default): " value; printf '%s' "${value:-$default}"; else read -r -p "$prompt: " value; printf '%s' "$value"; fi; }
confirm() { local answer; read -r -p "$1 [y/N] " answer; [[ "$answer" == [yY] || "$answer" == [yY][eE][sS] ]]; }

printf '\nOpen Billie guided setup\n========================\nThis installs the platform on a prepared Ubuntu 24.04 node over SSH.\nIt does not install Ubuntu or create node/network credentials.\n\n'
for cmd in ssh scp; do require "$cmd"; done

build_default=1
if ! command -v dpkg-deb >/dev/null 2>&1; then build_default=2; fi
mac_platform_engine=""
if [ "$(uname -s)" = Darwin ]; then
  build_default=2
  if platform_check="$(bash tools/check-container-prerequisites.sh platform 2>&1)"; then
    mac_platform_engine="$(printf '%s\n' "$platform_check" | sed -n 's/^Selected container engine: //p' | tail -n 1)"
    build_default=1
  fi
  printf 'The platform .deb is built inside a Linux container on macOS.\n'
  printf '%s\n' "${platform_check:-No ready container engine was detected.}"
  build_choice="$(ask 'Release source: [1] Build in Linux container [2] Existing' "$build_default")"
else
  build_choice="$(ask 'Release source: [1] Build [2] Existing' "$build_default")"
fi
built_locally=0
case "$build_choice" in
  1|build|Build|BUILD)
    built_locally=1
    require tar; require sha256sum
    if [ "$(uname -s)" = Darwin ]; then
      host_arch="$(uname -m)"
    else
      require cargo; require rustc; require dpkg-deb
      host_arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"
    fi
    case "$host_arch" in x86_64|amd64) host_deb=amd64 ;; aarch64|arm64) host_deb=arm64 ;; *) fail "unsupported workstation architecture: $host_arch" ;; esac
    case "$host_deb" in amd64) arch_default=1 ;; arm64) arch_default=2 ;; esac
    arch_choice="$(ask 'Target node architecture: [1] amd64 [2] arm64' "$arch_default")"
    case "$arch_choice" in 1|amd64) target_arch=amd64 ;; 2|arm64) target_arch=arm64 ;; *) fail 'enter 1 for amd64 or 2 for arm64' ;; esac
    case "$target_arch" in
      amd64) triple=x86_64-unknown-linux-gnu ;;
      arm64) triple=aarch64-unknown-linux-gnu ;;
      *) fail 'choose amd64 or arm64' ;;
    esac
    if [ "$(uname -s)" = Darwin ]; then
      if [ -z "$mac_platform_engine" ]; then
        platform_check="$(bash tools/check-container-prerequisites.sh platform 2>&1)" || fail "$platform_check"
        printf '%s\n' "$platform_check"
        mac_platform_engine="$(printf '%s\n' "$platform_check" | sed -n 's/^Selected container engine: //p' | tail -n 1)"
      fi
      [ -n "$mac_platform_engine" ] || fail 'container prerequisite check did not select an engine'
      BILLIE_CONTAINER_ENGINE="$mac_platform_engine" bash tools/build-platform-release-container.sh --target-triple "$triple"
    elif [ "$target_arch" = "$host_deb" ]; then
      bash tools/build-platform-release.sh
    else
      printf 'Cross-building requires the matching Rust target and GNU cross compiler.\n'
      confirm 'Continue with the cross-build now?' || exit 0
      BILLIE_TARGET_TRIPLE="$triple" bash tools/build-platform-release.sh
    fi
    deb="$(ls -t dist/billie-platform_*_"$target_arch".deb 2>/dev/null | head -n 1)"
    [ -n "$deb" ] || fail 'the build completed but its Debian package could not be located in dist/'
    ;;
  2|existing|Existing|EXISTING)
    deb="$(ask 'Path to the release .deb package')"
    ;;
  *) fail 'enter 1 for Build or 2 for Existing' ;;
esac
[ -f "$deb" ] || fail "package not found: $deb"

target="$(ask 'Node SSH target (user@host)')"
[[ "$target" =~ ^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]] || fail 'target must be user@host'
default_verify=1
[ "$built_locally" -eq 1 ] && default_verify=2
verify="$(ask 'Release verification: [1] Signed [2] Checksum-only' "$default_verify")"
install_args=(--target "$target" --deb "$deb")
case "$verify" in
  1|signed|Signed|SIGNED)
    require cosign
    identity="$(ask 'Trusted release certificate identity (from project maintainers)')"
    [ -n "$identity" ] || fail 'a trusted signing identity is required for signed releases'
    install_args+=(--certificate-identity "$identity")
    ;;
  2|checksum-only|Checksum-only|CHECKSUM-ONLY)
    printf 'Checksum-only verifies file integrity but does not identify who built the release. Use only for local development.\n'
    confirm 'Use checksum-only verification for this local development install?' || exit 0
    install_args+=(--checksum-only)
    ;;
  *) fail 'enter 1 for Signed or 2 for Checksum-only' ;;
esac

printf '\nThe installer will now check host trust, SSH, node OS/architecture, and sudo before changing the node.\n'
confirm "Install Open Billie on $target now?" || exit 0
bash tools/install-to-node.sh "${install_args[@]}"
if confirm 'Continue to the interactive node configuration now?'; then
  while true; do
    if bash tools/configure-node.sh "$target"; then
      break
    fi
    printf '\nNode configuration did not complete. Billie remains installed; you can retry this step without rebuilding or reinstalling.\n' >&2
    if ! confirm 'Retry node configuration now?'; then
      printf '\nTo resume later, run: bash tools/configure-node.sh %s\n' "$target"
      exit 0
    fi
  done
  if confirm 'Deploy a kid package now?'; then
    while true; do
      if bash tools/deploy-kid.sh "$target"; then
        break
      fi
      printf '\nKid deployment did not complete. Billie remains installed and configured; you can retry this step.\n' >&2
      if ! confirm 'Retry kid deployment now?'; then
        printf '\nTo resume later, run: bash tools/deploy-kid.sh %s\n' "$target"
        exit 0
      fi
    done
  else
    printf '\nNode configuration is complete. To deploy a kid later, run: bash tools/deploy-kid.sh %s\n' "$target"
  fi
else
  printf '\nInstall is complete. To configure later, run: bash tools/configure-node.sh %s\n' "$target"
fi
