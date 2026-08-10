#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
umask 077

if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  if [[ "$EUID" -eq 0 ]]; then
    printf 'RESULT=STOP_TEST_MODE\nREASON=test-mode-is-for-unprivileged-tests-only\n' >&2
    exit 10
  fi
  if [[ -z "${BOOTSTRAP_TEST_ROOT:-}" || "$BOOTSTRAP_TEST_ROOT" != /* || "$BOOTSTRAP_TEST_ROOT" == / || ! -d "$BOOTSTRAP_TEST_ROOT" || -L "$BOOTSTRAP_TEST_ROOT" || ! -O "$BOOTSTRAP_TEST_ROOT" ]]; then
    printf 'RESULT=STOP_TEST_MODE\nREASON=test-root-must-be-isolated\n' >&2
    exit 10
  fi
else
  export PATH=/usr/sbin:/usr/bin:/sbin:/bin
  for test_override in "${!BOOTSTRAP_TEST_@}"; do
    : "$test_override"
    printf 'RESULT=STOP_TEST_OVERRIDE\nREASON=test-override-in-production\n' >&2
    exit 10
  done
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${script_dir}/lib/common.sh"

# PHASE 由公共 evidence helper 间接读取。
# shellcheck disable=SC2034
readonly PHASE=kubeadm-init
readonly EXPECTED_HOSTNAME=retail-test-workflow
readonly EXPECTED_NODE_IP=10.93.1.27
readonly SERVICE_CIDR=172.20.0.0/16
readonly POD_CIDR=172.21.0.0/16
readonly CONFIG_SHA256=e37b38f198bd7279ae3d203a990a4c2d40e1b2a8b59796475b814f09445103c6
readonly CONFIG_FILE="${repo_root}/bootstrap/kubeadm/init.yaml"

host_path() {
  local absolute=$1
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
    printf '%s%s\n' "${BOOTSTRAP_TEST_ROOT:?}" "$absolute"
  else
    printf '%s\n' "$absolute"
  fi
}

complete() {
  local result=$1 reason=$2 code=$3 next=$4
  finish_phase "$result" "$reason" "$code" "$next"
  exit "$code"
}

path_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null
}

path_owner() {
  stat -c '%u:%g' "$1" 2>/dev/null || stat -f '%u:%g' "$1" 2>/dev/null
}

owned_by_expected() {
  local expected_uid=0 expected_gid=0
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 && "$EUID" -ne 0 ]]; then
    expected_uid=$EUID
    expected_gid=${GROUPS[0]}
  fi
  [[ "$(path_owner "$1")" == "${expected_uid}:${expected_gid}" ]]
}

safe_test_gate() {
  local path=$1
  [[ "$path" == /* && -f "$path" && ! -L "$path" && -x "$path" && -O "$path" ]]
}

run_stage_gate() {
  /bin/bash "$1" --check >/dev/null 2>&1
}

initialization_state_gate() {
  local admin_conf manifest_dir etcd_member listener first_manifest
  admin_conf=$(host_path /etc/kubernetes/admin.conf)
  manifest_dir=$(host_path /etc/kubernetes/manifests)
  etcd_member=$(host_path /var/lib/etcd/member)
  for marker in "$admin_conf" "$etcd_member"; do
    if [[ -e "$marker" || -L "$marker" ]]; then
      complete STOP_ALREADY_INITIALIZED initialized-or-partial-marker-present "$EXIT_UNKNOWN_STATE" NONE
    fi
  done
  if [[ -e "$manifest_dir" || -L "$manifest_dir" ]]; then
    if [[ -L "$manifest_dir" || ! -d "$manifest_dir" ]]; then
      complete STOP_ALREADY_INITIALIZED static-manifest-path-present "$EXIT_UNKNOWN_STATE" NONE
    fi
    first_manifest=$(find "$manifest_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null) ||
      complete STOP_ALREADY_INITIALIZED static-manifest-state-unreadable "$EXIT_UNKNOWN_STATE" NONE
    [[ -z "$first_manifest" ]] || complete STOP_ALREADY_INITIALIZED static-manifest-present "$EXIT_UNKNOWN_STATE" NONE
  fi
  listener=$(ss -H -ltn 'sport = :6443' 2>/dev/null) ||
    complete STOP_PRECONDITION apiserver-listener-state-unreadable "$EXIT_PRECONDITION" NONE
  [[ -z "$listener" ]] || complete STOP_ALREADY_INITIALIZED apiserver-port-listener-present "$EXIT_UNKNOWN_STATE" NONE
}

parse_mode "$@" || exit "$?"
require_root || complete STOP_PRECONDITION not-root "$EXIT_PRECONDITION" NONE
for required_command in awk date find grep hostname id ip kubeadm openssl python3 sed sha256sum sort ss stat swapon systemctl tr uname; do
  if [[ "$required_command" == sha256sum ]] && command -v shasum >/dev/null 2>&1; then
    continue
  fi
  require_command "$required_command" || complete STOP_PRECONDITION "missing-command-${required_command}" "$EXIT_PRECONDITION" NONE
done

admin_conf=$(host_path /etc/kubernetes/admin.conf)
etcd_member=$(host_path /var/lib/etcd/member)
initialization_state_gate

actual_hostname=$(hostname 2>/dev/null) || complete STOP_PRECONDITION hostname-unreadable "$EXIT_PRECONDITION" NONE
[[ "$actual_hostname" == "$EXPECTED_HOSTNAME" ]] || complete STOP_PRECONDITION hostname-mismatch "$EXIT_PRECONDITION" NONE
os_release=$(host_path /etc/os-release)
[[ -f "$os_release" && ! -L "$os_release" ]] || complete STOP_PRECONDITION os-release-unsafe "$EXIT_PRECONDITION" NONE
os_id=$(awk -F= '$1 == "ID" {gsub(/"/, "", $2); print $2}' "$os_release")
os_version=$(awk -F= '$1 == "VERSION_ID" {gsub(/"/, "", $2); print $2}' "$os_release")
[[ "$os_id" == ubuntu && "$os_version" == 24.04* ]] || complete STOP_PRECONDITION os-mismatch "$EXIT_PRECONDITION" NONE
[[ "$(uname -m 2>/dev/null)" == x86_64 ]] || complete STOP_PRECONDITION architecture-mismatch "$EXIT_PRECONDITION" NONE
address_output=$(ip -o -4 address show up 2>/dev/null) || complete STOP_PRECONDITION address-unreadable "$EXIT_PRECONDITION" NONE
printf '%s\n' "$address_output" | awk -v ip="$EXPECTED_NODE_IP" '$4 ~ ("^" ip "/") {found=1} END {exit !found}' || complete STOP_PRECONDITION node-ip-not-bound-up "$EXIT_PRECONDITION" NONE
swap_file=$(host_path /swap.img)
[[ -f "$swap_file" && ! -L "$swap_file" ]] || complete STOP_PRECONDITION swap-file-missing "$EXIT_PRECONDITION" NONE
swap_output=$(swapon --show --noheadings --bytes --output NAME,SIZE 2>/dev/null) || complete STOP_PRECONDITION swap-unreadable "$EXIT_PRECONDITION" NONE
[[ "$(printf '%s\n' "$swap_output" | awk 'NF {count++} END {print count+0}')" == 1 ]] || complete STOP_PRECONDITION swap-layout-mismatch "$EXIT_PRECONDITION" NONE
[[ "$(printf '%s\n' "$swap_output" | awk 'NF {print $1}')" == /swap.img ]] || complete STOP_PRECONDITION swap-layout-mismatch "$EXIT_PRECONDITION" NONE

config_digest=$(sha256_file "$CONFIG_FILE") || complete STOP_PRECONDITION kubeadm-config-unreadable "$EXIT_PRECONDITION" NONE
[[ "$config_digest" == "$CONFIG_SHA256" ]] || complete STOP_PRECONDITION kubeadm-config-digest-mismatch "$EXIT_PRECONDITION" NONE

kernel_script="${script_dir}/20-prepare-kernel.sh"
containerd_script="${script_dir}/30-install-containerd.sh"
kubernetes_script="${script_dir}/40-install-kubernetes.sh"
cidr_script="${script_dir}/check_cidrs.py"
if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  kernel_script=${BOOTSTRAP_TEST_KERNEL_SCRIPT:-$kernel_script}
  containerd_script=${BOOTSTRAP_TEST_CONTAINERD_SCRIPT:-$containerd_script}
  kubernetes_script=${BOOTSTRAP_TEST_KUBERNETES_SCRIPT:-$kubernetes_script}
  cidr_script=${BOOTSTRAP_TEST_CIDR_SCRIPT:-$cidr_script}
  for gate in "$kernel_script" "$containerd_script" "$kubernetes_script" "$cidr_script"; do
    safe_test_gate "$gate" || complete STOP_PRECONDITION test-gate-unsafe "$EXIT_PRECONDITION" NONE
  done
fi
run_stage_gate "$kernel_script" || complete STOP_PRECONDITION kernel-gate-failed "$EXIT_PRECONDITION" NONE
run_stage_gate "$containerd_script" || complete STOP_PRECONDITION containerd-gate-failed "$EXIT_PRECONDITION" NONE
run_stage_gate "$kubernetes_script" || complete STOP_PRECONDITION kubernetes-gate-failed "$EXIT_PRECONDITION" NONE

route_output=$(ip -o -4 route show table all 2>/dev/null) || complete STOP_PRECONDITION route-unreadable "$EXIT_PRECONDITION" NONE
declare -a cidr_arguments=(--service-cidr "$SERVICE_CIDR" --pod-cidr "$POD_CIDR")
while IFS= read -r address; do
  [[ -n "$address" ]] && cidr_arguments+=(--address "$address")
done < <(printf '%s\n' "$address_output" | awk '{print $4}')
while IFS= read -r route; do
  [[ -n "$route" ]] && cidr_arguments+=(--route "$route")
done < <(printf '%s\n' "$route_output" | awk '$1 != "default" {print $1}')
if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  "$cidr_script" "${cidr_arguments[@]}" >/dev/null 2>&1 || complete STOP_PRECONDITION cidr-gate-failed "$EXIT_PRECONDITION" NONE
else
  python3 "$cidr_script" "${cidr_arguments[@]}" >/dev/null 2>&1 || complete STOP_PRECONDITION cidr-gate-failed "$EXIT_PRECONDITION" NONE
fi

# MODE 由公共 parse_mode helper 赋值。
# shellcheck disable=SC2153
if [[ "$MODE" == CHECK ]]; then
  complete PASS_KUBEADM_CHECK apply-required 0 '50-kubeadm-init.sh --apply'
fi

if ! kubeadm config validate --config "$CONFIG_FILE" >/dev/null 2>&1; then
  complete STOP_APPLY_FAILED kubeadm-config-validation-failed "$EXIT_APPLY_FAILED" NONE
fi
if ! kubeadm init phase preflight --config "$CONFIG_FILE" >/dev/null 2>&1; then
  complete STOP_APPLY_FAILED kubeadm-phase-preflight-failed "$EXIT_APPLY_FAILED" NONE
fi
initialization_state_gate
evidence_dir=$(host_path /root/dev-infra-evidence)
open_evidence 12-kubeadm "$evidence_dir" || complete STOP_EVIDENCE evidence-open-failed "$EXIT_UNKNOWN_STATE" NONE
if ! kubeadm init --config "$CONFIG_FILE" >/dev/null 2>&1; then
  complete STOP_APPLY_FAILED kubeadm-init-failed "$EXIT_APPLY_FAILED" NONE
fi

if [[ ! -f "$admin_conf" || -L "$admin_conf" || "$(path_mode "$admin_conf")" != 600 ]] || ! owned_by_expected "$admin_conf"; then
  complete STOP_VERIFY_FAILED admin-conf-metadata-drift "$EXIT_VERIFY_FAILED" NONE
fi
manifest_dir=$(host_path /etc/kubernetes/manifests)
actual_manifests=$(find "$manifest_dir" -mindepth 1 -maxdepth 1 -print 2>/dev/null | sed 's#.*/##' | sort) || complete STOP_VERIFY_FAILED static-manifest-state-unreadable "$EXIT_VERIFY_FAILED" NONE
expected_manifests=$'etcd.yaml\nkube-apiserver.yaml\nkube-controller-manager.yaml\nkube-scheduler.yaml'
[[ "$actual_manifests" == "$expected_manifests" ]] || complete STOP_VERIFY_FAILED static-manifest-set-drift "$EXIT_VERIFY_FAILED" NONE
for component in kube-apiserver kube-controller-manager kube-scheduler etcd; do
  manifest="${manifest_dir}/${component}.yaml"
  if [[ ! -f "$manifest" || -L "$manifest" || "$(path_mode "$manifest")" != 600 ]] || ! owned_by_expected "$manifest"; then
    complete STOP_VERIFY_FAILED "manifest-metadata-drift-${component}" "$EXIT_VERIFY_FAILED" NONE
  fi
done
[[ -d "$etcd_member" && ! -L "$etcd_member" ]] || complete STOP_VERIFY_FAILED etcd-member-missing "$EXIT_VERIFY_FAILED" NONE
[[ "$(systemctl is-active kubelet.service 2>/dev/null)" == active ]] || complete STOP_VERIFY_FAILED kubelet-inactive "$EXIT_VERIFY_FAILED" NONE

certificate=$(host_path /etc/kubernetes/pki/apiserver.crt)
[[ -f "$certificate" && ! -L "$certificate" ]] || complete STOP_VERIFY_FAILED apiserver-certificate-missing "$EXIT_VERIFY_FAILED" NONE
certificate_output=$(openssl x509 -in "$certificate" -noout -subject -ext subjectAltName -enddate 2>/dev/null) || complete STOP_VERIFY_FAILED apiserver-certificate-unreadable "$EXIT_VERIFY_FAILED" NONE
certificate_subject=$(printf '%s\n' "$certificate_output" | sed -n 's/^subject=//p')
certificate_expiry=$(printf '%s\n' "$certificate_output" | sed -n 's/^notAfter=//p')
[[ -n "$certificate_subject" && "$certificate_subject" != *$'\n'* ]] || complete STOP_VERIFY_FAILED certificate-subject-invalid "$EXIT_VERIFY_FAILED" NONE
[[ -n "$certificate_expiry" && "$certificate_expiry" != *$'\n'* ]] || complete STOP_VERIFY_FAILED certificate-expiry-invalid "$EXIT_VERIFY_FAILED" NONE
grep -Fq 'IP Address:10.93.1.27' <<<"$certificate_output" || complete STOP_VERIFY_FAILED certificate-san-missing "$EXIT_VERIFY_FAILED" NONE

log_evidence CONFIG_SHA256="$CONFIG_SHA256"
log_evidence NODE="$EXPECTED_HOSTNAME"
log_evidence CONTROL_PLANE_ENDPOINT=10.93.1.27:6443
log_evidence ADMIN_CONF_PRESENT=true
log_evidence ADMIN_CONF_MODE=600
log_evidence STATIC_COMPONENTS=kube-apiserver,kube-controller-manager,kube-scheduler,etcd
log_evidence KUBELET_ACTIVE=active
log_evidence "CERTIFICATE_SUBJECT=${certificate_subject}"
log_evidence CERTIFICATE_SAN_IP=10.93.1.27
log_evidence "CERTIFICATE_EXPIRY=${certificate_expiry}"
complete PASS_KUBEADM_INITIALIZED control-plane-initialized 0 '60-install-cilium.sh --check'
