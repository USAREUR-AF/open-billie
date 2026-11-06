#!/usr/bin/env bash
# Configure an installed Open Billie node from the workstation.
# Secret values are never saved in the repository or a local inventory.
set -euo pipefail

usage() {
  cat <<'HELP'
Configure an installed Open Billie node interactively from this workstation.

Usage:
  bash tools/configure-node.sh <user@host>

The node must already have Open Billie installed and SSH host-key trust set up.
The command prompts for the node handle, offers NetBird enrollment if needed,
then selects a one-time API bundle URL or local credential-bundle directory and discovers/confirms the endpoint from the bundle.
It discovers the CA root, matching client certificate/key, and vendor prefix
from the bundle filenames. A NetBird setup key is entered silently and streamed
to the node over SSH.
HELP
}

die() { printf 'billie configure: %s\n' "$*" >&2; exit 2; }

[ "$#" -eq 1 ] || { usage >&2; exit 2; }
target="$1"
[[ "$target" =~ ^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]] \
  || die 'target must be a user@hostname, user@IPv4, or user@[IPv6] value'
command -v ssh >/dev/null 2>&1 || die 'ssh is required'

ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes)
remote_key=""
remote_stage=""
setup_key=""
credential_tmp=""
credential_source=""
remote() { ssh "${ssh_options[@]}" "$target" "$@"; }
cleanup() {
  local rc=$?
  setup_key=""
  if [ -n "$credential_tmp" ]; then rm -rf -- "$credential_tmp" >/dev/null 2>&1 || true; fi
  if [ -n "$remote_key" ]; then
    remote "sudo -n shred -u '$remote_key' 2>/dev/null || sudo -n rm -f '$remote_key'" >/dev/null 2>&1 || true
  fi
  if [ -n "$remote_stage" ]; then
    remote "sudo -n rm -rf -- '$remote_stage'" >/dev/null 2>&1 || true
  fi
  return "$rc"
}
trap cleanup EXIT

printf 'Checking SSH, Billie, and non-interactive sudo on %s...\n' "$target"
remote 'sudo -n true && command -v billie >/dev/null && test -r /etc/os-release' \
  || die 'SSH, installed Billie, or non-interactive sudo is unavailable; install Billie and prepare SSH/sudo first'

suggested_handle="$(remote 'hostname -s' 2>/dev/null || true)"
printf '\n'
read -r -p "Billie node handle [${suggested_handle:-node-01}]: " node_handle
node_handle="${node_handle:-${suggested_handle:-node-01}}"
[[ "$node_handle" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die 'node handle must use lowercase letters, digits, and hyphens, beginning with a letter or digit'

identity_exists=0
if remote 'sudo -n test -s /etc/billie/identity/node.yml'; then identity_exists=1; fi

netbird_status="$(remote 'sudo -n netbird status 2>/dev/null || true' 2>/dev/null || true)"
if printf '%s\n' "$netbird_status" | grep -q 'Management: Connected'; then
  printf 'NetBird is already connected; preserving the current peer and skipping enrollment.\n'
  if [ "$identity_exists" -eq 0 ]; then
    remote "sudo -n billie init '$node_handle' --supply connected"
  fi
else
  if [ "$identity_exists" -eq 1 ]; then
    printf 'Billie identity exists; leaving it unchanged.\n'
  else
    printf '\n'
    read -r -p 'NetBird setup: [1] Enroll with setup key [2] Continue without enrollment (default 2): ' enroll_answer
    enroll_answer="${enroll_answer:-2}"
    case "$enroll_answer" in
      1|y|Y|yes|YES)
        netbird_installed="$(remote 'command -v netbird >/dev/null 2>&1 && echo yes || echo no')"
        if [ "$netbird_installed" != yes ]; then
          remote 'sudo -n billie bootstrap' || die 'NetBird bootstrap failed'
        fi
        printf '\n'
        read -r -p 'NetBird management URL (https://...): ' management_url
        [[ "$management_url" =~ ^https://([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(:[0-9]{1,5})?(/[A-Za-z0-9._/-]*)?$ ]] \
          || die 'management URL must be an HTTPS URL'
        printf '\nOne-time NetBird setup key (input hidden): '
        IFS= read -r -s setup_key
        printf '\n'
        [ -n "$setup_key" ] || die 'setup key cannot be empty'
        candidate_key="$(remote 'sudo -n mktemp /run/billie-netbird-setup.XXXXXXXX')" \
          || die 'could not create a protected setup-key staging file'
        [[ "$candidate_key" =~ ^/run/billie-netbird-setup\.[A-Za-z0-9]{8}$ ]] \
          || die 'node returned an unexpected setup-key staging path'
        remote_key="$candidate_key"
        printf '%s' "$setup_key" | remote "sudo -n sh -c 'umask 077; cat > \"$remote_key\" && chmod 0600 \"$remote_key\"'" \
          || die 'could not stream the setup key to the node'
        setup_key=""
        if ! remote "sudo -n billie join '$node_handle' --setup-key-file '$remote_key' --management-url '$management_url' --supply connected"; then
          die 'NetBird enrollment failed; the staged key will be removed; obtain a fresh one before retrying'
        fi
        remote "sudo -n shred -u '$remote_key' 2>/dev/null || sudo -n rm -f '$remote_key'" \
          || die 'joined successfully, but could not remove the staged setup key'
        remote_key=""
        identity_exists=1
        ;;
      2|n|N|no|NO|'')
        remote "sudo -n billie init '$node_handle' --supply connected" \
          || die 'could not initialize the node identity'
        identity_exists=1
        ;;
      *) die 'enter 1 to enroll or 2 to continue without NetBird enrollment' ;;
    esac
  fi
fi

while true; do
  printf '\n'
  printf 'Where can this machine’s fabric credentials be found?\n'
  printf '  [1] One-time API bundle URL\n'
  printf '  [2] Local folder\n'
  read -r -p 'Select an option (default: 1): ' credential_choice || die 'input ended before credential source was selected'
  credential_choice="${credential_choice:-1}"
  case "$credential_choice" in
    1)
      printf '\nOne-time API bundle URL returned by enrollment (input hidden): '
      IFS= read -r -s bundle_url || die 'input ended before the bundle URL was provided'
      printf '\n'
      credential_tmp="$(mktemp -d "${TMPDIR:-/tmp}/billie-credentials.XXXXXXXX")" || die 'could not create a private temporary credential directory'
      chmod 0700 "$credential_tmp"
      if ! printf '%s' "$bundle_url" | python3 "$(dirname "$0")/fetch-org-bundle.py" "$credential_tmp"; then
        bundle_url=""; rm -rf -- "$credential_tmp"; credential_tmp=""
        printf 'Fetch or validation failed. If the one-time URL was consumed, obtain a fresh URL and retry.\n' >&2
        continue
      fi
      bundle_url=""
      credential_dir="$credential_tmp"
      credential_source=api
      ;;
    2)
      printf '\n'
      read -r -p 'Local folder containing the fabric CA, client certificate, and key: ' credential_dir || die 'input ended before the credential folder was provided'
      credential_source=folder
      ;;
    *) printf 'Enter 1 for the one-time API URL or 2 for a local folder.\n' >&2; continue ;;
  esac
  if [ "$credential_source" = folder ]; then
  case "$credential_dir" in
    '~') credential_dir="$HOME" ;;
    '~/'*) credential_dir="$HOME/${credential_dir#~/}" ;;
  esac
  if [[ "$credential_dir" =~ ^[A-Za-z]:\\ ]]; then
    if ! command -v wslpath >/dev/null 2>&1; then
      printf 'Cannot convert a Windows path here; enter its WSL path (for example, C:\\data becomes /mnt/c/data).\n' >&2
      continue
    fi
    if ! credential_dir="$(wslpath -u "$credential_dir")"; then
      printf 'Could not convert that Windows folder path. Try again.\n' >&2
      continue
    fi
  fi
  if [ ! -d "$credential_dir" ]; then
    printf 'Credential folder does not exist: %s\nEnter the folder path again.\n' "$credential_dir" >&2
    continue
  fi
  if ! credential_dir="$(cd "$credential_dir" && pwd -P)"; then
    printf 'Credential folder is not accessible. Enter another path.\n' >&2
    continue
  fi

  fi

  shopt -s nullglob
  ca_candidates=("$credential_dir"/*-ca-root.pem)
  if [ "${#ca_candidates[@]}" -eq 0 ]; then
    ca_candidates=("$credential_dir"/fabric-ca.pem "$credential_dir"/ca.pem)
  fi
  cert_candidates=("$credential_dir"/*-cert.pem)
  if [ "${#ca_candidates[@]}" -ne 1 ]; then
    printf 'Folder must contain one fabric CA root (*-ca-root.pem preferred; otherwise fabric-ca.pem or ca.pem). Auxiliary onboarding CA certificates are not fabric roots.\n' >&2
    continue
  fi
  if [ "${#cert_candidates[@]}" -ne 1 ]; then
    printf 'Folder must contain exactly one *-cert.pem client certificate.\n' >&2
    continue
  fi
  ca_file="${ca_candidates[0]}"
  client_cert_file="${cert_candidates[0]}"
  cert_prefix="$(basename "$client_cert_file" -cert.pem)"
  client_key_file="$credential_dir/$cert_prefix-key.pem"
  if [ ! -f "$client_key_file" ] || [ ! -r "$client_key_file" ]; then
    printf 'Matching client private key is missing or unreadable: %s\n' "$client_key_file" >&2
    continue
  fi
  prefix="$cert_prefix"
  if [[ ! "$prefix" =~ ^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$ ]]; then
    printf 'Certificate filename prefix is not a valid literal Zenoh key prefix.\n' >&2
    continue
  fi
  bundle_error=""
  for input_file in "$ca_file" "$client_cert_file" "$client_key_file"; do
    if [ ! -f "$input_file" ] || [ ! -r "$input_file" ]; then
      bundle_error="Credential file is missing or unreadable: $input_file"
      break
    fi
  done
  if [ -n "$bundle_error" ]; then
    printf '%s\n' "$bundle_error" >&2
    continue
  fi
  break
done
printf 'Found credential bundle for prefix %s (CA, client certificate, and matching key).\n' "$prefix"
printf '\n'
# Read the endpoint from the onboarding docs/examples included in the bundle where possible.
endpoint_candidates=()
while IFS= read -r discovered_endpoint; do
  [ -n "$discovered_endpoint" ] && endpoint_candidates+=("$discovered_endpoint")
done < <(find "$credential_dir" -type f \( -name '*.md' -o -name '*.py' \) -exec grep -hoE 'tls/[A-Za-z0-9.-]+:[0-9]{1,5}' {} + 2>/dev/null | sort -u || true)
endpoint=""
if [ "${#endpoint_candidates[@]}" -eq 1 ]; then
  endpoint="${endpoint_candidates[0]}"
  printf 'Discovered Zenoh endpoint in bundle: %s\n' "$endpoint"
  read -r -p 'Use this endpoint? [Y/n]: ' endpoint_confirm
  case "${endpoint_confirm:-Y}" in n|N|no|NO) endpoint="" ;; esac
fi
if [ -z "$endpoint" ]; then
while true; do
  printf '\n'
  read -r -p 'Zenoh TLS endpoint (tls/host:port): ' endpoint \
    || die 'input ended before the Zenoh endpoint was provided'
  if [[ "$endpoint" =~ ^tls/([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):[0-9]{1,5}$ ]]; then
    break
  fi
  printf 'Invalid endpoint. Enter tls/host:port, for example tls/zenoh.example.net:7447.\n' >&2
done
fi
candidate_stage="$(remote 'sudo -n mktemp -d /run/billie-zenoh-import.XXXXXXXX')" \
  || die 'could not create a protected mTLS staging directory'
[[ "$candidate_stage" =~ ^/run/billie-zenoh-import\.[A-Za-z0-9]{8}$ ]] \
  || die 'node returned an unexpected mTLS staging path'
remote_stage="$candidate_stage"

stream_file() {
  local source="$1" name="$2" mode="$3"
  remote "sudo -n sh -c 'umask 077; cat > \"$remote_stage/$name\" && chmod $mode \"$remote_stage/$name\"'" < "$source"
}
printf 'Streaming mTLS files to a temporary root-only directory on %s...\n' "$target"
stream_file "$ca_file" ca.pem 0644 || die 'CA transfer failed'
stream_file "$client_cert_file" client.pem 0644 || die 'client certificate transfer failed'
stream_file "$client_key_file" client-key.pem 0600 || die 'client private-key transfer failed'

remote "sudo -n billie zenoh configure --endpoint '$endpoint' --prefix '$prefix' --ca-file '$remote_stage/ca.pem' --client-cert-file '$remote_stage/client.pem' --client-key-file '$remote_stage/client-key.pem'" \
  || die 'Zenoh configuration failed'
remote "sudo -n rm -rf -- '$remote_stage'" || die 'configuration succeeded, but temporary credential files could not be removed'
remote_stage=""

printf '\nApplying and verifying the node configuration...\n'
remote 'sudo -n billie check' || die 'billie check failed'
remote 'sudo -n billie apply' || die 'billie apply failed'
remote 'sudo -n billie verify' || die 'billie verify failed'
printf '\nOpen Billie configuration completed on %s.\n' "$target"
printf 'The one-time setup key and temporary mTLS copies were removed; protected mTLS files remain under /etc/billie/zenoh/tls.\n'
