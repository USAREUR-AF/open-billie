#!/usr/bin/env bash
# Guided workstation-side kid build, transfer, configuration, and activation.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() { printf '\nOpen Billie kid setup: %s\n' "$*" >&2; exit 2; }
require() { command -v "$1" >/dev/null 2>&1 || fail "missing prerequisite '$1'. See deploy/README.md."; }
ask() { local prompt="$1" default="${2:-}" value; printf '\n' >&2; if [ -n "$default" ]; then read -r -p "$prompt (default: $default): " value; value="${value:-$default}"; else read -r -p "$prompt: " value; fi; printf '%s' "$value"; }
confirm() { local answer; printf '\n' >&2; read -r -p "$1 [y/N] " answer; [[ "$answer" == [yY] || "$answer" == [yY][eE][sS] ]]; }
valid_ipv4() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] && python3 -c 'import ipaddress,sys; ipaddress.IPv4Address(sys.argv[1])' "$1" >/dev/null 2>&1; }
valid_cidr() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]] && python3 -c 'import ipaddress,sys; ipaddress.IPv4Network(sys.argv[1], strict=False)' "$1" >/dev/null 2>&1; }
ipv4_with_mask() { python3 -c 'import ipaddress,sys; ip=ipaddress.IPv4Address(sys.argv[1]); n=ipaddress.IPv4Network("0.0.0.0/"+sys.argv[2]); mask=sys.argv[2]; assert str(n.netmask)==mask and n.prefixlen>=8, "use a contiguous mask from /8 through /32"; print(f"{ip}/{n.prefixlen}")' "$1" "$2" 2>/dev/null; }
valid_target() { [[ "$1" =~ ^[A-Za-z0-9._-]+@([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]]; }
recover_ssh_target() {
  local candidate
  printf '\nIf the management connection dropped, the Pi may have renewed its DHCP lease. The sensor address command changes only the selected sensor interface.\n' >&2
  printf 'If SSH shows a new host-key fingerprint, verify it through a trusted channel before accepting it.\n' >&2
  while true; do
    candidate="$(ask 'Current Billie SSH target (user@host)' "$target")"
    if ! valid_target "$candidate"; then
      printf 'Enter a username and hostname or IP address, for example operator@192.0.2.10.\n' >&2
      continue
    fi
    if ssh -o BatchMode=no -o PreferredAuthentications=publickey -o NumberOfPasswordPrompts=0 \
      -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
      -o StrictHostKeyChecking=ask "$candidate" 'sudo -n true'; then
      target="$candidate"
      printf 'SSH access restored to %s.\n' "$target"
      return 0
    fi
    printf 'Could not authenticate to %s with SSH keys and non-interactive sudo. Check the address, host-key trust, and key access, then retry.\n' "$candidate" >&2
  done
}

for cmd in ssh scp python3; do require "$cmd"; done
ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2)
target="${1:-}"
if [ -z "$target" ]; then target="$(ask 'Node SSH target (user@host)')"; fi
valid_target "$target" || fail 'target must be user@host'
ssh "${ssh_options[@]}" "$target" 'sudo -n true' >/dev/null 2>&1 \
  || fail 'SSH or non-interactive sudo check failed; trust the node host key and configure passwordless sudo for this account before running the kid wizard'
python3 -c 'import yaml, jsonschema' >/dev/null 2>&1 \
  || fail 'Python dependencies are missing; install PyYAML and jsonschema as described in deploy/README.md.'

printf '\nOpen Billie kid deployment wizard\n==================================\nThis builds on the workstation and installs/activates the selected kid on the prepared node.\n\n'
scan_json="$(mktemp)"
build_log="$(mktemp)"
trap 'rm -f "$scan_json" "$build_log"' EXIT
python3 deploy/bin/billie-kid-scan.py kids --json > "$scan_json" || fail 'could not scan local kid sources; check Python YAML prerequisites.'
packages=()
while IFS= read -r package_line; do packages+=("$package_line"); done < <(python3 -c 'import json,sys; from pathlib import Path; d=json.load(open(sys.argv[1])); [print("\t".join(str(p.get(k, "")) for k in ("id","version","path","validation"))) for p in d["packages"] if p.get("validation") != "invalid" and p.get("id") and p.get("version") and p.get("path") and Path(p["path"]).name != "_template"]' "$scan_json")
printf 'Kid package source:\n'
for i in "${!packages[@]}"; do IFS=$'\t' read -r kid_id version kid_path validation <<< "${packages[$i]}"; printf '  %d) %s@%s — %s (%s)\n' "$((i + 1))" "$kid_id" "$version" "$kid_path" "$validation"; done
external_choice=$((${#packages[@]} + 1))
printf '  %d) Use a package from another folder\n' "$external_choice"
choice="$(ask 'Select a package number' '1')"
[[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$external_choice" ] || fail 'select one of the listed package numbers'
kid_id=""; version=""; kid_path=""
if [ "$choice" -eq "$external_choice" ]; then
  while true; do
    kid_path="$(ask 'Path to the folder containing billie-kid.yaml')"
    if command -v wslpath >/dev/null 2>&1 && [[ "$kid_path" == *:* ]]; then
      kid_path="$(wslpath -u "$kid_path" 2>/dev/null)" || { printf 'Could not convert that Windows path. Enter a valid Windows or WSL path.\n' >&2; continue; }
    fi
    kid_path="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$kid_path")"
    if [ ! -d "$kid_path" ] || [ ! -f "$kid_path/billie-kid.yaml" ]; then
      printf 'That folder must exist and contain billie-kid.yaml. Try again.\n' >&2
      continue
    fi
    if python3 deploy/bin/billie-kid-validate.py "$kid_path"; then break; fi
    printf 'Package validation failed. Correct the package or enter another folder.\n' >&2
  done
  kid_id="$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["metadata"]["id"])' "$kid_path/billie-kid.yaml")"
  version="$(python3 -c 'import sys,yaml; print(yaml.safe_load(open(sys.argv[1]))["metadata"]["version"])' "$kid_path/billie-kid.yaml")"
else
  IFS=$'\t' read -r kid_id version kid_path _ <<< "${packages[$((choice - 1))]}"
fi
[[ "$kid_id" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || fail 'selected package has an invalid kid ID'
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([+-][A-Za-z0-9.-]+)?$ ]] || fail 'selected package has an unsupported version string'

remote_arch="$(ssh "${ssh_options[@]}" "$target" 'dpkg --print-architecture')" || fail "could not query the node architecture over SSH: $target"
case "$remote_arch" in arm64) platform=linux/arm64 ;; amd64) platform=linux/amd64 ;; *) fail "unsupported node architecture: $remote_arch" ;; esac
printf '\nSelected %s@%s; node architecture is %s.\n' "$kid_id" "$version" "$platform"
installed_path="/opt/billie/kids/$kid_id/$version"
if ssh "${ssh_options[@]}" "$target" "sudo -n test -d '$installed_path'"; then
  printf 'Kid %s@%s is already installed; resuming listener configuration without reinstalling it.\n' "$kid_id" "$version"
else
  container_check="$(bash tools/check-container-prerequisites.sh kid 2>&1)" || fail "$container_check"
  printf '\n%s\n' "$container_check"
  kid_engine="$(printf '%s\n' "$container_check" | sed -n 's/^Selected container engine: //p' | tail -n 1)"
  [ -n "$kid_engine" ] || fail 'container prerequisite check did not select an engine'
  printf 'The builder will ask which deployable decoder implementation to use when the package offers more than one.\n\n'
  confirm "Validate and build $kid_id for $platform?" || exit 0
  build_args=("$kid_path" --platform "$platform" --engine "$kid_engine")
  expected_bundle="$ROOT/dist/kids/billie-kid-${kid_id}_${version}.tar.gz"
  if [ -e "$expected_bundle" ]; then
    confirm "A bundle for $kid_id@$version already exists. Replace it?" || exit 0
    build_args+=(--force)
  fi
  python3 deploy/bin/billie-kid-build.py "${build_args[@]}" | tee "$build_log"
  bundle="$(sed -n 's/^Built kid bundle: //p' "$build_log" | tail -n 1)"
  [ -n "$bundle" ] && [ -f "$bundle" ] || fail 'build completed but its bundle path could not be found in the build output'
  checksum="$bundle.sha256"
  [ -f "$checksum" ] || fail "bundle checksum sidecar is missing: $checksum"
  base="$(basename "$bundle")"

  printf '\nCopying the kid bundle and checksum to %s:/tmp ...\n' "$target"
  scp "${ssh_options[@]}" -- "$bundle" "$target:/tmp/$base"
  scp "${ssh_options[@]}" -- "$checksum" "$target:/tmp/$base.sha256"
  confirm "Install $kid_id@$version on $target now?" || { printf 'Bundle remains on the node at /tmp/%s\n' "$base"; exit 0; }
  ssh "${ssh_options[@]}" "$target" "sudo -n billie kid install /tmp/$base"
fi

printf '\nSensor-facing network interfaces on the node:\n'
network_interfaces="$(ssh "${ssh_options[@]}" "$target" 'sudo -n billie network interfaces')" || fail 'could not read sensor-facing network interfaces from the node'
printf '%s\n' "$network_interfaces"
printf '\nBillie is the node receiving sensor traffic. The sensor sends to Billie’s sensor-facing IP and listener port. The sensor source IP/mask below are only used to scope the node firewall; Billie does not configure the sensor.\n'
printf '\nIs Billie’s sensor-port address already configured?\n'
printf '  [1] Already configured\n'
printf '  [2] Assign Billie IP now\n'
network_configured="$(ask 'Select an option' '1')"
case "$network_configured" in
  1|y|Y|yes|YES) ;;
  2|n|N|no|NO)
    sensor_interface="$(ask 'Billie sensor-facing interface name (from the list above)')"
    [[ "$sensor_interface" =~ ^[A-Za-z0-9_.:-]+$ ]] || fail 'invalid interface name'
    bind_address="$(ask 'Billie sensor-facing IPv4 address (the destination the sensor will send to)')"
    valid_ipv4 "$bind_address" || fail 'enter a valid IPv4 address for Billie'
    billie_mask="$(ask 'Billie sensor-port subnet mask (example: 255.255.255.0)')"
    billie_cidr="$(ipv4_with_mask "$bind_address" "$billie_mask")" || fail 'enter a valid contiguous IPv4 subnet mask, such as 255.255.255.0'
    printf 'Billie will assign %s to %s with no gateway or DNS. This works before the sensor is connected. SSH/default-route interfaces are refused.\n' "$billie_cidr" "$sensor_interface"
    confirm "Assign Billie $bind_address with subnet mask $billie_mask on $sensor_interface?" || fail 'Billie sensor interface configuration was declined'
    printf 'Applying the sensor-port address. If the Pi’s management lease changes, the wizard will prompt for its current SSH address.\n'
    if ! ssh "${ssh_options[@]}" "$target" "sudo -n billie network configure --interface $sensor_interface --address $billie_cidr --yes"; then
      if ssh "${ssh_options[@]}" "$target" 'sudo -n true' >/dev/null 2>&1; then
        fail 'sensor-port configuration failed while SSH remained available; review the Billie network error above'
      fi
      recover_ssh_target
    fi
    if ! ssh "${ssh_options[@]}" "$target" 'sudo -n true' >/dev/null 2>&1; then
      recover_ssh_target
    fi
    assigned_cidrs="$(ssh "${ssh_options[@]}" "$target" "ip -o -4 addr show dev $sensor_interface | awk '\$4 ~ /^$bind_address\\// {print \$4}'")" \
      || fail "could not verify Billie’s sensor-facing address over SSH: $target"
    printf '%s\n' "$assigned_cidrs" | grep -Fxq "$billie_cidr" \
      || fail "Billie does not have $billie_cidr assigned to $sensor_interface after configuration"
    ;;
  *) fail 'choose 1 (already configured) or 2 (assign Billie IP now)' ;;
esac
if [ "$network_configured" = 1 ] || [[ "$network_configured" =~ ^(y|Y|yes|YES)$ ]]; then
  bind_address="$(ask 'Billie sensor-facing IPv4 address (the destination the sensor will send to)')"
  valid_ipv4 "$bind_address" || fail 'enter a valid IPv4 address for Billie'
  billie_mask="$(ask 'Billie sensor-port subnet mask (example: 255.255.255.0)')"
  billie_cidr="$(ipv4_with_mask "$bind_address" "$billie_mask")" || fail 'enter a valid contiguous IPv4 subnet mask, such as 255.255.255.0'
  assigned_cidrs="$(ssh "${ssh_options[@]}" "$target" "ip -o -4 addr show | awk '\$4 ~ /^$bind_address\\// {print \$4}'" 2>/dev/null)" || fail 'could not verify Billie’s sensor-facing address over SSH'
  if ! printf '%s\n' "$assigned_cidrs" | grep -Fxq "$billie_cidr"; then
    fail "Billie does not have $billie_cidr assigned. Choose [2] Assign Billie IP now, or check the interface’s address and subnet mask."
  fi
fi
printf 'Billie listener destination: %s (network %s)\n' "$bind_address" "$billie_cidr"

listeners=()
while IFS= read -r listener_line; do listeners+=("$listener_line"); done < <(python3 -c 'import sys,yaml; m=yaml.safe_load(open(sys.argv[1])); [print("\t".join((str(x["name"]),str(x["transport"]).lower(),str(x["port"])))) for x in m["interfaces"]["inputs"]]' "$kid_path/billie-kid.yaml")
[ "${#listeners[@]}" -gt 0 ] || fail 'selected package declares no input listeners'
printf '\nDeclared sensor inputs:\n'
for i in "${!listeners[@]}"; do IFS=$'\t' read -r lname ltransport lport <<< "${listeners[$i]}"; printf '  %d) %s — %s, container port %s\n' "$((i + 1))" "$lname" "$ltransport" "$lport"; done
listener_choice="$(ask 'Select an input number' '1')"
[[ "$listener_choice" =~ ^[0-9]+$ ]] && [ "$listener_choice" -ge 1 ] && [ "$listener_choice" -le "${#listeners[@]}" ] || fail 'select one of the listed input numbers'
IFS=$'\t' read -r listener transport container_port <<< "${listeners[$((listener_choice - 1))]}"
[[ "$listener" =~ ^[A-Za-z0-9_.:-]+$ ]] || fail 'manifest listener name contains unsupported characters'
[[ "$transport" == udp || "$transport" == tcp ]] || fail 'manifest listener transport must be TCP or UDP'
[[ "$container_port" =~ ^[0-9]+$ ]] && [ "$container_port" -ge 1 ] && [ "$container_port" -le 65535 ] || fail 'manifest listener has an invalid container port'
host_port="$(ask 'Billie listener port for the sensor to send to' "$container_port")"
[[ "$host_port" =~ ^[0-9]+$ ]] && [ "$host_port" -ge 1 ] && [ "$host_port" -le 65535 ] || fail 'port must be an integer from 1 to 65535'
ufw_status="$(ssh "${ssh_options[@]}" "$target" 'sudo -n ufw status' 2>/dev/null || true)"
ufw_active=0
if printf '%s\n' "$ufw_status" | grep -qi '^Status: active'; then ufw_active=1; fi
source_cidr=""
printf '\nSensor source IP/mask means the address and subnet Billie sees on incoming packets. NAT or workstation routing can make this differ from the sensor’s configured address.\n'
if [ "$ufw_active" -eq 1 ]; then
  while true; do
    source_mode="$(ask 'Sensor source for firewall: [1] Detect incoming sender [2] Enter sensor IP and subnet mask' '1')"
    case "$source_mode" in
      1)
        sensor_interface="$(ssh "${ssh_options[@]}" "$target" "ip -o -4 addr show | awk '\$4 ~ /^$bind_address\\// {print \$2; exit}'" 2>/dev/null || true)"
        if [ -z "$sensor_interface" ] || ! [[ "$sensor_interface" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
          printf 'Could not determine which node interface owns %s. Enter the interface name shown by billie network interfaces.\n' "$bind_address" >&2
          sensor_interface="$(ask 'Sensor-facing interface name')"
        fi
        [[ "$sensor_interface" =~ ^[A-Za-z0-9_.:-]+$ ]] || fail 'invalid interface name'
        printf 'Start or continue the sensor now. Detecting its source IP on %s while it sends to Billie %s:%s (up to 15 seconds)...\n' "$sensor_interface" "$bind_address" "$host_port"
        capture="$(ssh "${ssh_options[@]}" "$target" "sudo -n timeout 15 tcpdump -nn -l -i '$sensor_interface' -c 1 'dst host $bind_address and dst port $host_port' 2>/dev/null" 2>/dev/null || true)"
        source_ip="$(python3 -c 'import re,sys; m=re.search(r"\bIP\s+((?:\d{1,3}\.){3}\d{1,3})\.\d+\s+>", sys.stdin.read()); print(m.group(1) if m else "")' <<< "$capture")"
        if [ -n "$source_ip" ] && valid_ipv4 "$source_ip"; then
          sensor_source_ip="$source_ip"
          printf 'Observed sensor source IP as seen by Billie: %s\n' "$sensor_source_ip"
          while true; do
            sensor_source_mask="$(ask 'Sensor source subnet mask (one sender only: 255.255.255.255)' '255.255.255.255')"
            source_cidr="$(ipv4_with_mask "$sensor_source_ip" "$sensor_source_mask")" && break
            printf 'That mask is not a valid contiguous IPv4 subnet mask. Try again.\n' >&2
          done
          printf 'Firewall will allow sensor source network %s.\n' "$source_cidr"
          confirm "Use sensor source $sensor_source_ip with subnet mask $sensor_source_mask?" && break
          source_cidr=""
        else
          printf 'No matching packet was captured. Check that the sensor is transmitting to this bind address and port, then retry detection or enter its expected source CIDR.\n' >&2
          retry="$(ask '[1] Retry capture [2] Enter expected source CIDR manually' '2')"
          case "$retry" in 1) continue ;; 2) source_mode=2 ;; *) printf 'Choose 1 or 2.\n' >&2; continue ;; esac
        fi
        ;;
      2) ;;
      *) printf 'Choose 1 or 2.\n' >&2; continue ;;
    esac
    if [ "$source_mode" = 2 ]; then
      while true; do
        sensor_source_ip="$(ask 'Sensor source IPv4 address (as Billie sees it; not Billie’s listener IP)')"
        valid_ipv4 "$sensor_source_ip" || { printf 'Enter a valid sensor source IPv4 address.\n' >&2; continue; }
        sensor_source_mask="$(ask 'Sensor source subnet mask (one sender: 255.255.255.255; example network: 255.255.255.0)')"
        source_cidr="$(ipv4_with_mask "$sensor_source_ip" "$sensor_source_mask")" && break
        printf 'Enter a valid contiguous IPv4 subnet mask.\n' >&2
      done
      break
    fi
    [ -n "$source_cidr" ] && break
  done
else
  printf 'UFW is inactive, so the wizard will not add a source firewall rule.\n'
fi
configure=(sudo -n billie kid configure "$kid_id" --transport "$transport" --bind-address "$bind_address" --port "$host_port" --listener "$listener" --version "$version")
if [ -n "$source_cidr" ]; then configure+=(--source-cidr "$source_cidr"); fi
printf '\nBillie will configure the selected listener and manage only its own UFW rules when UFW is active.\n'
transport_upper="$(printf '%s' "$transport" | tr '[:lower:]' '[:upper:]')"
printf 'The sensor must send to Billie at %s:%s using %s. The kid receives it inside its container on port %s.\n' "$bind_address" "$host_port" "$transport_upper" "$container_port"
confirm "Configure $kid_id listener for $transport_upper on Billie $bind_address:$host_port?" || fail 'kid listener configuration was declined'
ssh "${ssh_options[@]}" "$target" "${configure[*]}"
confirm "Activate $kid_id@$version now?" || { printf 'Kid is installed and configured. Activate later with: ssh %s sudo -n billie kid activate %s --version %s\n' "$target" "$kid_id" "$version"; exit 0; }
ssh "${ssh_options[@]}" "$target" "sudo -n billie kid activate $kid_id --version $version"
printf '\nKid status:\n'
ssh "${ssh_options[@]}" "$target" "sudo -n billie kid status $kid_id"
printf '\nKid deployment wizard completed. To inspect logs: ssh %s sudo -n billie kid logs %s\n' "$target" "$kid_id"
