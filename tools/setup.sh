#!/usr/bin/env bash
# Guided workstation flow: build or select a release, install it, then configure the node.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { printf '\nOpen Billie setup: %s\n' "$*" >&2; exit 2; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing prerequisite '$1'. See deploy/README.md for platform setup."; }
ask() { local prompt="$1" default="${2:-}" value; printf '\n' >&2; if [ -n "$default" ]; then read -r -p "$prompt (default: $default): " value; printf '%s' "${value:-$default}"; else read -r -p "$prompt: " value; printf '%s' "$value"; fi; }
confirm() { local answer; printf '\n' >&2; read -r -p "$1 [y/N] " answer; [[ "$answer" == [yY] || "$answer" == [yY][eE][sS] ]]; }

version="$(tr -d '\r\n' < deploy/VERSION)"
if [ -z "$version" ]; then version='unknown'; fi
printf '\n####  #####  #      #      #####  #####\n'
printf   '#   #   #    #      #        #    #\n'
printf   '####    #    #      #        #    ####\n'
printf   '#   #   #    #      #        #    #\n'
printf   '####  #####  #####  #####  #####  #####\n\n'
printf 'Open Billie v%s | Guided setup \n' "$version \n"
printf '            ____\n'
printf '           / __ `.\n'
printf '          / /   `.\ \n'
printf '       __/_/      ` \n'
printf '      /  `  \__)\n'
printf '     / (o)  | \n'
printf '    /       |                          / \n'
printf '   /        \~^~^~^~^~^~^~^~^~^~^~^~.// \n'
printf '  (_o __,--.                         | \n'
printf '     )   |>o<|                       | \n'
printf '    (      |                         | \n'
printf '     )     |      \~^~^~^~^~^~/      | \n'
printf '           | | | |             | | | | \n'
printf '           | | | |             | | | | \n'
printf '          /__|/__|            /__|/__| \n \n'
printf 'This installs the platform on a prepared Ubuntu 24.04 node over SSH.\n'
printf 'It does not install Ubuntu or create node/network credentials.\n\n'
for cmd in ssh scp; do require "$cmd"; done

build_default=1
mac_platform_engine=""
if [ "$(uname -s)" = Darwin ]; then
  if platform_check="$(bash tools/check-container-prerequisites.sh platform 2>&1)"; then
    mac_platform_engine="$(printf '%s\n' "$platform_check" | sed -n 's/^Selected container engine: //p' | tail -n 1)"
    build_default=1
  fi
  printf 'The platform .deb is built inside a Linux container on macOS.\n'
  printf '%s\n' "${platform_check:-No ready container engine was detected.}"
fi
printf '\nWhat would you like to do?\n'
printf '  [1] Build a new image\n'
printf '  [2] Use an existing image\n'
read -r -p 'Select an option (default: Build a new image): ' build_choice
build_choice="${build_choice:-$build_default}"
built_locally=0
case "$build_choice" in
  1|build|Build|BUILD|'Build a new image')
    built_locally=1
    require tar; require sha256sum
    if [ "$(uname -s)" = Darwin ]; then
      host_arch="$(uname -m)"
    else
      require cargo; require rustc; require dpkg-deb
      host_arch="$(dpkg --print-architecture 2>/dev/null || uname -m)"
    fi
    case "$host_arch" in x86_64|amd64) host_deb=amd64 ;; aarch64|arm64) host_deb=arm64 ;; *) fail "unsupported workstation architecture: $host_arch" ;; esac
    printf '\nWhich architecture are you building for?\n'
    printf '  [1] arm64\n'
    printf '  [2] amd64\n'
    read -r -p 'Select an option (default: arm64): ' arch_choice
    arch_choice="${arch_choice:-1}"
    case "$arch_choice" in 1|arm64) target_arch=arm64 ;; 2|amd64) target_arch=amd64 ;; *) fail 'enter 1 for arm64 or 2 for amd64' ;; esac
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
      printf '\nCross-building requires the matching Rust target and GNU cross compiler.\n' >&2
      read -r -p 'Continue with the cross-build now? [y/N] ' cross_build_answer
      case "$cross_build_answer" in y|Y|yes|YES) ;; *) exit 0 ;; esac
      BILLIE_TARGET_TRIPLE="$triple" bash tools/build-platform-release.sh
    fi
    deb="$(ls -t dist/billie-platform_*_"$target_arch".deb 2>/dev/null | head -n 1)"
    [ -n "$deb" ] || fail 'the build completed but its Debian package could not be located in dist/'
    ;;
  2|existing|Existing|EXISTING|'Use an existing image')
    deb="$(ask 'Path to the release .deb package')"
    ;;
  *) fail 'enter 1 for Build a new image or 2 for Use an existing image' ;;
esac
[ -f "$deb" ] || fail "package not found: $deb"

while true; do
  target="$(ask 'What is the SSH Target? (user@host)')"
  if [[ "$target" =~ ^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]]; then
    break
  fi
  printf 'Invalid target. Enter a username and hostname or IP address, for example operator@192.0.2.10.\n' >&2
done
default_verify=1
[ "$built_locally" -eq 1 ] && default_verify=2
if [ "$default_verify" -eq 1 ]; then verify_default_label='Signed'; else verify_default_label='Checksum-only'; fi
printf '\nWhat type of release verification?\n'
printf '  [1] Signed\n'
printf '  [2] Checksum-only\n'
verify="$(ask 'Select an option' "$verify_default_label")"
install_args=(--target "$target" --deb "$deb")
case "$verify" in
  1|signed|Signed|SIGNED)
    require cosign
    identity="$(ask 'Trusted release certificate identity (from project maintainers)')"
    [ -n "$identity" ] || fail 'a trusted signing identity is required for signed releases'
    install_args+=(--certificate-identity "$identity")
    ;;
  2|checksum-only|Checksum-only|CHECKSUM-ONLY)
    printf '\nChecksum-only verifies file integrity but does not identify who built the release. Use only for local development.\n'
    read -r -p 'Use checksum-only verification for this local development install? [y/N] ' checksum_confirm
    [[ "$checksum_confirm" == [yY] || "$checksum_confirm" == [yY][eE][sS] ]] || exit 0
    install_args+=(--checksum-only)
    ;;
  *) fail 'enter 1 for Signed or 2 for Checksum-only' ;;
esac

printf '\nThe installer will now check host trust, SSH, node OS/architecture, and sudo before changing the node.\n'
confirm "Install Open Billie on $target now?" || exit 0
install_attempt=1
while true; do
  if [ "$install_attempt" -eq 1 ]; then
    if bash tools/install-to-node.sh "${install_args[@]}"; then
      break
    fi
  fi
  install_attempt=1
  printf '\nInstallation did not complete on %s. Select how to continue.\n' "$target" >&2
  printf '  [1] Retry this target\n'
  printf '  [2] Enter a different target\n'
  printf '  [3] Verify/trust this host key from this WSL/Linux terminal\n'
  printf '  [4] Stop setup\n'
  install_retry="$(ask 'Select an option')"
  case "$install_retry" in
    1) ;;
    2)
      while true; do
        target="$(ask 'What is the SSH Target? (user@host)')"
        if [[ "$target" =~ ^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]]; then
          break
        fi
        printf 'Invalid target. Enter a username and hostname or IP address, for example operator@192.0.2.10.\n' >&2
      done
      install_args[1]="$target"
      ;;
    3)
      printf '\nVerify the displayed fingerprint through a trusted channel before accepting it.\n' >&2
      ssh_trust_options=(-o BatchMode=no -o PreferredAuthentications=publickey -o NumberOfPasswordPrompts=0 -o ConnectTimeout=10 -o StrictHostKeyChecking=ask)
      if [ -n "${BILLIE_SSH_KNOWN_HOSTS:-}" ]; then
        ssh_trust_options+=(-o "UserKnownHostsFile=$BILLIE_SSH_KNOWN_HOSTS")
      fi
      if ssh "${ssh_trust_options[@]}" "$target" true; then
        printf 'Host key trusted and key-based SSH access confirmed. Select retry to continue.\n' >&2
      else
        printf 'Host-key trust or key-based SSH authentication failed. Configure key-based access before retrying.\n' >&2
      fi
      install_attempt=0
      ;;
    4) printf 'Setup stopped. The release remains available at %s.\n' "$deb"; exit 0 ;;
    *) printf 'Enter 1, 2, 3, or 4.\n' >&2 ;;
  esac
done
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
