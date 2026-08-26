#!/bin/bash -p
set -Eeuo pipefail
export LC_ALL=C
umask 077

untrusted_environment=
for untrusted_name in APT_CONFIG KUBECONFIG GNUPGHOME CURL_HOME CURL_CA_BUNDLE \
    SSL_CERT_FILE SSL_CERT_DIR XDG_CONFIG_HOME KUBECACHEDIR \
    KUBECTL_EXTERNAL_DIFF TAR_OPTIONS BASH_ENV ENV; do
  [[ -z "${!untrusted_name+x}" ]] ||
    untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
done
for untrusted_name in "${!PYTHON@}" "${!KUBECTL_@}" "${!CURL_@}"; do
  [[ ",${untrusted_environment}," == *",${untrusted_name},"* ]] ||
    untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
done
if [[ -n "$untrusted_environment" ]]; then
  printf 'RESULT=STOP_PRECONDITION\nREASON=untrusted-environment-override\nVARS=%s\n' \
    "$untrusted_environment" >&2
  exit 10
fi

if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  if [[ "$EUID" -eq 0 ]]; then
    printf 'RESULT=STOP_TEST_MODE\nREASON=test-mode-is-for-unprivileged-tests-only\n' >&2
    exit 10
  fi
  if [[ -z "${BOOTSTRAP_TEST_ROOT:-}" || "$BOOTSTRAP_TEST_ROOT" != /* ||
        "$BOOTSTRAP_TEST_ROOT" == / || ! -d "$BOOTSTRAP_TEST_ROOT" ||
        -L "$BOOTSTRAP_TEST_ROOT" || ! -O "$BOOTSTRAP_TEST_ROOT" ]]; then
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
bootstrap_dir=$(cd "${script_dir}/../.." && pwd -P)
repo_root=$(cd "${bootstrap_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/common.sh"
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/path-facts.sh"
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/exec-safety.sh"
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/host-config.sh"
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/admin-conf.sh"
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/kubectl.sh"

# shellcheck disable=SC2034
readonly PHASE=flux-phase-a
readonly PYTHON_BINARY=/usr/bin/python3
TAR_BINARY=/usr/bin/tar
if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  TAR_BINARY=$(host_path /usr/bin/tar)
fi
readonly TAR_BINARY
readonly DESIRED_ROOT="${repo_root}/clusters/dev/flux-system/phase-a"
readonly RAW_RENDERED_SHA256=1a82990f5b4a84bc52692a84871a04ebbda4cc02fb1e72e4283d6f320f4f4994
readonly FIELD_MANAGER=engineering-platform-flux-phase-a
readonly FLUX_VERSION=2.9.3
readonly FLUX_ARCHIVE_SHA256=eae4e8608c0ade2bf4e8dec1669dbb6b0c28b5822b252d97feccfb4fb1181fd2
readonly FLUX_ARCHIVE_URL=https://github.com/fluxcd/flux2/releases/download/v2.9.3/flux_2.9.3_linux_amd64.tar.gz
readonly INTERNAL_PROBE="${repo_root}/runbook/examples/flux-phase-a-network-probe.yaml"
readonly EXTERNAL_PROBE="${repo_root}/runbook/examples/flux-phase-a-external-network-probe.yaml"
readonly EXPECTED_CRDS=$'customresourcedefinition.apiextensions.k8s.io/alerts.notification.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/buckets.source.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/externalartifacts.source.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/gitrepositories.source.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/helmcharts.source.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/helmreleases.helm.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/helmrepositories.source.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/kustomizations.kustomize.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/ocirepositories.source.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/providers.notification.toolkit.fluxcd.io\ncustomresourcedefinition.apiextensions.k8s.io/receivers.notification.toolkit.fluxcd.io'
readonly EXPECTED_DEPLOYMENTS=$'deployment.apps/helm-controller\ndeployment.apps/kustomize-controller\ndeployment.apps/notification-controller\ndeployment.apps/source-controller'
readonly EXPECTED_CLUSTER_RBAC=$'clusterrole.rbac.authorization.k8s.io/flux-controller-api-health\nclusterrolebinding.rbac.authorization.k8s.io/flux-controller-api-health'
readonly FLUX_CUSTOM_RESOURCE_TYPES=alerts.notification.toolkit.fluxcd.io,buckets.source.toolkit.fluxcd.io,externalartifacts.source.toolkit.fluxcd.io,gitrepositories.source.toolkit.fluxcd.io,helmcharts.source.toolkit.fluxcd.io,helmreleases.helm.toolkit.fluxcd.io,helmrepositories.source.toolkit.fluxcd.io,kustomizations.kustomize.toolkit.fluxcd.io,ocirepositories.source.toolkit.fluxcd.io,providers.notification.toolkit.fluxcd.io,receivers.notification.toolkit.fluxcd.io
readonly EXPECTED_BUSINESS_NAMESPACES=$'namespace/cert-manager\nnamespace/cnpg-system\nnamespace/local-path-storage\nnamespace/platform'
readonly EXPECTED_BUSINESS_SYNC=$'gitrepository.source.toolkit.fluxcd.io/flux-system\nkustomization.kustomize.toolkit.fluxcd.io/cert-manager-config\nkustomization.kustomize.toolkit.fluxcd.io/cert-manager-controller\nkustomization.kustomize.toolkit.fluxcd.io/cnpg-controller\nkustomization.kustomize.toolkit.fluxcd.io/flux-system\nkustomization.kustomize.toolkit.fluxcd.io/infrastructure-foundation\nkustomization.kustomize.toolkit.fluxcd.io/platform-apps\nkustomization.kustomize.toolkit.fluxcd.io/platform-database\nkustomization.kustomize.toolkit.fluxcd.io/platform-migration'

namespace_json_is_exact() {
  python_isolated -c '
import json
import sys

expected = {
    "app.kubernetes.io/instance": "flux-system",
    "app.kubernetes.io/part-of": "flux",
    "app.kubernetes.io/version": "v2.9.3",
    "pod-security.kubernetes.io/audit": "restricted",
    "pod-security.kubernetes.io/audit-version": "v1.36",
    "pod-security.kubernetes.io/enforce": "restricted",
    "pod-security.kubernetes.io/enforce-version": "v1.36",
    "pod-security.kubernetes.io/warn": "restricted",
    "pod-security.kubernetes.io/warn-version": "v1.36",
}
try:
    document = json.load(sys.stdin)
    metadata = document["metadata"]
    labels = metadata["labels"]
    if metadata.get("name") != "flux-system":
        raise ValueError
    if metadata.get("deletionTimestamp") is not None:
        raise ValueError
    if not isinstance(labels, dict) or any(labels.get(k) != v for k, v in expected.items()):
        raise ValueError
    if document.get("status", {}).get("phase") != "Active":
        raise ValueError
except (KeyError, TypeError, ValueError):
    raise SystemExit(1)
'
}

deployments_are_ready() {
  python_isolated -c '
import json
import sys

expected = {
    "source-controller", "kustomize-controller",
    "helm-controller", "notification-controller",
}
try:
    document = json.load(sys.stdin)
    items = document.get("items")
    if not isinstance(items, list) or len(items) != 4:
        raise ValueError
    seen = set()
    for item in items:
        metadata = item["metadata"]
        spec = item["spec"]
        status = item["status"]
        name = metadata["name"]
        if name in seen or name not in expected or spec.get("replicas") != 1:
            raise ValueError
        if status.get("observedGeneration") != metadata.get("generation"):
            raise ValueError
        if any(status.get(field) != 1 for field in (
            "readyReplicas", "availableReplicas", "updatedReplicas"
        )):
            raise ValueError
        seen.add(name)
    if seen != expected:
        raise ValueError
except (KeyError, TypeError, ValueError):
    raise SystemExit(1)
'
}

inventory_is_approved_subset() {
  python_isolated -c '
import sys

observed = [line for line in sys.argv[1].splitlines() if line]
expected = set(line for line in sys.argv[2].splitlines() if line)
if len(observed) != len(set(observed)) or not set(observed).issubset(expected):
    raise SystemExit(1)
' "$1" "$2"
}

parse_mode "$@" || exit "$?"
require_root || complete STOP_PRECONDITION not-root "$EXIT_PRECONDITION" NONE
for required_command in awk chmod cmp dirname id mktemp rm rmdir sort stat; do
  require_command "$required_command" ||
    complete STOP_PRECONDITION "missing-command-${required_command}" "$EXIT_PRECONDITION" NONE
done
if ! command -v sha256sum >/dev/null 2>&1 &&
   ! command -v shasum >/dev/null 2>&1; then
  complete STOP_PRECONDITION missing-command-sha256 "$EXIT_PRECONDITION" NONE
fi
[[ -x "$PYTHON_BINARY" ]] ||
  complete STOP_PRECONDITION missing-command-python3 "$EXIT_PRECONDITION" NONE
if [[ ! -x "$TAR_BINARY" ]] || ! safe_file "$TAR_BINARY" 755; then
  complete STOP_UNKNOWN_STATE tar-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
fi
load_host_config ||
  complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE

# shellcheck disable=SC2034
kubectl_binary=$(host_path /usr/bin/kubectl)
# shellcheck disable=SC2034
admin_conf=$(host_path /etc/kubernetes/admin.conf)
if [[ ! -x "$kubectl_binary" ]] || ! safe_file "$kubectl_binary" 755; then
  complete STOP_UNKNOWN_STATE kubectl-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
fi
capture_admin_conf ||
  complete STOP_UNKNOWN_STATE admin-conf-content-or-structure-drift "$EXIT_UNKNOWN_STATE" NONE

expected_raw_rendered_sha=$RAW_RENDERED_SHA256
if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  expected_raw_rendered_sha=${BOOTSTRAP_TEST_RAW_RENDERED_SHA256:-}
  [[ "$expected_raw_rendered_sha" =~ ^[0-9a-f]{64}$ ]] ||
    complete STOP_PRECONDITION test-rendered-sha256-unsafe "$EXIT_PRECONDITION" NONE
fi
rendered_sha=$(
  kubectl_run kustomize "$DESIRED_ROOT" |
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum
    else
      shasum -a 256
    fi |
    awk '{print $1}'
) || complete STOP_SUPPLY_CHAIN_MISMATCH render-failed "$EXIT_SUPPLY_CHAIN" NONE
[[ "$rendered_sha" == "$expected_raw_rendered_sha" ]] ||
  complete STOP_SUPPLY_CHAIN_MISMATCH rendered-bundle-digest-drift "$EXIT_SUPPLY_CHAIN" NONE
kubectl_run create --dry-run=client --kustomize "$DESIRED_ROOT" >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED client-dry-run-failed "$EXIT_VERIFY_FAILED" NONE

namespace_name=$(kubectl_run get namespace flux-system --ignore-not-found --output=name 2>/dev/null) ||
  complete STOP_UNKNOWN_STATE flux-namespace-query-failed "$EXIT_UNKNOWN_STATE" NONE
flux_crds=$(kubectl_run get customresourcedefinitions.apiextensions.k8s.io \
  --selector=app.kubernetes.io/part-of=flux --output=name 2>/dev/null) ||
  complete STOP_UNKNOWN_STATE flux-crd-query-failed "$EXIT_UNKNOWN_STATE" NONE
flux_cluster_resources=$(kubectl_run get clusterrole,clusterrolebinding \
  --selector=app.kubernetes.io/part-of=flux --output=name 2>/dev/null) ||
  complete STOP_UNKNOWN_STATE flux-cluster-resource-query-failed "$EXIT_UNKNOWN_STATE" NONE
api_health_rbac=$(kubectl_run get clusterrole,clusterrolebinding \
  flux-controller-api-health --ignore-not-found --output=name 2>/dev/null) ||
  complete STOP_UNKNOWN_STATE flux-cluster-resource-query-failed "$EXIT_UNKNOWN_STATE" NONE
downstream_namespaces=$(kubectl_run get namespace platform openbao cert-manager \
  monitoring cnpg-system minio local-path-storage --ignore-not-found \
  --output=name 2>/dev/null) ||
  complete STOP_UNKNOWN_STATE downstream-namespace-query-failed "$EXIT_UNKNOWN_STATE" NONE

if [[ -z "$namespace_name" && -z "$flux_crds" ]]; then
  [[ -z "$flux_cluster_resources" && -z "$api_health_rbac" &&
     -z "$downstream_namespaces" ]] ||
    complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE
  if [[ "$MODE" == CHECK ]]; then
    complete PASS_FLUX_PHASE_A_CHECK apply-required 0 \
      'stages/100-flux-phase-a/run.sh --apply'
  fi
  cluster_state=ABSENT
fi

if [[ "${cluster_state:-}" != ABSENT ]]; then
  [[ "$namespace_name" == namespace/flux-system ]] ||
    complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE
  namespace_json=$(kubectl_run get namespace flux-system --output=json 2>/dev/null) ||
    complete STOP_UNKNOWN_STATE flux-namespace-query-failed "$EXIT_UNKNOWN_STATE" NONE
  printf '%s' "$namespace_json" | namespace_json_is_exact ||
    complete STOP_UNKNOWN_STATE flux-namespace-drift "$EXIT_UNKNOWN_STATE" NONE
  deployments=$(kubectl_run --namespace=flux-system get deployment.apps --output=name 2>/dev/null) ||
    complete STOP_UNKNOWN_STATE flux-deployment-query-failed "$EXIT_UNKNOWN_STATE" NONE
  secrets=$(kubectl_run --namespace=flux-system get secret --output=name 2>/dev/null) ||
    complete STOP_UNKNOWN_STATE flux-secret-query-failed "$EXIT_UNKNOWN_STATE" NONE

  if [[ -z "$flux_crds" ]]; then
    namespace_resources=$(kubectl_run --namespace=flux-system get \
      serviceaccount,service,role,rolebinding,resourcequota,networkpolicy,ciliumnetworkpolicy \
      --output=name 2>/dev/null) ||
      complete STOP_UNKNOWN_STATE flux-resource-query-failed "$EXIT_UNKNOWN_STATE" NONE
    if [[ -z "$deployments" && -z "$secrets" && -z "$namespace_resources" &&
          -z "$flux_cluster_resources" && -z "$api_health_rbac" &&
          -z "$downstream_namespaces" ]]; then
      if [[ "$MODE" == CHECK ]]; then
        complete PASS_FLUX_PHASE_A_CHECK namespace-only-apply-required 0 \
          'stages/100-flux-phase-a/run.sh --apply'
      fi
      cluster_state=NAMESPACE_ONLY
    else
      complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE
    fi
  fi
fi

if [[ -n "$flux_crds" ]]; then
  sorted_crds=$(printf '%s\n' "$flux_crds" | sort)
  sorted_deployments=$(printf '%s\n' "$deployments" | sort)
  sorted_api_health_rbac=$(printf '%s\n' "$api_health_rbac" | sort)
  [[ "$sorted_crds" == "$EXPECTED_CRDS" &&
     "$sorted_deployments" == "$EXPECTED_DEPLOYMENTS" &&
     "$sorted_api_health_rbac" == "$EXPECTED_CLUSTER_RBAC" &&
     -z "$flux_cluster_resources" && -z "$secrets" ]] ||
    complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE
  inventory_is_approved_subset \
    "$downstream_namespaces" "$EXPECTED_BUSINESS_NAMESPACES" ||
    complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE
  sync_inventory=$(kubectl_run get "$FLUX_CUSTOM_RESOURCE_TYPES" \
    --all-namespaces --ignore-not-found --output=name 2>/dev/null) ||
    complete STOP_UNKNOWN_STATE flux-sync-query-failed "$EXIT_UNKNOWN_STATE" NONE
  inventory_is_approved_subset "$sync_inventory" "$EXPECTED_BUSINESS_SYNC" ||
    complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE

  diff_rc=0
  kubectl_run diff --server-side --field-manager="$FIELD_MANAGER" \
    --kustomize "$DESIRED_ROOT" >/dev/null 2>&1 || diff_rc=$?
  [[ "$diff_rc" == 0 ]] ||
    complete STOP_UNKNOWN_STATE flux-desired-state-drift "$EXIT_UNKNOWN_STATE" NONE
  deployment_json=$(kubectl_run --namespace=flux-system get deployment.apps \
    --output=json 2>/dev/null) ||
    complete STOP_UNKNOWN_STATE flux-deployment-query-failed "$EXIT_UNKNOWN_STATE" NONE
  printf '%s' "$deployment_json" | deployments_are_ready ||
    complete STOP_VERIFY_FAILED flux-controller-not-ready "$EXIT_VERIFY_FAILED" NONE

  complete ALREADY_COMPLIANT flux-phase-a-ready 0 NONE
fi

[[ "$MODE" == APPLY && ( "$cluster_state" == ABSENT ||
   "$cluster_state" == NAMESPACE_ONLY ) ]] ||
  complete STOP_UNKNOWN_STATE flux-phase-a-state-unknown "$EXIT_UNKNOWN_STATE" NONE

curl_binary=$(host_path /usr/bin/curl)
if [[ ! -x "$curl_binary" ]] || ! safe_file "$curl_binary" 755; then
  complete STOP_UNKNOWN_STATE curl-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
fi
root_dir=$(host_path /root)
safe_directory "$root_dir" 700 ||
  complete STOP_UNKNOWN_STATE flux-work-root-unsafe "$EXIT_UNKNOWN_STATE" NONE
work_dir=$(mktemp -d "${root_dir}/.flux-phase-a.XXXXXX") ||
  complete STOP_APPLY_FAILED flux-work-directory-create-failed "$EXIT_APPLY_FAILED" NONE
safe_directory "$work_dir" 700 ||
  complete STOP_UNKNOWN_STATE flux-work-directory-unsafe "$EXIT_UNKNOWN_STATE" NONE
archive="${work_dir}/flux_${FLUX_VERSION}_linux_amd64.tar.gz"
flux_binary="${work_dir}/flux"
rendered_file="${work_dir}/rendered.yaml"
namespace_file="${work_dir}/namespace.yaml"
kubeconfig_file="${work_dir}/admin.conf"

cleanup_flux_work_dir() {
  local candidate
  for candidate in "$archive" "$flux_binary" "$rendered_file" \
      "$namespace_file" "$kubeconfig_file"; do
    [[ ! -e "$candidate" && ! -L "$candidate" ]] || rm -f -- "$candidate" || return 1
  done
  rmdir -- "$work_dir"
}

FLUX_PHASE_A_PROBE_POD=
FLUX_PHASE_A_PROBE_UID=
FLUX_PHASE_A_EXTERNAL_PROBE_POD=
FLUX_PHASE_A_EXTERNAL_PROBE_UID=

delete_flux_phase_a_probe_if_owned() {
  local pod_namespace=$1
  local pod_name=$2
  local expected_uid=$3
  local current_uid

  [[ -n "$pod_name" ]] || return 0
  current_uid=$(kubectl_run --namespace="$pod_namespace" get pod "$pod_name" \
    --ignore-not-found --output=jsonpath='{.metadata.uid}') || return 1
  [[ -n "$current_uid" ]] || return 0
  [[ "$current_uid" == "$expected_uid" ]] || return 1
  kubectl_run --namespace="$pod_namespace" delete pod "$pod_name" --wait=true \
    >/dev/null 2>&1
}

cleanup_flux_phase_a_probes() {
  local cleanup_status=0
  delete_flux_phase_a_probe_if_owned flux-system \
    "$FLUX_PHASE_A_PROBE_POD" "$FLUX_PHASE_A_PROBE_UID" || cleanup_status=$?
  delete_flux_phase_a_probe_if_owned default \
    "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" "$FLUX_PHASE_A_EXTERNAL_PROBE_UID" || cleanup_status=$?
  return "$cleanup_status"
}

# shellcheck disable=SC2317  # invoked indirectly by the EXIT trap
cleanup_flux_phase_a_apply() {
  local cleanup_status=0
  cleanup_flux_phase_a_probes || cleanup_status=$?
  cleanup_flux_work_dir || cleanup_status=$?
  return "$cleanup_status"
}

probe_identity_is_safe() {
  local identity=$1
  local name=${identity%%:*}
  local uid=${identity#*:}

  [[ "$identity" == *:* && "$name" != "$uid" ]] || return 1
  [[ "$name" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || return 1
  [[ "$uid" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]
}

complete_with_evidence_sidecar() {
  local result=$1 reason=$2 code=$3 next=$4
  local digest sidecar

  finish_phase "$result" "$reason" "$code" "$next" || exit "$EXIT_UNKNOWN_STATE"
  digest=$(sha256_file "$EVIDENCE_FILE") || exit "$EXIT_UNKNOWN_STATE"
  sidecar="${EVIDENCE_FILE}.sha256"
  if ! (umask 077; set -o noclobber; printf '%s  %s\n' \
      "$digest" "${EVIDENCE_FILE##*/}" >"$sidecar") 2>/dev/null; then
    printf 'STOP: evidence SHA-256 sidecar create failed: %s\n' "$sidecar" >&2
    exit "$EXIT_UNKNOWN_STATE"
  fi
  chmod 600 "$sidecar" || exit "$EXIT_APPLY_FAILED"
  safe_file "$sidecar" 600 || exit "$EXIT_UNKNOWN_STATE"
  printf 'SHA256_FILE=%s\n' "$sidecar"
  exit "$code"
}

trap 'cleanup_flux_phase_a_apply || :' EXIT

"$curl_binary" --fail --location --proto '=https' --tlsv1.2 \
  --output "$archive" "$FLUX_ARCHIVE_URL" ||
  complete STOP_APPLY_FAILED flux-cli-download-failed "$EXIT_APPLY_FAILED" NONE
expected_archive_sha=$FLUX_ARCHIVE_SHA256
if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  expected_archive_sha=${BOOTSTRAP_TEST_FLUX_ARCHIVE_SHA256:-}
  [[ "$expected_archive_sha" =~ ^[0-9a-f]{64}$ ]] ||
    complete STOP_PRECONDITION test-flux-archive-sha256-unsafe "$EXIT_PRECONDITION" NONE
fi
[[ "$(sha256_file "$archive")" == "$expected_archive_sha" ]] ||
  complete STOP_SUPPLY_CHAIN_MISMATCH flux-cli-archive-digest-drift "$EXIT_SUPPLY_CHAIN" NONE
tar_safe -xzf "$archive" -C "$work_dir" flux ||
  complete STOP_SUPPLY_CHAIN_MISMATCH flux-cli-extraction-failed "$EXIT_SUPPLY_CHAIN" NONE
if [[ ! -x "$flux_binary" ]] || ! safe_file "$flux_binary" 755; then
  complete STOP_SUPPLY_CHAIN_MISMATCH flux-cli-binary-unsafe "$EXIT_SUPPLY_CHAIN" NONE
fi
[[ "$("$flux_binary" version --client 2>/dev/null)" == 'flux version 2.9.3' ]] ||
  complete STOP_SUPPLY_CHAIN_MISMATCH flux-cli-version-drift "$EXIT_SUPPLY_CHAIN" NONE
printf '%s' "$ADMIN_CONF_CONTENT" >"$kubeconfig_file" ||
  complete STOP_APPLY_FAILED flux-kubeconfig-create-failed "$EXIT_APPLY_FAILED" NONE
chmod 600 "$kubeconfig_file" ||
  complete STOP_APPLY_FAILED flux-kubeconfig-mode-failed "$EXIT_APPLY_FAILED" NONE
safe_file "$kubeconfig_file" 600 ||
  complete STOP_UNKNOWN_STATE flux-kubeconfig-unsafe "$EXIT_UNKNOWN_STATE" NONE
admin_conf_is_safe ||
  complete STOP_UNKNOWN_STATE admin-conf-raced-before-flux-precheck "$EXIT_UNKNOWN_STATE" NONE
"$flux_binary" check --pre --kubeconfig="$kubeconfig_file" >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED flux-precheck-failed "$EXIT_VERIFY_FAILED" NONE
admin_conf_is_safe ||
  complete STOP_UNKNOWN_STATE admin-conf-raced-after-flux-precheck "$EXIT_UNKNOWN_STATE" NONE

kubectl_run kustomize "$DESIRED_ROOT" >"$rendered_file" ||
  complete STOP_SUPPLY_CHAIN_MISMATCH render-raced "$EXIT_SUPPLY_CHAIN" NONE
[[ "$(sha256_file "$rendered_file")" == "$expected_raw_rendered_sha" ]] ||
  complete STOP_SUPPLY_CHAIN_MISMATCH rendered-bundle-raced "$EXIT_SUPPLY_CHAIN" NONE
awk 'NR == 1 && $0 == "---" {next} /^---$/ {exit} {print}' \
  "$rendered_file" >"$namespace_file" ||
  complete STOP_SUPPLY_CHAIN_MISMATCH namespace-extraction-failed "$EXIT_SUPPLY_CHAIN" NONE
[[ -s "$namespace_file" ]] ||
  complete STOP_SUPPLY_CHAIN_MISMATCH namespace-extraction-failed "$EXIT_SUPPLY_CHAIN" NONE

if [[ "$cluster_state" == ABSENT ]]; then
  kubectl_run apply --server-side --dry-run=server \
    --field-manager="$FIELD_MANAGER" --filename=- <"$namespace_file" >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED namespace-server-dry-run-failed "$EXIT_VERIFY_FAILED" NONE
  kubectl_run apply --server-side --field-manager="$FIELD_MANAGER" \
    --filename=- <"$namespace_file" >/dev/null 2>&1 ||
    complete STOP_APPLY_FAILED namespace-apply-failed "$EXIT_APPLY_FAILED" NONE
fi
kubectl_run wait '--for=jsonpath={.status.phase}=Active' namespace/flux-system \
  --timeout=60s >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED namespace-active-wait-failed "$EXIT_VERIFY_FAILED" NONE

kubectl_run apply --server-side --dry-run=server \
  --field-manager="$FIELD_MANAGER" --kustomize "$DESIRED_ROOT" >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED bundle-server-dry-run-failed "$EXIT_VERIFY_FAILED" NONE
diff_rc=0
kubectl_run diff --server-side --field-manager="$FIELD_MANAGER" \
  --kustomize "$DESIRED_ROOT" >/dev/null 2>&1 || diff_rc=$?
[[ "$diff_rc" == 1 ]] ||
  complete STOP_UNKNOWN_STATE bundle-diff-state-unexpected "$EXIT_UNKNOWN_STATE" NONE
kubectl_run apply --server-side --field-manager="$FIELD_MANAGER" \
  --kustomize "$DESIRED_ROOT" >/dev/null 2>&1 ||
  complete STOP_APPLY_FAILED bundle-server-apply-failed "$EXIT_APPLY_FAILED" NONE

for controller in source-controller kustomize-controller helm-controller \
    notification-controller; do
  kubectl_run --namespace=flux-system rollout status "deployment/${controller}" \
    --timeout=5m >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED flux-controller-rollout-failed "$EXIT_VERIFY_FAILED" NONE
done
"$flux_binary" check --kubeconfig="$kubeconfig_file" \
  --components=source-controller,kustomize-controller,helm-controller,notification-controller \
  >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED flux-check-failed "$EXIT_VERIFY_FAILED" NONE

internal_probe_identity=$(kubectl_run create --filename="$INTERNAL_PROBE" \
  --output=jsonpath='{.metadata.name}:{.metadata.uid}') ||
  complete STOP_APPLY_FAILED flux-internal-probe-create-failed "$EXIT_APPLY_FAILED" NONE
probe_identity_is_safe "$internal_probe_identity" ||
  complete STOP_UNKNOWN_STATE flux-internal-probe-identity-unsafe "$EXIT_UNKNOWN_STATE" NONE
FLUX_PHASE_A_PROBE_POD=${internal_probe_identity%%:*}
FLUX_PHASE_A_PROBE_UID=${internal_probe_identity#*:}

external_probe_identity=$(kubectl_run create --filename="$EXTERNAL_PROBE" \
  --output=jsonpath='{.metadata.name}:{.metadata.uid}') ||
  complete STOP_APPLY_FAILED flux-external-probe-create-failed "$EXIT_APPLY_FAILED" NONE
probe_identity_is_safe "$external_probe_identity" ||
  complete STOP_UNKNOWN_STATE flux-external-probe-identity-unsafe "$EXIT_UNKNOWN_STATE" NONE
FLUX_PHASE_A_EXTERNAL_PROBE_POD=${external_probe_identity%%:*}
FLUX_PHASE_A_EXTERNAL_PROBE_UID=${external_probe_identity#*:}

kubectl_run --namespace=flux-system wait --for=condition=Ready \
  "pod/$FLUX_PHASE_A_PROBE_POD" --timeout=2m >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED flux-internal-probe-not-ready "$EXIT_VERIFY_FAILED" NONE
kubectl_run --namespace=default wait --for=condition=Ready \
  "pod/$FLUX_PHASE_A_EXTERNAL_PROBE_POD" --timeout=2m >/dev/null 2>&1 ||
  complete STOP_VERIFY_FAILED flux-external-probe-not-ready "$EXIT_VERIFY_FAILED" NONE

for command in \
    'flux-system|internal|nslookup kubernetes.default.svc.cluster.local' \
    'flux-system|internal|nc -z -w 5 kubernetes.default.svc.cluster.local 443' \
    'flux-system|internal|nc -z -w 5 source-controller.flux-system.svc.cluster.local 80' \
    'flux-system|internal|nc -z -w 5 notification-controller.flux-system.svc.cluster.local 80' \
    'default|external|nslookup kubernetes.default.svc.cluster.local' \
    'default|external|nc -z -w 5 kubernetes.default.svc.cluster.local 443' \
    'default|external|nc -z -w 5 github.com 443'; do
  IFS='|' read -r probe_namespace probe_kind probe_command <<<"$command"
  probe_pod=$FLUX_PHASE_A_PROBE_POD
  [[ "$probe_kind" == internal ]] || probe_pod=$FLUX_PHASE_A_EXTERNAL_PROBE_POD
  read -r -a probe_arguments <<<"$probe_command"
  kubectl_run --namespace="$probe_namespace" exec "$probe_pod" -- \
    "${probe_arguments[@]}" >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED flux-network-positive-probe-failed "$EXIT_VERIFY_FAILED" NONE
done

for command in \
    'flux-system|internal|nc -z -w 5 github.com 443' \
    'default|external|nc -z -w 5 source-controller.flux-system.svc.cluster.local 80' \
    'default|external|nc -z -w 5 notification-controller.flux-system.svc.cluster.local 80' \
    'default|external|nc -z -w 5 webhook-receiver.flux-system.svc.cluster.local 80'; do
  IFS='|' read -r probe_namespace probe_kind probe_command <<<"$command"
  probe_pod=$FLUX_PHASE_A_PROBE_POD
  [[ "$probe_kind" == internal ]] || probe_pod=$FLUX_PHASE_A_EXTERNAL_PROBE_POD
  read -r -a probe_arguments <<<"$probe_command"
  if kubectl_run --namespace="$probe_namespace" exec "$probe_pod" -- \
      "${probe_arguments[@]}" >/dev/null 2>&1; then
    complete STOP_VERIFY_FAILED flux-network-boundary-failed "$EXIT_VERIFY_FAILED" NONE
  fi
done

source_pod_ip=$(kubectl_run --namespace=flux-system get pod \
  --selector=app=source-controller --output=jsonpath='{.items[0].status.podIP}') ||
  complete STOP_VERIFY_FAILED flux-network-pod-ip-query-failed "$EXIT_VERIFY_FAILED" NONE
notification_pod_ip=$(kubectl_run --namespace=flux-system get pod \
  --selector=app=notification-controller --output=jsonpath='{.items[0].status.podIP}') ||
  complete STOP_VERIFY_FAILED flux-network-pod-ip-query-failed "$EXIT_VERIFY_FAILED" NONE
if ! host_config_ipv4_is_valid "$source_pod_ip" ||
   ! host_config_ipv4_is_valid "$notification_pod_ip"; then
  complete STOP_UNKNOWN_STATE flux-network-pod-ip-unsafe "$EXIT_UNKNOWN_STATE" NONE
fi

if kubectl_run --namespace=flux-system exec "$FLUX_PHASE_A_PROBE_POD" -- \
    nc -z -w 5 "$source_pod_ip" 8080 >/dev/null 2>&1; then
  complete STOP_VERIFY_FAILED flux-network-boundary-failed "$EXIT_VERIFY_FAILED" NONE
fi
if kubectl_run --namespace=flux-system exec "$FLUX_PHASE_A_PROBE_POD" -- \
    nc -z -w 5 "$notification_pod_ip" 9292 >/dev/null 2>&1; then
  complete STOP_VERIFY_FAILED flux-network-boundary-failed "$EXIT_VERIFY_FAILED" NONE
fi

cleanup_flux_phase_a_probes ||
  complete STOP_UNKNOWN_STATE flux-network-probe-cleanup-failed "$EXIT_UNKNOWN_STATE" NONE
FLUX_PHASE_A_PROBE_POD=
FLUX_PHASE_A_PROBE_UID=
FLUX_PHASE_A_EXTERNAL_PROBE_POD=
FLUX_PHASE_A_EXTERNAL_PROBE_UID=

postcheck=$(
  /bin/bash -p "$0" --check 2>&1
) || complete STOP_VERIFY_FAILED flux-postcheck-failed "$EXIT_VERIFY_FAILED" NONE
expected_postcheck=$'PHASE=flux-phase-a\nMODE=CHECK\nRESULT=ALREADY_COMPLIANT\nREASON=flux-phase-a-ready\nEVIDENCE=NONE\nEXIT_CODE=0\nNEXT=NONE\nSHA256=NONE'
[[ "$postcheck" == "$expected_postcheck" ]] ||
  complete STOP_VERIFY_FAILED flux-postcheck-output-drift "$EXIT_VERIFY_FAILED" NONE

cleanup_flux_work_dir ||
  complete STOP_UNKNOWN_STATE flux-work-directory-cleanup-failed "$EXIT_UNKNOWN_STATE" NONE
trap - EXIT
evidence_dir=$(host_path /root/dev-infra-evidence)
open_evidence 15-flux-phase-a "$evidence_dir" ||
  complete STOP_EVIDENCE evidence-open-failed "$EXIT_UNKNOWN_STATE" NONE
log_evidence FLUX_VERSION=v2.9.3
log_evidence RAW_RENDERED_SHA256="$expected_raw_rendered_sha"
log_evidence CONTROLLERS=source,kustomize,helm,notification
log_evidence FLUX_CRD_COUNT=11
log_evidence FLUX_CHECK=all-checks-passed
log_evidence SECRET_COUNT=0
log_evidence SYNC_INVENTORY=empty
log_evidence DOWNSTREAM_NAMESPACE_INVENTORY=empty
log_evidence NETWORK_PROBE_RESULT=PASS
log_evidence NETWORK_PROBE_POSITIVE_COUNT=7
log_evidence NETWORK_PROBE_NEGATIVE_COUNT=6
log_evidence NETWORK_PROBE_CLEANUP=owned-uid-exact
log_evidence OPENBAO=NOT_EXECUTED
log_evidence BACKUPS=NOT_EXECUTED
log_evidence APPLICATIONS=NOT_EXECUTED
complete_with_evidence_sidecar PASS_FLUX_PHASE_A_INSTALLED flux-phase-a-ready 0 NONE
