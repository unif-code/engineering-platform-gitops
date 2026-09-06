#!/usr/bin/env bash

RUN_APPROVED_LOCK_REASON=

run_approved_lock_owner_uid() {
  local owner
  owner=$(/usr/bin/stat -c '%u' "$1" 2>/dev/null) || return 1
  [[ "$owner" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$owner"
}

run_approved_lock_mode() {
  local mode
  mode=$(/usr/bin/stat -c '%a' "$1" 2>/dev/null) || return 1
  [[ "$mode" =~ ^[0-7]{3,4}$ ]] || return 1
  printf '%s\n' "$mode"
}

run_approved_lock_parent_is_safe() {
  local directory=$1 expected_uid=$2 expected_mode=$3 canonical
  [[ "$directory" == /* && "$directory" != / &&
     -d "$directory" && ! -L "$directory" ]] || return 1
  canonical=$(cd "$directory" 2>/dev/null && pwd -P) || return 1
  [[ "$canonical" == "$directory" ]] || return 1
  [[ "$(run_approved_lock_owner_uid "$directory")" == "$expected_uid" ]] ||
    return 1
  [[ "$(run_approved_lock_mode "$directory")" == "$expected_mode" ]]
}

run_approved_lock_file_is_safe() {
  local file=$1 expected_uid=$2 mode
  [[ "$file" == /* && -f "$file" && ! -L "$file" ]] || return 1
  [[ "$(run_approved_lock_owner_uid "$file")" == "$expected_uid" ]] ||
    return 1
  mode=$(run_approved_lock_mode "$file") || return 1
  (( (8#$mode & 0022) == 0 ))
}

run_approved_acquire_directory_lock() {
  local directory flock_binary lock_fd canonical owner mode
  local directory_identity fd_identity open_rc=0
  RUN_APPROVED_LOCK_REASON=
  [[ $# -eq 3 ]] || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-arguments
    return 1
  }
  directory=$1
  flock_binary=$2
  lock_fd=$3
  [[ "$directory" == /* && "$directory" != / &&
     -d "$directory" && ! -L "$directory" &&
     "$flock_binary" == /* && -x "$flock_binary" &&
     "$lock_fd" == 8 ]] || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-arguments
    return 1
  }
  canonical=$(cd "$directory" 2>/dev/null && pwd -P) || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  [[ "$canonical" == "$directory" ]] || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  owner=$(run_approved_lock_owner_uid "$directory") || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  [[ "$owner" =~ ^[0-9]+$ ]] || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  mode=$(run_approved_lock_mode "$directory") || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  (( (8#$mode & 0022) == 0 )) || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  exec 8<"$directory" || open_rc=$?
  if (( open_rc != 0 )); then
    RUN_APPROVED_LOCK_REASON=lock-open-failed
    return 1
  fi
  if ! "$flock_binary" -n "$lock_fd"; then
    exec 8>&-
    RUN_APPROVED_LOCK_REASON=concurrent-run
    return 1
  fi
  directory_identity=$(/usr/bin/stat -Lc '%d:%i' "$directory" 2>/dev/null) || {
    exec 8>&-
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  fd_identity=$(/usr/bin/stat -Lc '%d:%i' "/proc/self/fd/${lock_fd}" 2>/dev/null) || {
    exec 8>&-
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  }
  if [[ "$directory_identity" != "$fd_identity" ]]; then
    exec 8>&-
    RUN_APPROVED_LOCK_REASON=unsafe-lock-directory
    return 1
  fi
  [[ -z "$RUN_APPROVED_LOCK_REASON" ]]
}

run_approved_acquire_lock() {
  local lock_file=$1 expected_uid=$2 expected_parent_mode=$3 flock_binary=$4
  local lock_fd=$5 lock_parent snapshot_dir snapshot_file create_rc
  local lock_identity fd_identity
  RUN_APPROVED_LOCK_REASON=
  [[ "$expected_uid" =~ ^[0-9]+$ &&
     "$EUID" == "$expected_uid" &&
     "$expected_parent_mode" =~ ^[0-7]{3,4}$ &&
     "$flock_binary" == /* && -x "$flock_binary" &&
     "$lock_fd" =~ ^[89]$ ]] || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-arguments
    return 1
  }
  lock_parent=${lock_file%/*}
  run_approved_lock_parent_is_safe \
    "$lock_parent" "$expected_uid" "$expected_parent_mode" || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-parent
    return 1
  }

  if [[ ! -e "$lock_file" && ! -L "$lock_file" ]]; then
    set +e
    (umask 077; set -o noclobber; : >"$lock_file") 2>/dev/null
    create_rc=$?
    set -e
    if (( create_rc != 0 )) &&
       [[ ! -e "$lock_file" && ! -L "$lock_file" ]]; then
      RUN_APPROVED_LOCK_REASON=lock-create-failed
      return 1
    fi
  fi
  run_approved_lock_file_is_safe "$lock_file" "$expected_uid" || {
    RUN_APPROVED_LOCK_REASON=unsafe-lock-target
    return 1
  }

  snapshot_dir=$(
    /usr/bin/mktemp -d \
      "${lock_parent}/.engineering-platform-run-approved-lock.XXXXXX"
  ) || {
    RUN_APPROVED_LOCK_REASON=lock-snapshot-create-failed
    return 1
  }
  if [[ ! -d "$snapshot_dir" || -L "$snapshot_dir" ||
        "$(run_approved_lock_owner_uid "$snapshot_dir")" != "$expected_uid" ||
        "$(run_approved_lock_mode "$snapshot_dir")" != 700 ]]; then
    /bin/rmdir -- "$snapshot_dir" 2>/dev/null || true
    RUN_APPROVED_LOCK_REASON=unsafe-lock-snapshot
    return 1
  fi
  snapshot_file=${snapshot_dir}/lock
  if ! /bin/ln -- "$lock_file" "$snapshot_file" 2>/dev/null ||
     ! run_approved_lock_file_is_safe "$snapshot_file" "$expected_uid"; then
    /bin/rm -f -- "$snapshot_file" 2>/dev/null || true
    /bin/rmdir -- "$snapshot_dir" 2>/dev/null || true
    RUN_APPROVED_LOCK_REASON=unsafe-lock-target
    return 1
  fi
  create_rc=0
  if [[ "$lock_fd" == 8 ]]; then
    exec 8<>"$snapshot_file" || create_rc=$?
  else
    exec 9<>"$snapshot_file" || create_rc=$?
  fi
  if (( ${create_rc:-0} != 0 )); then
    /bin/rm -f -- "$snapshot_file" 2>/dev/null || true
    /bin/rmdir -- "$snapshot_dir" 2>/dev/null || true
    RUN_APPROVED_LOCK_REASON=lock-open-failed
    return 1
  fi
  if ! /bin/rm -- "$snapshot_file" || ! /bin/rmdir -- "$snapshot_dir"; then
    if [[ "$lock_fd" == 8 ]]; then exec 8>&-; else exec 9>&-; fi
    RUN_APPROVED_LOCK_REASON=lock-snapshot-cleanup-failed
    return 1
  fi
  if ! "$flock_binary" -n "$lock_fd"; then
    if [[ "$lock_fd" == 8 ]]; then exec 8>&-; else exec 9>&-; fi
    RUN_APPROVED_LOCK_REASON=concurrent-run
    return 1
  fi
  if ! run_approved_lock_file_is_safe "$lock_file" "$expected_uid"; then
    if [[ "$lock_fd" == 8 ]]; then exec 8>&-; else exec 9>&-; fi
    RUN_APPROVED_LOCK_REASON=unsafe-lock-target
    return 1
  fi
  lock_identity=$(/usr/bin/stat -Lc '%d:%i' "$lock_file" 2>/dev/null) || {
    if [[ "$lock_fd" == 8 ]]; then exec 8>&-; else exec 9>&-; fi
    RUN_APPROVED_LOCK_REASON=unsafe-lock-target
    return 1
  }
  fd_identity=$(/usr/bin/stat -Lc '%d:%i' "/proc/self/fd/${lock_fd}" 2>/dev/null) || {
    if [[ "$lock_fd" == 8 ]]; then exec 8>&-; else exec 9>&-; fi
    RUN_APPROVED_LOCK_REASON=unsafe-lock-target
    return 1
  }
  if [[ "$lock_identity" != "$fd_identity" ]]; then
    if [[ "$lock_fd" == 8 ]]; then exec 8>&-; else exec 9>&-; fi
    RUN_APPROVED_LOCK_REASON=unsafe-lock-target
    return 1
  fi
  [[ -z "$RUN_APPROVED_LOCK_REASON" ]]
}
