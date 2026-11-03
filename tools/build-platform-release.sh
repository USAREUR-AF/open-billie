#!/usr/bin/env bash
# Build an allowlisted Debian platform package and a matching tarball.
set -eo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
BASE_VERSION="$(tr -d '[:space:]' < "$ROOT/deploy/VERSION")"
[[ "$BASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "invalid platform version: $BASE_VERSION" >&2
  exit 2
}

command -v cargo >/dev/null 2>&1 || {
  echo "cargo is required to build the shared translator service" >&2
  exit 2
}
command -v rustc >/dev/null 2>&1 || {
  echo "rustc is required to build the shared translator service" >&2
  exit 2
}
HOST_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
TARGET_TRIPLE="${BILLIE_TARGET_TRIPLE:-$HOST_TRIPLE}"
case "$TARGET_TRIPLE" in
  x86_64-unknown-linux-gnu)
    DEB_ARCH=amd64
    LINKER_VAR=CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER
    DEFAULT_LINKER=x86_64-linux-gnu-gcc
    ;;
  aarch64-unknown-linux-gnu)
    DEB_ARCH=arm64
    LINKER_VAR=CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER
    DEFAULT_LINKER=aarch64-linux-gnu-gcc
    ;;
  *) echo "unsupported Rust target triple: $TARGET_TRIPLE" >&2; exit 2 ;;
esac
if [ "$TARGET_TRIPLE" != "$HOST_TRIPLE" ]; then
  CROSS_LINKER="${!LINKER_VAR:-$DEFAULT_LINKER}"
  command -v "$CROSS_LINKER" >/dev/null 2>&1 || {
    echo "cross-linker '$CROSS_LINKER' is required for $TARGET_TRIPLE" >&2
    echo "install the matching GNU cross toolchain or set $LINKER_VAR" >&2
    exit 2
  }
  export "$LINKER_VAR=$CROSS_LINKER"
  echo "Cross-compiling $HOST_TRIPLE -> $TARGET_TRIPLE with $CROSS_LINKER"
fi
TARGET_LIBDIR="$(rustc --print target-libdir --target "$TARGET_TRIPLE" 2>/dev/null || true)"
if [ -z "$TARGET_LIBDIR" ] || ! compgen -G "$TARGET_LIBDIR/libcore-*.rlib" >/dev/null; then
  echo "Rust standard library for $TARGET_TRIPLE is missing from the active compiler." >&2
  echo "Install that target for the same Rust toolchain (for example: rustup target add --toolchain 1.75.0 $TARGET_TRIPLE), then run this build through that toolchain." >&2
  exit 2
fi
# Remap compiler source paths so Rust debug/panic metadata cannot disclose the
# builder's checkout path in the shipped translator binary. Use Cargo's
# unit-separator encoded form so checkout paths containing spaces remain one
# rustc argument, while retaining caller-provided Rust flags.
if [ -n "${CARGO_ENCODED_RUSTFLAGS:-}" ]; then
  ENCODED_RUSTFLAGS="$CARGO_ENCODED_RUSTFLAGS"
elif [ -n "${RUSTFLAGS:-}" ]; then
  ENCODED_RUSTFLAGS="$(python3 -c 'import shlex, sys; print("\x1f".join(shlex.split(sys.argv[1])), end="")' "$RUSTFLAGS")"
else
  ENCODED_RUSTFLAGS=""
fi
if [ -n "$ENCODED_RUSTFLAGS" ]; then
  ENCODED_RUSTFLAGS+=$'\x1f'
fi
ENCODED_RUSTFLAGS+="--remap-path-prefix=$ROOT=/usr/src/open-billie"
CARGO_HOME_EFFECTIVE="${CARGO_HOME:-${HOME:?HOME must be set to build the release}/.cargo}"
RUST_SYSROOT="$(rustc --print sysroot)"
ENCODED_RUSTFLAGS+=$'\x1f'
ENCODED_RUSTFLAGS+="--remap-path-prefix=$CARGO_HOME_EFFECTIVE=/usr/local/cargo"
ENCODED_RUSTFLAGS+=$'\x1f'
ENCODED_RUSTFLAGS+="--remap-path-prefix=$RUST_SYSROOT=/usr/local/rust"
CARGO_ENCODED_RUSTFLAGS="$ENCODED_RUSTFLAGS" \
  cargo build --locked --release --target "$TARGET_TRIPLE" \
  --manifest-path "$ROOT/runtime/rust/Cargo.toml" --workspace

if GIT_REVISION="$(git -c safe.directory="$ROOT" -C "$ROOT" rev-parse --short HEAD 2>/dev/null)"; then
  if [ -n "$(git -c safe.directory="$ROOT" -C "$ROOT" status --porcelain 2>/dev/null)" ]; then
    GIT_REVISION="${GIT_REVISION}.dirty"
  fi
else
  GIT_REVISION=local
fi
RELEASE_VERSION="$BASE_VERSION+$GIT_REVISION"
DIST="$ROOT/dist"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PAYLOAD="$WORK/billie-platform"
RELEASE_TREE="$PAYLOAD/opt/billie/platform/releases/$RELEASE_VERSION"
DEBIAN="$PAYLOAD/DEBIAN"
mkdir -p "$RELEASE_TREE/bin" "$RELEASE_TREE/platform/templates" "$DEBIAN" "$DIST"

# Positive allowlist: new repository files do not enter releases implicitly.
install -m 0755 "$ROOT/deploy/bin/billie" "$RELEASE_TREE/bin/billie"
install -m 0755 "$ROOT/deploy/bin/billie-kid-validate.py" "$RELEASE_TREE/bin/billie-kid-validate.py"
install -m 0755 "$ROOT/deploy/bin/billie-kid-scan.py" "$RELEASE_TREE/bin/billie-kid-scan.py"
install -m 0755 "$ROOT/deploy/bin/billie-kid-ops.py" "$RELEASE_TREE/bin/billie-kid-ops.py"
install -m 0755 "$ROOT/deploy/bin/billie-kid-build.py" "$RELEASE_TREE/bin/billie-kid-build.py"
install -m 0755 "$ROOT/deploy/bin/billie-network.py" "$RELEASE_TREE/bin/billie-network.py"
install -m 0755 "$ROOT/deploy/bin/billie-teardown.py" "$RELEASE_TREE/bin/billie-teardown.py"
install -m 0755 "$ROOT/deploy/bin/billie-mapper-generate.py" "$RELEASE_TREE/bin/billie-mapper-generate.py"
install -m 0755 "$ROOT/deploy/bin/billie-cat062-sources.py" "$RELEASE_TREE/bin/billie-cat062-sources.py"
install -m 0755 "$ROOT/deploy/bin/billie-zenoh-config.py" "$RELEASE_TREE/bin/billie-zenoh-config.py"
install -m 0755 "$ROOT/deploy/bin/billie-island-bridge.py" "$RELEASE_TREE/bin/billie-island-bridge.py"
install -m 0755 "$ROOT/runtime/rust/target/$TARGET_TRIPLE/release/billie-translator" "$RELEASE_TREE/bin/billie-translator"
install -m 0644 "$ROOT/deploy/VERSION" "$RELEASE_TREE/VERSION"
install -m 0644 "$ROOT/LICENSE" "$RELEASE_TREE/LICENSE"
install -m 0644 "$ROOT/THIRD_PARTY_NOTICES.md" "$RELEASE_TREE/THIRD_PARTY_NOTICES.md"
install -m 0644 "$ROOT/NOTICE" "$RELEASE_TREE/NOTICE"
mkdir -p "$RELEASE_TREE/schemas"
install -m 0644 "$ROOT/schemas/kid-manifest.schema.json" "$RELEASE_TREE/schemas/kid-manifest.schema.json"
install -m 0644 "$ROOT/deploy/platform/ansible.cfg" "$RELEASE_TREE/platform/ansible.cfg"
install -m 0644 "$ROOT/deploy/platform/inventory-local.ini" "$RELEASE_TREE/platform/inventory-local.ini"
install -m 0644 "$ROOT/deploy/platform/write-identity.yml" "$RELEASE_TREE/platform/write-identity.yml"
install -m 0644 "$ROOT/deploy/platform/configure.yml" "$RELEASE_TREE/platform/configure.yml"
install -m 0644 "$ROOT/deploy/platform/bootstrap.yml" "$RELEASE_TREE/platform/bootstrap.yml"
install -m 0644 "$ROOT/deploy/platform/verify.yml" "$RELEASE_TREE/platform/verify.yml"
for template in node.yml.j2 billie-health.sh.j2 billie-health.service.j2 billie-health.timer.j2 platform-state.json.j2 zenohd.container.j2 zenohd.json5.j2 fabric-client.container.j2 fabric-client.json5.j2 island-bridge.service.j2 billie-translator.service.j2; do
  install -m 0644 "$ROOT/deploy/platform/templates/$template" "$RELEASE_TREE/platform/templates/$template"
done

leaks="$(find "$PAYLOAD" \( -name '*.pem' -o -name '*.key' -o -name '.env' -o -name 'inventory.yml' -o -path '*/host_vars/*' -o -name 'node.yml' \) -print)"
if [ -n "$leaks" ]; then
  printf 'refusing to package identity or credential material:\n%s\n' "$leaks" >&2
  exit 1
fi

cat > "$DEBIAN/control" <<CONTROL
Package: billie-platform
Version: $RELEASE_VERSION
Section: admin
Priority: optional
Architecture: $DEB_ARCH
Depends: bash, ansible-core, podman, systemd, python3, python3-yaml, python3-jsonschema, openssl, curl
Maintainer: Open Billie maintainers
Description: Sensor-neutral Billie node platform
 Platform CLI and generic local Ansible runtime for a Billie node.
CONTROL

cat > "$DEBIAN/postinst" <<POST
#!/bin/sh
set -eu
release="/opt/billie/platform/releases/$RELEASE_VERSION"
[ -x "\$release/bin/billie" ] || {
  echo "billie-platform: installed CLI is missing from \$release" >&2
  exit 1
}
ln -sfn "\$release" /opt/billie/platform/current
ln -sfn /opt/billie/platform/current/bin/billie /usr/local/bin/billie
if [ -d /run/systemd/system ]; then
  systemctl daemon-reload
  active_translators="\$(systemctl list-units --type=service --state=active --no-legend | awk '\$1 ~ /-translator\\.service$/ { print \$1 }')"
  for unit in \$active_translators; do
    exec_start="\$(systemctl show --property=ExecStart --value "\$unit" 2>/dev/null || true)"
    case "\$exec_start" in
      *"/opt/billie/platform/current/bin/billie-translator"*) systemctl try-restart "\$unit" ;;
    esac
  done
fi
POST
chmod 0755 "$DEBIAN/postinst"

DEB="$DIST/billie-platform_${RELEASE_VERSION}_${DEB_ARCH}.deb"
TARBALL="$DIST/billie-platform-${RELEASE_VERSION}_${DEB_ARCH}.tar.gz"
MANIFEST="$DIST/SHA256SUMS-$DEB_ARCH"
dpkg-deb --build --root-owner-group "$PAYLOAD" "$DEB"
tar -czf "$TARBALL" -C "$RELEASE_TREE" .
(
  cd "$DIST"
  sha256sum "$(basename "$DEB")" "$(basename "$TARBALL")" > "$(basename "$MANIFEST")"
)
printf 'Built release %s\n' "$RELEASE_VERSION"
printf '  %s\n  %s\n  %s\n' "$DEB" "$TARBALL" "$MANIFEST"
