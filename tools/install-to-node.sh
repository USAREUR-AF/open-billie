#!/usr/bin/env bash
# Verify and install a signed Billie platform release over SSH.
set -euo pipefail

usage() {
  cat <<'HELP'
Install an Open Billie release from a workstation to a prepared Ubuntu node.

Usage:
  bash tools/install-to-node.sh --target <user@host> --deb <path> \
    (--certificate-identity <identity> [--certificate-oidc-issuer <issuer>] | --public-key <path>) \
    [--checksum-only] [--known-hosts <file>]

A signed architecture-specific SHA256SUMS manifest and signature bundles for
the manifest, Debian package, and tarball must be beside the package for normal
installs. Checksum-only mode needs the manifest but not signature bundles.
Choose the package matching the target node (amd64 or arm64).
The default issuer is GitHub Actions OIDC.
The public-key option is for a separately trusted key, including local development.
--checksum-only skips Cosign for a local install; the exact SHA256 manifest is
still required. Signed verification remains the default for published releases.
HELP
}

die() { printf 'billie installer: %s\n' "$*" >&2; exit 2; }
need_command() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }

target=""
deb_arg=""
certificate_identity="${BILLIE_RELEASE_CERT_IDENTITY:-}"
certificate_oidc_issuer="${BILLIE_RELEASE_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"
public_key=""
identity_option_set=0
checksum_only=0
known_hosts="${BILLIE_SSH_KNOWN_HOSTS:-}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) [ "$#" -ge 2 ] || die '--target needs user@host'; target="$2"; shift 2 ;;
    --deb) [ "$#" -ge 2 ] || die '--deb needs a package path'; deb_arg="$2"; shift 2 ;;
    --certificate-identity) [ "$#" -ge 2 ] || die '--certificate-identity needs an expected signer'; certificate_identity="$2"; identity_option_set=1; shift 2 ;;
    --certificate-oidc-issuer) [ "$#" -ge 2 ] || die '--certificate-oidc-issuer needs an issuer URL'; certificate_oidc_issuer="$2"; shift 2 ;;
    --public-key) [ "$#" -ge 2 ] || die '--public-key needs a trusted public key path'; public_key="$2"; shift 2 ;;
    --checksum-only) checksum_only=1; shift ;;
    --known-hosts) [ "$#" -ge 2 ] || die '--known-hosts needs a file path'; known_hosts="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[ -n "$target" ] || die '--target is required'
[ -n "$deb_arg" ] || die '--deb is required'
if [[ ! "$target" =~ ^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]]; then
  die 'target must be a user@hostname, user@IPv4, or user@[IPv6] value'
fi
if [ "$checksum_only" -eq 1 ] && { [ -n "$public_key" ] || [ "$identity_option_set" -eq 1 ]; }; then
  die '--checksum-only cannot be combined with signature identity or public-key options'
fi
if [ -n "$public_key" ] && [ "$identity_option_set" -eq 1 ]; then
  die 'choose either --public-key or --certificate-identity, not both'
fi
if [ -n "$public_key" ]; then certificate_identity=""; fi
if [ "$checksum_only" -eq 0 ] && [ -z "$public_key" ] && [ -z "$certificate_identity" ]; then
  die 'signed releases require --certificate-identity (or BILLIE_RELEASE_CERT_IDENTITY)'
fi
if [ -n "$public_key" ] && [ ! -r "$public_key" ]; then
  die "trusted public key is missing or unreadable: $public_key"
fi

need_command ssh
need_command scp
if [ "$checksum_only" -eq 0 ]; then need_command cosign; fi
need_command sha256sum
if [ -n "$known_hosts" ] && [ ! -r "$known_hosts" ]; then
  die "SSH known-hosts file is missing or unreadable: $known_hosts"
fi

if [ ! -r "$deb_arg" ]; then die "package is missing or unreadable: $deb_arg"; fi
deb_path="$(cd "$(dirname "$deb_arg")" && pwd)/$(basename "$deb_arg")"
deb_name="$(basename "$deb_path")"
if [[ ! "$deb_name" =~ ^billie-platform_([0-9]+\.[0-9]+\.[0-9]+\+[A-Za-z0-9._-]+)_(amd64|arm64)\.deb$ ]]; then
  die 'package filename must be billie-platform_<version>_<amd64|arm64>.deb'
fi
release_version="${BASH_REMATCH[1]}"
deb_arch="${BASH_REMATCH[2]}"
tarball_name="billie-platform-$release_version"_"$deb_arch".tar.gz
tarball_path="$(dirname "$deb_path")/$tarball_name"
manifest_name="SHA256SUMS-$deb_arch"
manifest_path="$(dirname "$deb_path")/$manifest_name"
deb_bundle="$deb_path.sigstore.json"
tarball_bundle="$tarball_path.sigstore.json"
manifest_bundle="$manifest_path.sigstore.json"
required_release_files=("$tarball_path" "$manifest_path")
if [ "$checksum_only" -eq 0 ]; then
  required_release_files+=("$deb_bundle" "$tarball_bundle" "$manifest_bundle")
fi
for file in "${required_release_files[@]}"; do
  [ -r "$file" ] || die "required release file is missing or unreadable: $file"
done

expected_names="$(printf '%s\n%s\n' "$deb_name" "$tarball_name" | sort)"
actual_names="$(awk 'NF { print $2 }' "$manifest_path" | sort)"
[ "$actual_names" = "$expected_names" ] || die 'SHA256SUMS must contain exactly the selected package and matching tarball'

verify_signature() {
  local artifact="$1"
  local bundle="$2"
  if [ -n "$public_key" ]; then
    cosign verify-blob "$artifact" --bundle "$bundle" --key "$public_key"
  else
    cosign verify-blob "$artifact" --bundle "$bundle" \
      --certificate-identity "$certificate_identity" \
      --certificate-oidc-issuer "$certificate_oidc_issuer"
  fi
}

if [ "$checksum_only" -eq 0 ]; then
  printf 'Verifying release signatures...\n'
  verify_signature "$manifest_path" "$manifest_bundle"
  verify_signature "$deb_path" "$deb_bundle"
  verify_signature "$tarball_path" "$tarball_bundle"
else
  printf 'Checksum-only verification selected; validating SHA256 manifest without Cosign.\n'
fi
(
  cd "$(dirname "$deb_path")"
  sha256sum --check --strict "$manifest_name"
)

ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes)
if [ -n "$known_hosts" ]; then ssh_options+=(-o "UserKnownHostsFile=$known_hosts"); fi
printf 'Checking SSH and sudo access to %s...\n' "$target"
ssh "${ssh_options[@]}" "$target" true || die "SSH check failed for $target; confirm host-key trust and key-based login"
ssh "${ssh_options[@]}" "$target" 'test -r /etc/os-release && . /etc/os-release && [ "$ID" = ubuntu ] && [ "$VERSION_ID" = 24.04 ] && sudo -n true && command -v apt-get >/dev/null && command -v sha256sum >/dev/null' \
  || die "$target must be Ubuntu 24.04 with non-interactive sudo, apt-get, and sha256sum"

remote_dir="$(ssh "${ssh_options[@]}" "$target" 'umask 077 && mktemp -d /tmp/open-billie-install.XXXXXXXX')" \
  || die "could not create a private staging directory on $target"
[[ "$remote_dir" =~ ^/tmp/open-billie-install\.[A-Za-z0-9]{8}$ ]] \
  || die "remote host returned an unexpected staging path: $remote_dir"
remote_arch="$(ssh "${ssh_options[@]}" "$target" 'dpkg --print-architecture')" || die "could not determine Debian architecture on $target"
[ "$remote_arch" = "$deb_arch" ] || die "package architecture $deb_arch does not match node architecture $remote_arch"
root_stage="/var/tmp/open-billie-${release_version}"
cleanup_on_exit() {
  local result=$?
  if [ "$result" -ne 0 ] && [ -n "$remote_dir" ]; then
    printf 'Install stopped; staged files remain on %s at %s for inspection.\n' "$target" "$remote_dir" >&2
  fi
  return "$result"
}
trap cleanup_on_exit EXIT

printf 'Transferring verified release to %s...\n' "$target"
transfer_files=("$deb_path" "$tarball_path" "$manifest_path")
if [ "$checksum_only" -eq 0 ]; then
  transfer_files+=("$deb_bundle" "$tarball_bundle" "$manifest_bundle")
fi
scp "${ssh_options[@]}" -- "${transfer_files[@]}" "$target:$remote_dir/" \
  || die "release transfer failed for $target"

deb_sha="$(sha256sum "$deb_path" | awk '{print $1}')"
tarball_sha="$(sha256sum "$tarball_path" | awk '{print $1}')"
remote_command="set -e
cd '$remote_dir'
sha256sum --check --strict '$manifest_name'
sudo -n install -d -o root -g root -m 0700 '$root_stage'
sudo -n install -o root -g root -m 0644 '$deb_name' '$root_stage/$deb_name'
printf '%s  %s\\n' '$deb_sha' '$root_stage/$deb_name' | sudo -n sha256sum --check --status -
candidate_version=\$(sudo -n dpkg-deb -f '$root_stage/$deb_name' Version)
installed_version=\$(dpkg-query -W -f='\${Version}' billie-platform 2>/dev/null || true)
if [ -n \"\$installed_version\" ] && dpkg --compare-versions \"\$candidate_version\" lt \"\$installed_version\"; then
  printf 'Refusing platform downgrade from %s to %s.\n' \"\$installed_version\" \"\$candidate_version\" >&2
  exit 1
fi
# The previous Billie bootstrap could leave this source using an .asc keyring,
# conflicting with NetBird's existing official .gpg source before APT can run.
if sudo -n grep -qF 'netbird-archive-keyring.asc' /etc/apt/sources.list.d/netbird.list 2>/dev/null; then
  printf 'Removing the previous Billie-managed NetBird APT source before updating APT.\\n'
  sudo -n rm -f -- /etc/apt/sources.list.d/netbird.list
fi
sudo -n apt-get update
sudo -n apt-get install -y '$root_stage/$deb_name'
sudo -n billie install
if sudo -n test -s /etc/billie/identity/node.yml; then
  printf 'Existing Billie identity found; applying the upgraded platform configuration.\n'
  sudo -n billie apply
fi
sudo -n rm -rf -- '$root_stage'
rm -rf -- '$remote_dir'"
ssh "${ssh_options[@]}" "$target" "$remote_command" \
  || die "remote installation failed on $target"
remote_dir=""
printf '\nBillie platform %s is installed on %s.\n' "$release_version" "$target"
printf 'Next: ssh %s, then run sudo billie bootstrap for NetBird or sudo billie init for an isolated node.\n' "$target"
