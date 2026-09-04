#!/usr/bin/env bash

openbao_nonce_variables_sanitize() {
  local name
  for name in "$@"; do
    unset "$name" || return 1
    export -n "${name?}" 2>/dev/null || return 1
  done
}

openbao_nonce_variables_sanitize \
  OPENBAO_ROTATION_NONCE \
  OPENBAO_ROTATION_VERIFICATION_NONCE \
  OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE \
  OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256 \
  OPENBAO_FINALIZATION_REMOTE_HOME \
  OPENBAO_FINALIZATION_REMOTE_BINDING || exit 1

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
readonly OPENBAO_REASON_REMOTE_CLEANUP=remote-session-cleanup-failed

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
OPENBAO_ROTATION_READY_CHECKPOINT=
OPENBAO_ROTATION_REVOKED_CHECKPOINT=
OPENBAO_ROTATION_FINAL_STAGING_ROOT=
OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY=
OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE=
OPENBAO_ROTATION_FINAL_STAGING_SIDECAR=
OPENBAO_ROTATION_TEMP_DIRECTORY=
OPENBAO_ROTATION_RESPONSE=
OPENBAO_ROTATION_STATUS_RESPONSE=
OPENBAO_ROTATION_STATUS_STATE=
OPENBAO_ROTATION_VERIFICATION_RESPONSE=
OPENBAO_ROTATION_VERIFICATION_STATE=
OPENBAO_ROTATION_PHASE=
OPENBAO_ROTATION_NONCE=
OPENBAO_ROTATION_PROGRESS=
OPENBAO_ROTATION_REQUIRED=
OPENBAO_ROTATION_VERIFICATION_NONCE=
OPENBAO_ROTATION_VERIFICATION_PHASE=
OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE=
OPENBAO_ROTATION_VERIFICATION_PROGRESS=
OPENBAO_CLUSTER_ID=
OPENBAO_CLUSTER_NAME=
OPENBAO_SECRET_INPUT=
OPENBAO_REMOTE_HOME=
OPENBAO_REMOTE_SESSION_KIND=
OPENBAO_RECOVER_PROBE_HOME=
OPENBAO_RECOVER_PROBE_SESSION_KIND=
OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256=
OPENBAO_FINALIZATION_REMOTE_HOME=
OPENBAO_FINALIZATION_REMOTE_BINDING=
OPENBAO_INITIALIZE_TRAPS_ACTIVE=false

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
  OPENBAO_ROTATION_CANDIDATE_STAGING_ROOT=${OPENBAO_RECOVERY_ROOT}/.openbao-candidate-staging-${OPENBAO_RECOVERY_ID}
  OPENBAO_RECOVERY_DIRECTORY=${OPENBAO_RECOVERY_ROOT}/openbao-recovery-${OPENBAO_RECOVERY_ID}
  OPENBAO_RECOVERY_ARCHIVE=${OPENBAO_RECOVERY_DIRECTORY}.tar.gz
  OPENBAO_RECOVERY_SIDECAR=${OPENBAO_RECOVERY_ARCHIVE}.sha256
  OPENBAO_ROTATION_VERIFIED_MARKER=${OPENBAO_RECOVERY_ROOT}/openbao-rotation-${OPENBAO_RECOVERY_ID}.verified.json
  OPENBAO_ROTATION_READY_CHECKPOINT=${OPENBAO_RECOVERY_ROOT}/.openbao-rotation-${OPENBAO_RECOVERY_ID}.ready-to-revoke.json
  OPENBAO_ROTATION_REVOKED_CHECKPOINT=${OPENBAO_RECOVERY_ROOT}/.openbao-rotation-${OPENBAO_RECOVERY_ID}.root-revoked.json
  OPENBAO_ROTATION_FINAL_STAGING_ROOT=${OPENBAO_RECOVERY_ROOT}/.openbao-final-staging-${OPENBAO_RECOVERY_ID}
  OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY=${OPENBAO_ROTATION_FINAL_STAGING_ROOT}/openbao-recovery-${OPENBAO_RECOVERY_ID}
  OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE=${OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY}.tar.gz
  OPENBAO_ROTATION_FINAL_STAGING_SIDECAR=${OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE}.sha256
}

openbao_fsync_directory() {
  local directory=$1
  safe_owned_directory "$directory" 0 || return 1
  "$PYTHON_BINARY" -I -B - "$directory" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
flags = os.O_RDONLY
for name in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_CLOEXEC'):
    flags |= getattr(os, name, 0)
descriptor = os.open(path, flags)
try:
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        raise OSError('not a directory')
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
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
  if (( candidate_count < 3 && final_count == 0 )) && \
      [[ "$marker" == false && -n "${OPENBAO_ROTATION_CANDIDATE_STAGING_ROOT:-}" &&
         ( -e "$OPENBAO_ROTATION_CANDIDATE_STAGING_ROOT" ||
           -L "$OPENBAO_ROTATION_CANDIDATE_STAGING_ROOT" ) ]]; then
    printf 'PARTIAL_CANDIDATE\n'
  elif (( candidate_count == 0 && final_count == 0 )) && \
      [[ "$marker" == false ]]; then
    printf 'MISSING\n'
  elif (( candidate_count == 3 && final_count == 0 )) && \
      [[ "$marker" == false ]]; then
    printf 'CANDIDATE\n'
  elif (( candidate_count == 3 && final_count > 0 && final_count < 3 )) && \
      [[ "$marker" == false ]]; then
    printf 'PARTIAL_FINAL\n'
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

openbao_rotation_response_file_prepare() {
  local destination=$1
  case "$destination" in
    "$OPENBAO_ROTATION_RESPONSE"|"$OPENBAO_ROTATION_STATUS_RESPONSE"|\
      "$OPENBAO_ROTATION_STATUS_STATE"|\
      "$OPENBAO_ROTATION_VERIFICATION_RESPONSE"|\
      "$OPENBAO_ROTATION_VERIFICATION_STATE") ;;
    *) return 1 ;;
  esac
  if [[ -e "$destination" || -L "$destination" ]]; then
    safe_file "$destination" 600 || return 1
    : >"$destination" || return 1
  else
    (umask 077; set -o noclobber; : >"$destination") || return 1
    chmod 600 "$destination" || return 1
  fi
  safe_file "$destination" 600
}

openbao_rotation_temp_create() {
  local directory
  [[ -z "$OPENBAO_ROTATION_TEMP_DIRECTORY" ]] || return 1
  directory=$(mktemp -d "${OPENBAO_RECOVERY_ROOT}/.openbao-rotation.XXXXXX") ||
    return 1
  OPENBAO_ROTATION_TEMP_DIRECTORY=$directory
  OPENBAO_ROTATION_RESPONSE=${directory}/response.json
  OPENBAO_ROTATION_STATUS_RESPONSE=${directory}/status.json
  OPENBAO_ROTATION_STATUS_STATE=${directory}/status.state
  OPENBAO_ROTATION_VERIFICATION_RESPONSE=${directory}/verification.json
  OPENBAO_ROTATION_VERIFICATION_STATE=${directory}/verification.state
  chmod 700 "$directory" || return 1
  safe_owned_directory "$directory" 0 || return 1
  openbao_rotation_response_file_prepare "$OPENBAO_ROTATION_RESPONSE" &&
    openbao_rotation_response_file_prepare "$OPENBAO_ROTATION_STATUS_RESPONSE" &&
    openbao_rotation_response_file_prepare "$OPENBAO_ROTATION_STATUS_STATE" &&
    openbao_rotation_response_file_prepare \
      "$OPENBAO_ROTATION_VERIFICATION_RESPONSE" &&
    openbao_rotation_response_file_prepare \
      "$OPENBAO_ROTATION_VERIFICATION_STATE"
}

openbao_rotation_temp_cleanup() {
  local directory=$OPENBAO_ROTATION_TEMP_DIRECTORY leaf
  if [[ -z "$directory" ]]; then
    return 0
  fi
  leaf=${directory##*/}
  [[ "${directory%/*}" == "$OPENBAO_RECOVERY_ROOT" &&
     "$leaf" =~ ^\.openbao-rotation\.[A-Za-z0-9]{6}$ ]] || return 1
  rm -f -- "${directory}/response.json" "${directory}/status.json" \
    "${directory}/status.state" "${directory}/verification.json" \
    "${directory}/verification.state" || return 1
  rmdir -- "$directory" || return 1
  OPENBAO_ROTATION_TEMP_DIRECTORY=
  OPENBAO_ROTATION_RESPONSE=
  OPENBAO_ROTATION_STATUS_RESPONSE=
  OPENBAO_ROTATION_STATUS_STATE=
  OPENBAO_ROTATION_VERIFICATION_RESPONSE=
  OPENBAO_ROTATION_VERIFICATION_STATE=
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

openbao_rotation_status_parse() {
  local kind=$1 response=$2 state_file=$3
  "$PYTHON_BINARY" -I -B - "$kind" "$response" "$state_file" \
    "$OPENBAO_PUBLIC_KEY_FINGERPRINT" <<'PY'
import json
import os
import re
import stat
import sys

kind, response_path, state_path, fingerprint_path = sys.argv[1:]
nonce_pattern = re.compile(r'[A-Za-z0-9_-]{8,128}')
try:
    response_stat = os.stat(response_path, follow_symlinks=False)
    if not stat.S_ISREG(response_stat.st_mode) or response_stat.st_size > 65536:
        raise ValueError
    with open(response_path, encoding='utf-8') as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError

    if kind == 'normal':
        with open(fingerprint_path, encoding='ascii') as stream:
            expected_fingerprint = stream.read().strip()
        base_fields = {
            'nonce', 'started', 't', 'n', 'progress', 'required',
            'pgp_fingerprints', 'backup', 'verification_required',
            'verification_nonce',
        }
        observed_fields = set(document)
        if observed_fields != base_fields:
            raise ValueError
        verification_nonce = document['verification_nonce']
        if (
            type(document['started']) is not bool
            or type(document['t']) is not int
            or type(document['n']) is not int
            or type(document['progress']) is not int
            or type(document['required']) is not int
            or type(document['backup']) is not bool
            or type(document['verification_required']) is not bool
            or not isinstance(document['nonce'], str)
            or not isinstance(verification_nonce, str)
        ):
            raise ValueError
        idle = (
            document['started'] is False
            and document['nonce'] == ''
            and document['t'] == 0
            and document['n'] == 0
            and document['progress'] == 0
            and document['required'] == 0
            and document['pgp_fingerprints'] is None
            and document['backup'] is False
            and document['verification_required'] is False
            and verification_nonce == ''
        )
        if idle:
            fields = ('IDLE', '', '0', '0', '')
        else:
            fingerprints = document['pgp_fingerprints']
            if (
                document['started'] is not True
                or nonce_pattern.fullmatch(document['nonce']) is None
                or document['t'] != 3
                or document['n'] != 5
                or document['required'] != 3
                or document['progress'] not in (0, 1, 2, 3)
                or not isinstance(fingerprints, list)
                or len(fingerprints) != 5
                or any(
                    not isinstance(value, str)
                    or re.fullmatch(r'(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})', value) is None
                    or value.upper() != expected_fingerprint
                    for value in fingerprints
                )
                or document['backup'] is not True
                or document['verification_required'] is not True
            ):
                raise ValueError
            if document['progress'] < 3:
                if verification_nonce != '':
                    raise ValueError
                phase = 'OLD_QUORUM_PENDING'
            else:
                if (
                    verification_nonce != ''
                    and nonce_pattern.fullmatch(verification_nonce) is None
                ):
                    raise ValueError
                phase = 'OLD_QUORUM_COMPLETE'
            fields = (
                phase,
                document['nonce'],
                str(document['progress']),
                str(document['required']),
                verification_nonce,
            )
    elif kind == 'verification':
        if set(document) != {'nonce', 'started', 't', 'n', 'progress'}:
            raise ValueError
        if (
            not isinstance(document['nonce'], str)
            or type(document['started']) is not bool
            or type(document['t']) is not int
            or type(document['n']) is not int
            or type(document['progress']) is not int
        ):
            raise ValueError
        idle = (
            document['started'] is False
            and document['nonce'] == ''
            and document['t'] == 0
            and document['n'] == 0
            and document['progress'] == 0
        )
        if idle:
            fields = ('IDLE', '', '0')
        elif (
            document['started'] is True
            and nonce_pattern.fullmatch(document['nonce']) is not None
            and document['t'] == 3
            and document['n'] == 5
            and document['progress'] in (0, 1, 2)
        ):
            fields = ('PENDING', document['nonce'], str(document['progress']))
        else:
            raise ValueError
    else:
        raise ValueError

    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(state_path, flags)
    with os.fdopen(descriptor, 'w', encoding='ascii') as stream:
        for field in fields:
            stream.write(field + '\n')
        stream.flush()
        os.fsync(stream.fileno())
except Exception:
    raise SystemExit(1)
PY
}

openbao_rotation_status() {
  local kind=$1
  local -a fields=()
  case "$kind" in
    normal)
      openbao_nonce_variables_sanitize \
        OPENBAO_ROTATION_NONCE \
        OPENBAO_ROTATION_VERIFICATION_NONCE || return 1
      OPENBAO_ROTATION_PHASE=
      OPENBAO_ROTATION_NONCE=
      OPENBAO_ROTATION_PROGRESS=
      OPENBAO_ROTATION_REQUIRED=
      OPENBAO_ROTATION_VERIFICATION_NONCE=
      openbao_rotation_response_file_prepare \
        "$OPENBAO_ROTATION_STATUS_RESPONSE" || return 1
      openbao_bao operator rotate-keys -status -format=json \
        >"$OPENBAO_ROTATION_STATUS_RESPONSE" || return 1
      openbao_rotation_response_file_prepare \
        "$OPENBAO_ROTATION_STATUS_STATE" || return 1
      openbao_rotation_status_parse normal \
        "$OPENBAO_ROTATION_STATUS_RESPONSE" \
        "$OPENBAO_ROTATION_STATUS_STATE" || return 1
      mapfile -t fields <"$OPENBAO_ROTATION_STATUS_STATE"
      : >"$OPENBAO_ROTATION_STATUS_STATE" || return 1
      [[ ${#fields[@]} == 5 ]] || return 1
      OPENBAO_ROTATION_PHASE=${fields[0]}
      OPENBAO_ROTATION_NONCE=${fields[1]}
      OPENBAO_ROTATION_PROGRESS=${fields[2]}
      OPENBAO_ROTATION_REQUIRED=${fields[3]}
      OPENBAO_ROTATION_VERIFICATION_NONCE=${fields[4]}
      ;;
    verification)
      openbao_nonce_variables_sanitize \
        OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE || return 1
      OPENBAO_ROTATION_VERIFICATION_PHASE=
      OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE=
      OPENBAO_ROTATION_VERIFICATION_PROGRESS=
      openbao_rotation_response_file_prepare \
        "$OPENBAO_ROTATION_VERIFICATION_RESPONSE" || return 1
      openbao_bao operator rotate-keys -status -verify -format=json \
        >"$OPENBAO_ROTATION_VERIFICATION_RESPONSE" || return 1
      openbao_rotation_response_file_prepare \
        "$OPENBAO_ROTATION_VERIFICATION_STATE" || return 1
      openbao_rotation_status_parse verification \
        "$OPENBAO_ROTATION_VERIFICATION_RESPONSE" \
        "$OPENBAO_ROTATION_VERIFICATION_STATE" || return 1
      mapfile -t fields <"$OPENBAO_ROTATION_VERIFICATION_STATE"
      : >"$OPENBAO_ROTATION_VERIFICATION_STATE" || return 1
      [[ ${#fields[@]} == 3 ]] || return 1
      OPENBAO_ROTATION_VERIFICATION_PHASE=${fields[0]}
      OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE=${fields[1]}
      OPENBAO_ROTATION_VERIFICATION_PROGRESS=${fields[2]}
      ;;
    *) return 1 ;;
  esac
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
  local cluster_digest=$1 fingerprint public_key_sha source_digest live_nonce=${2:-}
  local -a nonce_arguments=()
  export -n live_nonce 2>/dev/null || return 1
  openbao_rotation_artifact_paths || return 1
  openbao_source_recovery_bundle_is_valid || return 1
  safe_owned_directory "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" 0 || return 1
  safe_file "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" 600 || return 1
  safe_file "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" 600 || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  if [[ -n "$live_nonce" ]]; then
    [[ "$live_nonce" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || return 1
    nonce_arguments=(--live-nonce-stdin)
  fi
  printf '%s\n' "$live_nonce" |
    "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" validate-candidate \
    --archive "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
    --sidecar "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
    --directory "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key-sha256 "$public_key_sha" \
    --public-key-fingerprint "$fingerprint" \
    --cluster-identity-sha256 "$cluster_digest" "${nonce_arguments[@]}" || return 1
  # Restore durability after a crash at the last candidate publication fsync.
  openbao_fsync_directory "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" &&
    openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT"
}

openbao_build_rotation_candidate() {
  local response=$1 response_kind=$2 cluster_id=$3 cluster_name=$4
  local verification_nonce=${5:-} cluster_digest source_digest rc
  export -n verification_nonce 2>/dev/null || true
  openbao_rotation_artifact_paths || return 1
  openbao_source_recovery_bundle_is_valid || return 1
  safe_file "$response" 600 || return 1
  cluster_digest=$(
    openbao_cluster_identity_sha256 "$cluster_id" "$cluster_name"
  ) || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  case "$response_kind" in
    direct)
      [[ -z "$verification_nonce" ]] || return 1
      "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" build-candidate \
        --response "$response" --response-kind direct \
        --archive "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
        --sidecar "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
        --current-sha "$OPENBAO_RECOVERY_ID" \
        --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
        --source-bundle-sha256 "$source_digest" \
        --public-key "$OPENBAO_PUBLIC_KEY" \
        --public-key-fingerprint-file "$OPENBAO_PUBLIC_KEY_FINGERPRINT" \
        --cluster-id "$cluster_id" --cluster-name "$cluster_name" \
        --key-shares 5 --key-threshold 3 || return 1
      ;;
    backup)
      [[ "$verification_nonce" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || return 1
      # Keep the verification nonce out of argv and the ordinary environment.
      # The isolated bridge reads exactly one private stdin line, then calls the
      # already allowlisted Task 4 normalizer directly.
      if printf '%s\n' "$verification_nonce" |
          "$PYTHON_BINARY" -I -B -c '
import importlib.util
import pathlib
import sys

(
    helper_path,
    response_path,
    archive_path,
    sidecar_path,
    current_sha,
    source_sha,
    source_digest,
    public_key_path,
    fingerprint_path,
    cluster_id,
    cluster_name,
) = sys.argv[1:]
payload = sys.stdin.buffer.read(130)
if (
    not payload.endswith(b"\n")
    or payload.count(b"\n") != 1
    or len(payload) > 129
):
    raise SystemExit(1)
try:
    verification_nonce = payload[:-1].decode("ascii")
except UnicodeDecodeError:
    raise SystemExit(1)
spec = importlib.util.spec_from_file_location(
    "_openbao_recovery_helper", helper_path
)
if spec is None or spec.loader is None:
    raise SystemExit(1)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.build_candidate(
    response=pathlib.Path(response_path),
    response_kind="backup",
    verification_nonce=verification_nonce,
    archive=pathlib.Path(archive_path),
    sidecar=pathlib.Path(sidecar_path),
    current_sha=current_sha,
    source_sha=source_sha,
    source_bundle_sha256=source_digest,
    public_key_path=pathlib.Path(public_key_path),
    fingerprint_path=pathlib.Path(fingerprint_path),
    cluster_id=cluster_id,
    cluster_name=cluster_name,
    key_shares=5,
    key_threshold=3,
)
' "$OPENBAO_RECOVERY_HELPER" "$response" \
            "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
            "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
            "$OPENBAO_RECOVERY_ID" "$OPENBAO_SOURCE_RECOVERY_SHA" \
            "$source_digest" "$OPENBAO_PUBLIC_KEY" \
            "$OPENBAO_PUBLIC_KEY_FINGERPRINT" "$cluster_id" "$cluster_name"; then
        rc=0
      else
        rc=$?
      fi
      verification_nonce=
      unset verification_nonce
      (( rc == 0 )) || return 1
      ;;
    *) return 1 ;;
  esac
  openbao_rotation_candidate_is_valid "$cluster_digest"
}

openbao_rotation_final_paths_are_valid() {
  local cluster_digest=$1 directory=$2 archive=$3 sidecar=$4
  local fingerprint public_key_sha source_digest
  openbao_source_recovery_bundle_is_valid || return 1
  [[ "${directory##*/}" == "openbao-recovery-${OPENBAO_RECOVERY_ID}" &&
     "${archive##*/}" == "openbao-recovery-${OPENBAO_RECOVERY_ID}.tar.gz" &&
     "${sidecar##*/}" == \
       "openbao-recovery-${OPENBAO_RECOVERY_ID}.tar.gz.sha256" &&
     "${directory%/*}" == "${archive%/*}" &&
     "${directory%/*}" == "${sidecar%/*}" ]] || return 1
  safe_owned_directory "$directory" 0 || return 1
  safe_file "$archive" 600 || return 1
  safe_file "$sidecar" 600 || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" validate-final \
    --archive "$archive" \
    --sidecar "$sidecar" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key-sha256 "$public_key_sha" \
    --public-key-fingerprint "$fingerprint" \
    --cluster-identity-sha256 "$cluster_digest"
}

openbao_rotation_final_is_valid() {
  local cluster_digest=$1
  openbao_rotation_artifact_paths || return 1
  openbao_rotation_final_paths_are_valid "$cluster_digest" \
    "$OPENBAO_RECOVERY_DIRECTORY" "$OPENBAO_RECOVERY_ARCHIVE" \
    "$OPENBAO_RECOVERY_SIDECAR"
}

openbao_rotation_final_staging_cleanup() {
  local entry name
  openbao_rotation_artifact_paths || return 1
  if [[ ! -e "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" &&
        ! -L "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" ]]; then
    return 0
  fi
  safe_owned_directory "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" 0 || return 1
  while IFS= read -r name; do
    case "$name" in
      "${OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY##*/}"|\
      "${OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE##*/}"|\
      "${OPENBAO_ROTATION_FINAL_STAGING_SIDECAR##*/}") ;;
      *) return 1 ;;
    esac
  done < <(find "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" \
    -mindepth 1 -maxdepth 1 -printf '%f\n')
  if [[ -e "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" ||
        -L "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" ]]; then
    safe_owned_directory "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" 0 ||
      return 1
    while IFS= read -r name; do
      case "$name" in
        shares.json|metadata.json|openbao-recovery-public-key.b64|\
          openbao-recovery-public-key.fingerprint) ;;
        *) return 1 ;;
      esac
      safe_file "${OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY}/${name}" 600 ||
        return 1
    done < <(find "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" \
      -mindepth 1 -maxdepth 1 -printf '%f\n')
    for name in shares.json metadata.json openbao-recovery-public-key.b64 \
        openbao-recovery-public-key.fingerprint; do
      entry=${OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY}/${name}
      if [[ -e "$entry" || -L "$entry" ]]; then
        rm -f -- "$entry" || return 1
        openbao_fsync_directory \
          "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" || return 1
      fi
    done
    rmdir -- "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" || return 1
    openbao_fsync_directory "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" || return 1
  fi
  for entry in "$OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE" \
      "$OPENBAO_ROTATION_FINAL_STAGING_SIDECAR"; do
    if [[ -e "$entry" || -L "$entry" ]]; then
      safe_file "$entry" 600 || return 1
      rm -f -- "$entry" || return 1
      openbao_fsync_directory "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" ||
        return 1
    fi
  done
  rmdir -- "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT"
}

openbao_build_rotation_final() {
  local cluster_digest=$1 verified_at_utc=$2 entry fingerprint name
  local public_key_sha source_digest
  openbao_rotation_artifact_paths || return 1
  openbao_rotation_candidate_is_valid "$cluster_digest" || return 1
  [[ ! -e "$OPENBAO_RECOVERY_DIRECTORY" &&
     ! -L "$OPENBAO_RECOVERY_DIRECTORY" &&
     ! -e "$OPENBAO_RECOVERY_ARCHIVE" &&
     ! -L "$OPENBAO_RECOVERY_ARCHIVE" &&
     ! -e "$OPENBAO_RECOVERY_SIDECAR" &&
     ! -L "$OPENBAO_RECOVERY_SIDECAR" ]] || return 1
  openbao_rotation_final_staging_cleanup || return 1
  mkdir -- "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" || return 1
  chmod 700 "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  public_key_sha=$(sha256_file "$OPENBAO_PUBLIC_KEY") || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  fingerprint=$(<"$OPENBAO_PUBLIC_KEY_FINGERPRINT") || return 1
  "$PYTHON_BINARY" -I -B "$OPENBAO_RECOVERY_HELPER" build-final \
    --candidate-archive "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
    --candidate-sidecar "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
    --archive "$OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE" \
    --sidecar "$OPENBAO_ROTATION_FINAL_STAGING_SIDECAR" \
    --current-sha "$OPENBAO_RECOVERY_ID" \
    --source-sha "$OPENBAO_SOURCE_RECOVERY_SHA" \
    --source-bundle-sha256 "$source_digest" \
    --public-key-sha256 "$public_key_sha" \
    --public-key-fingerprint "$fingerprint" \
    --cluster-identity-sha256 "$cluster_digest" \
    --verified-at-utc "$verified_at_utc" || return 1
  openbao_rotation_final_paths_are_valid "$cluster_digest" \
    "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" \
    "$OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE" \
    "$OPENBAO_ROTATION_FINAL_STAGING_SIDECAR" || return 1
  openbao_fsync_directory "$OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY" ||
    return 1
  openbao_fsync_directory "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" || return 1

  mkdir -- "$OPENBAO_RECOVERY_DIRECTORY" || return 1
  chmod 700 "$OPENBAO_RECOVERY_DIRECTORY" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  for name in shares.json metadata.json openbao-recovery-public-key.b64 \
      openbao-recovery-public-key.fingerprint; do
    entry=${OPENBAO_ROTATION_FINAL_STAGING_DIRECTORY}/${name}
    safe_file "$entry" 600 || return 1
    ln -- "$entry" "${OPENBAO_RECOVERY_DIRECTORY}/${name}" || return 1
    openbao_fsync_directory "$OPENBAO_RECOVERY_DIRECTORY" || return 1
  done
  ln -- "$OPENBAO_ROTATION_FINAL_STAGING_ARCHIVE" \
    "$OPENBAO_RECOVERY_ARCHIVE" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  # The sidecar is published last. A three-of-three top-level shape therefore
  # cannot appear until every canonical object already has its final bytes.
  ln -- "$OPENBAO_ROTATION_FINAL_STAGING_SIDECAR" \
    "$OPENBAO_RECOVERY_SIDECAR" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  openbao_rotation_final_is_valid "$cluster_digest" || return 1
  openbao_rotation_final_staging_cleanup || return 1
  openbao_rotation_final_is_valid "$cluster_digest"
}

openbao_rotation_verified_marker_file_is_valid() {
  local marker=$1 cluster_digest=$2 final_digest
  safe_file "$marker" 600 || return 1
  safe_file "$OPENBAO_RECOVERY_ARCHIVE" 600 || return 1
  final_digest=$(sha256_file "$OPENBAO_RECOVERY_ARCHIVE") || return 1
  "$PYTHON_BINARY" -I -B - "$marker" "$OPENBAO_RECOVERY_ID" \
    "$OPENBAO_SOURCE_RECOVERY_SHA" "$final_digest" "$cluster_digest" <<'PY'
import hmac
import json
import re
import sys

marker, current_sha, source_sha, final_digest, cluster_digest = sys.argv[1:]
try:
    with open(marker, encoding='utf-8') as stream:
        document = json.load(stream)
    expected = {
        'schema': 'engineering-platform/openbao-rotation-verification/v1',
        'git_commit': current_sha,
        'source_recovery_sha': source_sha,
        'final_bundle_sha256': final_digest,
        'cluster_identity_sha256': cluster_digest,
        'rotation_state': 'verified',
        'initial_root_token': 'revoked',
    }
    if (
        not re.fullmatch(r'[0-9a-f]{40}', current_sha)
        or not re.fullmatch(r'[0-9a-f]{40}', source_sha)
        or not re.fullmatch(r'[0-9a-f]{64}', final_digest)
        or not re.fullmatch(r'[0-9a-f]{64}', cluster_digest)
        or set(document) != set(expected)
        or any(
            not isinstance(document[key], str)
            or not hmac.compare_digest(document[key], value)
            for key, value in expected.items()
        )
    ):
        raise ValueError
except Exception:
    raise SystemExit(1)
PY
}

openbao_rotation_verified_marker_is_valid() {
  local cluster_digest=$1
  openbao_rotation_artifact_paths || return 1
  openbao_rotation_final_is_valid "$cluster_digest" || return 1
  openbao_rotation_verified_marker_file_is_valid \
    "$OPENBAO_ROTATION_VERIFIED_MARKER" "$cluster_digest"
}

openbao_rotation_verified_marker_create() {
  local cluster_digest=$1 final_digest marker_temp
  openbao_rotation_artifact_paths || return 1
  openbao_rotation_final_is_valid "$cluster_digest" || return 1
  [[ ! -e "$OPENBAO_ROTATION_VERIFIED_MARKER" &&
     ! -L "$OPENBAO_ROTATION_VERIFIED_MARKER" ]] || return 1
  final_digest=$(sha256_file "$OPENBAO_RECOVERY_ARCHIVE") || return 1
  marker_temp=$(mktemp \
    "${OPENBAO_RECOVERY_ROOT}/.openbao-rotation-marker.XXXXXX") || return 1
  chmod 600 "$marker_temp" || { rm -f -- "$marker_temp"; return 1; }
  if ! "$PYTHON_BINARY" -I -B - "$marker_temp" "$OPENBAO_RECOVERY_ID" \
      "$OPENBAO_SOURCE_RECOVERY_SHA" "$final_digest" \
      "$cluster_digest" <<'PY'
import json
import os
import sys

marker, current_sha, source_sha, final_digest, cluster_digest = sys.argv[1:]
document = {
    'schema': 'engineering-platform/openbao-rotation-verification/v1',
    'git_commit': current_sha,
    'source_recovery_sha': source_sha,
    'final_bundle_sha256': final_digest,
    'cluster_identity_sha256': cluster_digest,
    'rotation_state': 'verified',
    'initial_root_token': 'revoked',
}
with open(marker, 'w', encoding='utf-8') as stream:
    json.dump(document, stream, ensure_ascii=True, separators=(',', ':'), sort_keys=True)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())
PY
  then
    rm -f -- "$marker_temp"
    return 1
  fi
  openbao_rotation_verified_marker_file_is_valid \
    "$marker_temp" "$cluster_digest" || {
      rm -f -- "$marker_temp"
      return 1
    }
  # A same-filesystem hard link is an atomic noclobber publish. Unlike
  # `mv -n`, link(2) fails when another process wins the destination race.
  ln -- "$marker_temp" "$OPENBAO_ROTATION_VERIFIED_MARKER" || {
    rm -f -- "$marker_temp"
    return 1
  }
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  rm -f -- "$marker_temp" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  openbao_rotation_verified_marker_is_valid "$cluster_digest"
}

openbao_rotation_partial_final_cleanup() {
  local entry name state
  [[ "$(openbao_rotation_artifact_presence_state)" == PARTIAL_FINAL ]] ||
    return 1
  for entry in "$OPENBAO_RECOVERY_ARCHIVE" "$OPENBAO_RECOVERY_SIDECAR"; do
    if [[ -e "$entry" || -L "$entry" ]]; then
      safe_file "$entry" 600 || return 1
    fi
  done
  if [[ -e "$OPENBAO_RECOVERY_DIRECTORY" ||
        -L "$OPENBAO_RECOVERY_DIRECTORY" ]]; then
    safe_owned_directory "$OPENBAO_RECOVERY_DIRECTORY" 0 || return 1
    while IFS= read -r name; do
      case "$name" in
        shares.json|metadata.json|openbao-recovery-public-key.b64|\
          openbao-recovery-public-key.fingerprint) ;;
        *) return 1 ;;
      esac
      safe_file "${OPENBAO_RECOVERY_DIRECTORY}/${name}" 600 || return 1
    done < <(find "$OPENBAO_RECOVERY_DIRECTORY" -mindepth 1 -maxdepth 1 \
      -printf '%f\n')
    for name in shares.json metadata.json openbao-recovery-public-key.b64 \
        openbao-recovery-public-key.fingerprint; do
      entry=${OPENBAO_RECOVERY_DIRECTORY}/${name}
      if [[ -e "$entry" || -L "$entry" ]]; then
        rm -f -- "$entry" || return 1
        openbao_fsync_directory "$OPENBAO_RECOVERY_DIRECTORY" || return 1
      fi
    done
    rmdir -- "$OPENBAO_RECOVERY_DIRECTORY" || return 1
    openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  fi
  for entry in "$OPENBAO_RECOVERY_ARCHIVE" "$OPENBAO_RECOVERY_SIDECAR"; do
    if [[ -e "$entry" || -L "$entry" ]]; then
      rm -f -- "$entry" || return 1
      openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
    fi
  done
  state=$(openbao_rotation_artifact_presence_state) || return 1
  [[ "$state" == CANDIDATE ]]
}

openbao_finalization_transaction_binding() {
  local cluster_digest=$1 candidate_digest source_digest
  [[ "$cluster_digest" =~ ^[0-9a-f]{64}$ ]] || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  candidate_digest=$(sha256_file "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE") ||
    return 1
  "$PYTHON_BINARY" -I -B - "$OPENBAO_RECOVERY_ID" \
    "$OPENBAO_SOURCE_RECOVERY_SHA" "$source_digest" "$candidate_digest" \
    "$cluster_digest" <<'PY'
import hashlib
import json
import re
import sys

current, source, source_digest, candidate_digest, cluster_digest = sys.argv[1:]
values = (current, source, source_digest, candidate_digest, cluster_digest)
if (
    re.fullmatch(r'[0-9a-f]{40}', current) is None
    or re.fullmatch(r'[0-9a-f]{40}', source) is None
    or any(re.fullmatch(r'[0-9a-f]{64}', value) is None for value in values[2:])
):
    raise SystemExit(1)
payload = json.dumps(
    {
        'candidate_bundle_sha256': candidate_digest,
        'cluster_identity_sha256': cluster_digest,
        'git_commit': current,
        'live_rotation_state': 'idle-no-pending',
        'source_bundle_sha256': source_digest,
        'source_recovery_sha': source,
    },
    ensure_ascii=True,
    separators=(',', ':'),
    sort_keys=True,
).encode('ascii')
print(hashlib.sha256(payload).hexdigest())
PY
}

openbao_root_session_binding_create() {
  local binding=$1 path=$OPENBAO_REMOTE_HOME
  [[ "$OPENBAO_REMOTE_SESSION_KIND" == root &&
     "$path" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ &&
     "$binding" =~ ^[0-9a-f]{64}$ ]] || return 1
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c '
set -eu
umask 077
uid=$(id -u)
[ -d "$1" ] && [ ! -L "$1" ]
[ "$(stat -c %a "$1")" = 700 ]
[ "$(stat -c %u "$1")" = "$uid" ]
[ -f "$1/.bao-token" ] && [ ! -L "$1/.bao-token" ]
[ "$(stat -c %a "$1/.bao-token")" = 600 ]
[ "$(stat -c %u "$1/.bao-token")" = "$uid" ]
path=$1/.openbao-session-binding
[ ! -e "$path" ] && [ ! -L "$path" ]
(set -C; printf "%s\n" "$2" >"$path")
chmod 600 "$path"
[ "$(stat -c %u "$path")" = "$uid" ]
[ "$(wc -l <"$path")" -eq 1 ]
[ "$(cat "$path")" = "$2" ]
' bind-root-helper "$path" "$binding" >/dev/null 2>&1
}

openbao_root_token_sha256() {
  local digest path=$OPENBAO_REMOTE_HOME
  [[ "$OPENBAO_REMOTE_SESSION_KIND" == root &&
     "$path" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ ]] || return 1
  # The token file never crosses the container boundary; only its SHA-256
  # commitment is returned.
  # The single-quoted program is expanded by the remote /bin/sh.
  # shellcheck disable=SC2016
  digest=$(kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c \
    'set -eu; umask 077; test -f "$1/.bao-token"; test ! -L "$1/.bao-token"; stat -c %a "$1/.bao-token" | grep -qx 600; sha256sum "$1/.bao-token" | awk '\''{print $1}'\''' \
    root-token-commitment "$path" 2>/dev/null) || return 1
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || return 1
  printf '%s\n' "$digest"
}

openbao_finalization_ready_checkpoint_file_is_valid() {
  local file=$1 cluster_digest=$2 candidate_digest expected_binding source_digest
  safe_file "$file" 600 || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  candidate_digest=$(sha256_file "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE") ||
    return 1
  expected_binding=$(
    openbao_finalization_transaction_binding "$cluster_digest"
  ) || return 1
  "$PYTHON_BINARY" -I -B - "$file" "$OPENBAO_RECOVERY_ID" \
    "$OPENBAO_SOURCE_RECOVERY_SHA" "$source_digest" "$candidate_digest" \
    "$cluster_digest" "$expected_binding" <<'PY'
import hmac
import json
import re
import sys

(
    path, current, source, source_digest, candidate_digest, cluster_digest,
    expected_binding,
) = sys.argv[1:]
try:
    with open(path, encoding='utf-8') as stream:
        document = json.load(stream)
    expected = {
        'schema': 'engineering-platform/openbao-finalization/v1',
        'state': 'ready-to-revoke',
        'git_commit': current,
        'source_recovery_sha': source,
        'source_bundle_sha256': source_digest,
        'candidate_bundle_sha256': candidate_digest,
        'cluster_identity_sha256': cluster_digest,
        'live_rotation_state': 'idle-no-pending',
        'remote_session_binding': expected_binding,
    }
    if set(document) != set(expected) | {
        'root_token_sha256', 'remote_home'
    }:
        raise ValueError
    if any(
        not isinstance(document[key], str)
        or not hmac.compare_digest(document[key], value)
        for key, value in expected.items()
    ):
        raise ValueError
    if re.fullmatch(r'[0-9a-f]{64}', document['root_token_sha256']) is None:
        raise ValueError
    if re.fullmatch(
        r'/tmp/openbao-stage180\.[A-Za-z0-9]{6}', document['remote_home']
    ) is None:
        raise ValueError
except Exception:
    raise SystemExit(1)
PY
}

openbao_finalization_ready_checkpoint_load() {
  local cluster_digest=$1
  local -a fields=()
  openbao_finalization_ready_checkpoint_file_is_valid \
    "$OPENBAO_ROTATION_READY_CHECKPOINT" "$cluster_digest" || return 1
  mapfile -t fields < <(
    "$PYTHON_BINARY" -I -B - "$OPENBAO_ROTATION_READY_CHECKPOINT" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as stream:
    document = json.load(stream)
for key in ('root_token_sha256', 'remote_home', 'remote_session_binding'):
    print(document[key])
PY
  ) || return 1
  [[ ${#fields[@]} == 3 ]] || return 1
  openbao_nonce_variables_sanitize \
    OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256 \
    OPENBAO_FINALIZATION_REMOTE_HOME \
    OPENBAO_FINALIZATION_REMOTE_BINDING || return 1
  OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256=${fields[0]}
  OPENBAO_FINALIZATION_REMOTE_HOME=${fields[1]}
  OPENBAO_FINALIZATION_REMOTE_BINDING=${fields[2]}
}

openbao_finalization_ready_checkpoint_create() {
  local cluster_digest=$1 token_digest=$2 remote_home=$3 binding=$4
  local candidate_digest source_digest temporary
  openbao_rotation_artifact_paths || return 1
  safe_owned_directory "$OPENBAO_RECOVERY_ROOT" 0 || return 1
  [[ "$cluster_digest" =~ ^[0-9a-f]{64}$ &&
     "$token_digest" =~ ^[0-9a-f]{64}$ &&
     "$remote_home" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ &&
     "$binding" =~ ^[0-9a-f]{64}$ ]] || return 1
  [[ ! -e "$OPENBAO_ROTATION_READY_CHECKPOINT" &&
     ! -L "$OPENBAO_ROTATION_READY_CHECKPOINT" &&
     ! -e "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" &&
     ! -L "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" ]] || return 1
  source_digest=$(sha256_file "$OPENBAO_SOURCE_RECOVERY_ARCHIVE") || return 1
  candidate_digest=$(sha256_file "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE") ||
    return 1
  temporary=$(mktemp \
    "${OPENBAO_RECOVERY_ROOT}/.openbao-finalization-ready.XXXXXX") || return 1
  chmod 600 "$temporary" || { rm -f -- "$temporary"; return 1; }
  if ! "$PYTHON_BINARY" -I -B - "$temporary" "$OPENBAO_RECOVERY_ID" \
      "$OPENBAO_SOURCE_RECOVERY_SHA" "$source_digest" "$candidate_digest" \
      "$cluster_digest" "$token_digest" "$remote_home" "$binding" <<'PY'
import json
import os
import sys

(
    path, current, source, source_digest, candidate_digest, cluster_digest,
    token_digest, remote_home, binding,
) = sys.argv[1:]
document = {
    'schema': 'engineering-platform/openbao-finalization/v1',
    'state': 'ready-to-revoke',
    'git_commit': current,
    'source_recovery_sha': source,
    'source_bundle_sha256': source_digest,
    'candidate_bundle_sha256': candidate_digest,
    'cluster_identity_sha256': cluster_digest,
    'live_rotation_state': 'idle-no-pending',
    'root_token_sha256': token_digest,
    'remote_home': remote_home,
    'remote_session_binding': binding,
}
with open(path, 'w', encoding='utf-8') as stream:
    json.dump(document, stream, ensure_ascii=True, separators=(',', ':'), sort_keys=True)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())
PY
  then
    rm -f -- "$temporary"
    return 1
  fi
  openbao_finalization_ready_checkpoint_file_is_valid \
    "$temporary" "$cluster_digest" || { rm -f -- "$temporary"; return 1; }
  ln -- "$temporary" "$OPENBAO_ROTATION_READY_CHECKPOINT" || {
    rm -f -- "$temporary"
    return 1
  }
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  rm -f -- "$temporary" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  openbao_finalization_ready_checkpoint_load "$cluster_digest"
}

openbao_finalization_revoked_checkpoint_file_is_valid() {
  local file=$1 cluster_digest=$2 ready_digest
  openbao_finalization_ready_checkpoint_load "$cluster_digest" || return 1
  safe_file "$file" 600 || return 1
  ready_digest=$(sha256_file "$OPENBAO_ROTATION_READY_CHECKPOINT") || return 1
  "$PYTHON_BINARY" -I -B - "$file" "$ready_digest" \
    "$OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256" <<'PY'
import hmac
import json
import re
import sys

path, ready_digest, token_digest = sys.argv[1:]
try:
    with open(path, encoding='utf-8') as stream:
        document = json.load(stream)
    expected = {
        'schema': 'engineering-platform/openbao-finalization/v1',
        'state': 'root-revoked',
        'ready_checkpoint_sha256': ready_digest,
        'root_token_sha256': token_digest,
    }
    if set(document) != set(expected):
        raise ValueError
    if any(
        not isinstance(document[key], str)
        or not hmac.compare_digest(document[key], value)
        for key, value in expected.items()
    ):
        raise ValueError
    if any(
        re.fullmatch(r'[0-9a-f]{64}', document[key]) is None
        for key in ('ready_checkpoint_sha256', 'root_token_sha256')
    ):
        raise ValueError
except Exception:
    raise SystemExit(1)
PY
}

openbao_finalization_revoked_checkpoint_create() {
  local cluster_digest=$1 ready_digest temporary
  openbao_finalization_ready_checkpoint_load "$cluster_digest" || return 1
  [[ ! -e "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" &&
     ! -L "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" ]] || return 1
  ready_digest=$(sha256_file "$OPENBAO_ROTATION_READY_CHECKPOINT") || return 1
  temporary=$(mktemp \
    "${OPENBAO_RECOVERY_ROOT}/.openbao-finalization-revoked.XXXXXX") || return 1
  chmod 600 "$temporary" || { rm -f -- "$temporary"; return 1; }
  if ! "$PYTHON_BINARY" -I -B - "$temporary" "$ready_digest" \
      "$OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256" <<'PY'
import json
import os
import sys

path, ready_digest, token_digest = sys.argv[1:]
document = {
    'schema': 'engineering-platform/openbao-finalization/v1',
    'state': 'root-revoked',
    'ready_checkpoint_sha256': ready_digest,
    'root_token_sha256': token_digest,
}
with open(path, 'w', encoding='utf-8') as stream:
    json.dump(document, stream, ensure_ascii=True, separators=(',', ':'), sort_keys=True)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())
PY
  then
    rm -f -- "$temporary"
    return 1
  fi
  openbao_finalization_revoked_checkpoint_file_is_valid \
    "$temporary" "$cluster_digest" || { rm -f -- "$temporary"; return 1; }
  ln -- "$temporary" "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" || {
    rm -f -- "$temporary"
    return 1
  }
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  rm -f -- "$temporary" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  openbao_finalization_revoked_checkpoint_file_is_valid \
    "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" "$cluster_digest"
}

openbao_finalization_checkpoint_state() {
  local cluster_digest=$1 ready=false revoked=false
  openbao_rotation_artifact_paths || return 1
  [[ -e "$OPENBAO_ROTATION_READY_CHECKPOINT" ||
     -L "$OPENBAO_ROTATION_READY_CHECKPOINT" ]] && ready=true
  [[ -e "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" ||
     -L "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" ]] && revoked=true
  case "$ready:$revoked" in
    false:false) printf 'NONE\n' ;;
    true:false)
      if openbao_finalization_ready_checkpoint_load "$cluster_digest"; then
        printf 'READY\n'
      else
        printf 'UNSAFE\n'
      fi
      ;;
    true:true)
      if openbao_finalization_revoked_checkpoint_file_is_valid \
          "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" "$cluster_digest"; then
        printf 'REVOKED\n'
      else
        printf 'UNSAFE\n'
      fi
      ;;
    *) printf 'UNSAFE\n' ;;
  esac
}

openbao_finalization_checkpoint_cleanup() {
  local cluster_digest=$1 state
  state=$(openbao_finalization_checkpoint_state "$cluster_digest") || return 1
  [[ "$state" == READY || "$state" == REVOKED ]] || return 1
  if [[ "$state" == REVOKED ]]; then
    rm -f -- "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" || return 1
    openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  fi
  rm -f -- "$OPENBAO_ROTATION_READY_CHECKPOINT" || return 1
  openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" || return 1
  openbao_nonce_variables_sanitize \
    OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256 \
    OPENBAO_FINALIZATION_REMOTE_HOME \
    OPENBAO_FINALIZATION_REMOTE_BINDING || return 1
  [[ "$(openbao_finalization_checkpoint_state "$cluster_digest")" == NONE ]]
}

openbao_finalization_resume_root_revocation() {
  local token_digest=$1
  set +x
  [[ "$token_digest" =~ ^[0-9a-f]{64}$ ]] || return 1
  openbao_require_interactive_tty || return 1
  # v2.6.1 storage-only login uses its own actual hidden TTY handler. Store
  # success is NOT authentication proof. Suppress stdout BEFORE TTY merging:
  # even -no-print may otherwise print the token on a token-helper Store error.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec --stdin --tty pod/openbao-0 -- /bin/sh -c '
set -eu
umask 077
home=$(mktemp -d /tmp/openbao-stage180-resume.XXXXXX)
error= status=
cleanup() {
  rc=$?
  trap - EXIT HUP INT TERM
  rm -f -- "$home/.bao-token" || rc=1
  [ -z "$error" ] || rm -f -- "$error" || rc=1
  [ -z "$status" ] || rm -f -- "$status" || rc=1
  rmdir -- "$home" || rc=1
  exit "$rc"
}
trap cleanup EXIT
trap '\''exit 129'\'' HUP
trap '\''exit 130'\'' INT
trap '\''exit 143'\'' TERM
error=$(mktemp /tmp/openbao-root-resume.XXXXXX)
status=$(mktemp /tmp/openbao-root-resume-status.XXXXXX)
env HOME="$home" \
  BAO_ADDR=https://openbao.openbao.svc:8200 \
  BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
  bao login -no-print lookup=false >/dev/null
[ -f "$home/.bao-token" ] && [ ! -L "$home/.bao-token" ]
[ "$(stat -c %a "$home/.bao-token")" = 600 ]
actual=$(sha256sum "$home/.bao-token" | awk '\''{print $1}'\'')
[ "$actual" = "$1" ]
lookup() {
  : >"$error"
  : >"$status"
  (
    set +e
    env HOME="$home" \
      BAO_ADDR=https://openbao.openbao.svc:8200 \
      BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
      bao token lookup -format=json >/dev/null
    printf "%s\n" "$?" >"$status"
    exit 0
  ) 2>&1 | head -c 4097 >"$error"
  rc=$(cat "$status")
  case "$rc" in ""|*[!0-9]*) return 1 ;; esac
  return "$rc"
}
exact_denial() {
  bytes=$(wc -c <"$error")
  [ "$bytes" -gt 0 ] && [ "$bytes" -le 4096 ] || return 1
  grep -Fqx "Code: 403. Errors:" "$error" || return 1
  grep -Fqx "* permission denied" "$error"
}
if lookup; then
  env HOME="$home" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao token revoke -self >/dev/null 2>&1 || exit 1
  if lookup; then
    exit 1
  fi
  exact_denial
else
  exact_denial
fi
' resume-root-revocation "$token_digest"
}

openbao_finalization_remote_helper_cleanup() {
  local binding=$OPENBAO_FINALIZATION_REMOTE_BINDING
  local path=$OPENBAO_FINALIZATION_REMOTE_HOME
  [[ "$path" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ &&
     "$binding" =~ ^[0-9a-f]{64}$ ]] || return 1
  # Missing means an earlier ordinary cleanup already removed this exact
  # helper. A reused path is rejected unless its binding sentinel matches.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c '
set -eu
path=$1
binding=$2
uid=$(id -u)
if [ ! -e "$path" ] && [ ! -L "$path" ]; then
  exit 0
fi
[ -d "$path" ] && [ ! -L "$path" ]
[ "$(stat -c %a "$path")" = 700 ]
[ "$(stat -c %u "$path")" = "$uid" ]
[ -f "$path/.openbao-session-binding" ] && [ ! -L "$path/.openbao-session-binding" ]
[ "$(stat -c %a "$path/.openbao-session-binding")" = 600 ]
[ "$(stat -c %u "$path/.openbao-session-binding")" = "$uid" ]
[ "$(wc -l <"$path/.openbao-session-binding")" -eq 1 ]
[ "$(cat "$path/.openbao-session-binding")" = "$binding" ]
if [ -e "$path/.bao-token" ] || [ -L "$path/.bao-token" ]; then
  [ -f "$path/.bao-token" ] && [ ! -L "$path/.bao-token" ]
  [ "$(stat -c %a "$path/.bao-token")" = 600 ]
  [ "$(stat -c %u "$path/.bao-token")" = "$uid" ]
fi
rm -f -- "$path/.bao-token" "$path/.openbao-session-binding"
rmdir -- "$path"
' cleanup-finalized-root "$path" "$binding" >/dev/null 2>&1 || return 1
  if [[ "$OPENBAO_REMOTE_HOME" == "$path" ]]; then
    OPENBAO_REMOTE_HOME=
    OPENBAO_REMOTE_SESSION_KIND=
  fi
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
  # This wrapper is reserved for hidden root login; discard CLI stdout inside
  # the container, before kubectl multiplexes the remote terminal streams.
  [[ "$*" == 'login -no-print' ]] || return 1
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec --stdin --tty pod/openbao-0 -- env \
    HOME="$OPENBAO_REMOTE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    /bin/sh -c 'exec bao login -no-print >/dev/null'
}

openbao_bao_stdin() {
  kubectl_run --namespace=openbao exec -i pod/openbao-0 -- env \
    HOME="$OPENBAO_REMOTE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_live_cluster_identity() {
  local -a identity=()
  mapfile -t identity < <(
    openbao_status_json | "$PYTHON_BINARY" -I -B -c '
import json
import re
import sys

document = json.load(sys.stdin)
cluster_id = document.get("cluster_id")
cluster_name = document.get("cluster_name")
if (
    not isinstance(cluster_id, str)
    or re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        cluster_id,
    ) is None
    or not isinstance(cluster_name, str)
    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", cluster_name) is None
):
    raise SystemExit(1)
print(cluster_id)
print(cluster_name)
'
  ) || return 1
  [[ ${#identity[@]} == 2 ]] || return 1
  OPENBAO_CLUSTER_ID=${identity[0]}
  OPENBAO_CLUSTER_NAME=${identity[1]}
}

openbao_rotation_initialize() {
  local response=$1
  [[ "$OPENBAO_REMOTE_SESSION_KIND" == root &&
     "$OPENBAO_REMOTE_HOME" =~ ^/tmp/openbao-stage180\.[A-Za-z0-9]{6}$ ]] ||
    return 1
  openbao_rotation_response_file_prepare "$response" || return 1
  # The public key is copied into a private remote temporary file that is
  # removed by the same remote process before kubectl returns.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec -i pod/openbao-0 -- /bin/sh -c '
set -eu
umask 077
key=$(mktemp /tmp/openbao-rotation-pgp.XXXXXX)
trap '\''rm -f -- "$key"'\'' EXIT HUP INT TERM
cat >"$key"
chmod 600 "$key"
pgp_keys=$(printf '\''%s,%s,%s,%s,%s'\'' "$key" "$key" "$key" "$key" "$key")
env HOME="$1" \
  BAO_ADDR=https://openbao.openbao.svc:8200 \
  BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
  bao operator rotate-keys -format=json -init -verify -backup \
    -key-shares=5 -key-threshold=3 "-pgp-keys=${pgp_keys}"
' rotation-init "$OPENBAO_REMOTE_HOME" <"$OPENBAO_PUBLIC_KEY" >"$response"
}

openbao_rotation_submit_share() {
  local rotation_nonce=$1 response=$2 rc
  set +x
  [[ "$rotation_nonce" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || return 1
  openbao_rotation_response_file_prepare "$response" || return 1
  if ! openbao_prompt_secret \
      'Paste one of the three other old unseal shares (hidden): '; then
    OPENBAO_SECRET_INPUT=
    unset OPENBAO_SECRET_INPUT
    return 1
  fi
  if ! export -n OPENBAO_SECRET_INPUT 2>/dev/null; then
    OPENBAO_SECRET_INPUT=
    unset OPENBAO_SECRET_INPUT
    return 1
  fi
  if printf '%s\n' "$OPENBAO_SECRET_INPUT" |
      openbao_bao_stdin operator rotate-keys -format=json \
        "-nonce=${rotation_nonce}" - >"$response"; then
    rc=0
  else
    rc=$?
  fi
  OPENBAO_SECRET_INPUT=
  unset OPENBAO_SECRET_INPUT
  (( rc == 0 ))
}

openbao_rotation_verification_submit_share() {
  local verification_nonce=$1 response=$2 rc
  set +x
  [[ "$verification_nonce" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || return 1
  openbao_rotation_response_file_prepare "$response" || return 1
  if ! openbao_prompt_secret \
      'Paste one new unseal share for rotation verification (hidden): '; then
    OPENBAO_SECRET_INPUT=
    unset OPENBAO_SECRET_INPUT
    return 1
  fi
  if ! export -n OPENBAO_SECRET_INPUT 2>/dev/null; then
    OPENBAO_SECRET_INPUT=
    unset OPENBAO_SECRET_INPUT
    return 1
  fi
  if printf '%s\n' "$OPENBAO_SECRET_INPUT" |
      openbao_bao_stdin operator rotate-keys -format=json -verify \
        "-nonce=${verification_nonce}" - >"$response"; then
    rc=0
  else
    rc=$?
  fi
  OPENBAO_SECRET_INPUT=
  unset OPENBAO_SECRET_INPUT
  (( rc == 0 ))
}

openbao_rotation_backup_delete() {
  openbao_bao operator rotate-keys -backup-delete >/dev/null
}

openbao_rotation_backup_retrieve() {
  local response=$1
  openbao_rotation_response_file_prepare "$response" || return 1
  openbao_bao operator rotate-keys -format=json -backup-retrieve >"$response"
}

openbao_rotation_capture_candidate() {
  local response=$1 response_kind=$2 cluster_id=$3 cluster_name=$4
  local verification_nonce=$5
  case "$response_kind" in
    direct)
      [[ -z "$verification_nonce" ]] || return 1
      openbao_build_rotation_candidate "$response" direct \
        "$cluster_id" "$cluster_name"
      ;;
    backup)
      [[ "$verification_nonce" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || return 1
      openbao_build_rotation_candidate "$response" backup \
        "$cluster_id" "$cluster_name" "$verification_nonce"
      ;;
    *) return 1 ;;
  esac
}

openbao_rotation_candidate_nonce_matches_live() {
  local live_nonce=$1 cluster_digest=$2
  export -n live_nonce 2>/dev/null || return 1
  [[ "$live_nonce" =~ ^[A-Za-z0-9_-]{8,128}$ ]] || return 1
  openbao_rotation_candidate_is_valid "$cluster_digest" "$live_nonce"
}

openbao_remote_session_cleanup() {
  local path=$OPENBAO_REMOTE_HOME kind=$OPENBAO_REMOTE_SESSION_KIND
  if [[ -z "$path" ]]; then
    [[ -z "$kind" ]] || return 1
    return 0
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
    'rm -f -- "$1/.bao-token" "$1/.openbao-session-binding"; rmdir -- "$1"' \
    cleanup "$path" \
    >/dev/null 2>&1 || return 1
  OPENBAO_REMOTE_HOME=
  OPENBAO_REMOTE_SESSION_KIND=
}

openbao_recover_probe_home_create() {
  local path
  [[ -z "$OPENBAO_RECOVER_PROBE_HOME" &&
     -z "$OPENBAO_RECOVER_PROBE_SESSION_KIND" ]] || return 1
  path=$(kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c \
    'umask 077; mktemp -d /tmp/openbao-stage180-probe.XXXXXX') || return 1
  [[ "$path" =~ ^/tmp/openbao-stage180-probe\.[A-Za-z0-9]{6}$ ]] || return 1
  OPENBAO_RECOVER_PROBE_HOME=$path
  OPENBAO_RECOVER_PROBE_SESSION_KIND=pending
}

openbao_bao_recover_probe() {
  kubectl_run --namespace=openbao exec pod/openbao-0 -- env \
    HOME="$OPENBAO_RECOVER_PROBE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_bao_recover_probe_stdin() {
  kubectl_run --namespace=openbao exec -i pod/openbao-0 -- env \
    HOME="$OPENBAO_RECOVER_PROBE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_recover_probe_cleanup() {
  local path=$OPENBAO_RECOVER_PROBE_HOME
  local kind=$OPENBAO_RECOVER_PROBE_SESSION_KIND
  if [[ -z "$path" ]]; then
    [[ -z "$kind" ]] || return 1
    return 0
  fi
  [[ "$path" =~ ^/tmp/openbao-stage180-probe\.[A-Za-z0-9]{6}$ ]] || return 1
  if [[ "$kind" == authenticated ]]; then
    openbao_bao_recover_probe token revoke -self >/dev/null 2>&1 || return 1
    OPENBAO_RECOVER_PROBE_SESSION_KIND=pending
  elif [[ "$kind" != pending ]]; then
    return 1
  fi
  # $1 is intentionally expanded by the remote shell.
  # shellcheck disable=SC2016
  kubectl_run --namespace=openbao exec pod/openbao-0 -- /bin/sh -c \
    'rm -f -- "$1/.bao-token"; rmdir -- "$1"' cleanup "$path" \
    >/dev/null 2>&1 || return 1
  OPENBAO_RECOVER_PROBE_HOME=
  OPENBAO_RECOVER_PROBE_SESSION_KIND=
}

openbao_recover_auth_probe() {
  local observed rc=0
  openbao_recover_probe_home_create || return 1
  if kubectl_run --namespace=openbao create token openbao-runtime-probe \
      --audience=openbao --duration=10m |
      openbao_bao_recover_probe_stdin write -field=token \
        auth/kubernetes/login role=openbao-runtime-probe jwt=- |
      openbao_bao_recover_probe_stdin login -no-print >/dev/null; then
    OPENBAO_RECOVER_PROBE_SESSION_KIND=authenticated
  else
    openbao_recover_probe_cleanup || true
    return 1
  fi
  set +e
  openbao_bao_recover_probe kv put openbao-probe/runtime-check \
    value="$OPENBAO_PROBE_VALUE" >/dev/null || rc=1
  observed=$(openbao_bao_recover_probe kv get -field=value \
    openbao-probe/runtime-check 2>/dev/null) || rc=1
  [[ "$observed" == "$OPENBAO_PROBE_VALUE" ]] || rc=1
  if openbao_bao_recover_probe read sys/auth >/dev/null 2>&1; then
    rc=1
  fi
  openbao_bao_recover_probe operator raft list-peers -format=json |
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
  openbao_bao_recover_probe kv delete openbao-probe/runtime-check \
    >/dev/null || rc=1
  openbao_recover_probe_cleanup || rc=1
  set -e
  (( rc == 0 ))
}

openbao_initialize_cleanup() {
  local rc=0
  set +x
  OPENBAO_SECRET_INPUT=
  unset OPENBAO_SECRET_INPUT
  openbao_rotation_temp_cleanup || rc=1
  openbao_recover_probe_cleanup || rc=1
  openbao_remote_session_cleanup || rc=1
  (( rc == 0 ))
}

openbao_initialize_trap() {
  local event=$1 prior_status=$2 final_status
  trap - EXIT HUP INT TERM
  if [[ "$OPENBAO_INITIALIZE_TRAPS_ACTIVE" != true ]]; then
    exit "$prior_status"
  fi
  OPENBAO_INITIALIZE_TRAPS_ACTIVE=false
  case "$event" in
    EXIT) final_status=$prior_status ;;
    HUP) final_status=129 ;;
    INT) final_status=130 ;;
    TERM) final_status=143 ;;
    *) final_status=$EXIT_UNKNOWN_STATE ;;
  esac
  if openbao_initialize_cleanup; then
    exit "$final_status"
  fi
  finish_phase STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
    "$EXIT_UNKNOWN_STATE" NONE || true
  exit "$EXIT_UNKNOWN_STATE"
}

openbao_initialize_traps_install() {
  [[ "$OPENBAO_INITIALIZE_TRAPS_ACTIVE" == false ]] || return 1
  OPENBAO_INITIALIZE_TRAPS_ACTIVE=true
  trap 'openbao_initialize_trap EXIT "$?"' EXIT
  trap 'openbao_initialize_trap HUP 129' HUP
  trap 'openbao_initialize_trap INT 130' INT
  trap 'openbao_initialize_trap TERM 143' TERM
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
  openbao_status_json | "$PYTHON_BINARY" -I -B -c '
import json
import sys

attempt = int(sys.argv[1])
document = json.load(sys.stdin)
if document.get("initialized") is not True:
    raise SystemExit(1)
progress = document.get("progress")
if type(progress) is not int:
    raise SystemExit(1)
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

path "sys/rotate/root/init" {
  capabilities = ["read"]
}

path "sys/rotate/root/verify" {
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
  local auth_config expected_policy policy role
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
  expected_policy=$(openbao_probe_policy) || return 1
  [[ "$policy" == "$expected_policy" ]] || return 1
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
  openbao_root_session_revoke_self || return 1
  openbao_root_session_revocation_is_proven || return 1
  OPENBAO_REMOTE_SESSION_KIND=
}

openbao_root_session_revoke_self() {
  openbao_bao token revoke -self >/dev/null
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
status=
trap '\''rm -f -- "$error"; [ -z "$status" ] || rm -f -- "$status"'\'' EXIT HUP INT TERM
status=$(mktemp /tmp/openbao-root-revoke-status.XXXXXX)
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
  if openbao_apply_configuration; then
    openbao_root_session_revoke || rc=1
  else
    rc=1
  fi
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

openbao_incident_artifacts_are_absent() {
  local path
  for path in "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" \
      "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
      "$OPENBAO_ROTATION_VERIFIED_MARKER" "$OPENBAO_ROTATION_READY_CHECKPOINT" \
      "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" \
      "${OPENBAO_ROTATION_CANDIDATE_STAGING_ROOT:-}"; do
    if [[ -n "$path" && ( -e "$path" || -L "$path" ) ]]; then
      return 1
    fi
  done
}

openbao_incident_acceptance_state() {
  local artifact_state checkpoint_present=false incident_present=false path
  for path in "$OPENBAO_ROTATION_CANDIDATE_DIRECTORY" \
      "$OPENBAO_ROTATION_CANDIDATE_ARCHIVE" \
      "$OPENBAO_ROTATION_CANDIDATE_SIDECAR" \
      "$OPENBAO_ROTATION_VERIFIED_MARKER"; do
    [[ -n "$path" && ( -e "$path" || -L "$path" ) ]] &&
      incident_present=true
  done
  for path in "$OPENBAO_ROTATION_READY_CHECKPOINT" \
      "$OPENBAO_ROTATION_REVOKED_CHECKPOINT" \
      "$OPENBAO_ROTATION_FINAL_STAGING_ROOT"; do
    [[ -n "$path" && ( -e "$path" || -L "$path" ) ]] &&
      checkpoint_present=true
  done
  if [[ "$checkpoint_present" == true ]]; then
    printf 'AMBIGUOUS\n'
    return
  fi
  if openbao_recovery_bundle_is_valid && openbao_incident_artifacts_are_absent; then
    printf 'NORMAL_V1\n'
  elif [[ "$incident_present" == true ]]; then
    artifact_state=$(openbao_rotation_artifact_presence_state) || return 1
    if [[ "$artifact_state" == VERIFIED ]]; then
      printf 'INCIDENT_V2\n'
    else
      printf 'AMBIGUOUS\n'
    fi
  else
    printf 'AMBIGUOUS\n'
  fi
}

openbao_incident_source_sha_load() {
  local metadata source_sha
  metadata=${OPENBAO_RECOVERY_DIRECTORY}/metadata.json
  safe_file "$metadata" 600 || return 1
  source_sha=$("$PYTHON_BINARY" -I -B - "$metadata" \
    "$OPENBAO_RECOVERY_ID" <<'PY'
import json
import re
import sys

metadata_path, current_sha = sys.argv[1:]
try:
    with open(metadata_path, encoding='utf-8') as stream:
        document = json.load(stream)
    source_sha = document.get('source_recovery_sha')
    if (
        document.get('schema') != 'engineering-platform/openbao-recovery/v2'
        or document.get('git_commit') != current_sha
        or not isinstance(source_sha, str)
        or re.fullmatch(r'[0-9a-f]{40}', source_sha) is None
    ):
        raise ValueError
    print(source_sha)
except Exception:
    raise SystemExit(1)
PY
  ) || return 1
  OPENBAO_SOURCE_RECOVERY_SHA=$source_sha
}

openbao_incident_artifacts_are_valid() {
  local artifact_state cluster_digest
  artifact_state=$(openbao_rotation_artifact_presence_state) || return 1
  [[ "$artifact_state" == VERIFIED ]] || return 1
  openbao_incident_source_sha_load || return 1
  openbao_source_recovery_bundle_is_valid || return 1
  openbao_live_cluster_identity || return 1
  cluster_digest=$(openbao_cluster_identity_sha256 \
    "$OPENBAO_CLUSTER_ID" "$OPENBAO_CLUSTER_NAME") || return 1
  openbao_rotation_candidate_is_valid "$cluster_digest" || return 1
  openbao_rotation_final_is_valid "$cluster_digest" || return 1
  openbao_rotation_verified_marker_is_valid "$cluster_digest"
}

openbao_incident_live_rotation_is_idle() {
  local rc=0
  openbao_rotation_temp_create || return 1
  if ! openbao_probe_session_start; then
    openbao_remote_session_cleanup || true
    openbao_rotation_temp_cleanup || true
    return 1
  fi
  openbao_rotation_status normal || rc=1
  openbao_rotation_status verification || rc=1
  [[ "$OPENBAO_ROTATION_PHASE" == IDLE &&
     "$OPENBAO_ROTATION_PROGRESS" == 0 &&
     "$OPENBAO_ROTATION_REQUIRED" == 0 &&
     -z "$OPENBAO_ROTATION_NONCE" &&
     -z "$OPENBAO_ROTATION_VERIFICATION_NONCE" &&
     "$OPENBAO_ROTATION_VERIFICATION_PHASE" == IDLE &&
     "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" == 0 &&
     -z "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ]] || rc=1
  openbao_remote_session_cleanup || rc=1
  openbao_rotation_temp_cleanup || rc=1
  (( rc == 0 ))
}

openbao_recover_verify_live_readback() {
  local rc=0
  if ! openbao_probe_session_start; then
    openbao_remote_session_cleanup || true
    return 1
  fi
  openbao_rotation_status normal || rc=1
  openbao_rotation_status verification || rc=1
  openbao_remote_session_cleanup || rc=1
  (( rc == 0 ))
}

openbao_recover_runtime_readback() {
  [[ "$(openbao_state_flags)" == 'true|false' ]] &&
    openbao_configuration_readback_is_exact &&
    openbao_recover_auth_probe &&
    openbao_audit_runtime_is_exact &&
    openbao_source_recovery_bundle_is_valid
}

openbao_rotation_verified_at_utc() {
  local timestamp
  timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ) || return 1
  [[ "$timestamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] ||
    return 1
  printf '%s\n' "$timestamp"
}

openbao_incident_evidence_is_exact() {
  local file=$1
  safe_file "$file" 600 || return 1
  "$PYTHON_BINARY" -I -B - "$file" <<'PY'
import sys

path = sys.argv[1]
expected = {
    'UNSEAL_KEY_ROTATION': 'PASS',
    'COMPROMISED_SHARE_INVALIDATED': 'true',
    'INITIAL_ROOT_TOKEN': 'REVOKED',
    'RECOVERY_BUNDLE_SCHEMA': 'engineering-platform/openbao-recovery/v2',
    'MINIO': 'NOT_EXECUTED',
    'SNAPSHOT': 'NOT_EXECUTED',
    'BACKUP': 'NOT_EXECUTED',
    'RESTORE': 'NOT_EXECUTED',
    'APP_SECRET_MIGRATION': 'NOT_EXECUTED',
}
observed = {key: [] for key in expected}
try:
    with open(path, encoding='utf-8') as stream:
        for raw_line in stream:
            line = raw_line.rstrip('\n')
            key, separator, value = line.partition('=')
            if separator and key in observed:
                observed[key].append(value)
    if any(values != [expected[key]] for key, values in observed.items()):
        raise ValueError
except Exception:
    raise SystemExit(1)
PY
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
    r'(?i)(?:verification_nonce|keys_base64|raw_rotation_response|rotation_response|ciphertext)\s*[:=]',
    r'[A-Za-z0-9+/]{80,}={0,2}',
):
    if re.search(pattern, text):
        raise SystemExit(1)
PY
}

openbao_existing_evidence() {
  local acceptance_state=${1:-NORMAL_V1}
  local candidate digest recorded recorded_name sidecar
  for candidate in "$(host_path /root/dev-infra-evidence)"/17-openbao-runtime-*.txt; do
    safe_file "$candidate" 600 || continue
    grep -Fx "GIT_COMMIT=${OPENBAO_RECOVERY_ID}" "$candidate" >/dev/null 2>&1 ||
      continue
    openbao_evidence_is_secret_free "$candidate" || continue
    if [[ "$acceptance_state" == INCIDENT_V2 ]]; then
      openbao_incident_evidence_is_exact "$candidate" || continue
    fi
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
  local destination=$1 acceptance_state=${2:-NORMAL_V1}
  local bundle_sha platform_fingerprint public_fingerprint
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
    if [[ "$acceptance_state" == INCIDENT_V2 ]]; then
      printf 'UNSEAL_KEY_ROTATION=PASS\n'
      printf 'COMPROMISED_SHARE_INVALIDATED=true\n'
      printf 'RECOVERY_BUNDLE_SCHEMA=engineering-platform/openbao-recovery/v2\n'
    fi
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
  openbao_incident_artifacts_are_absent ||
    complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
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

openbao_recover_start_cleanup() {
  local rc=0
  openbao_rotation_temp_cleanup || rc=1
  openbao_remote_session_cleanup || rc=1
  (( rc == 0 ))
}

openbao_recover_start_fail() {
  local result=$1 reason=$2 code=$3
  if ! openbao_recover_start_cleanup; then
    complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
      "$EXIT_UNKNOWN_STATE" NONE
  fi
  complete "$result" "$reason" "$code" NONE
}

openbao_stage_180_recover_start() {
  local artifact_state cluster_digest expected_progress response_kind state
  local expected_rotation_nonce=
  local submitted_final_response=false
  export -n expected_rotation_nonce 2>/dev/null || return 1
  set +x
  openbao_stage_180_preflight
  openbao_source_recovery_bundle_is_valid ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      "$OPENBAO_REASON_SOURCE_UNSAFE" "$EXIT_UNKNOWN_STATE"
  openbao_require_interactive_tty ||
    openbao_recover_start_fail STOP_PRECONDITION interactive-tty-required \
      "$EXIT_PRECONDITION"

  state=$(openbao_state_flags) ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE"
  if [[ "$state" == 'true|true' ]]; then
    openbao_unseal_interactively ||
      openbao_recover_start_fail STOP_APPLY_FAILED openbao-unseal-failed \
        "$EXIT_APPLY_FAILED"
    [[ "$(openbao_state_flags)" == 'true|false' ]] ||
      openbao_recover_start_fail STOP_VERIFY_FAILED unexpected-openbao-state \
        "$EXIT_VERIFY_FAILED"
  elif [[ "$state" != 'true|false' ]]; then
    openbao_recover_start_fail STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE"
  fi

  openbao_root_session_start ||
    openbao_recover_start_fail STOP_APPLY_FAILED openbao-root-login-failed \
      "$EXIT_APPLY_FAILED"
  openbao_apply_configuration ||
    openbao_recover_start_fail STOP_APPLY_FAILED openbao-configuration-failed \
      "$EXIT_APPLY_FAILED"
  openbao_live_cluster_identity ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      openbao-cluster-identity-invalid "$EXIT_UNKNOWN_STATE"
  openbao_rotation_temp_create ||
    openbao_recover_start_fail STOP_APPLY_FAILED \
      rotation-candidate-write-failed "$EXIT_APPLY_FAILED"

  artifact_state=$(openbao_rotation_artifact_presence_state) ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
  case "$artifact_state" in
    MISSING|CANDIDATE|PARTIAL_CANDIDATE) ;;
    *)
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
      ;;
  esac

  openbao_rotation_status normal ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
  openbao_rotation_status verification ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
  if [[ "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
        "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" != 0 ]]; then
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
  fi

  if [[ "$artifact_state" == CANDIDATE || "$artifact_state" == PARTIAL_CANDIDATE ]]; then
    [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_COMPLETE &&
       "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
       ( -z "$OPENBAO_ROTATION_VERIFICATION_NONCE" ||
         "$OPENBAO_ROTATION_VERIFICATION_NONCE" == "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ) ]] ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    if [[ "$artifact_state" == PARTIAL_CANDIDATE ]]; then
      openbao_rotation_backup_retrieve "$OPENBAO_ROTATION_RESPONSE" ||
        openbao_recover_start_fail STOP_APPLY_FAILED \
          rotation-candidate-write-failed "$EXIT_APPLY_FAILED"
      response_kind=backup
    fi
  elif [[ "$OPENBAO_ROTATION_PHASE" == IDLE &&
          "$OPENBAO_ROTATION_VERIFICATION_PHASE" == IDLE ]]; then
    openbao_rotation_initialize "$OPENBAO_ROTATION_RESPONSE" ||
      openbao_recover_start_fail STOP_APPLY_FAILED \
        openbao-rotation-init-failed "$EXIT_APPLY_FAILED"
    openbao_rotation_status normal ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    openbao_rotation_status verification ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_PENDING &&
       "$OPENBAO_ROTATION_PROGRESS" == 0 &&
       "$OPENBAO_ROTATION_REQUIRED" == 3 &&
       "$OPENBAO_ROTATION_VERIFICATION_PHASE" == IDLE ]] ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
  elif [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_PENDING &&
          "$OPENBAO_ROTATION_VERIFICATION_PHASE" == IDLE ]]; then
    :
  elif [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_COMPLETE &&
          "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
          ( -z "$OPENBAO_ROTATION_VERIFICATION_NONCE" ||
            "$OPENBAO_ROTATION_VERIFICATION_NONCE" == "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ) ]]; then
    openbao_rotation_backup_retrieve "$OPENBAO_ROTATION_RESPONSE" ||
      openbao_recover_start_fail STOP_APPLY_FAILED \
        rotation-candidate-write-failed "$EXIT_APPLY_FAILED"
    response_kind=backup
  else
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
  fi

  if [[ "$artifact_state" == MISSING &&
        "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_PENDING ]]; then
    expected_rotation_nonce=$OPENBAO_ROTATION_NONCE
    while (( OPENBAO_ROTATION_PROGRESS < OPENBAO_ROTATION_REQUIRED )); do
      expected_progress=$((OPENBAO_ROTATION_PROGRESS + 1))
      openbao_rotation_submit_share "$expected_rotation_nonce" \
        "$OPENBAO_ROTATION_RESPONSE" ||
        openbao_recover_start_fail STOP_APPLY_FAILED \
          openbao-rotation-share-submit-failed "$EXIT_APPLY_FAILED"
      openbao_rotation_status normal ||
        openbao_recover_start_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      [[ "$OPENBAO_ROTATION_NONCE" == "$expected_rotation_nonce" ]] ||
        openbao_recover_start_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      if (( expected_progress < 3 )); then
        [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_PENDING &&
           "$OPENBAO_ROTATION_PROGRESS" == "$expected_progress" ]] ||
          openbao_recover_start_fail STOP_UNKNOWN_STATE \
            openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      else
        [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_COMPLETE &&
           "$OPENBAO_ROTATION_PROGRESS" == 3 ]] ||
          openbao_recover_start_fail STOP_UNKNOWN_STATE \
            openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
        submitted_final_response=true
      fi
    done
    openbao_rotation_status verification ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_COMPLETE &&
       "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
       "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" == 0 &&
       ( -z "$OPENBAO_ROTATION_VERIFICATION_NONCE" ||
         "$OPENBAO_ROTATION_VERIFICATION_NONCE" == "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ) ]] ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    [[ "$submitted_final_response" == true ]] ||
      openbao_recover_start_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    response_kind=direct
  fi

  if [[ "$artifact_state" == MISSING || "$artifact_state" == PARTIAL_CANDIDATE ]]; then
    case "$response_kind" in
      direct)
        openbao_rotation_capture_candidate "$OPENBAO_ROTATION_RESPONSE" direct \
          "$OPENBAO_CLUSTER_ID" "$OPENBAO_CLUSTER_NAME" '' ||
          openbao_recover_start_fail STOP_APPLY_FAILED \
            rotation-candidate-write-failed "$EXIT_APPLY_FAILED"
        ;;
      backup)
        openbao_rotation_capture_candidate "$OPENBAO_ROTATION_RESPONSE" backup \
          "$OPENBAO_CLUSTER_ID" "$OPENBAO_CLUSTER_NAME" \
          "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ||
          openbao_recover_start_fail STOP_APPLY_FAILED \
            rotation-candidate-write-failed "$EXIT_APPLY_FAILED"
        ;;
      *)
        openbao_recover_start_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
        ;;
    esac
  fi

  cluster_digest=$(openbao_cluster_identity_sha256 \
    "$OPENBAO_CLUSTER_ID" "$OPENBAO_CLUSTER_NAME") ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      openbao-cluster-identity-invalid "$EXIT_UNKNOWN_STATE"
  openbao_rotation_candidate_is_valid "$cluster_digest" ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
  openbao_rotation_candidate_nonce_matches_live \
    "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" "$cluster_digest" ||
    openbao_recover_start_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
  openbao_recover_start_cleanup ||
    complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
      "$EXIT_UNKNOWN_STATE" NONE
  complete PASS_OPENBAO_RECOVERY_STARTED \
    openbao-key-rotation-verification-required 0 \
    "download and verify ${OPENBAO_ROTATION_CANDIDATE_ARCHIVE} and ${OPENBAO_ROTATION_CANDIDATE_SIDECAR}; then run stages/180-openbao-initialize/run.sh --recover-verify --source-recovery-sha=${OPENBAO_SOURCE_RECOVERY_SHA}"
}

openbao_recover_verify_cleanup() {
  local rc=0
  openbao_rotation_temp_cleanup || rc=1
  openbao_recover_probe_cleanup || rc=1
  openbao_remote_session_cleanup || rc=1
  (( rc == 0 ))
}

openbao_recover_verify_fail() {
  local result=$1 reason=$2 code=$3
  if ! openbao_recover_verify_cleanup; then
    complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
      "$EXIT_UNKNOWN_STATE" NONE
  fi
  complete "$result" "$reason" "$code" NONE
}

openbao_rotation_live_fields_are_idle() {
  [[ "$OPENBAO_ROTATION_PHASE" == IDLE &&
     "$OPENBAO_ROTATION_PROGRESS" == 0 &&
     "$OPENBAO_ROTATION_REQUIRED" == 0 &&
     -z "$OPENBAO_ROTATION_NONCE" &&
     -z "$OPENBAO_ROTATION_VERIFICATION_NONCE" &&
     "$OPENBAO_ROTATION_VERIFICATION_PHASE" == IDLE &&
     "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" == 0 &&
     -z "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ]]
}

openbao_stage_180_recover_verify() {
  local artifact_state checkpoint_state cluster_digest expected_progress state
  local root_token_digest transaction_binding verified_at
  local expected_verification_nonce=
  export -n expected_verification_nonce 2>/dev/null || return 1
  set +x
  openbao_stage_180_preflight
  openbao_source_recovery_bundle_is_valid ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      "$OPENBAO_REASON_SOURCE_UNSAFE" "$EXIT_UNKNOWN_STATE"
  openbao_require_interactive_tty ||
    openbao_recover_verify_fail STOP_PRECONDITION interactive-tty-required \
      "$EXIT_PRECONDITION"
  state=$(openbao_state_flags) ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE unexpected-openbao-state \
      "$EXIT_UNKNOWN_STATE"
  [[ "$state" == 'true|false' ]] ||
    openbao_recover_verify_fail STOP_PRECONDITION unexpected-openbao-state \
      "$EXIT_PRECONDITION"

  # Establish all non-secret source, cluster, candidate, artifact, checkpoint,
  # and live-rotation bindings before asking for the root token.
  openbao_live_cluster_identity ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      openbao-cluster-identity-invalid "$EXIT_UNKNOWN_STATE"
  openbao_rotation_temp_create ||
    openbao_recover_verify_fail STOP_APPLY_FAILED \
      rotation-candidate-state-unsafe "$EXIT_APPLY_FAILED"
  artifact_state=$(openbao_rotation_artifact_presence_state) ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
  case "$artifact_state" in CANDIDATE|PARTIAL_FINAL|FINAL|VERIFIED) ;; *)
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE" ;;
  esac
  cluster_digest=$(openbao_cluster_identity_sha256 \
    "$OPENBAO_CLUSTER_ID" "$OPENBAO_CLUSTER_NAME") ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      openbao-cluster-identity-invalid "$EXIT_UNKNOWN_STATE"
  openbao_rotation_candidate_is_valid "$cluster_digest" ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
  openbao_recover_verify_live_readback ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
  checkpoint_state=$(openbao_finalization_checkpoint_state "$cluster_digest") ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
  if [[ "$checkpoint_state" == READY || "$checkpoint_state" == REVOKED ]]; then
    openbao_finalization_ready_checkpoint_load "$cluster_digest" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
  fi

  case "$artifact_state:$checkpoint_state" in
    VERIFIED:NONE)
      if ! openbao_rotation_live_fields_are_idle ||
          ! openbao_rotation_verified_marker_is_valid "$cluster_digest"; then
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      fi
      [[ ! -e "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" &&
         ! -L "$OPENBAO_ROTATION_FINAL_STAGING_ROOT" ]] ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      openbao_recover_verify_cleanup ||
        complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
          "$EXIT_UNKNOWN_STATE" NONE
      complete PASS_OPENBAO_RECOVERED openbao-key-rotation-verified 0 \
        'stages/180-openbao-initialize/run.sh --accept'
      ;;
    VERIFIED:READY|VERIFIED:REVOKED)
      if ! openbao_rotation_live_fields_are_idle ||
          ! openbao_rotation_verified_marker_is_valid "$cluster_digest"; then
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      fi
      openbao_rotation_final_staging_cleanup ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-final-bundle-state-unsafe "$EXIT_UNKNOWN_STATE"
      openbao_finalization_remote_helper_cleanup ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          "$OPENBAO_REASON_REMOTE_CLEANUP" "$EXIT_UNKNOWN_STATE"
      openbao_recover_verify_cleanup ||
        complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
          "$EXIT_UNKNOWN_STATE" NONE
      openbao_finalization_checkpoint_cleanup "$cluster_digest" ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      complete PASS_OPENBAO_RECOVERED openbao-key-rotation-verified 0 \
        'stages/180-openbao-initialize/run.sh --accept'
      ;;
    FINAL:REVOKED)
      if ! openbao_rotation_live_fields_are_idle ||
          ! openbao_rotation_final_is_valid "$cluster_digest"; then
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-final-bundle-state-unsafe "$EXIT_UNKNOWN_STATE"
      fi
      openbao_rotation_final_staging_cleanup ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-final-bundle-state-unsafe "$EXIT_UNKNOWN_STATE"
      ;;
    PARTIAL_FINAL:REVOKED)
      openbao_rotation_live_fields_are_idle ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      openbao_rotation_partial_final_cleanup ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-final-bundle-state-unsafe "$EXIT_UNKNOWN_STATE"
      artifact_state=CANDIDATE
      ;;
    CANDIDATE:READY)
      openbao_rotation_live_fields_are_idle ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      # A prior publish may have linked READY but failed its directory fsync.
      # Reestablish durability before crossing the irreversible revoke boundary.
      openbao_fsync_directory "$OPENBAO_RECOVERY_ROOT" ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      openbao_finalization_resume_root_revocation \
        "$OPENBAO_FINALIZATION_ROOT_TOKEN_SHA256" ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          initial-root-token-still-valid "$EXIT_UNKNOWN_STATE"
      openbao_finalization_revoked_checkpoint_create "$cluster_digest" ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      checkpoint_state=REVOKED
      ;;
    CANDIDATE:REVOKED)
      openbao_rotation_live_fields_are_idle ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      ;;
    CANDIDATE:NONE) ;;
    *)
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
      ;;
  esac

  if [[ "$checkpoint_state" == NONE ]]; then
    if [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_COMPLETE &&
          "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
          "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" =~ ^[0-2]$ &&
          "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" =~ ^[A-Za-z0-9_-]{8,128}$ ]] &&
        [[ -z "$OPENBAO_ROTATION_VERIFICATION_NONCE" ||
          "$OPENBAO_ROTATION_VERIFICATION_NONCE" == "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ]]; then
      expected_verification_nonce=$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE
      openbao_rotation_candidate_nonce_matches_live \
        "$expected_verification_nonce" "$cluster_digest" ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
    elif ! openbao_rotation_live_fields_are_idle; then
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    fi

    openbao_root_session_start ||
      openbao_recover_verify_fail STOP_APPLY_FAILED openbao-root-login-failed \
        "$EXIT_APPLY_FAILED"
    if ! openbao_rotation_status normal ||
        ! openbao_rotation_status verification; then
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    fi
    openbao_rotation_candidate_is_valid "$cluster_digest" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"

    if [[ -n "$expected_verification_nonce" ]]; then
      [[ "$OPENBAO_ROTATION_PHASE" == OLD_QUORUM_COMPLETE &&
         "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
         "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" == \
           "$expected_verification_nonce" ]] ||
        openbao_recover_verify_fail STOP_UNKNOWN_STATE \
          openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
      while (( OPENBAO_ROTATION_VERIFICATION_PROGRESS < 3 )); do
        expected_progress=$((OPENBAO_ROTATION_VERIFICATION_PROGRESS + 1))
        openbao_rotation_verification_submit_share \
          "$expected_verification_nonce" "$OPENBAO_ROTATION_RESPONSE" ||
          openbao_recover_verify_fail STOP_APPLY_FAILED \
            rotation-verification-failed "$EXIT_APPLY_FAILED"
        openbao_rotation_status verification ||
          openbao_recover_verify_fail STOP_UNKNOWN_STATE \
            openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
        if (( expected_progress < 3 )); then
          [[ "$OPENBAO_ROTATION_VERIFICATION_PHASE" == PENDING &&
             "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" == "$expected_progress" &&
             "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" == \
               "$expected_verification_nonce" ]] ||
            openbao_recover_verify_fail STOP_UNKNOWN_STATE \
              openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
        else
          [[ "$OPENBAO_ROTATION_VERIFICATION_PHASE" == IDLE &&
             "$OPENBAO_ROTATION_VERIFICATION_PROGRESS" == 0 &&
             -z "$OPENBAO_ROTATION_VERIFICATION_LIVE_NONCE" ]] ||
            openbao_recover_verify_fail STOP_UNKNOWN_STATE \
              openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
          OPENBAO_ROTATION_VERIFICATION_PROGRESS=3
        fi
      done
    fi

    if ! openbao_rotation_status normal ||
        ! openbao_rotation_status verification; then
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    fi
    openbao_rotation_live_fields_are_idle ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        openbao-rotation-state-unsafe "$EXIT_UNKNOWN_STATE"
    openbao_rotation_candidate_is_valid "$cluster_digest" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
    transaction_binding=$(
      openbao_finalization_transaction_binding "$cluster_digest"
    ) || openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      rotation-candidate-state-unsafe "$EXIT_UNKNOWN_STATE"
    openbao_root_session_binding_create "$transaction_binding" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        "$OPENBAO_REASON_REMOTE_CLEANUP" "$EXIT_UNKNOWN_STATE"
    openbao_rotation_backup_delete ||
      openbao_recover_verify_fail STOP_APPLY_FAILED \
        rotation-backup-delete-failed "$EXIT_APPLY_FAILED"
    openbao_recover_runtime_readback ||
      openbao_recover_verify_fail STOP_VERIFY_FAILED openbao-auth-probe-failed \
        "$EXIT_VERIFY_FAILED"
    root_token_digest=$(openbao_root_token_sha256) ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        initial-root-token-still-valid "$EXIT_UNKNOWN_STATE"
    openbao_finalization_ready_checkpoint_create "$cluster_digest" \
      "$root_token_digest" "$OPENBAO_REMOTE_HOME" "$transaction_binding" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
    root_token_digest=
    unset root_token_digest
    openbao_root_session_revoke_self ||
      openbao_recover_verify_fail STOP_APPLY_FAILED \
        initial-root-token-revoke-failed "$EXIT_APPLY_FAILED"
    openbao_root_session_revocation_is_proven ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        initial-root-token-still-valid "$EXIT_UNKNOWN_STATE"
    openbao_finalization_revoked_checkpoint_create "$cluster_digest" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
    checkpoint_state=REVOKED
  fi

  if [[ "$artifact_state" == CANDIDATE ]]; then
    [[ "$checkpoint_state" == REVOKED ]] ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
    openbao_finalization_remote_helper_cleanup ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        "$OPENBAO_REASON_REMOTE_CLEANUP" "$EXIT_UNKNOWN_STATE"
    openbao_recover_verify_cleanup ||
      complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
        "$EXIT_UNKNOWN_STATE" NONE
    verified_at=$(openbao_rotation_verified_at_utc) ||
      complete STOP_UNKNOWN_STATE recovery-final-bundle-state-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
    openbao_build_rotation_final "$cluster_digest" "$verified_at" ||
      openbao_recover_verify_fail STOP_APPLY_FAILED \
        recovery-final-bundle-write-failed "$EXIT_APPLY_FAILED"
    openbao_rotation_final_is_valid "$cluster_digest" ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        recovery-final-bundle-state-unsafe "$EXIT_UNKNOWN_STATE"
  else
    openbao_finalization_remote_helper_cleanup ||
      openbao_recover_verify_fail STOP_UNKNOWN_STATE \
        "$OPENBAO_REASON_REMOTE_CLEANUP" "$EXIT_UNKNOWN_STATE"
    openbao_recover_verify_cleanup ||
      complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
        "$EXIT_UNKNOWN_STATE" NONE
  fi
  openbao_rotation_verified_marker_create "$cluster_digest" ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
  openbao_finalization_checkpoint_cleanup "$cluster_digest" ||
    openbao_recover_verify_fail STOP_UNKNOWN_STATE \
      recovery-verification-marker-unsafe "$EXIT_UNKNOWN_STATE"
  complete PASS_OPENBAO_RECOVERED openbao-key-rotation-verified 0 \
    'stages/180-openbao-initialize/run.sh --accept'
}

openbao_stage_180_configure() {
  local state
  openbao_stage_180_preflight
  [[ "$(openbao_incident_acceptance_state)" == NORMAL_V1 ]] ||
    complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
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
  local acceptance_state evidence_dir payload digest sidecar
  openbao_stage_180_preflight
  acceptance_state=$(openbao_incident_acceptance_state) ||
    complete STOP_UNKNOWN_STATE recovery-verification-marker-unsafe \
      "$EXIT_UNKNOWN_STATE" NONE
  case "$acceptance_state" in
    NORMAL_V1)
      openbao_recovery_bundle_is_valid ||
        complete STOP_UNKNOWN_STATE recovery-bundle-state-unsafe \
          "$EXIT_UNKNOWN_STATE" NONE
      ;;
    INCIDENT_V2)
      openbao_incident_artifacts_are_valid ||
        complete STOP_UNKNOWN_STATE recovery-verification-marker-unsafe \
          "$EXIT_UNKNOWN_STATE" NONE
      openbao_incident_live_rotation_is_idle ||
        complete STOP_UNKNOWN_STATE openbao-rotation-state-unsafe \
          "$EXIT_UNKNOWN_STATE" NONE
      ;;
    *)
      complete STOP_UNKNOWN_STATE recovery-verification-marker-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
      ;;
  esac
  [[ "$(openbao_state_flags)" == 'true|false' ]] ||
    complete STOP_PRECONDITION unexpected-openbao-state \
      "$EXIT_PRECONDITION" NONE
  if [[ "$acceptance_state" == NORMAL_V1 ]]; then
    openbao_platform_secrets_match_recovery_baseline ||
      complete STOP_VERIFY_FAILED platform-secret-drift \
        "$EXIT_VERIFY_FAILED" NONE
  else
    openbao_source_recovery_bundle_is_valid ||
      complete STOP_VERIFY_FAILED platform-secret-drift \
        "$EXIT_VERIFY_FAILED" NONE
  fi
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
  if [[ "$acceptance_state" == NORMAL_V1 ]]; then
    openbao_platform_secrets_match_recovery_baseline ||
      complete STOP_VERIFY_FAILED platform-secret-drift \
        "$EXIT_VERIFY_FAILED" NONE
  else
    openbao_source_recovery_bundle_is_valid ||
      complete STOP_VERIFY_FAILED platform-secret-drift \
        "$EXIT_VERIFY_FAILED" NONE
  fi
  if openbao_existing_evidence "$acceptance_state" >/dev/null; then
    complete ALREADY_COMPLIANT openbao-runtime-evidence-exists 0 NONE
  fi
  evidence_dir=$(host_path /root/dev-infra-evidence)
  payload=$(mktemp "$(host_path /root)/.openbao-evidence.XXXXXX") ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  rm -f -- "$payload" ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  openbao_write_acceptance_payload "$payload" "$acceptance_state" ||
    complete STOP_APPLY_FAILED evidence-open-failed \
      "$EXIT_APPLY_FAILED" NONE
  if [[ "$acceptance_state" == INCIDENT_V2 ]]; then
    openbao_incident_evidence_is_exact "$payload" ||
      complete STOP_VERIFY_FAILED evidence-scan-failed \
        "$EXIT_VERIFY_FAILED" NONE
  fi
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
  if [[ "$acceptance_state" == INCIDENT_V2 ]]; then
    openbao_incident_evidence_is_exact "$EVIDENCE_FILE" ||
      exit "$EXIT_VERIFY_FAILED"
  fi
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
  openbao_initialize_traps_install ||
    complete STOP_UNKNOWN_STATE "$OPENBAO_REASON_REMOTE_CLEANUP" \
      "$EXIT_UNKNOWN_STATE" NONE
  case "$OPENBAO_OPERATION" in
    CHECK) openbao_stage_180_check ;;
    INITIALIZE) openbao_stage_180_initialize ;;
    CONFIGURE) openbao_stage_180_configure ;;
    RECOVER_START) openbao_stage_180_recover_start ;;
    RECOVER_VERIFY) openbao_stage_180_recover_verify ;;
    ACCEPT) openbao_stage_180_accept ;;
    *) complete STOP_PRECONDITION invalid-openbao-operation \
      "$EXIT_PRECONDITION" NONE ;;
  esac
}
