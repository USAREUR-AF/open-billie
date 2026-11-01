#!/usr/bin/env bash
set -euo pipefail

deb="${BILLIE_PLATFORM_DEB:-}"
if [[ -z "$deb" ]]; then
  deb="$(find /artifacts -maxdepth 1 -type f -name 'billie-platform_*_arm64.deb' -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
fi
if [[ -z "$deb" || ! -r "$deb" ]]; then echo "No readable ARM64 platform package found in /artifacts." >&2; exit 2; fi
architecture="$(dpkg-deb -f "$deb" Architecture)"
if [[ "$architecture" != arm64 ]]; then echo "Expected arm64 package, found: $architecture" >&2; exit 2; fi
work="$(mktemp -d)"
translator_pid=""
cleanup() { if [[ -n "$translator_pid" ]]; then kill "$translator_pid" 2>/dev/null || true; wait "$translator_pid" 2>/dev/null || true; fi; rm -rf "$work"; }
trap cleanup EXIT
dpkg-deb -x "$deb" "$work/root"
translator="$(find "$work/root" -type f -name billie-translator -print -quit)"
if [[ -z "$translator" || ! -x "$translator" ]]; then echo "Package has no executable billie-translator." >&2; exit 1; fi
groupadd --system billie-kids
export BILLIE_TRANSLATOR_SOCKET="$work/translator.sock"
export BILLIE_TRANSLATOR_REGISTRY="$work/registry.json"
export BILLIE_TRANSLATOR_SOCKET_GROUP=billie-kids
export BILLIE_LOCAL_ZENOH_ENDPOINT=tcp/127.0.0.1:17447
export BILLIE_NODE_ID=11111111-2222-4333-8444-555555555555
"$translator" >"$work/translator.log" 2>&1 & translator_pid=$!
for _ in $(seq 1 50); do
  [[ -S "$BILLIE_TRANSLATOR_SOCKET" ]] && break
  if ! kill -0 "$translator_pid" 2>/dev/null; then cat "$work/translator.log" >&2; echo "Translator exited before creating its socket." >&2; exit 1; fi
  sleep 0.1
done
if [[ ! -S "$BILLIE_TRANSLATOR_SOCKET" ]]; then cat "$work/translator.log" >&2; echo "Translator did not create its socket within five seconds." >&2; exit 1; fi
mode="$(stat -c '%a' "$BILLIE_TRANSLATOR_SOCKET")"
socket_gid="$(stat -c '%g' "$BILLIE_TRANSLATOR_SOCKET")"
group_gid="$(getent group billie-kids | cut -d: -f3)"
if [[ "$mode" != 660 || "$socket_gid" != "$group_gid" ]]; then echo "Unexpected socket mode/group: mode=$mode gid=$socket_gid expected_gid=$group_gid" >&2; exit 1; fi
echo "PASS: ARM64 billie-translator starts under Docker ARM64 emulation."
echo "PASS: Unix socket mode is 0660 and group is billie-kids."
echo "Package: $(basename "$deb") (Architecture: $architecture)"
