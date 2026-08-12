#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
umask 077

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck source=scripts/bootstrap/lib/common.sh
source "${script_dir}/lib/common.sh"

readonly PHASE=preflight
readonly EXPECTED_HOSTNAME=retail-test-workflow
readonly EXPECTED_NODE_IP=10.93.1.27
readonly SERVICE_CIDR=172.20.0.0/16
readonly POD_CIDR=172.21.0.0/16
readonly CLEANUP_EVIDENCE_SHA256=a68a3d2ff340bcdcb4265853107a3a2c22a9f7328728473d81d9be2d1486e635

host_path() {
  local absolute=$1
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == "1" ]]; then
    printf '%s%s\n' "${BOOTSTRAP_TEST_ROOT:?}" "$absolute"
  else
    printf '%s\n' "$absolute"
  fi
}

complete() {
  local result=$1
  local reason=$2
  local code=$3
  local next=$4
  finish_phase "$result" "$reason" "$code" "$next"
  exit "$code"
}

parse_mode "$@" || exit "$?"
if [[ "$MODE" != CHECK ]]; then
  printf 'RESULT=STOP_MODE\nREASON=preflight-is-read-only\n' >&2
  exit "$EXIT_PRECONDITION"
fi
if [[ "${BOOTSTRAP_TEST_MODE:-0}" == "1" && "$EUID" -eq 0 ]]; then
  printf 'RESULT=STOP_TEST_MODE\nREASON=test-mode-is-for-unprivileged-tests-only\n' >&2
  exit "$EXIT_PRECONDITION"
fi

evidence_dir=$(host_path /root/dev-infra-evidence)
if ! open_evidence 07-preflight "$evidence_dir"; then
  printf 'RESULT=STOP_EVIDENCE\nREASON=evidence-open-failed\n' >&2
  exit "$EXIT_UNKNOWN_STATE"
fi

for required_command in awk cmp date dpkg-query grep hostname id ip python3 readlink ss stat swapon systemctl tr uname; do
  require_command "$required_command" || complete STOP_PRECONDITION "missing-command-${required_command}" "$EXIT_PRECONDITION" NONE
done
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  complete STOP_PRECONDITION missing-command-sha256 "$EXIT_PRECONDITION" NONE
fi

if ! require_root; then
  complete STOP_HOST_IDENTITY not-root "$EXIT_PRECONDITION" NONE
fi

actual_hostname=$(hostname 2>/dev/null) || complete STOP_HOST_IDENTITY hostname-unreadable "$EXIT_PRECONDITION" NONE
if [[ "$actual_hostname" != "$EXPECTED_HOSTNAME" ]]; then
  complete STOP_HOST_IDENTITY hostname-mismatch "$EXIT_PRECONDITION" NONE
fi
log_evidence "HOSTNAME=${actual_hostname}"

os_release=$(host_path /etc/os-release)
canonical_os_release=$(host_path /usr/lib/os-release)
if [[ -L "$os_release" ]]; then
  os_release_link=$(readlink -- "$os_release" 2>/dev/null) ||
    complete STOP_HOST_IDENTITY os-release-missing "$EXIT_PRECONDITION" NONE
  if [[ "$os_release_link" != ../usr/lib/os-release ||
        ! -f "$canonical_os_release" || -L "$canonical_os_release" ]]; then
    complete STOP_HOST_IDENTITY os-release-missing "$EXIT_PRECONDITION" NONE
  fi
  os_release=$canonical_os_release
elif [[ ! -f "$os_release" ]]; then
  complete STOP_HOST_IDENTITY os-release-missing "$EXIT_PRECONDITION" NONE
fi
os_id=$(awk -F= '$1 == "ID" {gsub(/"/, "", $2); print $2}' "$os_release")
os_version=$(awk -F= '$1 == "VERSION_ID" {gsub(/"/, "", $2); print $2}' "$os_release")
if [[ "$os_id" != ubuntu || "$os_version" != 24.04* ]]; then
  complete STOP_HOST_IDENTITY os-mismatch "$EXIT_PRECONDITION" NONE
fi
log_evidence "OS=${os_id}-${os_version}"

architecture=$(uname -m 2>/dev/null) || complete STOP_HOST_IDENTITY architecture-unreadable "$EXIT_PRECONDITION" NONE
if [[ "$architecture" != x86_64 ]]; then
  complete STOP_HOST_IDENTITY architecture-mismatch "$EXIT_PRECONDITION" NONE
fi
log_evidence "ARCHITECTURE=${architecture}"

cgroup_path=$(host_path /sys/fs/cgroup)
cgroup_fs=$(stat -fc %T "$cgroup_path" 2>/dev/null) || complete STOP_HOST_IDENTITY cgroup-unreadable "$EXIT_PRECONDITION" NONE
if [[ "$cgroup_fs" != cgroup2fs ]]; then
  complete STOP_HOST_IDENTITY cgroup-v2-required "$EXIT_PRECONDITION" NONE
fi
log_evidence "CGROUP_FS=${cgroup_fs}"

address_output=$(ip -o -4 address show up 2>/dev/null) || complete STOP_NETWORK ip-address-unreadable "$EXIT_PRECONDITION" NONE
if ! printf '%s\n' "$address_output" | awk -v ip="$EXPECTED_NODE_IP" '$4 ~ ("^" ip "/") {found=1} END {exit !found}'; then
  complete STOP_NETWORK node-ip-not-bound-up "$EXIT_PRECONDITION" NONE
fi
log_evidence "NODE_IP=${EXPECTED_NODE_IP}"

swap_file=$(host_path /swap.img)
if [[ ! -f "$swap_file" || -L "$swap_file" ]]; then
  complete STOP_SWAP swap-file-missing "$EXIT_PRECONDITION" NONE
fi
swap_output=$(swapon --show=NAME,SIZE --noheadings --raw --bytes 2>/dev/null) || complete STOP_SWAP swapon-unreadable "$EXIT_PRECONDITION" NONE
swap_lines=$(printf '%s\n' "$swap_output" | awk 'NF {count++} END {print count+0}')
swap_name=$(printf '%s\n' "$swap_output" | awk 'NF {print $1}')
swap_bytes=$(printf '%s\n' "$swap_output" | awk 'NF {print $2}')
if [[ "$swap_lines" != 1 || "$swap_name" != /swap.img || ! "$swap_bytes" =~ ^[0-9]+$ ]]; then
  complete STOP_SWAP swap-layout-mismatch "$EXIT_PRECONDITION" NONE
fi
if (( swap_bytes < 4000000000 || swap_bytes > 4400000000 )); then
  complete STOP_SWAP swap-size-mismatch "$EXIT_PRECONDITION" NONE
fi
log_evidence "SWAP=/swap.img"
log_evidence "SWAP_BYTES=${swap_bytes}"

for service in chrony systemd-networkd systemd-resolved ssh; do
  service_state=$(systemctl is-active "$service" 2>/dev/null) || complete STOP_HOST_HEALTH "service-${service}-inactive" "$EXIT_PRECONDITION" NONE
  if [[ "$service_state" != active ]]; then
    complete STOP_HOST_HEALTH "service-${service}-not-active" "$EXIT_PRECONDITION" NONE
  fi
done
log_evidence "BASE_SERVICES=active"

cleanup_evidence=$(host_path /root/dev-infra-evidence/06-host-workflow-cleanup-20260810T033358Z.txt)
if [[ ! -f "$cleanup_evidence" || -L "$cleanup_evidence" ]]; then
  complete STOP_CLEANUP_EVIDENCE cleanup-evidence-missing "$EXIT_PRECONDITION" NONE
fi
cleanup_digest=$(sha256_file "$cleanup_evidence") || complete STOP_CLEANUP_EVIDENCE cleanup-evidence-unreadable "$EXIT_PRECONDITION" NONE
if [[ "$cleanup_digest" != "$CLEANUP_EVIDENCE_SHA256" ]]; then
  complete STOP_CLEANUP_EVIDENCE cleanup-evidence-digest-mismatch "$EXIT_PRECONDITION" NONE
fi
log_evidence "CLEANUP_EVIDENCE_SHA256=${cleanup_digest}"

for binary in caddy containerd docker dockerd node npm npx pnpm runc; do
  if command -v "$binary" >/dev/null 2>&1; then
    complete STOP_OLD_RUNTIME "unexpected-binary-${binary}" "$EXIT_UNKNOWN_STATE" NONE
  fi
done

for package in caddy containerd.io docker-ce docker-ce-cli docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras; do
  if dpkg-query -W -f='${Status}\n' "$package" 2>/dev/null | grep -Fxq 'install ok installed'; then
    complete STOP_OLD_RUNTIME "unexpected-package-${package}" "$EXIT_UNKNOWN_STATE" NONE
  fi
done

for path in /data/workflow /etc/caddy /etc/containerd /etc/docker /opt/containerd /usr/local/lib/node-v24.18.0 /var/lib/containerd /var/lib/docker; do
  resolved=$(host_path "$path")
  if [[ -e "$resolved" || -L "$resolved" ]]; then
    complete STOP_OLD_RUNTIME "unexpected-path-${path}" "$EXIT_UNKNOWN_STATE" NONE
  fi
done

unit_files=$(systemctl list-unit-files caddy.service containerd.service docker.service docker.socket 2>/dev/null || true)
if printf '%s\n' "$unit_files" | grep -Eq '^(caddy|containerd|docker)\.(service|socket)[[:space:]]'; then
  complete STOP_OLD_RUNTIME unexpected-old-unit "$EXIT_UNKNOWN_STATE" NONE
fi

port_3001=$(ss -H -ltn 'sport = :3001' 2>/dev/null || true)
if [[ -n "$port_3001" ]]; then
  complete STOP_OLD_RUNTIME port-3001-listening "$EXIT_UNKNOWN_STATE" NONE
fi
log_evidence "OLD_RUNTIME=absent"
log_evidence "PORT_3001=closed"

cidr_arguments=(
  --service-cidr "$SERVICE_CIDR"
  --pod-cidr "$POD_CIDR"
)
while IFS= read -r address; do
  [[ -n "$address" ]] && cidr_arguments+=(--address "$address")
done < <(printf '%s\n' "$address_output" | awk 'NF >= 4 {print $4}')

route_output=$(ip -o -4 route show table all 2>/dev/null) || complete STOP_NETWORK ip-route-unreadable "$EXIT_PRECONDITION" NONE
while IFS= read -r route; do
  [[ -n "$route" && "$route" != default ]] && cidr_arguments+=(--route "$route")
done < <(printf '%s\n' "$route_output" | awk '$1 != "default" && $1 ~ /\// {print $1}')

set +e
cidr_output=$(python3 "${script_dir}/check_cidrs.py" "${cidr_arguments[@]}" 2>/dev/null)
cidr_exit=$?
set -e
if [[ "$cidr_exit" -ne 0 ]]; then
  cidr_result=$(printf '%s\n' "$cidr_output" | awk -F= '$1 == "RESULT" {print $2}')
  complete "${cidr_result:-STOP_CIDR_INVALID}" cidr-overlap-or-invalid "$EXIT_PRECONDITION" NONE
fi
log_evidence "SERVICE_CIDR=${SERVICE_CIDR}"
log_evidence "POD_CIDR=${POD_CIDR}"
log_evidence "CIDR_SCOPE=SERVER_LOCAL_SCOPE_ONLY"
log_evidence "REPO_ROOT=${repo_root}"

complete PASS_PREFLIGHT server-local-preflight-passed 0 '10-stage-artifacts.sh --check'
