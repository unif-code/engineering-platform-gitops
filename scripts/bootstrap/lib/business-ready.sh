#!/usr/bin/env bash

# Shared fail-closed implementation for stages 110-160. Stage wrappers set PHASE
# and BUSINESS_STAGE before sourcing this file.

business_lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
business_bootstrap_dir=$(cd "${business_lib_dir}/.." && pwd -P)
business_repo_root=$(cd "${business_bootstrap_dir}/../.." && pwd -P)

# shellcheck disable=SC1091
source "${business_lib_dir}/common.sh"
# shellcheck disable=SC1091
source "${business_lib_dir}/path-facts.sh"
# shellcheck disable=SC1091
source "${business_lib_dir}/exec-safety.sh"
# shellcheck disable=SC1091
source "${business_lib_dir}/host-config.sh"
# shellcheck disable=SC1091
source "${business_lib_dir}/admin-conf.sh"
# shellcheck disable=SC1091
source "${business_lib_dir}/kubectl.sh"

readonly BUSINESS_REPO_ROOT=$business_repo_root
readonly BUSINESS_FIELD_MANAGER=engineering-platform-business-ready
readonly BUSINESS_SECRET_COUNT=13
readonly BUSINESS_MIGRATION_JOB=platform-migrate-4aaf721-g2
readonly -a BUSINESS_NAMESPACES=(cert-manager cnpg-system local-path-storage platform)
readonly -a BUSINESS_ROOT_KUSTOMIZATIONS=(
  infrastructure-foundation cert-manager-controller cert-manager-config
  cnpg-controller platform-database platform-migration platform-apps
)
readonly -a BUSINESS_DB_ROLES=(
  platform_owner audit_rw authorization_rw configuration_rw identity_rw
  organization_rw workspace_rw
)
BUSINESS_BASE64_BINARY=
BUSINESS_CURL_BINARY=
BUSINESS_OPENSSL_BINARY=

business_initialize() {
  local required_command untrusted_name untrusted_environment=

  for untrusted_name in APT_CONFIG KUBECONFIG GNUPGHOME CURL_HOME CURL_CA_BUNDLE \
      SSL_CERT_FILE SSL_CERT_DIR XDG_CONFIG_HOME KUBECACHEDIR \
      KUBECTL_EXTERNAL_DIFF TAR_OPTIONS BASH_ENV ENV HTTP_PROXY HTTPS_PROXY \
      ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy; do
    [[ -z "${!untrusted_name+x}" ]] ||
      untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
  done
  for untrusted_name in "${!PYTHON@}" "${!KUBECTL_@}" "${!CURL_@}"; do
    [[ ",${untrusted_environment}," == *",${untrusted_name},"* ]] ||
      untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
  done
  [[ -z "$untrusted_environment" ]] ||
    complete STOP_PRECONDITION untrusted-environment-override "$EXIT_PRECONDITION" NONE

  parse_mode "$@" || exit "$?"
  require_root || complete STOP_PRECONDITION not-root "$EXIT_PRECONDITION" NONE
  for required_command in awk base64 chmod cmp curl date dd dirname git grep head \
      id mktemp openssl python3 rm rmdir sort stat tail wc; do
    require_command "$required_command" ||
      complete STOP_PRECONDITION "missing-command-${required_command}" \
        "$EXIT_PRECONDITION" NONE
  done
  readonly PYTHON_BINARY=/usr/bin/python3
  if [[ ! -x "$PYTHON_BINARY" ]]; then
    required_command=python3
    complete STOP_PRECONDITION "missing-command-${required_command}" \
      "$EXIT_PRECONDITION" NONE
  fi
  load_host_config ||
    complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE

  # shellcheck disable=SC2034
  kubectl_binary=$(host_path /usr/bin/kubectl)
  BUSINESS_BASE64_BINARY=$(host_path /usr/bin/base64)
  BUSINESS_CURL_BINARY=$(host_path /usr/bin/curl)
  BUSINESS_OPENSSL_BINARY=$(host_path /usr/bin/openssl)
  # shellcheck disable=SC2034
  admin_conf=$(host_path /etc/kubernetes/admin.conf)
  if [[ ! -x "$kubectl_binary" ]] || ! safe_file "$kubectl_binary" 755; then
    complete STOP_UNKNOWN_STATE kubectl-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
  fi
  if [[ ! -x "$BUSINESS_BASE64_BINARY" ]] ||
    ! safe_file "$BUSINESS_BASE64_BINARY" 755; then
    complete STOP_UNKNOWN_STATE base64-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
  fi
  if [[ ! -x "$BUSINESS_CURL_BINARY" ]] ||
    ! safe_file "$BUSINESS_CURL_BINARY" 755; then
    complete STOP_UNKNOWN_STATE curl-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
  fi
  if [[ ! -x "$BUSINESS_OPENSSL_BINARY" ]] ||
    ! safe_file "$BUSINESS_OPENSSL_BINARY" 755; then
    complete STOP_UNKNOWN_STATE openssl-provenance-drift "$EXIT_UNKNOWN_STATE" NONE
  fi
  capture_admin_conf ||
    complete STOP_UNKNOWN_STATE admin-conf-content-or-structure-drift \
      "$EXIT_UNKNOWN_STATE" NONE
}

business_resource_json() {
  local namespace=$1 resource=$2 name=$3
  if [[ -n "$namespace" ]]; then
    kubectl_run --namespace="$namespace" get "$resource" "$name" \
      --ignore-not-found --output=json 2>/dev/null
  else
    kubectl_run get "$resource" "$name" --ignore-not-found --output=json 2>/dev/null
  fi
}

business_condition_true() {
  local namespace=$1 resource=$2 name=$3 condition=${4:-Ready} document
  document=$(business_resource_json "$namespace" "$resource" "$name") || return 2
  [[ -n "$document" ]] || return 1
  printf '%s' "$document" | /usr/bin/python3 -c '
import json
import sys

condition = sys.argv[1]
document = json.load(sys.stdin)
metadata = document.get("metadata", {})
status = document.get("status", {})
if metadata.get("deletionTimestamp") is not None:
    raise SystemExit(1)
if status.get("observedGeneration") not in (None, metadata.get("generation")):
    raise SystemExit(1)
for item in status.get("conditions", []):
    if (item.get("type") == condition
            and item.get("status") == "True"
            and item.get("observedGeneration") in (None, metadata.get("generation"))):
        raise SystemExit(0)
raise SystemExit(1)
' "$condition"
}

business_wait_ready() {
  local namespace=$1 resource=$2 name=$3 timeout=${4:-10m}
  if [[ -n "$namespace" ]]; then
    kubectl_run --namespace="$namespace" wait --for=condition=Ready \
      "${resource}/${name}" --timeout="$timeout" >/dev/null 2>&1
  else
    kubectl_run wait --for=condition=Ready "${resource}/${name}" \
      --timeout="$timeout" >/dev/null 2>&1
  fi
}

business_wait_current_ready() {
  local namespace=$1 resource=$2 name=$3 timeout=${4:-10m}
  local document generation
  document=$(business_resource_json "$namespace" "$resource" "$name") || return 2
  [[ -n "$document" ]] || return 1
  generation=$(printf '%s' "$document" | /usr/bin/python3 -c '
import json
import sys

document = json.load(sys.stdin)
generation = document.get("metadata", {}).get("generation")
if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
    raise SystemExit(1)
print(generation)
') || return 2
  if [[ -n "$namespace" ]]; then
    kubectl_run --namespace="$namespace" wait \
      --for="jsonpath={.status.observedGeneration}=${generation}" \
      "${resource}/${name}" --timeout="$timeout" >/dev/null 2>&1 || return 1
  else
    kubectl_run wait \
      --for="jsonpath={.status.observedGeneration}=${generation}" \
      "${resource}/${name}" --timeout="$timeout" >/dev/null 2>&1 || return 1
  fi
  business_wait_ready "$namespace" "$resource" "$name" "$timeout" || return 1
  business_condition_true "$namespace" "$resource" "$name" Ready
}

business_root_inventory_safe() {
  local document
  document=$(business_resource_json flux-system \
    kustomization.kustomize.toolkit.fluxcd.io flux-system) || return 2
  [[ -n "$document" ]] || return 0
  printf '%s' "$document" | /usr/bin/python3 -c '
import json
import sys

document = json.load(sys.stdin)
inventory = document.get("status", {}).get("inventory")
if inventory is None:
    raise SystemExit(0)
if not isinstance(inventory, dict) or not isinstance(inventory.get("entries"), list):
    raise SystemExit(1)
allowed = {
    (f"flux-system_{name}_kustomize.toolkit.fluxcd.io_Kustomization", "v1")
    for name in sys.argv[1:]
}
observed = []
for entry in inventory["entries"]:
    if not isinstance(entry, dict):
        raise SystemExit(1)
    identity = (entry.get("id"), entry.get("v"))
    if identity not in allowed:
        raise SystemExit(1)
    observed.append(identity)
if len(observed) != len(set(observed)):
    raise SystemExit(1)
' "${BUSINESS_ROOT_KUSTOMIZATIONS[@]}"
}

business_namespace_set_state() {
  local name captured observed=
  for name in "${BUSINESS_NAMESPACES[@]}"; do
    captured=$(kubectl_run get namespace "$name" --ignore-not-found \
      --output=name 2>/dev/null) || return 2
    [[ -z "$captured" || "$captured" == "namespace/${name}" ]] || return 2
    [[ -z "$captured" ]] || observed="${observed:+${observed},}${name}"
  done
  if [[ -z "$observed" ]]; then
    printf 'MISSING\n'
  elif [[ "$observed" == 'cert-manager,cnpg-system,local-path-storage,platform' ]]; then
    printf 'COMPLIANT\n'
  else
    printf 'PARTIAL\n'
  fi
}

business_flux_sync_diff() {
  kubectl_run diff --server-side --field-manager="$BUSINESS_FIELD_MANAGER" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/reconcile-rbac.yaml" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/flux-system/phase-b-network-policy.yaml" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/flux-system/gotk-sync.yaml" \
    >/dev/null 2>&1
}

business_stage_110_check() {
  local namespace_state diff_rc=0 inventory_rc=0
  business_root_inventory_safe || inventory_rc=$?
  case "$inventory_rc" in
    0) ;;
    1)
      complete STOP_UNKNOWN_STATE root-sync-inventory-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
    *)
      complete STOP_UNKNOWN_STATE root-sync-inventory-query-failed \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
  namespace_state=$(business_namespace_set_state) ||
    complete STOP_UNKNOWN_STATE namespace-inventory-query-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  if [[ "$namespace_state" != COMPLIANT ]]; then
    complete PASS_FLUX_SYNC_CHECK namespace-and-sync-apply-required 0 \
      'stages/110-flux-sync/run.sh --apply'
  fi
  business_flux_sync_diff || diff_rc=$?
  case "$diff_rc" in
    0) ;;
    1)
      complete PASS_FLUX_SYNC_CHECK sync-apply-required 0 \
        'stages/110-flux-sync/run.sh --apply'
      ;;
    *)
      complete STOP_UNKNOWN_STATE sync-diff-failed "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
  business_condition_true flux-system gitrepository.source.toolkit.fluxcd.io \
    flux-system Ready ||
    complete PASS_FLUX_SYNC_CHECK git-source-wait-required 0 \
      'stages/110-flux-sync/run.sh --apply'
  business_condition_true flux-system \
    kustomization.kustomize.toolkit.fluxcd.io flux-system Ready ||
    complete PASS_FLUX_SYNC_CHECK root-sync-wait-required 0 \
      'stages/110-flux-sync/run.sh --apply'
  complete ALREADY_COMPLIANT public-validated-sync-ready 0 NONE
}

business_render_namespaces() {
  /usr/bin/python3 -c '
import sys
import yaml

for document in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")):
    if isinstance(document, dict) and document.get("kind") == "Namespace":
        yaml.safe_dump(document, sys.stdout, explicit_start=True, sort_keys=False)
' "${BUSINESS_REPO_ROOT}/clusters/dev/reconcile-rbac.yaml"
}

business_stage_110_apply() {
  local namespace_file work_dir inventory_rc=0
  business_root_inventory_safe || inventory_rc=$?
  case "$inventory_rc" in
    0) ;;
    1)
      complete STOP_UNKNOWN_STATE root-sync-inventory-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
    *)
      complete STOP_UNKNOWN_STATE root-sync-inventory-query-failed \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
  work_dir=$(mktemp -d "$(host_path /root)/.business-sync.XXXXXX") ||
    complete STOP_APPLY_FAILED sync-work-directory-create-failed \
      "$EXIT_APPLY_FAILED" NONE
  namespace_file="${work_dir}/namespaces.yaml"
  business_render_namespaces >"$namespace_file" || {
    rm -f -- "$namespace_file"
    rmdir -- "$work_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH namespace-render-failed \
      "$EXIT_SUPPLY_CHAIN" NONE
  }
  chmod 600 "$namespace_file" ||
    complete STOP_APPLY_FAILED namespace-render-mode-failed "$EXIT_APPLY_FAILED" NONE
  kubectl_run apply --server-side --dry-run=server \
    --field-manager="$BUSINESS_FIELD_MANAGER" --filename="$namespace_file" \
    >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED namespace-server-dry-run-failed \
      "$EXIT_VERIFY_FAILED" NONE
  kubectl_run apply --server-side --field-manager="$BUSINESS_FIELD_MANAGER" \
    --filename="$namespace_file" >/dev/null 2>&1 ||
    complete STOP_APPLY_FAILED namespace-apply-failed "$EXIT_APPLY_FAILED" NONE
  rm -f -- "$namespace_file" ||
    complete STOP_UNKNOWN_STATE sync-work-cleanup-failed "$EXIT_UNKNOWN_STATE" NONE
  rmdir -- "$work_dir" ||
    complete STOP_UNKNOWN_STATE sync-work-cleanup-failed "$EXIT_UNKNOWN_STATE" NONE

  kubectl_run apply --server-side --dry-run=server \
    --field-manager="$BUSINESS_FIELD_MANAGER" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/reconcile-rbac.yaml" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/flux-system/phase-b-network-policy.yaml" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/flux-system/gotk-sync.yaml" \
    >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED sync-server-dry-run-failed "$EXIT_VERIFY_FAILED" NONE
  kubectl_run apply --server-side --field-manager="$BUSINESS_FIELD_MANAGER" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/reconcile-rbac.yaml" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/flux-system/phase-b-network-policy.yaml" \
    --filename="${BUSINESS_REPO_ROOT}/clusters/dev/flux-system/gotk-sync.yaml" \
    >/dev/null 2>&1 ||
    complete STOP_APPLY_FAILED sync-apply-failed "$EXIT_APPLY_FAILED" NONE
  business_wait_ready flux-system gitrepository.source.toolkit.fluxcd.io \
    flux-system 5m ||
    complete STOP_VERIFY_FAILED git-source-not-ready "$EXIT_VERIFY_FAILED" NONE
  business_wait_current_ready flux-system \
    kustomization.kustomize.toolkit.fluxcd.io \
    flux-system 10m ||
    complete STOP_VERIFY_FAILED root-sync-not-ready "$EXIT_VERIFY_FAILED" NONE
  complete PASS_FLUX_SYNC_ENABLED public-validated-sync-ready 0 NONE
}

business_core_ready() {
  local name
  for name in infrastructure-foundation cert-manager-controller \
      cert-manager-config cnpg-controller; do
    business_condition_true flux-system kustomization.kustomize.toolkit.fluxcd.io \
      "$name" Ready || return 1
  done
}

business_stage_120_check() {
  business_core_ready &&
    complete ALREADY_COMPLIANT platform-core-ready 0 NONE
  complete PASS_PLATFORM_CORE_CHECK platform-core-wait-required 0 \
    'stages/120-platform-core/run.sh --apply'
}

business_stage_120_apply() {
  local name
  for name in infrastructure-foundation cert-manager-controller \
      cert-manager-config cnpg-controller; do
    business_wait_ready flux-system kustomization.kustomize.toolkit.fluxcd.io \
      "$name" 10m ||
      complete STOP_VERIFY_FAILED "${name}-not-ready" "$EXIT_VERIFY_FAILED" NONE
  done
  complete PASS_PLATFORM_CORE_READY platform-core-ready 0 NONE
}

business_secret_state() {
  local name=$1 type=$2 keys=$3 document
  document=$(business_resource_json platform secret "$name") || return 2
  [[ -n "$document" ]] || { printf 'MISSING\n'; return 0; }
  printf '%s' "$document" | /usr/bin/python3 -c '
import base64
import json
import re
import sys

expected_type = sys.argv[1]
expected_keys = set(sys.argv[2].split(","))
name = sys.argv[3]
document = json.load(sys.stdin)
metadata = document.get("metadata", {})
data = document.get("data")
if (metadata.get("deletionTimestamp") is not None
        or document.get("type") != expected_type
        or not isinstance(data, dict)
        or set(data) != expected_keys
        or any(not isinstance(value, str) or not value for value in data.values())):
    print("UNKNOWN")
    raise SystemExit(0)
try:
    decoded = {
        key: base64.b64decode(value, validate=True)
        for key, value in data.items()
    }
    if expected_type == "kubernetes.io/basic-auth":
        expected_username = (
            "platform_owner" if name == "platform-owner"
            else name.removeprefix("platform-").replace("-", "_")
        ).encode("ascii")
        valid = (
            decoded["username"] == expected_username
            and re.fullmatch(rb"[0-9a-f]{64}", decoded["password"]) is not None
        )
    elif name == "ghcr-pull":
        config = json.loads(decoded[".dockerconfigjson"].decode("utf-8"))
        valid = set(config) == {"auths"} and set(config["auths"]) == {"ghcr.io"}
        auth_entry = config["auths"]["ghcr.io"]
        valid = valid and isinstance(auth_entry, dict) and set(auth_entry) == {"auth"}
        credential = base64.b64decode(auth_entry["auth"], validate=True).decode("utf-8")
        username, separator, token = credential.partition(":")
        valid = valid and separator == ":" and bool(username) and bool(token)
        valid = valid and not any(character.isspace() for character in credential)
    elif name in {"platform-migration-config", "backend-runtime-config"}:
        lines = decoded[".env"].decode("utf-8").splitlines()
        values = dict(line.split("=", 1) for line in lines if "=" in line)
        roles = {
            "DATABASE_URL": "audit_rw",
            "IDENTITY_DATABASE_URL": "identity_rw",
            "ORGANIZATION_DATABASE_URL": "organization_rw",
            "WORKSPACE_DATABASE_URL": "workspace_rw",
            "AUTHORIZATION_DATABASE_URL": "authorization_rw",
            "CONFIGURATION_DATABASE_URL": "configuration_rw",
            "MIGRATION_DATABASE_URL": "platform_owner",
        }
        valid = len(lines) == len(values) == 8 and set(values) == {
            *roles, "SECRET_MATERIAL_PATH"
        }
        valid = valid and values.get("SECRET_MATERIAL_PATH") == (
            "/var/run/secrets/engineering-platform"
        )
        for key, role in roles.items():
            pattern = (
                rf"postgresql\+psycopg://{role}:[0-9a-f]{{64}}"
                r"@platform-rw\.platform\.svc\.cluster\.local:5432/platform"
            )
            valid = valid and re.fullmatch(pattern, values.get(key, "")) is not None
    else:
        valid = len(next(iter(decoded.values()))) == 32
except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
    valid = False
print("COMPLIANT" if valid else "UNKNOWN")
' "$type" "$keys" "$name"
}

business_secret_name_for_role() {
  local role=$1
  if [[ "$role" == platform_owner ]]; then
    printf 'platform-owner\n'
  else
    printf 'platform-%s\n' "${role//_/-}"
  fi
}

business_secret_contracts() {
  local role secret_name
  for role in "${BUSINESS_DB_ROLES[@]}"; do
    secret_name=$(business_secret_name_for_role "$role")
    printf '%s|kubernetes.io/basic-auth|username,password\n' "$secret_name"
  done
  printf '%s\n' \
    'ghcr-pull|kubernetes.io/dockerconfigjson|.dockerconfigjson' \
    'platform-migration-config|Opaque|.env' \
    'backend-runtime-config|Opaque|.env' \
    'backend-password-pepper|Opaque|pepper' \
    'backend-totp-key|Opaque|totp_key' \
    'backend-idempotency-key|Opaque|idempotency_key'
}

business_secret_inventory_state() {
  local name type keys state missing=0 count=0
  while IFS='|' read -r name type keys; do
    count=$((count + 1))
    state=$(business_secret_state "$name" "$type" "$keys") || return 2
    case "$state" in
      COMPLIANT) ;;
      MISSING) missing=$((missing + 1)) ;;
      *) return 3 ;;
    esac
  done < <(business_secret_contracts)
  [[ "$count" == "$BUSINESS_SECRET_COUNT" ]] || return 2
  if (( missing == 0 )); then
    printf 'COMPLIANT\n'
  else
    printf 'MISSING:%s\n' "$missing"
  fi
}

business_create_file_secret() {
  local name=$1 type=$2 key=$3 file=$4
  kubectl_run --namespace=platform create secret generic "$name" \
    --type="$type" --from-file="${key}=${file}" --dry-run=client \
    --output=yaml | kubectl_run --namespace=platform apply --filename=- \
    >/dev/null 2>&1
}

business_create_basic_auth_secret() {
  local name=$1 username_file=$2 password_file=$3
  kubectl_run --namespace=platform create secret generic "$name" \
    --type=kubernetes.io/basic-auth \
    --from-file="username=${username_file}" \
    --from-file="password=${password_file}" --dry-run=client --output=yaml |
    kubectl_run --namespace=platform apply --filename=- >/dev/null 2>&1
}

business_extract_basic_auth_secret() {
  local name=$1 expected_username=$2 username_file=$3 password_file=$4 document
  document=$(business_resource_json platform secret "$name") || return 1
  [[ -n "$document" ]] || return 1
  printf '%s' "$document" | /usr/bin/python3 -c '
import base64
import json
import re
import sys

document = json.load(sys.stdin)
username = base64.b64decode(document["data"]["username"], validate=True)
password = base64.b64decode(document["data"]["password"], validate=True)
if (username.decode("utf-8") != sys.argv[1]
        or re.fullmatch(rb"[0-9a-f]{64}", password) is None):
    raise SystemExit(1)
open(sys.argv[2], "wb").write(username)
open(sys.argv[3], "wb").write(password)
' "$expected_username" "$username_file" "$password_file"
}

business_safe_input_file() {
  local file=$1
  safe_file "$file" 600 && [[ -s "$file" ]]
}

business_stage_130_check() {
  local inventory
  inventory=$(business_secret_inventory_state) || {
    case "$?" in
      3) complete STOP_UNKNOWN_STATE secret-contract-drift "$EXIT_UNKNOWN_STATE" NONE ;;
      *) complete STOP_UNKNOWN_STATE secret-query-failed "$EXIT_UNKNOWN_STATE" NONE ;;
    esac
  }
  if [[ "$inventory" != COMPLIANT ]]; then
    complete PASS_PLATFORM_DATABASE_CHECK secret-generation-required 0 \
      'stages/130-platform-database/run.sh --apply'
  fi
  business_condition_true platform cluster.postgresql.cnpg.io platform Ready ||
    complete PASS_PLATFORM_DATABASE_CHECK database-wait-required 0 \
      'stages/130-platform-database/run.sh --apply'
  complete ALREADY_COMPLIANT platform-database-ready 0 NONE
}

business_stage_130_apply() {
  local config_root username_path token_path work_dir docker_config role
  local secret_name state password_path username_file env_file material inventory key
  inventory=$(business_secret_inventory_state) || {
    case "$?" in
      3) complete STOP_UNKNOWN_STATE secret-contract-drift "$EXIT_UNKNOWN_STATE" NONE ;;
      *) complete STOP_UNKNOWN_STATE secret-query-failed "$EXIT_UNKNOWN_STATE" NONE ;;
    esac
  }
  config_root=$(host_path /root/.config/engineering-platform)
  username_path="${config_root}/ghcr-username"
  token_path="${config_root}/ghcr-read-token"
  if ! business_safe_input_file "$username_path" ||
    ! business_safe_input_file "$token_path"; then
    complete STOP_PRECONDITION registry-credential-missing-or-unsafe \
      "$EXIT_PRECONDITION" NONE
  fi

  work_dir=$(mktemp -d "$(host_path /root)/.platform-secrets.XXXXXX") ||
    complete STOP_APPLY_FAILED secret-work-directory-create-failed \
      "$EXIT_APPLY_FAILED" NONE
  chmod 700 "$work_dir" ||
    complete STOP_APPLY_FAILED secret-work-directory-mode-failed \
      "$EXIT_APPLY_FAILED" NONE
  username_file="${work_dir}/username"
  env_file="${work_dir}/runtime.env"
  : >"$env_file"
  chmod 600 "$env_file"

  for role in "${BUSINESS_DB_ROLES[@]}"; do
    secret_name=$(business_secret_name_for_role "$role")
    password_path="${work_dir}/${role}.password"
    printf '%s' "$role" >"$username_file"
    chmod 600 "$username_file"
    state=$(business_secret_state "$secret_name" kubernetes.io/basic-auth \
      username,password) ||
      complete STOP_UNKNOWN_STATE secret-query-failed "$EXIT_UNKNOWN_STATE" NONE
    case "$state" in
      MISSING)
        "$BUSINESS_OPENSSL_BINARY" rand -hex 32 | head -c 64 >"$password_path" ||
          complete STOP_APPLY_FAILED secret-generation-failed "$EXIT_APPLY_FAILED" NONE
        chmod 600 "$password_path"
        business_create_basic_auth_secret "$secret_name" "$username_file" \
          "$password_path" ||
          complete STOP_APPLY_FAILED secret-create-failed "$EXIT_APPLY_FAILED" NONE
        ;;
      COMPLIANT)
        business_extract_basic_auth_secret "$secret_name" "$role" \
          "$username_file" "$password_path" ||
          complete STOP_UNKNOWN_STATE database-secret-content-invalid \
            "$EXIT_UNKNOWN_STATE" NONE
        chmod 600 "$username_file" "$password_path"
        ;;
      *)
        complete STOP_UNKNOWN_STATE secret-contract-drift "$EXIT_UNKNOWN_STATE" NONE
        ;;
    esac
    case "$role" in
      platform_owner) printf 'MIGRATION_DATABASE_URL=' >>"$env_file" ;;
      audit_rw) printf 'DATABASE_URL=' >>"$env_file" ;;
      identity_rw) printf 'IDENTITY_DATABASE_URL=' >>"$env_file" ;;
      organization_rw) printf 'ORGANIZATION_DATABASE_URL=' >>"$env_file" ;;
      workspace_rw) printf 'WORKSPACE_DATABASE_URL=' >>"$env_file" ;;
      authorization_rw) printf 'AUTHORIZATION_DATABASE_URL=' >>"$env_file" ;;
      configuration_rw) printf 'CONFIGURATION_DATABASE_URL=' >>"$env_file" ;;
    esac
    printf 'postgresql+psycopg://%s:%s@platform-rw.platform.svc.cluster.local:5432/platform\n' \
      "$role" "$(/bin/cat -- "$password_path")" >>"$env_file"
  done
  printf 'SECRET_MATERIAL_PATH=/var/run/secrets/engineering-platform\n' >>"$env_file"

  docker_config="${work_dir}/dockerconfig.json"
  /usr/bin/python3 -c '
import base64
import json
import sys

username = open(sys.argv[1], encoding="utf-8").read().strip()
token = open(sys.argv[2], encoding="utf-8").read().strip()
if not username or not token or any(ch.isspace() for ch in username + token):
    raise SystemExit(1)
auth = base64.b64encode(f"{username}:{token}".encode()).decode("ascii")
with open(sys.argv[3], "w", encoding="utf-8") as stream:
    json.dump({"auths": {"ghcr.io": {"auth": auth}}}, stream, separators=(",", ":"))
' "$username_path" "$token_path" "$docker_config" ||
    complete STOP_PRECONDITION registry-credential-invalid "$EXIT_PRECONDITION" NONE
  chmod 600 "$docker_config"

  state=$(business_secret_state ghcr-pull kubernetes.io/dockerconfigjson \
    .dockerconfigjson) ||
    complete STOP_UNKNOWN_STATE secret-query-failed "$EXIT_UNKNOWN_STATE" NONE
  if [[ "$state" == MISSING ]]; then
    business_create_file_secret ghcr-pull kubernetes.io/dockerconfigjson \
      .dockerconfigjson "$docker_config" ||
      complete STOP_APPLY_FAILED registry-secret-create-failed "$EXIT_APPLY_FAILED" NONE
  elif [[ "$state" != COMPLIANT ]]; then
    complete STOP_UNKNOWN_STATE secret-contract-drift "$EXIT_UNKNOWN_STATE" NONE
  fi
  for secret_name in platform-migration-config backend-runtime-config; do
    state=$(business_secret_state "$secret_name" Opaque .env) ||
      complete STOP_UNKNOWN_STATE secret-query-failed "$EXIT_UNKNOWN_STATE" NONE
    if [[ "$state" == MISSING ]]; then
      business_create_file_secret "$secret_name" Opaque .env "$env_file" ||
        complete STOP_APPLY_FAILED runtime-config-create-failed \
          "$EXIT_APPLY_FAILED" NONE
    elif [[ "$state" != COMPLIANT ]]; then
      complete STOP_UNKNOWN_STATE secret-contract-drift "$EXIT_UNKNOWN_STATE" NONE
    fi
  done

  for material in \
      'backend-password-pepper|pepper' \
      'backend-totp-key|totp_key' \
      'backend-idempotency-key|idempotency_key'; do
    IFS='|' read -r secret_name key <<<"$material"
    state=$(business_secret_state "$secret_name" Opaque "$key") ||
      complete STOP_UNKNOWN_STATE secret-query-failed "$EXIT_UNKNOWN_STATE" NONE
    if [[ "$state" == MISSING ]]; then
      dd if=/dev/urandom of="${work_dir}/${key}" bs=32 count=1 status=none ||
        complete STOP_APPLY_FAILED material-generation-failed "$EXIT_APPLY_FAILED" NONE
      chmod 600 "${work_dir}/${key}"
      business_create_file_secret "$secret_name" Opaque "$key" \
        "${work_dir}/${key}" ||
        complete STOP_APPLY_FAILED material-secret-create-failed \
          "$EXIT_APPLY_FAILED" NONE
    elif [[ "$state" != COMPLIANT ]]; then
      complete STOP_UNKNOWN_STATE secret-contract-drift "$EXIT_UNKNOWN_STATE" NONE
    fi
  done

  rm -f -- "$work_dir"/* ||
    complete STOP_UNKNOWN_STATE secret-work-cleanup-failed "$EXIT_UNKNOWN_STATE" NONE
  rmdir -- "$work_dir" ||
    complete STOP_UNKNOWN_STATE secret-work-cleanup-failed "$EXIT_UNKNOWN_STATE" NONE

  business_wait_ready flux-system kustomization.kustomize.toolkit.fluxcd.io \
    platform-database 15m ||
    complete STOP_VERIFY_FAILED database-kustomization-not-ready \
      "$EXIT_VERIFY_FAILED" NONE
  business_wait_ready platform cluster.postgresql.cnpg.io platform 15m ||
    complete STOP_VERIFY_FAILED database-not-ready "$EXIT_VERIFY_FAILED" NONE
  complete PASS_PLATFORM_DATABASE_READY platform-database-ready 0 NONE
}

business_stage_140_check() {
  if business_condition_true platform job.batch \
    "$BUSINESS_MIGRATION_JOB" Complete; then
    if business_condition_true flux-system \
      kustomization.kustomize.toolkit.fluxcd.io platform-migration Ready ||
      {
        business_wait_current_ready flux-system \
          kustomization.kustomize.toolkit.fluxcd.io platform-migration 1m &&
          business_condition_true platform job.batch \
            "$BUSINESS_MIGRATION_JOB" Complete
      }; then
      complete ALREADY_COMPLIANT platform-migration-complete 0 NONE
    fi
  fi
  complete PASS_PLATFORM_MIGRATION_CHECK migration-wait-required 0 \
    'stages/140-platform-migration/run.sh --apply'
}

business_stage_140_apply() {
  business_wait_ready flux-system kustomization.kustomize.toolkit.fluxcd.io \
    platform-migration 15m ||
    complete STOP_VERIFY_FAILED migration-kustomization-not-ready \
      "$EXIT_VERIFY_FAILED" NONE
  kubectl_run --namespace=platform wait --for=condition=Complete \
    "job/${BUSINESS_MIGRATION_JOB}" --timeout=10m >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED migration-job-failed "$EXIT_VERIFY_FAILED" NONE
  complete PASS_PLATFORM_MIGRATION_COMPLETE platform-migration-complete 0 NONE
}

business_apps_ready() {
  business_condition_true flux-system kustomization.kustomize.toolkit.fluxcd.io \
    platform-apps Ready &&
  business_condition_true platform deployment.apps frontend Available &&
  business_condition_true platform deployment.apps backend Available &&
  business_condition_true platform certificate.cert-manager.io \
    platform-gateway-tls Ready &&
  business_condition_true platform gateway.gateway.networking.k8s.io \
    platform-gateway Programmed
}

business_gateway_address() {
  local document
  document=$(business_resource_json platform gateway.gateway.networking.k8s.io \
    platform-gateway) || return 2
  [[ -n "$document" ]] || return 1
  printf '%s' "$document" | /usr/bin/python3 -c '
import ipaddress
import json
import re
import sys

document = json.load(sys.stdin)
addresses = document.get("status", {}).get("addresses", [])
if len(addresses) != 1 or not isinstance(addresses[0], dict):
    raise SystemExit(1)
address = addresses[0].get("value", "")
address_type = addresses[0].get("type", "IPAddress")
if address_type == "IPAddress":
    try:
        ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError:
        raise SystemExit(1)
elif address_type == "Hostname":
    if (len(address) > 253
            or re.fullmatch(
                r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*"
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                address,
            ) is None):
        raise SystemExit(1)
else:
    raise SystemExit(1)
print(address)
'
}

business_https_smoke() {
  local address ca_file connect_to http_status path
  business_apps_ready || return 1
  address=$(business_gateway_address) || return 1
  connect_to="platform.dev.local:443:${address}:443"
  ca_file=$(mktemp "$(host_path /root)/.platform-gateway-ca.XXXXXX") || return 1
  chmod 600 "$ca_file" || { rm -f -- "$ca_file"; return 1; }
  kubectl_run --namespace=platform get secret platform-gateway-tls \
    --output='jsonpath={.data.tls\.crt}' 2>/dev/null |
    "$BUSINESS_BASE64_BINARY" --decode >"$ca_file" || {
      rm -f -- "$ca_file"
      return 1
    }
  if [[ ! -s "$ca_file" ]] ||
    ! "$BUSINESS_OPENSSL_BINARY" x509 -in "$ca_file" -noout \
      -checkhost platform.dev.local >/dev/null 2>&1; then
    rm -f -- "$ca_file"
    return 1
  fi
  for path in / /healthz /readyz; do
    "$BUSINESS_CURL_BINARY" --disable --fail --silent --show-error \
      --max-time 10 --proto '=https' --tlsv1.2 --cacert "$ca_file" \
      --connect-to "$connect_to" "https://platform.dev.local${path}" \
      >/dev/null 2>&1 || {
        rm -f -- "$ca_file"
        return 1
      }
  done
  http_status=$("$BUSINESS_CURL_BINARY" --disable --silent --show-error \
    --max-time 10 --proto '=https' --tlsv1.2 --cacert "$ca_file" \
    --connect-to "$connect_to" --output /dev/null --write-out '%{http_code}' \
    https://platform.dev.local/api/v1/me 2>/dev/null) || {
      rm -f -- "$ca_file"
      return 1
    }
  rm -f -- "$ca_file" || return 1
  [[ "$http_status" == 401 ]]
}

business_stage_150_check() {
  business_apps_ready ||
    complete PASS_PLATFORM_APPS_CHECK application-wait-required 0 \
      'stages/150-platform-apps/run.sh --apply'
  business_https_smoke ||
    complete PASS_PLATFORM_APPS_CHECK https-smoke-required 0 \
      'stages/150-platform-apps/run.sh --apply'
  complete ALREADY_COMPLIANT platform-apps-and-smoke-ready 0 NONE
}

business_stage_150_apply() {
  business_wait_ready flux-system kustomization.kustomize.toolkit.fluxcd.io \
    platform-apps 15m ||
    complete STOP_VERIFY_FAILED apps-kustomization-not-ready "$EXIT_VERIFY_FAILED" NONE
  kubectl_run --namespace=platform rollout status deployment/frontend \
    --timeout=10m >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED frontend-not-ready "$EXIT_VERIFY_FAILED" NONE
  kubectl_run --namespace=platform rollout status deployment/backend \
    --timeout=10m >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED backend-not-ready "$EXIT_VERIFY_FAILED" NONE
  business_wait_ready platform certificate.cert-manager.io \
    platform-gateway-tls 10m ||
    complete STOP_VERIFY_FAILED certificate-not-ready "$EXIT_VERIFY_FAILED" NONE
  kubectl_run --namespace=platform wait --for=condition=Programmed \
    gateway/platform-gateway --timeout=10m >/dev/null 2>&1 ||
    complete STOP_VERIFY_FAILED gateway-not-programmed "$EXIT_VERIFY_FAILED" NONE
  business_https_smoke ||
    complete STOP_VERIFY_FAILED https-smoke-failed "$EXIT_VERIFY_FAILED" NONE
  complete PASS_PLATFORM_APPS_READY platform-apps-and-smoke-ready 0 NONE
}

business_existing_evidence() {
  local candidate sidecar digest recorded recorded_name
  for candidate in "$(host_path /root/dev-infra-evidence)"/16-business-ready-*.txt; do
    safe_file "$candidate" 600 || continue
    grep -Fx "GIT_COMMIT=$(git -C "$BUSINESS_REPO_ROOT" rev-parse HEAD)" \
      "$candidate" >/dev/null 2>&1 || continue
    sidecar="${candidate}.sha256"
    safe_file "$sidecar" 600 || continue
    digest=$(sha256_file "$candidate") || continue
    recorded=$(awk 'NR==1 {print $1}' "$sidecar")
    recorded_name=$(awk 'NR==1 {print $2}' "$sidecar")
    [[ "$recorded" == "$digest" && "$recorded_name" == "${candidate##*/}" ]] ||
      continue
    [[ "$(wc -l <"$sidecar")" == 1 ]] || continue
    printf '%s\n' "$candidate"
    return 0
  done
  return 1
}

business_stage_160_check() {
  business_apps_ready ||
    complete STOP_PRECONDITION applications-not-ready "$EXIT_PRECONDITION" NONE
  business_https_smoke ||
    complete STOP_VERIFY_FAILED https-smoke-failed "$EXIT_VERIFY_FAILED" NONE
  if business_existing_evidence >/dev/null; then
    complete ALREADY_COMPLIANT business-ready-evidence-exists 0 NONE
  fi
  complete PASS_BUSINESS_READY_EVIDENCE_CHECK evidence-capture-required 0 \
    'stages/160-business-ready-evidence/run.sh --apply'
}

business_stage_160_apply() {
  local evidence_dir digest sidecar git_commit secret_count
  evidence_dir=$(host_path /root/dev-infra-evidence)
  business_apps_ready ||
    complete STOP_PRECONDITION applications-not-ready "$EXIT_PRECONDITION" NONE
  business_https_smoke ||
    complete STOP_VERIFY_FAILED https-smoke-failed "$EXIT_VERIFY_FAILED" NONE
  git_commit=$(git -C "$BUSINESS_REPO_ROOT" rev-parse HEAD) ||
    complete STOP_UNKNOWN_STATE git-commit-unreadable "$EXIT_UNKNOWN_STATE" NONE
  secret_count=$(kubectl_run --namespace=platform get secret \
    --output=name 2>/dev/null | wc -l | awk '{print $1}') ||
    complete STOP_UNKNOWN_STATE secret-metadata-query-failed "$EXIT_UNKNOWN_STATE" NONE
  open_evidence 16-business-ready "$evidence_dir" ||
    complete STOP_UNKNOWN_STATE evidence-open-failed "$EXIT_UNKNOWN_STATE" NONE
  log_evidence "GIT_COMMIT=${git_commit}"
  log_evidence 'FLUX_CONTROLLERS=source,kustomize,helm,notification'
  log_evidence 'GIT_SYNC=PUBLIC_VALIDATED_READY'
  log_evidence 'CERT_MANAGER=READY'
  log_evidence 'CNPG_OPERATOR=READY'
  log_evidence 'POSTGRES_INSTANCES=1'
  log_evidence 'POSTGRES_BACKUP=NOT_EXECUTED'
  log_evidence "MIGRATION=${BUSINESS_MIGRATION_JOB}-complete"
  log_evidence 'FRONTEND=READY'
  log_evidence 'BACKEND=READY'
  log_evidence 'HTTPS_SMOKE=PASS'
  log_evidence "PLATFORM_SECRET_METADATA_COUNT=${secret_count}"
  log_evidence 'SECRET_VALUES=NOT_RECORDED'
  log_evidence 'OPENBAO=NOT_EXECUTED'
  log_evidence 'MINIO=NOT_EXECUTED'
  log_evidence 'BACKUPS=NOT_EXECUTED'
  log_evidence 'RESTORE=NOT_EXECUTED'
  log_evidence 'OBSERVABILITY=NOT_EXECUTED'
  finish_phase PASS_BUSINESS_READY business-ready 0 NONE || exit "$?"
  digest=$(sha256_file "$EVIDENCE_FILE") || exit "$EXIT_UNKNOWN_STATE"
  sidecar="${EVIDENCE_FILE}.sha256"
  (umask 077; set -o noclobber; printf '%s  %s\n' \
    "$digest" "${EVIDENCE_FILE##*/}" >"$sidecar") || exit "$EXIT_UNKNOWN_STATE"
  chmod 600 "$sidecar" || exit "$EXIT_APPLY_FAILED"
  printf 'SHA256_FILE=%s\n' "$sidecar"
  exit 0
}

business_stage_main() {
  business_initialize "$@"
  case "${BUSINESS_STAGE}:${MODE}" in
    110:CHECK) business_stage_110_check ;;
    110:APPLY) business_stage_110_apply ;;
    120:CHECK) business_stage_120_check ;;
    120:APPLY) business_stage_120_apply ;;
    130:CHECK) business_stage_130_check ;;
    130:APPLY) business_stage_130_apply ;;
    140:CHECK) business_stage_140_check ;;
    140:APPLY) business_stage_140_apply ;;
    150:CHECK) business_stage_150_check ;;
    150:APPLY) business_stage_150_apply ;;
    160:CHECK) business_stage_160_check ;;
    160:APPLY) business_stage_160_apply ;;
    *) complete STOP_PRECONDITION invalid-business-stage "$EXIT_PRECONDITION" NONE ;;
  esac
}
