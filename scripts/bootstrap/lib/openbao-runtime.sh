#!/usr/bin/env bash

openbao_lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${openbao_lib_dir}/business-ready.sh"

readonly OPENBAO_FIELD_MANAGER=engineering-platform-openbao-runtime
readonly OPENBAO_BOOTSTRAP_SHA256=52890177117a1bf16b4b340472643adef4718616a02f8aec2a331bf950283a20
readonly OPENBAO_RUNTIME_SHA256=c5bfd003cabb8a3350942cc4cb17025228f79300b1acda5c434c3003aab6720a
readonly OPENBAO_CHART_PACKAGE_SHA256=175c5cea2d36b68d348eca872044656bd8740c4dbe26b7dc8eb7c7438474a8b3
readonly OPENBAO_RENDERED_RAW_SHA256=ca5826e453916abdf3dc1c6942dfd9e94e3a11facda8cd762c9a040a72226890
readonly OPENBAO_RENDERED_CANONICAL_SHA256=ee07429197a8ca7644343d0d66b52e3dc7941a8a608fc6db00da3b4184dcc180
readonly OPENBAO_KUSTOMIZE_CANONICAL_SHA256=919745181a8b86b1af6f0af5d3d92c330c15e738beb66a851ef484f8557d893f
readonly OPENBAO_SERVER_DIGEST=sha256:15e90b578c970ae57b596ed51295380cd54f93860fe36758f05b455d71aae0e0
readonly OPENBAO_INJECTOR_DIGEST=sha256:3dd30a9ac5909d17555480f51be734dfb719a323409f06cffe8b48cdaf6237d2
readonly OPENBAO_HELM_VERSION=v3.21.0
readonly OPENBAO_MIN_AVAILABLE_KIB=20971520
# Ordered bits match openbao_inventory_state's identity list. Only these two
# failed-install checkpoints may resume; every other mixed inventory is PARTIAL.
readonly OPENBAO_INVENTORY_MISSING=00000000000000000000000
readonly OPENBAO_INVENTORY_PRESENT=11111111111111111111111
readonly OPENBAO_INVENTORY_RESUMABLE_BOOTSTRAP=11111100001111110110110
readonly OPENBAO_INVENTORY_RESUMABLE_RETAINED_PVCS=11111100111111110110110

OPENBAO_REPO_ROOT=
OPENBAO_BOOTSTRAP_MANIFEST=
OPENBAO_RUNTIME_MANIFEST=
OPENBAO_VALUES=
OPENBAO_CHART=
OPENBAO_CHART_PACKAGE=
OPENBAO_RENDERED=
OPENBAO_ACTIVE_ROOT=
OPENBAO_CONTROLLER_PATCH=
OPENBAO_HELM_BINARY=

openbao_initialize_paths() {
  OPENBAO_REPO_ROOT=$BUSINESS_REPO_ROOT
  OPENBAO_BOOTSTRAP_MANIFEST=${OPENBAO_REPO_ROOT}/clusters/dev/openbao-bootstrap.yaml
  OPENBAO_RUNTIME_MANIFEST=${OPENBAO_REPO_ROOT}/clusters/dev/openbao-runtime.yaml
  OPENBAO_VALUES=${OPENBAO_REPO_ROOT}/infrastructure/openbao/values.yaml
  OPENBAO_CHART=${OPENBAO_REPO_ROOT}/vendor/charts/openbao
  OPENBAO_CHART_PACKAGE=${OPENBAO_REPO_ROOT}/vendor/charts/openbao-0.28.6.tgz
  OPENBAO_RENDERED=${OPENBAO_REPO_ROOT}/infrastructure/openbao/rendered.yaml
  OPENBAO_ACTIVE_ROOT=${OPENBAO_REPO_ROOT}/clusters/dev/kustomization.yaml
  OPENBAO_CONTROLLER_PATCH=${OPENBAO_REPO_ROOT}/clusters/dev/flux-system/phase-a/kustomization.yaml
  OPENBAO_HELM_BINARY=$(host_path /usr/local/bin/helm)
}

openbao_sha256_is() {
  local path=$1 expected=$2
  safe_file "$path" 644 || return 1
  [[ "$(sha256_file "$path")" == "$expected" ]]
}

openbao_canonical_yaml_digest() {
  "$PYTHON_BINARY" -I -B -c '
import hashlib
import json
import sys

import yaml

text = sys.stdin.read()
text = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
documents = [item for item in yaml.safe_load_all(text) if item]
documents.sort(key=lambda item: (
    str(item.get("apiVersion", "")),
    str(item.get("kind", "")),
    str(item.get("metadata", {}).get("namespace", "")),
    str(item.get("metadata", {}).get("name", "")),
))
payload = json.dumps(
    documents,
    ensure_ascii=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8")
print(hashlib.sha256(payload).hexdigest())
'
}

openbao_render_chart() {
  "$OPENBAO_HELM_BINARY" template openbao "$OPENBAO_CHART" \
    --namespace openbao --values "$OPENBAO_VALUES" --kube-version 1.36.3
}

openbao_verify_assets() {
  local digest version

  openbao_sha256_is "$OPENBAO_BOOTSTRAP_MANIFEST" \
    "$OPENBAO_BOOTSTRAP_SHA256" || return 1
  openbao_sha256_is "$OPENBAO_RUNTIME_MANIFEST" \
    "$OPENBAO_RUNTIME_SHA256" || return 1
  openbao_sha256_is "$OPENBAO_CHART_PACKAGE" \
    "$OPENBAO_CHART_PACKAGE_SHA256" || return 1
  openbao_sha256_is "$OPENBAO_RENDERED" \
    "$OPENBAO_RENDERED_RAW_SHA256" || return 1
  safe_file "$OPENBAO_VALUES" 644 || return 1
  safe_file "$OPENBAO_ACTIVE_ROOT" 644 || return 1
  safe_file "$OPENBAO_CONTROLLER_PATCH" 644 || return 1
  [[ -d "$OPENBAO_CHART" && ! -L "$OPENBAO_CHART" ]] || return 1
  if grep -Eq 'openbao-(bootstrap|runtime)\.yaml|infrastructure/openbao' \
      "$OPENBAO_ACTIVE_ROOT"; then
    return 1
  fi
  grep -F -- '--no-cross-namespace-refs=true' \
    "$OPENBAO_CONTROLLER_PATCH" >/dev/null || return 1
  grep -F 'namespace: flux-system' "$OPENBAO_RUNTIME_MANIFEST" >/dev/null ||
    return 1

  [[ -x "$OPENBAO_HELM_BINARY" ]] && safe_file "$OPENBAO_HELM_BINARY" 755 ||
    return 1
  version=$("$OPENBAO_HELM_BINARY" version --short 2>/dev/null) || return 1
  [[ "$version" == "${OPENBAO_HELM_VERSION}"+* ]] || return 1

  digest=$(openbao_render_chart | openbao_canonical_yaml_digest) || return 1
  [[ "$digest" == "$OPENBAO_RENDERED_CANONICAL_SHA256" ]] || return 1
  digest=$(openbao_canonical_yaml_digest <"$OPENBAO_RENDERED") || return 1
  [[ "$digest" == "$OPENBAO_RENDERED_CANONICAL_SHA256" ]] || return 1
  digest=$(kubectl_run kustomize \
    "${OPENBAO_REPO_ROOT}/infrastructure/openbao" |
    openbao_canonical_yaml_digest) || return 1
  [[ "$digest" == "$OPENBAO_KUSTOMIZE_CANONICAL_SHA256" ]]
}

openbao_bootstrap_subset() {
  local scope=$1
  "$PYTHON_BINARY" -I -B - "$OPENBAO_BOOTSTRAP_MANIFEST" "$scope" <<'PY'
import sys

import yaml

path, scope = sys.argv[1:]
documents = [
    item for item in yaml.safe_load_all(open(path, encoding="utf-8")) if item
]
selected = []
for item in documents:
    kind = str(item.get("kind", ""))
    namespace = str(item.get("metadata", {}).get("namespace", ""))
    if scope == "namespace" and kind == "Namespace":
        selected.append(item)
    elif scope == "safe" and kind != "Namespace" and namespace != "openbao":
        selected.append(item)
    elif scope == "dependent" and namespace == "openbao":
        selected.append(item)
if not selected:
    raise SystemExit(1)
yaml.safe_dump_all(selected, sys.stdout, sort_keys=False)
PY
}

openbao_client_dry_run() {
  kubectl_run create --dry-run=client \
    --filename="$OPENBAO_BOOTSTRAP_MANIFEST" --output=name >/dev/null &&
    kubectl_run create --dry-run=client \
      --filename="$OPENBAO_RUNTIME_MANIFEST" --output=name >/dev/null &&
    kubectl_run create --dry-run=client \
      --kustomize="${OPENBAO_REPO_ROOT}/infrastructure/openbao" \
      --output=name >/dev/null
}

openbao_diff_accept_changes() {
  local exit_code=0
  set +e
  kubectl_run diff --server-side --field-manager="$OPENBAO_FIELD_MANAGER" \
    --filename=- >/dev/null 2>&1
  exit_code=$?
  set -e
  (( exit_code == 0 || exit_code == 1 ))
}

openbao_server_validate_safe_subset() {
  openbao_bootstrap_subset namespace |
    kubectl_run apply --server-side --dry-run=server \
      --field-manager="$OPENBAO_FIELD_MANAGER" --filename=- >/dev/null &&
    openbao_bootstrap_subset namespace | openbao_diff_accept_changes &&
    openbao_bootstrap_subset safe |
      kubectl_run apply --server-side --dry-run=server \
        --field-manager="$OPENBAO_FIELD_MANAGER" --filename=- >/dev/null &&
    openbao_bootstrap_subset safe | openbao_diff_accept_changes
}

openbao_capacity_is_safe() {
  local available node_json storage_class
  storage_class=$(kubectl_run get storageclass stateful-rwo-lowlatency \
    --output=name 2>/dev/null) || return 1
  [[ "$storage_class" == storageclass.storage.k8s.io/stateful-rwo-lowlatency ]] ||
    return 1
  node_json=$(kubectl_run get nodes --output=json 2>/dev/null) || return 1
  printf '%s' "$node_json" | "$PYTHON_BINARY" -I -B -c '
import json
import re
import sys

document = json.load(sys.stdin)
items = document.get("items", [])
if len(items) != 1:
    raise SystemExit(1)
node = items[0]
if node.get("spec", {}).get("unschedulable") is True:
    raise SystemExit(1)
if node.get("status", {}).get("nodeInfo", {}).get("architecture") != "amd64":
    raise SystemExit(1)
ready = any(
    item.get("type") == "Ready" and item.get("status") == "True"
    for item in node.get("status", {}).get("conditions", [])
)
memory = node.get("status", {}).get("allocatable", {}).get("memory", "")
match = re.fullmatch(r"([0-9]+)Ki", memory)
if not ready or match is None or int(match.group(1)) < 2 * 1024 * 1024:
    raise SystemExit(1)
' || return 1
  available=$(/usr/bin/df -Pk \
    "$(host_path /var/lib/engineering-platform/local-path)" 2>/dev/null |
    awk 'NR==2 {print $4}') || return 1
  [[ "$available" =~ ^[0-9]+$ ]] || return 1
  (( available >= OPENBAO_MIN_AVAILABLE_KIB ))
}

openbao_query_exists() {
  local namespace=$1 resource=$2 name=$3 output
  if [[ -n "$namespace" ]]; then
    output=$(kubectl_run --namespace="$namespace" get "$resource" "$name" \
      --ignore-not-found --output=name 2>/dev/null) || return 2
  else
    output=$(kubectl_run get "$resource" "$name" --ignore-not-found \
      --output=name 2>/dev/null) || return 2
  fi
  [[ -n "$output" ]]
}

openbao_inventory_state() {
  local fingerprint='' result namespace resource name
  while IFS='|' read -r namespace resource name; do
    [[ -n "$resource" ]] || continue
    set +e
    openbao_query_exists "$namespace" "$resource" "$name"
    result=$?
    set -e
    case "$result" in
      0) fingerprint+=1 ;;
      1) fingerprint+=0 ;;
      *) printf 'UNKNOWN\n'; return 0 ;;
    esac
  done <<'EOF'
|namespace|openbao
flux-system|kustomization.kustomize.toolkit.fluxcd.io|openbao-runtime
flux-system|helmrelease.helm.toolkit.fluxcd.io|openbao
flux-system|serviceaccount|flux-openbao-reconciler
flux-system|serviceaccount|helm-openbao-reconciler
flux-system|role.rbac.authorization.k8s.io|flux-openbao-control-plane
openbao|statefulset.apps|openbao
openbao|deployment.apps|openbao-agent-injector
openbao|persistentvolumeclaim|data-openbao-0
openbao|persistentvolumeclaim|audit-openbao-0
openbao|certificate.cert-manager.io|openbao-server-tls
openbao|certificate.cert-manager.io|openbao-injector-tls
openbao|certificate.cert-manager.io|openbao-transport-ca
openbao|secret|openbao-server-tls
openbao|secret|openbao-injector-tls
openbao|secret|openbao-transport-ca
openbao|service|openbao
openbao|serviceaccount|openbao-runtime-probe
openbao|networkpolicy.networking.k8s.io|default-deny
|clusterrole.rbac.authorization.k8s.io|openbao-agent-injector-clusterrole
|clusterrole.rbac.authorization.k8s.io|helm-openbao-reconciler
|clusterrolebinding.rbac.authorization.k8s.io|helm-openbao-reconciler
|mutatingwebhookconfiguration.admissionregistration.k8s.io|openbao-agent-injector-cfg
EOF
  case "$fingerprint" in
    "$OPENBAO_INVENTORY_MISSING") printf 'MISSING\n' ;;
    "$OPENBAO_INVENTORY_PRESENT") printf 'PRESENT\n' ;;
    "$OPENBAO_INVENTORY_RESUMABLE_BOOTSTRAP")
      printf 'RESUMABLE_BOOTSTRAP\n'
      ;;
    "$OPENBAO_INVENTORY_RESUMABLE_RETAINED_PVCS")
      printf 'RESUMABLE_RETAINED_PVCS\n'
      ;;
    *) printf 'PARTIAL\n' ;;
  esac
}

openbao_flux_source_matches_head() {
  local head source
  head=$(git -C "$OPENBAO_REPO_ROOT" rev-parse HEAD) || return 1
  source=$(kubectl_run --namespace=flux-system get \
    gitrepository.source.toolkit.fluxcd.io flux-system \
    --output='jsonpath={.status.artifact.revision}' 2>/dev/null) || return 1
  [[ "$source" == *"${head}" ]]
}

openbao_wait_flux_source() {
  local attempt
  for ((attempt = 0; attempt < 36; attempt++)); do
    openbao_flux_source_matches_head && return 0
    /bin/sleep 5
  done
  return 1
}

openbao_workload_is_ready() {
  local namespace=$1 resource=$2 name=$3 expected_image=$4 document
  document=$(kubectl_run --namespace="$namespace" get "$resource" "$name" \
    --output=json 2>/dev/null) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import sys

expected = sys.argv[1]
document = json.load(sys.stdin)
spec = document.get("spec", {})
status = document.get("status", {})
if spec.get("replicas") != 1 or status.get("readyReplicas", 0) != 1:
    raise SystemExit(1)
containers = spec.get("template", {}).get("spec", {}).get("containers", [])
if len(containers) != 1 or containers[0].get("image") != expected:
    raise SystemExit(1)
' "$expected_image"
}

openbao_pod_image_id_is_exact() {
  local selector=$1 expected_image=$2 expected_digest=$3 document
  document=$(kubectl_run --namespace=openbao get pods --selector="$selector" \
    --output=json 2>/dev/null) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import re
import sys

expected_image, expected_digest = sys.argv[1:]
pinned_name, separator, pinned_digest = expected_image.rpartition("@")
repository, tag_separator, tag = pinned_name.rpartition(":")
if (
    separator != "@"
    or expected_image.count("@") != 1
    or pinned_digest != expected_digest
    or re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest) is None
    or tag_separator != ":"
    or not repository
    or repository.startswith("/")
    or repository.endswith("/")
    or "//" in repository
    or "@" in repository
    or any(character.isspace() for character in repository)
    or ":" in repository.rsplit("/", 1)[-1]
    or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}", tag) is None
):
    raise SystemExit(1)
expected_image_id = f"{repository}@{expected_digest}"
items = json.load(sys.stdin).get("items", [])
if len(items) != 1:
    raise SystemExit(1)
pod = items[0]
if pod.get("status", {}).get("phase") != "Running":
    raise SystemExit(1)
statuses = pod.get("status", {}).get("containerStatuses", [])
if len(statuses) != 1:
    raise SystemExit(1)
status = statuses[0]
if (
    not status.get("ready")
    or re.fullmatch(r"sha256:[0-9a-f]{64}", str(status.get("image", ""))) is None
):
    raise SystemExit(1)
if str(status.get("imageID", "")) != expected_image_id:
    raise SystemExit(1)
' "$expected_image" "$expected_digest"
}

openbao_pvcs_are_exact() {
  local document
  document=$(kubectl_run --namespace=openbao get persistentvolumeclaims \
    data-openbao-0 audit-openbao-0 --output=json 2>/dev/null) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import sys

expected = {"data-openbao-0": "10Gi", "audit-openbao-0": "5Gi"}
items = json.load(sys.stdin).get("items", [])
observed = {}
for item in items:
    metadata = item.get("metadata", {})
    spec = item.get("spec", {})
    name = metadata.get("name")
    observed[name] = spec.get("resources", {}).get("requests", {}).get("storage")
    if spec.get("storageClassName") != "stateful-rwo-lowlatency":
        raise SystemExit(1)
    if item.get("status", {}).get("phase") != "Bound":
        raise SystemExit(1)
if observed != expected:
    raise SystemExit(1)
'
}

openbao_services_are_private() {
  local document
  document=$(kubectl_run --namespace=openbao get service \
    openbao openbao-active openbao-internal openbao-agent-injector-svc \
    --output=json 2>/dev/null) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import sys

items = json.load(sys.stdin).get("items", [])
expected = {
    "openbao", "openbao-active", "openbao-internal",
    "openbao-agent-injector-svc",
}
if {item.get("metadata", {}).get("name") for item in items} != expected:
    raise SystemExit(1)
for item in items:
    spec = item.get("spec", {})
    if spec.get("type", "ClusterIP") != "ClusterIP":
        raise SystemExit(1)
    if spec.get("externalIPs") or spec.get("loadBalancerIP"):
        raise SystemExit(1)
' || return 1
  openbao_forbidden_resources_are_absent
}

openbao_optional_resource_is_empty() {
  local api_group=$1 resource=$2 discovered
  discovered=$(kubectl_run api-resources --api-group="$api_group" \
    --namespaced=true --output=name 2>/dev/null) || return 1
  if ! grep -Eq "^${resource}(\.${api_group})?$" <<<"$discovered"; then
    return 0
  fi
  kubectl_query_is_empty --namespace=openbao get \
    "${resource}.${api_group}" --ignore-not-found --output=name
}

openbao_forbidden_resources_are_absent() {
  kubectl_query_is_empty --namespace=openbao get ingress,cronjob \
    --ignore-not-found --output=name &&
    openbao_optional_resource_is_empty gateway.networking.k8s.io gateways &&
    openbao_optional_resource_is_empty gateway.networking.k8s.io httproutes &&
    openbao_optional_resource_is_empty gateway.networking.k8s.io tlsroutes &&
    openbao_optional_resource_is_empty snapshot.storage.k8s.io volumesnapshots &&
    openbao_optional_resource_is_empty postgresql.cnpg.io backups &&
    openbao_optional_resource_is_empty postgresql.cnpg.io scheduledbackups
}

openbao_resume_surface_is_safe() {
  kubectl_query_is_empty --namespace=openbao get service \
    --ignore-not-found --output=name &&
    openbao_forbidden_resources_are_absent
}

openbao_secret_inventory_is_safe() {
  local document
  document=$(kubectl_run --namespace=openbao get secrets --output=json \
    2>/dev/null) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import re
import sys

allowed = {
    "openbao-transport-ca",
    "openbao-server-tls",
    "openbao-injector-tls",
}
for item in json.load(sys.stdin).get("items", []):
    name = str(item.get("metadata", {}).get("name", ""))
    if name in allowed:
        continue
    if re.fullmatch(r"sh\.helm\.release\.v1\.openbao\.v[1-9][0-9]*", name):
        continue
    raise SystemExit(1)
'
}

openbao_status_json() {
  local output exit_code=0
  set +e
  output=$(kubectl_run --namespace=openbao exec pod/openbao-0 -- \
    env BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao status -format=json 2>/dev/null)
  exit_code=$?
  set -e
  (( exit_code == 0 || exit_code == 2 )) || return 1
  printf '%s\n' "$output"
}

openbao_state_is_known() {
  local requirement=${1:-any} document
  document=$(openbao_status_json) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import sys

requirement = sys.argv[1]
document = json.load(sys.stdin)
initialized = document.get("initialized")
sealed = document.get("sealed")
if not isinstance(initialized, bool) or not isinstance(sealed, bool):
    raise SystemExit(1)
if requirement == "fresh" and (initialized is not False or sealed is not True):
    raise SystemExit(1)
if requirement not in ("fresh", "any"):
    raise SystemExit(1)
' "$requirement"
}

openbao_platform_secret_fingerprint() {
  kubectl_run --namespace=platform get secrets --output=json 2>/dev/null |
    "$PYTHON_BINARY" -I -B -c '
import hashlib
import json
import sys

items = []
for item in json.load(sys.stdin).get("items", []):
    metadata = item.get("metadata", {})
    data = item.get("data", {})
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    items.append({
        "name": metadata.get("name"),
        "uid": metadata.get("uid"),
        "resourceVersion": metadata.get("resourceVersion"),
        "type": item.get("type"),
        "dataSha256": hashlib.sha256(encoded).hexdigest(),
    })
payload = json.dumps(items, separators=(",", ":"), sort_keys=True).encode()
print(hashlib.sha256(payload).hexdigest())
'
}

openbao_runtime_is_compliant() {
  local expected_server expected_injector
  expected_server="quay.io/openbao/openbao:2.6.1@${OPENBAO_SERVER_DIGEST}"
  expected_injector="docker.io/hashicorp/vault-k8s:1.7.2@${OPENBAO_INJECTOR_DIGEST}"
  openbao_flux_source_matches_head &&
    business_condition_true flux-system \
      kustomization.kustomize.toolkit.fluxcd.io openbao-runtime Ready &&
    business_condition_true flux-system \
      helmrelease.helm.toolkit.fluxcd.io openbao Ready &&
    business_condition_true openbao certificate.cert-manager.io \
      openbao-transport-ca Ready &&
    business_condition_true openbao certificate.cert-manager.io \
      openbao-server-tls Ready &&
    business_condition_true openbao certificate.cert-manager.io \
      openbao-injector-tls Ready &&
    openbao_workload_is_ready openbao statefulset.apps openbao \
      "$expected_server" &&
    openbao_workload_is_ready openbao deployment.apps \
      openbao-agent-injector "$expected_injector" &&
    openbao_pod_image_id_is_exact \
      'app.kubernetes.io/name=openbao,component=server' \
      "$expected_server" "$OPENBAO_SERVER_DIGEST" &&
    openbao_pod_image_id_is_exact \
      'app.kubernetes.io/name=openbao-agent-injector,component=webhook' \
      "$expected_injector" "$OPENBAO_INJECTOR_DIGEST" &&
    openbao_pvcs_are_exact &&
    openbao_services_are_private &&
    openbao_secret_inventory_is_safe &&
    openbao_helm_pod_delegation_is_exact &&
    openbao_state_is_known any &&
    business_apps_ready && business_https_smoke
}

openbao_full_server_validation() {
  local diff_rc=0
  kubectl_run apply --server-side --dry-run=server \
    --field-manager="$OPENBAO_FIELD_MANAGER" \
    --filename="$OPENBAO_BOOTSTRAP_MANIFEST" >/dev/null || return 1
  kubectl_run apply --server-side --dry-run=server \
    --field-manager="$OPENBAO_FIELD_MANAGER" \
    --filename="$OPENBAO_RUNTIME_MANIFEST" >/dev/null || return 1
  kubectl_run apply --server-side --dry-run=server \
    --field-manager="$OPENBAO_FIELD_MANAGER" \
    --kustomize="${OPENBAO_REPO_ROOT}/infrastructure/openbao" >/dev/null ||
    return 1
  set +e
  kubectl_run diff --server-side --field-manager="$OPENBAO_FIELD_MANAGER" \
    --filename="$OPENBAO_BOOTSTRAP_MANIFEST" \
    --filename="$OPENBAO_RUNTIME_MANIFEST" >/dev/null 2>&1
  diff_rc=$?
  set -e
  (( diff_rc == 0 || diff_rc == 1 )) || return 1
  set +e
  kubectl_run diff --server-side --field-manager="$OPENBAO_FIELD_MANAGER" \
    --kustomize="${OPENBAO_REPO_ROOT}/infrastructure/openbao" \
    >/dev/null 2>&1
  diff_rc=$?
  set -e
  (( diff_rc == 0 || diff_rc == 1 ))
}

openbao_resume_checkpoint_is_safe() {
  local inventory=$1
  case "$inventory" in
    RESUMABLE_BOOTSTRAP) ;;
    RESUMABLE_RETAINED_PVCS)
      openbao_pvcs_are_exact || return 1
      ;;
    *) return 1 ;;
  esac
  openbao_secret_inventory_is_safe &&
    openbao_resume_surface_is_safe &&
    openbao_full_server_validation
}

openbao_helm_pod_permission_is() {
  local expected=$1 verb=$2 request_timeout=${3:-5s} output rc
  if output=$(kubectl_run --request-timeout="$request_timeout" \
    --namespace=openbao auth can-i "$verb" pods \
    --as=system:serviceaccount:flux-system:helm-openbao-reconciler \
    2>/dev/null); then
    rc=0
  else
    rc=$?
  fi
  case "$expected" in
    yes) (( rc == 0 )) && [[ "$output" == yes ]] ;;
    no) (( rc == 1 )) && [[ "$output" == no ]] ;;
    *) return 1 ;;
  esac
}

openbao_helm_pod_delegation_is_absent() {
  local verb
  for verb in get list watch create update patch delete deletecollection; do
    openbao_helm_pod_permission_is no "$verb" || return 1
  done
}

openbao_helm_pod_delegation_is_exact() {
  local deadline=${1:-} request_timeout=5s verb
  [[ -z "$deadline" ]] || request_timeout=1s
  for verb in get list watch update patch; do
    [[ -z "$deadline" ]] || (( SECONDS < deadline )) || return 1
    openbao_helm_pod_permission_is yes "$verb" "$request_timeout" || return 1
  done
  for verb in create delete deletecollection; do
    [[ -z "$deadline" ]] || (( SECONDS < deadline )) || return 1
    openbao_helm_pod_permission_is no "$verb" "$request_timeout" || return 1
  done
}

openbao_wait_helm_pod_delegation() {
  local deadline=$((SECONDS + 60))
  while :; do
    openbao_helm_pod_delegation_is_exact "$deadline" && return 0
    (( SECONDS < deadline )) || return 1
    /bin/sleep 1
  done
}

openbao_helm_rbac_upgrade_failure_status_is_exact() {
  local document
  document=$(business_resource_json flux-system \
    helmrelease.helm.toolkit.fluxcd.io openbao) || return 1
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import re
import sys

document = json.load(sys.stdin)
metadata = document.get("metadata", {})
status = document.get("status", {})
generation = metadata.get("generation")
if metadata.get("deletionTimestamp") is not None:
    raise SystemExit(1)
if type(generation) is not int or generation < 1:
    raise SystemExit(1)
if status.get("observedGeneration") != generation:
    raise SystemExit(1)
conditions = status.get("conditions", [])
if type(conditions) is not list or len(conditions) != 3:
    raise SystemExit(1)
by_type = {}
for condition in conditions:
    if type(condition) is not dict:
        raise SystemExit(1)
    condition_type = condition.get("type")
    if condition_type in by_type:
        raise SystemExit(1)
    by_type[condition_type] = condition
expected_conditions = {
    "Ready": ("False", "UpgradeFailed"),
    "Released": ("False", "UpgradeFailed"),
    "Stalled": ("True", "MissingRollbackTarget"),
}
if set(by_type) != set(expected_conditions):
    raise SystemExit(1)
for condition_type, (expected_status, expected_reason) in expected_conditions.items():
    condition = by_type[condition_type]
    if condition.get("status") != expected_status:
        raise SystemExit(1)
    if condition.get("reason") != expected_reason:
        raise SystemExit(1)
    if condition.get("observedGeneration") != generation:
        raise SystemExit(1)
ready_message = str(by_type["Ready"].get("message", ""))
if str(by_type["Released"].get("message", "")) != ready_message:
    raise SystemExit(1)
if str(by_type["Stalled"].get("message", "")) != (
    "Failed to perform remediation: missing target release for rollback: "
    "cannot remediate failed release"
):
    raise SystemExit(1)
pattern = re.compile(
    r"Helm upgrade failed for release openbao/openbao with chart "
    r"openbao@0\.28\.6\+[0-9a-f]{12}: failed to create resource: "
    r"server-side apply failed for object openbao/openbao-discovery-role "
    r"rbac\.authorization\.k8s\.io/v1, Kind=Role: "
    r"roles\.rbac\.authorization\.k8s\.io \"openbao-discovery-role\" "
    r"is forbidden: user \"system:serviceaccount:flux-system:"
    r"helm-openbao-reconciler\" \(groups=\[\"system:serviceaccounts\" "
    r"\"system:serviceaccounts:flux-system\" "
    r"\"system:authenticated\"\]\) is attempting to grant RBAC "
    r"permissions not currently held:\n"
    r"\{APIGroups:\[(?P<api_groups>[^]]*)\], "
    r"Resources:\[(?P<resources>[^]]*)\], "
    r"Verbs:\[(?P<verbs>[^]]*)\]\}"
)
match = pattern.fullmatch(ready_message)
if match is None:
    raise SystemExit(1)

def exact_list(fragment, expected):
    values = re.findall(r"\"([^\"]*)\"", fragment)
    if len(values) != len(expected) or set(values) != expected:
        raise SystemExit(1)
    residue = re.sub(r"\"[^\"]*\"", "", fragment)
    if residue.strip(" ,\t\r\n"):
        raise SystemExit(1)

exact_list(match.group("api_groups"), {""})
exact_list(match.group("resources"), {"pods"})
exact_list(match.group("verbs"), {"get", "list", "watch", "update", "patch"})
  '
}

openbao_helm_rbac_upgrade_failure_is_exact() {
  openbao_helm_rbac_upgrade_failure_status_is_exact &&
    openbao_helm_pod_delegation_is_absent
}

openbao_helm_rbac_retry_failure_is_exact() {
  openbao_helm_rbac_upgrade_failure_status_is_exact &&
    openbao_helm_pod_delegation_is_exact
}

openbao_helm_rbac_recovery_checkpoint_is_exact() {
  openbao_helm_rbac_upgrade_failure_is_exact ||
    openbao_helm_rbac_retry_failure_is_exact
}

openbao_present_recovery_checkpoint_is_safe() {
  local expected_injector expected_server
  expected_server="quay.io/openbao/openbao:2.6.1@${OPENBAO_SERVER_DIGEST}"
  expected_injector="docker.io/hashicorp/vault-k8s:1.7.2@${OPENBAO_INJECTOR_DIGEST}"
  openbao_helm_rbac_recovery_checkpoint_is_exact &&
    business_condition_true openbao certificate.cert-manager.io \
      openbao-transport-ca Ready &&
    business_condition_true openbao certificate.cert-manager.io \
      openbao-server-tls Ready &&
    business_condition_true openbao certificate.cert-manager.io \
      openbao-injector-tls Ready &&
    openbao_workload_is_ready openbao statefulset.apps openbao \
      "$expected_server" &&
    openbao_workload_is_ready openbao deployment.apps \
      openbao-agent-injector "$expected_injector" &&
    openbao_pod_image_id_is_exact \
      'app.kubernetes.io/name=openbao,component=server' \
      "$expected_server" "$OPENBAO_SERVER_DIGEST" &&
    openbao_pod_image_id_is_exact \
      'app.kubernetes.io/name=openbao-agent-injector,component=webhook' \
      "$expected_injector" "$OPENBAO_INJECTOR_DIGEST" &&
    openbao_pvcs_are_exact &&
    openbao_services_are_private &&
    openbao_secret_inventory_is_safe &&
    openbao_state_is_known fresh &&
    openbao_full_server_validation
}

openbao_apply_checkpoint_is_unchanged() {
  local expected=$1 observed
  observed=$(openbao_inventory_state) || return 1
  [[ "$observed" == "$expected" ]] || return 1
  case "$observed" in
    MISSING) return 0 ;;
    RESUMABLE_BOOTSTRAP|RESUMABLE_RETAINED_PVCS)
      openbao_resume_checkpoint_is_safe "$observed"
      ;;
    PRESENT)
      openbao_present_recovery_checkpoint_is_safe
      ;;
    *) return 1 ;;
  esac
}

openbao_apply_namespace() {
  openbao_bootstrap_subset namespace |
    kubectl_run apply --server-side --field-manager="$OPENBAO_FIELD_MANAGER" \
      --filename=- >/dev/null &&
    kubectl_run wait --for=jsonpath='{.status.phase}'=Active \
      namespace/openbao --timeout=2m >/dev/null
}

openbao_apply_bootstrap() {
  openbao_full_server_validation &&
    kubectl_run apply --server-side --field-manager="$OPENBAO_FIELD_MANAGER" \
      --filename="$OPENBAO_BOOTSTRAP_MANIFEST" >/dev/null
}

openbao_apply_runtime() {
  kubectl_run apply --server-side --field-manager="$OPENBAO_FIELD_MANAGER" \
    --filename="$OPENBAO_RUNTIME_MANIFEST" >/dev/null
}

openbao_wait_runtime() {
  business_wait_current_ready flux-system \
    kustomization.kustomize.toolkit.fluxcd.io openbao-runtime 20m &&
    business_wait_current_ready flux-system \
      helmrelease.helm.toolkit.fluxcd.io openbao 15m &&
    business_wait_ready openbao certificate.cert-manager.io \
      openbao-server-tls 10m &&
    business_wait_ready openbao certificate.cert-manager.io \
      openbao-injector-tls 10m &&
    kubectl_run --namespace=openbao wait --for=jsonpath='{.status.phase}'=Bound \
      persistentvolumeclaim/data-openbao-0 \
      persistentvolumeclaim/audit-openbao-0 --timeout=10m >/dev/null &&
    kubectl_run --namespace=openbao rollout status statefulset/openbao \
      --timeout=10m >/dev/null &&
    kubectl_run --namespace=openbao rollout status \
      deployment/openbao-agent-injector --timeout=10m >/dev/null
}

openbao_stage_170_check() {
  local inventory
  openbao_verify_assets ||
    complete STOP_SUPPLY_CHAIN_MISMATCH openbao-asset-drift \
      "$EXIT_SUPPLY_CHAIN" NONE
  openbao_client_dry_run ||
    complete STOP_VERIFY_FAILED client-dry-run-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_capacity_is_safe ||
    complete STOP_PRECONDITION insufficient-openbao-capacity \
      "$EXIT_PRECONDITION" NONE
  if ! business_apps_ready || ! business_https_smoke; then
    complete STOP_PRECONDITION applications-not-ready \
      "$EXIT_PRECONDITION" NONE
  fi
  openbao_flux_source_matches_head ||
    complete STOP_PRECONDITION flux-source-revision-drift \
      "$EXIT_PRECONDITION" NONE
  inventory=$(openbao_inventory_state) ||
    complete STOP_UNKNOWN_STATE inventory-query-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  case "$inventory" in
    MISSING)
      openbao_server_validate_safe_subset ||
        complete STOP_VERIFY_FAILED safe-server-validation-failed \
          "$EXIT_VERIFY_FAILED" NONE
      printf '%s\n' \
        'SERVER_VALIDATION_DEFERRED=namespace-dependent-server-validation-deferred' \
        >&2
      complete PASS_OPENBAO_RUNTIME_CHECK openbao-runtime-activation-required 0 \
        'stages/170-openbao-runtime/run.sh --apply'
      ;;
    RESUMABLE_BOOTSTRAP|RESUMABLE_RETAINED_PVCS)
      openbao_resume_checkpoint_is_safe "$inventory" ||
        complete STOP_VERIFY_FAILED unsafe-openbao-resume-checkpoint \
          "$EXIT_VERIFY_FAILED" NONE
      complete PASS_OPENBAO_RUNTIME_CHECK openbao-runtime-resume-required 0 \
        'stages/170-openbao-runtime/run.sh --apply'
      ;;
    PRESENT)
      if openbao_runtime_is_compliant; then
        openbao_full_server_validation ||
          complete STOP_VERIFY_FAILED full-server-validation-failed \
            "$EXIT_VERIFY_FAILED" NONE
        complete ALREADY_COMPLIANT openbao-runtime-ready 0 NONE
      fi
      openbao_present_recovery_checkpoint_is_safe ||
        complete STOP_UNKNOWN_STATE openbao-runtime-drift \
          "$EXIT_UNKNOWN_STATE" NONE
      complete PASS_OPENBAO_RUNTIME_CHECK \
        openbao-runtime-rbac-recovery-required 0 \
        'stages/170-openbao-runtime/run.sh --apply'
      ;;
    PARTIAL|UNKNOWN)
      complete STOP_UNKNOWN_STATE partial-or-unknown-openbao-inventory \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
    *)
      complete STOP_UNKNOWN_STATE invalid-openbao-inventory-state \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
}

openbao_stage_170_apply() {
  local after_fingerprint before_fingerprint inventory
  openbao_verify_assets ||
    complete STOP_SUPPLY_CHAIN_MISMATCH openbao-asset-drift \
      "$EXIT_SUPPLY_CHAIN" NONE
  openbao_client_dry_run ||
    complete STOP_VERIFY_FAILED client-dry-run-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_capacity_is_safe ||
    complete STOP_PRECONDITION insufficient-openbao-capacity \
      "$EXIT_PRECONDITION" NONE
  inventory=$(openbao_inventory_state) ||
    complete STOP_UNKNOWN_STATE inventory-query-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  case "$inventory" in
    MISSING) ;;
    RESUMABLE_BOOTSTRAP|RESUMABLE_RETAINED_PVCS)
      openbao_resume_checkpoint_is_safe "$inventory" ||
        complete STOP_VERIFY_FAILED unsafe-openbao-resume-checkpoint \
          "$EXIT_VERIFY_FAILED" NONE
      ;;
    PRESENT)
      openbao_present_recovery_checkpoint_is_safe ||
        complete STOP_UNKNOWN_STATE openbao-runtime-drift \
          "$EXIT_UNKNOWN_STATE" NONE
      ;;
    *)
      complete STOP_UNKNOWN_STATE apply-requires-empty-or-approved-checkpoint \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
  if ! business_apps_ready || ! business_https_smoke; then
    complete STOP_PRECONDITION applications-not-ready \
      "$EXIT_PRECONDITION" NONE
  fi
  before_fingerprint=$(openbao_platform_secret_fingerprint) ||
    complete STOP_UNKNOWN_STATE platform-secret-fingerprint-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  openbao_wait_flux_source ||
    complete STOP_UNKNOWN_STATE flux-source-revision-drift \
      "$EXIT_UNKNOWN_STATE" NONE
  openbao_apply_checkpoint_is_unchanged "$inventory" ||
    complete STOP_UNKNOWN_STATE openbao-apply-checkpoint-raced \
      "$EXIT_UNKNOWN_STATE" NONE
  openbao_apply_namespace ||
    complete STOP_APPLY_FAILED namespace-apply-failed "$EXIT_APPLY_FAILED" NONE
  openbao_apply_bootstrap ||
    complete STOP_APPLY_FAILED bootstrap-apply-failed "$EXIT_APPLY_FAILED" NONE
  openbao_wait_helm_pod_delegation ||
    complete STOP_VERIFY_FAILED openbao-rbac-delegation-not-effective \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_apply_runtime ||
    complete STOP_APPLY_FAILED runtime-activation-failed \
      "$EXIT_APPLY_FAILED" NONE
  openbao_wait_runtime ||
    complete STOP_VERIFY_FAILED openbao-runtime-not-ready \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_runtime_is_compliant ||
    complete STOP_VERIFY_FAILED openbao-runtime-readback-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_state_is_known fresh ||
    complete STOP_VERIFY_FAILED unexpected-initialization-state \
      "$EXIT_VERIFY_FAILED" NONE
  after_fingerprint=$(openbao_platform_secret_fingerprint) ||
    complete STOP_UNKNOWN_STATE platform-secret-fingerprint-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  [[ "$after_fingerprint" == "$before_fingerprint" ]] ||
    complete STOP_VERIFY_FAILED platform-secret-drift \
      "$EXIT_VERIFY_FAILED" NONE
  complete PASS_OPENBAO_RUNTIME_INSTALLED openbao-runtime-uninitialized-sealed 0 \
    'stages/180-openbao-initialize/run.sh --check'
}

openbao_stage_main() {
  local required untrusted_environment='' untrusted_name
  for untrusted_name in HELM_NAMESPACE HELM_DRIVER HELM_KUBECONTEXT \
      HELM_CONFIG_HOME HELM_CACHE_HOME HELM_DATA_HOME KUBECTL_EXTERNAL_DIFF; do
    [[ -z "${!untrusted_name+x}" ]] ||
      untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
  done
  for untrusted_name in "${!HELM_@}"; do
    [[ ",${untrusted_environment}," == *",${untrusted_name},"* ]] ||
      untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
  done
  [[ -z "$untrusted_environment" ]] ||
    complete STOP_PRECONDITION untrusted-environment-override \
      "$EXIT_PRECONDITION" NONE
  business_initialize "$@"
  required='df'
  require_command "$required" ||
    complete STOP_PRECONDITION "missing-command-${required}" \
      "$EXIT_PRECONDITION" NONE
  openbao_initialize_paths
  case "$MODE" in
    CHECK) openbao_stage_170_check ;;
    APPLY) openbao_stage_170_apply ;;
    *) complete STOP_PRECONDITION invalid-openbao-mode "$EXIT_PRECONDITION" NONE ;;
  esac
}
