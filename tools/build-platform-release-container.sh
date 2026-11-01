#!/usr/bin/env bash
# Build the Linux platform package from macOS using a pinned Linux toolchain container.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
IMAGE="open-billie/platform-builder:rust-1.75"
target_triple=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-triple)
      [ "$#" -ge 2 ] || { printf '%s\n' 'missing value for --target-triple' >&2; exit 2; }
      target_triple="$2"
      shift 2
      ;;
    -h|--help)
      printf 'Usage: bash tools/build-platform-release-container.sh --target-triple <x86_64-unknown-linux-gnu|aarch64-unknown-linux-gnu>\n'
      exit 0
      ;;
    *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
done
case "$target_triple" in
  x86_64-unknown-linux-gnu|aarch64-unknown-linux-gnu) ;;
  *) printf 'choose a supported Linux target triple with --target-triple\n' >&2; exit 2 ;;
esac

fail() { printf 'Open Billie container build: %s\n' "$*" >&2; exit 2; }
engine="${BILLIE_CONTAINER_ENGINE:-}"
if [ -n "$engine" ]; then
  case "$engine" in docker|podman) ;; *) fail 'BILLIE_CONTAINER_ENGINE must be docker or podman' ;; esac
  command -v "$engine" >/dev/null 2>&1 || fail "selected container engine is not installed: $engine"
  "$engine" info >/dev/null 2>&1 || fail "the $engine engine is not running; start Docker Desktop or run 'podman machine start'"
else
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    engine=docker
  elif command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
    engine=podman
  elif command -v docker >/dev/null 2>&1; then
    engine=docker
    fail 'Docker is installed but not running; start Docker Desktop and retry'
  elif command -v podman >/dev/null 2>&1; then
    engine=podman
    fail "Podman is installed but its machine is not running; run 'podman machine start' and retry"
  else
    fail 'install Docker Desktop or Podman Desktop before building on macOS'
  fi
fi

case "$(uname -m)" in
  arm64|aarch64) builder_arch=arm64 ;;
  x86_64|amd64) builder_arch=amd64 ;;
  *) fail "unsupported macOS workstation architecture: $(uname -m)" ;;
esac
builder_platform="linux/$builder_arch"
containerfile="$ROOT/tools/platform-builder/Containerfile"
[ -r "$containerfile" ] || fail "Linux builder definition is missing: $containerfile"

printf 'Preparing the pinned Rust 1.75 Linux builder (%s) with %s...\n' "$builder_platform" "$engine"
"$engine" build --platform "$builder_platform" --file "$containerfile" --tag "$IMAGE" "$(dirname "$containerfile")"

printf 'Building Billie for %s inside Linux...\n' "$target_triple"
"$engine" run --rm \
  --platform "$builder_platform" \
  --user "$(id -u):$(id -g)" \
  --volume "$ROOT:/workspace" \
  --workdir /workspace \
  --env HOME=/tmp/open-billie-builder-home \
  --env CARGO_HOME=/tmp/open-billie-cargo-home \
  --env RUSTUP_HOME=/usr/local/rustup \
  --env "BILLIE_TARGET_TRIPLE=$target_triple" \
  "$IMAGE" bash -c 'mkdir -p "$HOME" "$CARGO_HOME" && bash tools/build-platform-release.sh'
