#!/usr/bin/env bash

openbao_initialize_lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${openbao_initialize_lib_dir}/openbao-runtime.sh"

readonly OPENBAO_RECOVERY_HELPER=${openbao_initialize_lib_dir}/openbao_recovery.py
readonly OPENBAO_DOCS_COMMIT=0039d697237eb3f3a4a6238f47d4b971974a031e
readonly OPENBAO_DOCS_BASELINE=2026-08-28.2
readonly OPENBAO_DEVIATION=DEV-005
readonly OPENBAO_PROBE_VALUE=stage180-probe
readonly OPENBAO_REASON_SOURCE_REQUIRED=source-recovery-sha-required
readonly OPENBAO_REASON_SOURCE_INVALID=source-recovery-sha-invalid
readonly OPENBAO_REASON_SOURCE_UNSAFE=source-recovery-bundle-unsafe

OPENBAO_OPERATION=CHECK
OPENBAO_SOURCE_RECOVERY_SHA=
OPENBAO_CONFIG_ROOT=
OPENBAO_PUBLIC_KEY=
OPENBAO_PUBLIC_KEY_FINGERPRINT=
OPENBAO_RECOVERY_ROOT=
OPENBAO_RECOVERY_ID=
OPENBAO_RECOVERY_DIRECTORY=
OPENBAO_RECOVERY_ARCHIVE=
OPENBAO_RECOVERY_SIDECAR=
OPENBAO_SOURCE_RECOVERY_ARCHIVE=
OPENBAO_SOURCE_RECOVERY_SIDECAR=
OPENBAO_ROTATION_CANDIDATE_DIRECTORY=
OPENBAO_ROTATION_CANDIDATE_ARCHIVE=
OPENBAO_ROTATION_CANDIDATE_SIDECAR=
OPENBAO_ROTATION_VERIFIED_MARKER=
OPENBAO_SECRET_INPUT=
OPENBAO_REMOTE_HOME=
OPENBAO_REMOTE_SESSION_KIND=

safe_owned_directory() {
  local path=$1 expected_uid=$2
  [[ "$expected_uid" == 0 ]] && safe_directory "$path" 700
}

openbao_parse_operation() {
  local source_sha
  OPENBAO_SOURCE_RECOVERY_SHA=
  case "$#" in
    0) OPENBAO_OPERATION=CHECK ;;
    1)
      case "$1" in
        --check) OPENBAO_OPERATION=CHECK ;;
        --initialize) OPENBAO_OPERATION=INITIALIZE ;;
        --configure) OPENBAO_OPERATION=CONFIGURE ;;
        --accept) OPENBAO_OPERATION=ACCEPT ;;
        *) return "$EXIT_PRECONDITION" ;;
      esac
      ;;
    2)
      [[ "$2" == --source-recovery-sha=* ]] || return "$EXIT_PRECONDITION"
      source_sha=${2#--source-recovery-sha=}
      [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return "$EXIT_PRECONDITION"
      case "$1" in
        --check) OPENBAO_OPERATION=CHECK ;;
        --recover-start) OPENBAO_OPERATION=RECOVER_START ;;
        --recover-verify) OPENBAO_OPERATION=RECOVER_VERIFY ;;
        *) return "$EXIT_PRECONDITION" ;;
      esac
      # shellcheck disable=SC2034
      # The checked recovery provenance remains available to the stage operation.
      OPENBAO_SOURCE_RECOVERY_SHA=$source_sha
      ;;
    *) return "$EXIT_PRECONDITION" ;;
  esac
}

openbao_initialize_ceremony_paths() {
  local commit
  commit=$(git -C "$OPENBAO_REPO_ROOT" rev-parse HEAD) || return 1
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || return 1
  OPENBAO_CONFIG_ROOT=$(host_path /root/.config/engineering-platform)
  OPENBAO_PUBLIC_KEY=${OPENBAO_CONFIG_ROOT}/openbao-recovery-public-key.b64
  OPENBAO_PUBLIC_KEY_FINGERPRINT=${OPENBAO_CONFIG_ROOT}/openbao-recovery-public-key.fingerprint
  OPENBAO_RECOVERY_ROOT=$(host_path /root/openbao-recovery)
  OPENBAO_RECOVERY_ID=$commit
  OPENBAO_RECOVERY_DIRECTORY=${OPENBAO_RECOVERY_ROOT}/openbao-recovery-${commit}
  OPENBAO_RECOVERY_ARCHIVE=${OPENBAO_RECOVERY_ROOT}/openbao-recovery-${commit}.tar.gz
  OPENBAO_RECOVERY_SIDECAR=${OPENBAO_RECOVERY_ARCHIVE}.sha256
  openbao_rotation_artifact_paths
}

openbao_rotation_artifact_paths() {
  [[ "$OPENBAO_RECOVERY_ID" =~ ^[0-9a-f]{40}$ ]] || return 1
  OPENBAO_ROTATION_CANDIDATE_DIRECTORY=${OPENBAO_RECOVERY_ROOT}/openbao-recovery-rotation-candidate-${OPENBAO_RECOVERY_ID}
  OPENBAO_ROTATION_CANDIDATE_ARCHIVE=${OPENBAO_ROTATION_CANDIDATE_DIRECTORY}.tar.gz
  OPENBAO_ROTATION_CANDIDATE_SIDECAR=${OPENBAO_ROTATION_CANDIDATE_ARCHIVE}.sha256
  OPENBAO_RECOVERY_DIRECTORY=${OPENBAO_RECOVERY_ROOT}/openbao-recovery-${OPENBAO_RECOVERY_ID}
  OPENBAO_RECOVERY_ARCHIVE=${OPENBAO_RECOVERY_DIRECTORY}.tar.gz
  OPENBAO_RECOVERY_SIDECAR=${OPENBAO_RECOVERY_ARCHIVE}.sha256
  OPENBAO_ROTATION_VERIFIED_MARKER=${OPENBAO_RECOVERY_ROOT}/openbao-rotation-${OPENBAO_RECOVERY_ID}.verified.json
}

openbao_rotation_artifact_presence_state() {
  local candidate_count=0 final_count=0 marker=false path
  for path in "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" \
      "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
      "$OPENBAO_ROTATION_CANDIDATE_SIDECAR"; do
    [[ -e "$path" || -L "$path" ]] && ((candidate_count += 1))
  done
  for path in "$OPENBAO_RECOVERY_DIRECTORY" "$OPENBAO_RECOVERY_ARCHIVE" \
      "$OPENBAO_RECOVERY_SIDECAR"; do
    [[ -e "$path" || -L "$path" ]] && ((final_count += 1))
  done
  [[ -e "$OPENBAO_ROTATION_VERIFIED_MARKER" || \
     -L "$OPENBAO_ROTATION_VERIFIED_MARKER" ]] && marker=true
  if (( candidate_count == 0 && final_count == 0 )) && \
      [[ "$marker" == false ]]; then
    printf 'MISSING\n'
  elif (( candidate_count == 3 && final_count == 0 )) && \
      [[ "$marker" == false ]]; then
    printf 'CANDIDATE\n'
  elif (( candidate_count == 3 && final_count == 3 )) && \
      [[ "$marker" == false ]]; then
    printf 'FINAL\n'
  elif (( candidate_count == 3 && final_count == 3 )) && \
      [[ "$marker" == true ]]; then
    printf 'VERIFIED\n'
  else
    printf 'UNSAFE\n'
  fi
}

openbao_public_key_is_valid() {
  safe_file "$OPENBAO_PUBLIC_KEY" 600 &&
    safe_file "$OPENBAO_PUBLIC_KEY_FINGERPRINT" 600 &&
    "$PYTHON_BINARY" -I -B - "$OPENBAO_PUBLIC_KEY" \
      "$OPENBAO_PUBLIC_KEY_FINGERPRINT" <<'PY'
import base64
import re
import sys

key_path, fingerprint_path = sys.argv[1:]
encoded = open(key_path, encoding="ascii").read().strip()
fingerprint = open(fingerprint_path, encoding="ascii").read().strip()
if not encoded or any(character.isspace() for character in encoded):
    raise SystemExit(1)
try:
    public_key = base64.b64decode(encoded, validate=True)
except Exception:
    raise SystemExit(1)
if not 128 <= len(public_key) <= 16384:
    raise SystemExit(1)
if re.fullmatch(r"[0-9A-F]{40}|[0-9A-F]{64}", fingerprint) is None:
    raise SystemExit(1)
PY
}

openbao_recovery_root_is_safe() {
  safe_owned_directory "$OPENBAO_RECOVERY_ROOT" 0
}

openbao_source_recovery_sha_is_valid() {
  local source=$OPENBAO_SOURCE_RECOVERY_SHA
  [[ "$source" =~ ^[0-9a-f]{40}$ ]] || return 1
  git -C "$OPENBAO_REPO_ROOT" cat-file -e "${source}^{commit}" 2>/dev/null ||
    return 1
  git -C "$OPENBAO_REPO_ROOT" merge-base --is-ancestor \
    "$source" "$OPENBAO_RECOVERY_ID" 2>/dev/null
}

openbao_source_recovery_paths() {
  local source=$OPENBAO_SOURCE_RECOVERY_SHA
  [[ "$source" =~ ^[0-9a-f]{40}$ ]] || return 1
  OPENBAO_SOURCE_RECOVERY_ARCHIVE=${OPENBAO_RECOVERY_ROOT}/openbao-recovery-${source}.tar.gz
  OPENBAO_SOURCE_RECOVERY_SIDECAR=${OPENBAO_SOURCE_RECOVERY_ARCHIVE}.sha256
}

openbao_source_recovery_bundle_is_valid() {
  local fingerprint platform_fingerprint public_key_sha
  openbao_source_recovery_sha_is_valid || return 1
  openbao_source_recovery_paths || return 1
  openbao_recovery_root_is_safe || return 1
  safe_file "$OPENBAO_RECOVERY_HELPER" 644 || return 1
  safe_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE" 600 || return 1
  safe_file "$OPENBAO_SOURCE_RECOVERY_SIDECAR" 600 || return 1
  safe_file "$OPENBAO_PUBLIC_KEY" 600 || return 1
  safe_file "$OPENBAO_PUBLIC_KEY_FINGERPRINT" 600 || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  platform_fingerprint=$(openbao_platform_secret_fingerprint) || return 1
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" validate-source \
    "$OPENBAO_SOURCE_RECOVERY_ARCHIVE" "$OPENBAO_SOURCE_RECOVERY_SIDECAR" \
    "$OPENBAO_SOURCE_RECOVERY_SHA" "$OPENBAO_DOCS_COMMIT" \
    "$OPENBAO_DOCS_BASELINE" "$OPENBAO_DEVIATION" "$public_key_sha" \
    "$fingerprint" "$platform_fingerprint"
}

openbao_cluster_identity_sha256() {
  local cluster_id=$1 cluster_name=$2
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" \
    cluster-identity-sha256 --cluster-id "$cluster_id" \
    --cluster-name "$cluster_name"
}

openbao_rotation_candidate_is_valid() {
  local cluster_digest=$1 fingerprint public_key_sha source_digest
  openbao_rotation_artifact_paths || return 1
  openbao_source_recovery_bundle_is_valid || return 1
  safe_owned_directory "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" 0 || return 1
  safe_file "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" 600 || return 1
  safe_file "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" 600 || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" validate-candidate \
    --archive "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
    --sidecar "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key-sha256 "$public_key_sha" \
    --public-key-fingerprint "$fingerprint" \
    --cluster-identity-sha256 "$cluster_digest"
}

openbao_build_rotation_candidate() {
  local response=$1 response_kind=$2 cluster_id=$3 cluster_name=$4
  local verification_nonce=${5:-} cluster_digest source_digest
  local -a nonce_arguments=()
  openbao_rotation_artifact_paths || return 1
  openbao_source_recovery_bundle_is_valid || return 1
  safe_file "$response" 600 || return 1
  cluster_digest=$(
    openbao_cluster_identity_sha256 "$cluster_id" "$cluster_name"
  ) || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  if [[ -n "$verification_nonce" ]]; then
    nonce_arguments=(--verification-nonce "$verification_nonce")
  fi
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" build-candidate \
    --response "$response" --response-kind "$response_kind" \
    "${nonce_arguments[@]}" \
    --archive "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
    --sidecar "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key "$OPENBAO_PUBLIC_KEY" \
    --public-key-fingerprint-file "$OPENBAO_PUBLIC_KEY_FINGERPRINT" \
    --cluster-id "$cluster_id" --cluster-name "$cluster_name" \
    --key-shares 5 --key-threshold 3 || return 1
  openbao_rotation_candidate_is_valid "$cluster_digest"
}

openbao_rotation_final_is_valid() {
  local cluster_digest=$1 fingerprint public_key_sha source_digest
  openbao_rotation_artifact_paths || return 1
  openbao_source_recovery_bundle_is_valid || return 1
  safe_owned_directory "$OPENBAO_RECOVERY_DIRECTORY" 0 || return 1
  safe_file "$OPENBAO_RECOVERY_ARCHIVE" 600 || return 1
  safe_file "$OPENBAO_RECOVERY_SIDECAR" 600 || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" validate-final \
    --archive "$OPENBAO_RECOVERY_ARCHIVE" \
    --sidecar "$OPENBAO_RECOVERY_SIDECAR" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key-sha256 "$public_key_sha" \
    --public-key-fingerprint "$fingerprint" \
    --cluster-identity-sha256 "$cluster_digest"
}

openbao_build_rotation_final() {
  local cluster_digest=$1 verified_at_utc=$2 fingerprint public_key_sha
  local source_digest
  openbao_rotation_artifact_paths || return 1
  openbao_rotation_candidate_is_valid "$cluster_digest" || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" build-final \
    --candidate-archive "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
    --candidate-sidecar "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
    --archive "$OPENBAO_RECOVERY_ARCHIVE" \
    --sidecar "$OPENBAO_RECOVERY_SIDECAR" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key-sha256 "$public_key_sha" \
    --public-key-fingerprint "$fingerprint" \
    --cluster-identity-sha256 "$cluster_digest" \
    --verified-at-utc "$verified_at_utc" || return 1
  openbao_rotation_final_is_valid "$cluster_digest"
}

openbao_state_flags() {
  openbao_status_json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

document = json.load(sys.stdin)
initialized = document.get("initialized")
sealed = document.get("sealed")
if not isinstance(initialized, bool) or not isinstance(sealed, bool):
    raise SystemExit(1)
print(f"{str(initialized).lower()}|{str(sealed).lower()}")
'
}

openbao_recovery_metadata_value() {
  local field=$1
  "$PYTHON_BINARY" -I -B -c '
import json
import sys

field = sys.argv[1]
value = json.load(open(sys.argv[2], encoding="utf-8")).get(field)
if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
    raise SystemExit(1)
print(value)
' "$field" "${OPENBAO_RECOVERY_DIRECTORY}/metadata.json"
}

openbao_init_ciphertext_is_valid() {
  local file=$1
  safe_file "$file" 600 &&
    "$PYTHON_BINARY" -I -B - "$file" <<'PY'
import base64
import json
import re
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
if document.get("unseal_shares") != 5 or document.get("unseal_threshold") != 3:
    raise SystemExit(1)
keys = document.get("unseal_keys_b64")
root_token = document.get("root_token")
if not isinstance(keys, list) or len(keys) != 5 or not isinstance(root_token, str):
    raise SystemExit(1)
for value in [*keys, root_token]:
    if not isinstance(value, str) or len(value) < 100:
        raise SystemExit(1)
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:
        raise SystemExit(1)
    if len(decoded) < 64:
        raise SystemExit(1)
serialized = json.dumps(document, separators=(",", ":"))
if re.search(r'(?i)(?:hvs|hvb|hvr|s)\.[A-Za-z0-9_-]{8,}', serialized):
    raise SystemExit(1)
PY
}

openbao_recovery_directory_is_valid() {
  local commit fingerprint key_sha metadata init_file public_copy fingerprint_copy
  metadata=${OPENBAO_RECOVERY_DIRECTORY}/metadata.json
  init_file=${OPENBAO_RECOVERY_DIRECTORY}/init.json
  public_copy=${OPENBAO_RECOVERY_DIRECTORY}/openbao-recovery-public-key.b64
  fingerprint_copy=${OPENBAO_RECOVERY_DIRECTORY}/openbao-recovery-public-key.fingerprint
  safe_owned_directory "$OPENBAO_RECOVERY_DIRECTORY" 0 || return 1
  safe_file "$metadata" 600 || return 1
  safe_file "$public_copy" 600 || return 1
  safe_file "$fingerprint_copy" 600 || return 1
  openbao_init_ciphertext_is_valid "$init_file" || return 1
  cmp -s "$OPENBAO_PUBLIC_KEY" "$public_copy" || return 1
  cmp -s "$OPENBAO_PUBLIC_KEY_FINGERPRINT" "$fingerprint_copy" || return 1
  commit=$(openbao_recovery_metadata_value git_commit) || return 1
  fingerprint=$(openbao_recovery_metadata_value public_key_fingerprint) || return 1
  key_sha=$(openbao_recovery_metadata_value public_key_sha256) || return 1
  [[ "$commit" == "$OPENBAO_RECOVERY_ID" ]] || return 1
  [[ "$fingerprint" == "$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT")" ]] || return 1
  [[ "$key_sha" == "$(sha256_file "$OPENBAO_PUBLIC_KEY")" ]] || return 1
  [[ "$(openbao_recovery_metadata_value docs_commit)" == "$OPENBAO_DOCS_COMMIT" ]] ||
    return 1
  [[ "$(openbao_recovery_metadata_value docs_baseline)" == "$OPENBAO_DOCS_BASELINE" ]] ||
    return 1
  [[ "$(openbao_recovery_metadata_value deviation)" == "$OPENBAO_DEVIATION" ]]
}

openbao_recovery_bundle_is_valid() {
  local digest recorded recorded_name
  openbao_recovery_directory_is_valid || return 1
  safe_file "$OPENBAO_RECOVERY_ARCHIVE" 600 || return 1
  safe_file "$OPENBAO_RECOVERY_SIDECAR" 600 || return 1
  digest=$(sha256_file "$OPENBAO_RECOVERY_ARCHIVE") || return 1
  recorded=$(awk 'NR==1 {print $1}' "$OPENBAO_RECOVERY_SIDECAR")
  recorded_name=$(awk 'NR==1 {print $2}' "$OPENBAO_RECOVERY_SIDECAR")
  [[ "$recorded" == "$digest" ]] || return 1
  [[ "$recorded_name" == "${OPENBAO_RECOVERY_ARCHIVE##*/}" ]] || return 1
  [[ "$(wc -l <"$OPENBAO_RECOVERY_SIDECAR")" == 1 ]] || return 1
  tar_safe -tzf "$OPENBAO_RECOVERY_ARCHIVE" |
    "$PYTHON_BINARY" -I -B -c '
import sys

prefix = sys.argv[1].rstrip("/") + "/"
expected = {
    prefix,
    prefix + "init.json",
    prefix + "metadata.json",
    prefix + "openbao-recovery-public-key.b64",
    prefix + "openbao-recovery-public-key.fingerprint",
}
observed = {line.strip() for line in sys.stdin if line.strip()}
if observed != expected:
    raise SystemExit(1)
' "${OPENBAO_RECOVERY_DIRECTORY##*/}"
}

openbao_recovery_state() {
  local directory_exists=false archive_exists=false sidecar_exists=false
  [[ -e "$OPENBAO_RECOVERY_DIRECTORY" || -L "$OPENBAO_RECOVERY_DIRECTORY" ]] &&
    directory_exists=true
  [[ -e "$OPENBAO_RECOVERY_ARCHIVE" || -L "$OPENBAO_RECOVERY_ARCHIVE" ]] &&
    archive_exists=true
  [[ -e "$OPENBAO_RECOVERY_SIDECAR" || -L "$OPENBAO_RECOVERY_SIDECAR" ]] &&
    sidecar_exists=true
  if [[ "$directory_exists" == false && "$archive_exists" == false &&
        "$sidecar_exists" == false ]]; then
    printf 'MISSING\n'
  elif openbao_recovery_bundle_is_valid; then
    printf 'COMPLIANT\n'
  elif [[ "$directory_exists" == true && "$archive_exists" == false &&
          "$sidecar_exists" == false ]] && openbao_recovery_directory_is_valid; then
    printf 'DIRECTORY_READY\n'
  else
    printf 'UNSAFE\n'
  fi
}

openbao_write_recovery_metadata() {
  local destination=$1 platform_fingerprint=$2 public_key_sha fingerprint
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  "$PYTHON_BINARY" -I -B - "$destination" "$OPENBAO_RECOVERY_ID" \
    "$public_key_sha" "$fingerprint" "$platform_fingerprint" \
    "$OPENBAO_DOCS_COMMIT" "$OPENBAO_DOCS_BASELINE" "$OPENBAO_DEVIATION" <<'PY'
import json
import os
import sys

(
    destination,
    git_commit,
    public_key_sha256,
    public_key_fingerprint,
    platform_secret_fingerprint,
    docs_commit,
    docs_baseline,
    deviation,
) = sys.argv[1:]
document = {
    "schema": "engineering-platform/openbao-recovery/v1",
    "git_commit": git_commit,
    "docs_commit": docs_commit,
    "docs_baseline": docs_baseline,
    "deviation": deviation,
    "public_key_sha256": public_key_sha256,
    "public_key_fingerprint": public_key_fingerprint,
    "platform_secret_fingerprint": platform_secret_fingerprint,
    "key_shares": 5,
    "key_threshold": 3,
    "plaintext_recovery_material": "NOT_RECORDED",
}
descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
    json.dump(document, stream, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    stream.write("\n")
PY
}

openbao_finalize_recovery_bundle() {
  local digest
  openbao_recovery_directory_is_valid || return 1
  [[ ! -e "$OPENBAO_RECOVERY_ARCHIVE" && ! -L "$OPENBAO_RECOVERY_ARCHIVE" ]] ||
    return 1
  [[ ! -e "$OPENBAO_RECOVERY_SIDECAR" && ! -L "$OPENBAO_RECOVERY_SIDECAR" ]] ||
    return 1
  (umask 077; set -o noclobber; tar_safe -C "$OPENBAO_RECOVERY_ROOT" -czf - \
    "${OPENBAO_RECOVERY_DIRECTORY##*/}" >"$OPENBAO_RECOVERY_ARCHIVE") || return 1
  chmod 600 "$OPENBAO_RECOVERY_ARCHIVE" || return 1
  digest=$(sha256_file "$OPENBAO_RECOVERY_ARCHIVE") || return 1
  (umask 077; set -o noclobber; printf '%s  %s\n' "$digest" \
    "${OPENBAO_RECOVERY_ARCHIVE##*/}" >"$OPENBAO_RECOVERY_SIDECAR") || return 1
  chmod 600 "$OPENBAO_RECOVERY_SIDECAR" || return 1
  openbao_recovery_bundle_is_valid
}

openbao_operator_initialize() {
  local init_file=${OPENBAO_RECOVERY_DIRECTORY}/init.json
  (umask 077; set -o noclobber; : >"$init_file") || return 1
  chmod 600 "$init_file" || return 1
  # The single-quoted program is expanded by the remote /bin/sh, not this shell.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec -i pod/openbao-0 -- /bin/sh -c '
set -eu
umask 077
key=$(mktemp /tmp/openbao-pgp.XXXXXX)
trap '\''rm -f -- "$key"'\'' EXIT HUP INT TERM
cat >"$key"
chmod 600 "$key"
pgp_keys=$(printf '\''%s,%s,%s,%s,%s'\'' "$key" "$key" "$key" "$key" "$key")
env BAO_ADDR=https://openbao.openbao.svc:8200 \
  BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
  bao operator init -format=json -key-shares=5 -key-threshold=3 \
  "-pgp-keys=${pgp_keys}" "-root-token-pgp-key=${key}"
' <"$OPENBAO_PUBLIC_KEY" >"$init_file" || return 1
  openbao_init_ciphertext_is_valid "$init_file"
}

openbao_remote_home_create() {
  local kind=$1 path
  [[ -z "$OPENBAO_REMOTE_HOME" && -z "$OPENBAO_REMOTE_SESSION_KIND" ]] ||
    return 1
  [[ "$kind" == root || "$kind" == probe-pending ]] || return 1
  path=$(kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c \
    'umask 077; mktemp -d /tmp/openbao-stage180.XXXXXX') || return 1
  [[ "$path" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ ]] || return 1
  OPENBAO_REMOTE_HOME=$path
  OPENBAO_REMOTE_SESSION_KIND=$kind
}

openbao_bao_public() {
  kubectl_run --namespace=openbao exec pod/openbao-0 -- env \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_bao() {
  kubectl_run --namespace=openbao exec pod/openbao-0 -- env \
    HOME="$OPENBAO_REMOTE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_bao_tty_public() {
  kubectl_run --namespace=openbao exec --stdin --tty pod/openbao-0 -- env \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_bao_tty() {
  kubectl_run --namespace=openbao exec --stdin --tty pod/openbao-0 -- env \
    HOME="$OPENBAO_REMOTE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_bao_stdin() {
  kubectl_run --namespace=openbao exec -i pod/openbao-0 -- env \
    HOME="$OPENBAO_REMOTE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_remote_session_cleanup() {
  local path=$OPENBAO_REMOTE_HOME kind=$OPENBAO_REMOTE_SESSION_KIND
  if [[ -z "$path" ]]; then
    [[ -z "$kind" ]]
    return
  fi
  [[ "$path" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ ]] || return 1
  if [[ "$kind" == probe ]]; then
    kubectl_run --namespace=openbao exec pod/openbao-0 -- env HOME="$path" \
      BAO_ADDR=https://openbao.openbao.svc:8200 \
      BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
      bao token revoke -self >/dev/null 2>&1 || return 1
    OPENBAO_REMOTE_SESSION_KIND=probe-pending
  elif [[ "$kind" != root && "$kind" != probe-pending && -n "$kind" ]]; then
    return 1
  fi
  # $1 is intentionally expanded by the remote shell.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c \
    'rm -f -- "$1/.bao-token"; rmdir -- "$1"' cleanup "$path" \
    >/dev/null 2>&1 || return 1
  OPENBAO_REMOTE_HOME=
  OPENBAO_REMOTE_SESSION_KIND=
}

openbao_initialize_cleanup() {
  OPENBAO_SECRET_INPUT=
  unset OPENBAO_SECRET_INPUT
  openbao_remote_session_cleanup || true
}

openbao_prompt_secret() {
  local prompt=$1
  OPENBAO_SECRET_INPUT=
  read -r -s -p "$prompt" OPENBAO_SECRET_INPUT
  printf '\n' >&2
  [[ -n "$OPENBAO_SECRET_INPUT" &&
     ${#OPENBAO_SECRET_INPUT} -le 4096 &&
     "$OPENBAO_SECRET_INPUT" != *[[:space:]]* ]]
}

openbao_require_interactive_tty() {
  if [[ ! -t 0 || ! -t 1 || ! -t 2 ]]; then
    printf 'interactive-tty-required\n' >&2
    return 1
  fi
}

openbao_unseal_progress_is_safe() {
  local attempt=$1
  openbao_bao_public status -format=json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

attempt = int(sys.argv[1])
document = json.load(sys.stdin)
if document.get("initialized") is not True:
    raise SystemExit(1)
progress = document.get("progress")
if attempt in (1, 2):
    valid = document.get("sealed") is True and progress == attempt
elif attempt == 3:
    valid = document.get("sealed") is False and progress == 0
else:
    valid = False
if not valid:
    raise SystemExit(1)
' "$attempt"
}

openbao_unseal_interactively() {
  local attempt
  openbao_require_interactive_tty || return 1
  openbao_bao_public operator unseal -reset -format=json >/dev/null || return 1
  for attempt in 1 2 3; do
    openbao_bao_tty_public operator unseal -format=json >/dev/null || return 1
    openbao_unseal_progress_is_safe "$attempt" || return 1
  done
  [[ "$(openbao_state_flags)" == 'true|false' ]]
}

openbao_probe_policy() {
  cat <<'HCL'
path "openbao-probe/data/runtime-check" {
  capabilities = ["create", "update", "read", "delete"]
}

path "sys/storage/raft/configuration" {
  capabilities = ["read"]
}
HCL
}

openbao_auth_mount_state() {
  openbao_bao auth list -format=json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

entry = json.load(sys.stdin).get("kubernetes/")
if entry is None:
    print("MISSING")
elif entry.get("type") == "kubernetes":
    print("COMPLIANT")
else:
    print("UNSAFE")
'
}

openbao_probe_mount_state() {
  openbao_bao secrets list -format=json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

entry = json.load(sys.stdin).get("openbao-probe/")
if entry is None:
    print("MISSING")
elif entry.get("type") == "kv" and str(entry.get("options", {}).get("version")) == "2":
    print("COMPLIANT")
else:
    print("UNSAFE")
'
}

openbao_audit_api_is_exact() {
  openbao_bao audit list -format=json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

document = json.load(sys.stdin)
expected = {
    "to-file/": "/openbao/audit/openbao-audit.log",
    "to-stdout/": "stdout",
}
if set(document) != set(expected):
    raise SystemExit(1)
for name, file_path in expected.items():
    entry = document[name]
    options = entry.get("options", {})
    if entry.get("type") != "file" or options.get("file_path") != file_path:
        raise SystemExit(1)
    if str(options.get("hmac_accessor", "true")).lower() != "true":
        raise SystemExit(1)
    if str(options.get("log_raw", "false")).lower() != "false":
        raise SystemExit(1)
'
}

openbao_configuration_readback_is_exact() {
  local auth_config policy role
  auth_config=$(openbao_bao read -format=json auth/kubernetes/config) || return 1
  role=$(openbao_bao read -format=json \
    auth/kubernetes/role/openbao-runtime-probe) || return 1
  policy=$(openbao_bao policy read openbao-runtime-probe) || return 1
  printf '%s' "$auth_config" | "$PYTHON_BINARY" -I -B -c '
import json
import sys

data = json.load(sys.stdin).get("data", {})
if data.get("kubernetes_host") != "https://kubernetes.default.svc:443":
    raise SystemExit(1)
if data.get("disable_iss_validation") is not True:
    raise SystemExit(1)
' || return 1
  printf '%s' "$role" | "$PYTHON_BINARY" -I -B -c '
import json
import sys

data = json.load(sys.stdin).get("data", {})
if data.get("bound_service_account_names") != ["openbao-runtime-probe"]:
    raise SystemExit(1)
if data.get("bound_service_account_namespaces") != ["openbao"]:
    raise SystemExit(1)
if data.get("audience") != "openbao":
    raise SystemExit(1)
if data.get("token_policies") != ["openbao-runtime-probe"]:
    raise SystemExit(1)
if data.get("token_no_default_policy") is not True:
    raise SystemExit(1)
if data.get("token_ttl") != 600 or data.get("token_max_ttl") != 600:
    raise SystemExit(1)
' || return 1
  printf '%s' "$policy" | grep -F 'path "openbao-probe/data/runtime-check"' \
    >/dev/null || return 1
  printf '%s' "$policy" | grep -F 'path "sys/storage/raft/configuration"' \
    >/dev/null || return 1
  openbao_audit_api_is_exact
}

openbao_root_session_start() {
  openbao_require_interactive_tty || return 1
  openbao_remote_home_create root || return 1
  openbao_bao_tty login -no-print
}

openbao_apply_configuration() {
  local auth_state mount_state
  openbao_bao token lookup -format=json >/dev/null || return 1
  openbao_audit_api_is_exact || return 1

  auth_state=$(openbao_auth_mount_state) || return 1
  case "$auth_state" in
    MISSING) openbao_bao auth enable -path=kubernetes kubernetes >/dev/null || return 1 ;;
    COMPLIANT) ;;
    *) return 1 ;;
  esac
  mount_state=$(openbao_probe_mount_state) || return 1
  case "$mount_state" in
    MISSING) openbao_bao secrets enable -path=openbao-probe -version=2 kv \
      >/dev/null || return 1 ;;
    COMPLIANT) ;;
    *) return 1 ;;
  esac

  printf '%s\n' '{"kubernetes_host":"https://kubernetes.default.svc:443","disable_iss_validation":true}' |
    openbao_bao_stdin write auth/kubernetes/config - >/dev/null || return 1
  printf '%s\n' '{"bound_service_account_names":["openbao-runtime-probe"],"bound_service_account_namespaces":["openbao"],"audience":"openbao","token_policies":["openbao-runtime-probe"],"token_ttl":"10m","token_max_ttl":"10m","token_no_default_policy":true}' |
    openbao_bao_stdin write auth/kubernetes/role/openbao-runtime-probe - \
      >/dev/null || return 1
  openbao_probe_policy | openbao_bao_stdin policy write openbao-runtime-probe - \
    >/dev/null || return 1
  openbao_configuration_readback_is_exact
}

openbao_root_session_revoke() {
  openbao_bao token revoke -self >/dev/null || return 1
  openbao_root_session_revocation_is_proven || return 1
  OPENBAO_REMOTE_SESSION_KIND=
}

openbao_root_session_revocation_is_proven() {
  local path=$OPENBAO_REMOTE_HOME
  [[ "$OPENBAO_REMOTE_SESSION_KIND" == root ]] || return 1
  [[ "$path" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ ]] || return 1
  # The lookup error is bounded and inspected only inside the container. Nothing
  # from stdout, stderr, or token metadata crosses the kubectl boundary.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c '
set -eu
umask 077
error=$(mktemp /tmp/openbao-root-revoke.XXXXXX)
status=$(mktemp /tmp/openbao-root-revoke-status.XXXXXX)
trap '\''rm -f -- "$error" "$status"'\'' EXIT HUP INT TERM
(
  set +e
  env HOME="$1" \
      BAO_ADDR=https://openbao.openbao.svc:8200 \
      BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
      bao token lookup -format=json >/dev/null
  printf "%s\n" "$?" >"$status"
  exit 0
) 2>&1 | head -c 4097 >"$error"
rc=$(cat "$status")
case "$rc" in ""|*[!0-9]*) exit 1 ;; esac
[ "$rc" -ne 0 ] || exit 1
bytes=$(wc -c <"$error")
[ "$bytes" -gt 0 ] && [ "$bytes" -le 4096 ] || exit 1
grep -Fqx "Code: 403. Errors:" "$error" || exit 1
grep -Fqx "* permission denied" "$error"
' revoke-proof "$path" >/dev/null 2>&1
}

openbao_apply_configuration_with_root() {
  local rc=0
  if ! openbao_root_session_start; then
    openbao_remote_session_cleanup || true
    return 1
  fi
  openbao_apply_configuration || rc=1
  openbao_root_session_revoke || rc=1
  openbao_remote_session_cleanup || rc=1
  (( rc == 0 ))
}

openbao_probe_session_start() {
  openbao_remote_home_create probe-pending || return 1
  kubectl_run --namespace=openbao create token openbao-runtime-probe \
    --audience=openbao --duration=10m |
    openbao_bao_stdin write -field=token auth/kubernetes/login \
      role=openbao-runtime-probe jwt=- |
    openbao_bao_stdin login -no-print >/dev/null || return 1
  OPENBAO_REMOTE_SESSION_KIND=probe
}

openbao_auth_probe() {
  local observed rc=0
  openbao_probe_session_start || { openbao_remote_session_cleanup; return 1; }
  set +e
  openbao_bao kv put openbao-probe/runtime-check \
    value="$OPENBAO_PROBE_VALUE" >/dev/null || rc=1
  observed=$(openbao_bao kv get -field=value \
    openbao-probe/runtime-check 2>/dev/null) || rc=1
  [[ "$observed" == "$OPENBAO_PROBE_VALUE" ]] || rc=1
  if openbao_bao read sys/auth >/dev/null 2>&1; then
    rc=1
  fi
  openbao_bao operator raft list-peers -format=json |
    "$PYTHON_BINARY" -I -B -c '
import json
import sys

data = json.load(sys.stdin).get("data", {})
servers = data.get("config", {}).get("servers", [])
if len(servers) != 1 or servers[0].get("node_id") != "openbao-0":
    raise SystemExit(1)
if servers[0].get("leader") is not True:
    raise SystemExit(1)
' || rc=1
  openbao_bao kv delete openbao-probe/runtime-check >/dev/null || rc=1
  if openbao_bao token revoke -self >/dev/null; then
    OPENBAO_REMOTE_SESSION_KIND=
  else
    rc=1
  fi
  openbao_remote_session_cleanup || rc=1
  set -e
  (( rc == 0 ))
}

openbao_audit_runtime_is_exact() {
  kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c \
    'test -s /openbao/audit/openbao-audit.log &&
     grep -F '\''"path":"openbao-probe/data/runtime-check"'\'' /openbao/audit/openbao-audit.log >/dev/null &&
     grep -F '\''hmac-sha256:'\'' /openbao/audit/openbao-audit.log >/dev/null &&
     ! grep -F '\''stage180-probe'\'' /openbao/audit/openbao-audit.log >/dev/null' &&
    kubectl_run --namespace=openbao logs pod/openbao-0 --container=openbao |
      grep -F '"path":"openbao-probe/data/runtime-check"' >/dev/null &&
    kubectl_run --namespace=openbao logs pod/openbao-0 --container=openbao |
      grep -F 'hmac-sha256:' >/dev/null &&
    ! kubectl_run --namespace=openbao logs pod/openbao-0 --container=openbao |
      grep -F "$OPENBAO_PROBE_VALUE" >/dev/null
}

openbao_expected_platform_secret_fingerprint() {
  openbao_recovery_metadata_value platform_secret_fingerprint
}

openbao_platform_secrets_match_recovery_baseline() {
  local expected observed
  expected=$(openbao_expected_platform_secret_fingerprint) || return 1
  observed=$(openbao_platform_secret_fingerprint) || return 1
  [[ "$observed" == "$expected" ]]
}

openbao_resource_fact() {
  local namespace=$1 resource=$2 name=$3 label=$4 document
  if [[ -n "$namespace" ]]; then
    document=$(kubectl_run --namespace="$namespace" get "$resource" "$name" \
      --output=json 2>/dev/null) || return 1
  else
    document=$(kubectl_run get "$resource" "$name" --output=json 2>/dev/null) ||
      return 1
  fi
  printf '%s' "$document" | "$PYTHON_BINARY" -I -B -c '
import json
import re
import sys

label = sys.argv[1]
if re.fullmatch(r"[A-Z0-9_]+", label) is None:
    raise SystemExit(1)
document = json.load(sys.stdin)
metadata = document.get("metadata", {})
uid = metadata.get("uid")
generation = metadata.get("generation", 0)
if not isinstance(uid, str) or not uid or not isinstance(generation, int):
    raise SystemExit(1)
print(f"{label}_UID={uid}")
print(f"{label}_GENERATION={generation}")
' "$label"
}

openbao_status_evidence() {
  openbao_status_json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

document = json.load(sys.stdin)
if document.get("initialized") is not True or document.get("sealed") is not False:
    raise SystemExit(1)
version = document.get("version")
if version != "2.6.1":
    raise SystemExit(1)
print("OPENBAO_VERSION=2.6.1")
print("OPENBAO_INITIALIZED=true")
print("OPENBAO_SEALED=false")
'
}

openbao_evidence_is_secret_free() {
  local file=$1
  safe_file "$file" 600 &&
    "$PYTHON_BINARY" -I -B - "$file" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
for pattern in (
    r'(?i)(?:hvs|hvb|hvr|s)\.[A-Za-z0-9_-]{8,}',
    r'(?i)"?(?:unseal_keys_b64|root_token|client_token|jwt)"?\s*[:=]\s*["A-Za-z0-9+/_.-]{8,}',
    r'[A-Za-z0-9+/]{43}=',
):
    if re.search(pattern, text):
        raise SystemExit(1)
PY
}

openbao_existing_evidence() {
  local candidate digest recorded recorded_name sidecar
  for candidate in "$(host_path /root/dev-infra-evidence)"/17-openbao-runtime-*.txt; do
    safe_file "$candidate" 600 || continue
    grep -Fx "GIT_COMMIT=${OPENBAO_RECOVERY_ID}" "$candidate" >/dev/null 2>&1 ||
      continue
    openbao_evidence_is_secret_free "$candidate" || continue
    sidecar=${candidate}.sha256
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

openbao_write_acceptance_payload() {
  local destination=$1 bundle_sha platform_fingerprint public_fingerprint
  bundle_sha=$(sha256_file "$OPENBAO_RECOVERY_ARCHIVE") || return 1
  platform_fingerprint=$(openbao_platform_secret_fingerprint) || return 1
  public_fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  (umask 077; set -o noclobber; : >"$destination") || return 1
  chmod 600 "$destination" || return 1
  {
    printf 'GIT_COMMIT=%s\n' "$OPENBAO_RECOVERY_ID"
    printf 'DOCS_COMMIT=%s\n' "$OPENBAO_DOCS_COMMIT"
    printf 'DOCS_BASELINE=%s\n' "$OPENBAO_DOCS_BASELINE"
    printf 'DEVIATION=%s\n' "$OPENBAO_DEVIATION"
    printf 'CHART_VERSION=0.28.6\n'
    printf 'CHART_PACKAGE_SHA256=%s\n' "$OPENBAO_CHART_PACKAGE_SHA256"
    printf 'SERVER_IMAGE_DIGEST=%s\n' "$OPENBAO_SERVER_DIGEST"
    printf 'INJECTOR_IMAGE_DIGEST=%s\n' "$OPENBAO_INJECTOR_DIGEST"
    printf 'RECOVERY_PUBLIC_KEY_FINGERPRINT=%s\n' "$public_fingerprint"
    printf 'RECOVERY_BUNDLE_SHA256=%s\n' "$bundle_sha"
    openbao_status_evidence
    printf 'OPENBAO_RAFT_PEERS=1\n'
    printf 'OPENBAO_HA_CLASS=NON_HA\n'
    printf 'OPENBAO_DATA_PVC=10Gi_BOUND\n'
    printf 'OPENBAO_AUDIT_PVC=5Gi_BOUND\n'
    printf 'OPENBAO_SERVICE_EXPOSURE=CLUSTERIP_ONLY\n'
    printf 'OPENBAO_TLS_SERVICE_DNS=PASS\n'
    printf 'OPENBAO_AUDIT_FILE=PASS\n'
    printf 'OPENBAO_AUDIT_STDOUT=PASS\n'
    printf 'OPENBAO_AUDIT_HMAC=PASS\n'
    printf 'OPENBAO_AUDIT_LOG_RAW=false\n'
    printf 'KUBERNETES_AUTH=PASS\n'
    printf 'POLICY_POSITIVE_PROBE=PASS\n'
    printf 'POLICY_NEGATIVE_PROBE=PASS\n'
    printf 'TEMPORARY_TOKEN=REVOKED\n'
    printf 'INITIAL_ROOT_TOKEN=REVOKED\n'
    printf 'PLATFORM_SECRET_FINGERPRINT=%s\n' "$platform_fingerprint"
    printf 'PLATFORM_SECRET_DRIFT=NONE\n'
    printf 'APPLICATIONS=READY\n'
    printf 'HTTPS_SMOKE=PASS\n'
    printf 'MINIO=NOT_EXECUTED\n'
    printf 'SNAPSHOT=NOT_EXECUTED\n'
    printf 'BACKUP=NOT_EXECUTED\n'
    printf 'RESTORE=NOT_EXECUTED\n'
    printf 'APP_SECRET_MIGRATION=NOT_EXECUTED\n'
    printf 'SECRET_VALUES=NOT_RECORDED\n'
    openbao_resource_fact '' namespace openbao OPENBAO_NAMESPACE
    openbao_resource_fact flux-system kustomization.kustomize.toolkit.fluxcd.io \
      openbao-runtime OPENBAO_KUSTOMIZATION
    openbao_resource_fact flux-system helmrelease.helm.toolkit.fluxcd.io \
      openbao OPENBAO_HELMRELEASE
    openbao_resource_fact openbao statefulset.apps openbao OPENBAO_SERVER
    openbao_resource_fact openbao deployment.apps openbao-agent-injector \
      OPENBAO_INJECTOR
    openbao_resource_fact openbao persistentvolumeclaim data-openbao-0 \
      OPENBAO_DATA_PVC
    openbao_resource_fact openbao persistentvolumeclaim audit-openbao-0 \
      OPENBAO_AUDIT_PVC
  } >>"$destination"
}

openbao_stage_180_preflight() {
  openbao_verify_assets ||
    complete STOP_SUPPLY_CHAIN_MISMATCH openbao-asset-drift \
      "$EXIT_SUPPLY_CHAIN" NONE
  openbao_runtime_is_compliant ||
    complete STOP_PRECONDITION openbao-runtime-not-ready \
      "$EXIT_PRECONDITION" NONE
  openbao_public_key_is_valid ||
    complete STOP_PRECONDITION public-key-missing-or-unsafe \
      "$EXIT_PRECONDITION" NONE
  openbao_recovery_root_is_safe ||
    complete STOP_PRECONDITION recovery-root-missing-or-unsafe \
      "$EXIT_PRECONDITION" NONE
}

openbao_stage_180_check() {
  local recovery_state state
  openbao_stage_180_preflight
  state=$(openbao_state_flags) ||
    complete STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE" NONE
  recovery_state=$(openbao_recovery_state) ||
    complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
  case "$state:$recovery_state" in
    'false|true:MISSING')
      complete PASS_OPENBAO_INITIALIZATION_CHECK initialization-required 0 \
        'stages/180-openbao-initialize/run.sh --initialize'
      ;;
    'true|true:DIRECTORY_READY')
      complete PASS_OPENBAO_INITIALIZATION_CHECK recovery-finalization-required 0 \
        'stages/180-openbao-initialize/run.sh --initialize'
      ;;
    'true|true:MISSING')
      [[ -n "$OPENBAO_SOURCE_RECOVERY_SHA" ]] ||
        complete STOP_PRECONDITION "$OPENBAO_REASON_SOURCE_REQUIRED" \
          "$EXIT_PRECONDITION" NONE
      openbao_source_recovery_sha_is_valid ||
        complete STOP_PRECONDITION "$OPENBAO_REASON_SOURCE_INVALID" \
          "$EXIT_PRECONDITION" NONE
      openbao_source_recovery_bundle_is_valid ||
        complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_SOURCE_UNSAFE" \
          "$EXIT_UNKNOWN_STATE" NONE
      complete PASS_OPENBAO_RECOVERY_CHECK recover-start-required 0 \
        "stages/180-openbao-initialize/run.sh --recover-start --source-recovery-sha=${OPENBAO_SOURCE_RECOVERY_SHA}"
      ;;
    'true|true:COMPLIANT'|'true|false:COMPLIANT')
      if [[ "$state" == 'true|false' ]] && openbao_existing_evidence >/dev/null; then
        complete ALREADY_COMPLIANT openbao-runtime-evidence-exists 0 NONE
      fi
      complete PASS_OPENBAO_INITIALIZATION_CHECK configuration-required 0 \
        'stages/180-openbao-initialize/run.sh --configure'
      ;;
    *)
      complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
}

openbao_stage_180_initialize() {
  local after_fingerprint before_fingerprint init_file metadata public_copy
  local fingerprint_copy recovery_state state
  openbao_stage_180_preflight
  state=$(openbao_state_flags) ||
    complete STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE" NONE
  recovery_state=$(openbao_recovery_state) ||
    complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
  if [[ "$state" == 'true|true' && "$recovery_state" == COMPLIANT ]]; then
    complete ALREADY_COMPLIANT openbao-already-initialized 0 \
      'stages/180-openbao-initialize/run.sh --configure'
  fi
  if [[ "$state" == 'true|true' && "$recovery_state" == DIRECTORY_READY ]]; then
    openbao_finalize_recovery_bundle ||
      complete STOP_APPLY_FAILED recovery-bundle-finalization-failed \
        "$EXIT_APPLY_FAILED" NONE
    complete PASS_OPENBAO_INITIALIZED encrypted-recovery-bundle-ready 0 \
      'stages/180-openbao-initialize/run.sh --configure'
  fi
  [[ "$state" == 'false|true' && "$recovery_state" == MISSING ]] ||
    complete STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE" NONE
  before_fingerprint=$(openbao_platform_secret_fingerprint) ||
    complete STOP_UNKNOWN_STATE platform-secret-fingerprint-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  (umask 077; mkdir "$OPENBAO_RECOVERY_DIRECTORY") ||
    complete STOP_APPLY_FAILED recovery-bundle-state-unsafe \
      "$EXIT_APPLY_FAILED" NONE
  chmod 700 "$OPENBAO_RECOVERY_DIRECTORY" ||
    complete STOP_APPLY_FAILED recovery-bundle-state-unsafe \
      "$EXIT_APPLY_FAILED" NONE
  metadata=${OPENBAO_RECOVERY_DIRECTORY}/metadata.json
  public_copy=${OPENBAO_RECOVERY_DIRECTORY}/openbao-recovery-public-key.b64
  fingerprint_copy=${OPENBAO_RECOVERY_DIRECTORY}/openbao-recovery-public-key.fingerprint
  openbao_write_recovery_metadata "$metadata" "$before_fingerprint" ||
    complete STOP_APPLY_FAILED recovery-bundle-state-unsafe \
      "$EXIT_APPLY_FAILED" NONE
  install -m 600 "$OPENBAO_PUBLIC_KEY" "$public_copy" ||
    complete STOP_APPLY_FAILED recovery-bundle-state-unsafe \
      "$EXIT_APPLY_FAILED" NONE
  install -m 600 "$OPENBAO_PUBLIC_KEY_FINGERPRINT" "$fingerprint_copy" ||
    complete STOP_APPLY_FAILED recovery-bundle-state-unsafe \
      "$EXIT_APPLY_FAILED" NONE
  openbao_operator_initialize ||
    complete STOP_APPLY_FAILED openbao-initialization-failed \
      "$EXIT_APPLY_FAILED" NONE
  init_file=${OPENBAO_RECOVERY_DIRECTORY}/init.json
  openbao_init_ciphertext_is_valid "$init_file" ||
    complete STOP_VERIFY_FAILED recovery-bundle-validation-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_finalize_recovery_bundle ||
    complete STOP_APPLY_FAILED recovery-bundle-finalization-failed \
      "$EXIT_APPLY_FAILED" NONE
  state=$(openbao_state_flags) ||
    complete STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE" NONE
  [[ "$state" == 'true|true' ]] ||
    complete STOP_VERIFY_FAILED unexpected-openbao-state \
      "$EXIT_VERIFY_FAILED" NONE
  after_fingerprint=$(openbao_platform_secret_fingerprint) ||
    complete STOP_UNKNOWN_STATE platform-secret-fingerprint-failed \
      "$EXIT_UNKNOWN_STATE" NONE
  [[ "$after_fingerprint" == "$before_fingerprint" ]] ||
    complete STOP_VERIFY_FAILED platform-secret-drift \
      "$EXIT_VERIFY_FAILED" NONE
  complete PASS_OPENBAO_INITIALIZED encrypted-recovery-bundle-ready 0 \
    'stages/180-openbao-initialize/run.sh --configure'
}

openbao_stage_180_configure() {
  local state
  openbao_stage_180_preflight
  openbao_recovery_bundle_is_valid ||
    complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
  openbao_platform_secrets_match_recovery_baseline ||
    complete STOP_VERIFY_FAILED platform-secret-drift \
      "$EXIT_VERIFY_FAILED" NONE
  state=$(openbao_state_flags) ||
    complete STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE" NONE
  [[ "$state" != 'false|true' ]] ||
    complete STOP_PRECONDITION unexpected-openbao-state \
      "$EXIT_PRECONDITION" NONE
  if [[ "$state" == 'true|true' ]]; then
    openbao_unseal_interactively ||
      complete STOP_APPLY_FAILED openbao-unseal-failed \
        "$EXIT_APPLY_FAILED" NONE
  elif [[ "$state" != 'true|false' ]]; then
    complete STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE" NONE
  fi
  if openbao_auth_probe && openbao_audit_runtime_is_exact; then
    openbao_platform_secrets_match_recovery_baseline ||
      complete STOP_VERIFY_FAILED platform-secret-drift \
        "$EXIT_VERIFY_FAILED" NONE
    complete ALREADY_COMPLIANT openbao-configuration-ready 0 \
      'stages/180-openbao-initialize/run.sh --accept'
  fi
  openbao_apply_configuration_with_root ||
    complete STOP_APPLY_FAILED openbao-configuration-failed \
      "$EXIT_APPLY_FAILED" NONE
  openbao_auth_probe ||
    complete STOP_VERIFY_FAILED openbao-auth-probe-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_audit_runtime_is_exact ||
    complete STOP_VERIFY_FAILED openbao-audit-readback-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_platform_secrets_match_recovery_baseline ||
    complete STOP_VERIFY_FAILED platform-secret-drift \
      "$EXIT_VERIFY_FAILED" NONE
  complete PASS_OPENBAO_CONFIGURED openbao-kubernetes-auth-ready 0 \
    'stages/180-openbao-initialize/run.sh --accept'
}

openbao_stage_180_accept() {
  local evidence_dir payload digest sidecar
  openbao_stage_180_preflight
  openbao_recovery_bundle_is_valid ||
    complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
  [[ "$(openbao_state_flags)" == 'true|false' ]] ||
    complete STOP_PRECONDITION unexpected-openbao-state \
      "$EXIT_PRECONDITION" NONE
  openbao_platform_secrets_match_recovery_baseline ||
    complete STOP_VERIFY_FAILED platform-secret-drift \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_auth_probe ||
    complete STOP_VERIFY_FAILED openbao-auth-probe-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_audit_runtime_is_exact ||
    complete STOP_VERIFY_FAILED openbao-audit-readback-failed \
      "$EXIT_VERIFY_FAILED" NONE
  business_apps_ready ||
    complete STOP_PRECONDITION applications-not-ready \
      "$EXIT_PRECONDITION" NONE
  business_https_smoke ||
    complete STOP_VERIFY_FAILED https-smoke-failed \
      "$EXIT_VERIFY_FAILED" NONE
  openbao_platform_secrets_match_recovery_baseline ||
    complete STOP_VERIFY_FAILED platform-secret-drift \
      "$EXIT_VERIFY_FAILED" NONE
  if openbao_existing_evidence >/dev/null; then
    complete ALREADY_COMPLIANT openbao-runtime-evidence-exists 0 NONE
  fi
  evidence_dir=$(host_path /root/dev-infra-evidence)
  payload=$(mktemp "$(host_path /root)/.openbao-evidence.XXXXXX") ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  rm -f -- "$payload" ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  openbao_write_acceptance_payload "$payload" ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  openbao_evidence_is_secret_free "$payload" ||
    complete STOP_VERIFY_FAILED evidence-scan-failed \
      "$EXIT_VERIFY_FAILED" NONE
  open_evidence 17-openbao-runtime "$evidence_dir" ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  while IFS= read -r line; do
    log_evidence "$line" || exit "$EXIT_VERIFY_FAILED"
  done <"$payload"
  rm -f -- "$payload" || exit "$EXIT_UNKNOWN_STATE"
  finish_phase PASS_OPENBAO_RUNTIME_ACCEPTED openbao-runtime-accepted 0 NONE ||
    exit "$?"
  openbao_evidence_is_secret_free "$EVIDENCE_FILE" || exit "$EXIT_VERIFY_FAILED"
  digest=$(sha256_file "$EVIDENCE_FILE") || exit "$EXIT_UNKNOWN_STATE"
  sidecar=${EVIDENCE_FILE}.sha256
  (umask 077; set -o noclobber; printf '%s  %s\n' "$digest" \
    "${EVIDENCE_FILE##*/}" >"$sidecar") || exit "$EXIT_UNKNOWN_STATE"
  chmod 600 "$sidecar" || exit "$EXIT_APPLY_FAILED"
  printf 'SHA256_FILE=%s\n' "$sidecar"
  exit 0
}

openbao_initialize_main() {
  local required untrusted_environment='' untrusted_name
  for untrusted_name in BAO_ADDR BAO_AGENT_ADDR BAO_CACERT BAO_CAPATH BAO_CLIENT_CERT \
      BAO_CLIENT_KEY BAO_FORMAT BAO_NAMESPACE BAO_RATE_LIMIT BAO_SRV_LOOKUP \
      BAO_TOKEN BAO_TOKEN_HELPER VAULT_ADDR VAULT_AGENT_ADDR VAULT_CACERT \
      VAULT_CAPATH VAULT_CLIENT_CERT VAULT_CLIENT_KEY VAULT_FORMAT VAULT_NAMESPACE \
      VAULT_RATE_LIMIT VAULT_SRV_LOOKUP VAULT_TOKEN VAULT_TOKEN_HELPER; do
    [[ -z "${!untrusted_name+x}" ]] ||
      untrusted_environment="${untrusted_environment:+${untrusted_environment},}${untrusted_name}"
  done
  [[ -z "$untrusted_environment" ]] ||
    complete STOP_PRECONDITION untrusted-environment-override \
      "$EXIT_PRECONDITION" NONE
  openbao_parse_operation "$@" ||
    complete STOP_PRECONDITION invalid-openbao-operation \
      "$EXIT_PRECONDITION" NONE
  business_initialize --check
  # MODE is consumed by common.sh's structured finish helpers.
  # shellcheck disable=SC2034
  MODE=$OPENBAO_OPERATION
  for required in install mkdir tar; do
    require_command "$required" ||
      complete STOP_PRECONDITION "missing-command-${required}" \
        "$EXIT_PRECONDITION" NONE
  done
  readonly TAR_BINARY=/usr/bin/tar
  [[ -x "$TAR_BINARY" && "$(path_owner "$TAR_BINARY")" == 0:0 ]] ||
    complete STOP_PRECONDITION missing-command-tar "$EXIT_PRECONDITION" NONE
  openbao_initialize_paths
  openbao_initialize_ceremony_paths ||
    complete STOP_UNKNOWN_STATE git-commit-unreadable \
      "$EXIT_UNKNOWN_STATE" NONE
  trap openbao_initialize_cleanup EXIT HUP INT TERM
  case "$OPENBAO_OPERATION" in
    CHECK) openbao_stage_180_check ;;
    INITIALIZE) openbao_stage_180_initialize ;;
    CONFIGURE) openbao_stage_180_configure ;;
    ACCEPT) openbao_stage_180_accept ;;
    *) complete STOP_PRECONDITION invalid-openbao-operation \
      "$EXIT_PRECONDITION" NONE ;;
  esac
}
