#!/bin/bash
# 运行批准入口的固定 argv 映射。任何未列出的参数形状均拒绝，绝不透传调用方的 "$@"。

# shellcheck disable=SC2034
# These globals are the reviewed parser interface consumed by run-approved.sh.
run_approved_parse_arguments() {
  local mode=$1 source_sha
  shift

  RUN_APPROVED_MODE=$mode
  RUN_APPROVED_TARGET=bootstrap
  RUN_APPROVED_TARGET_ARGUMENTS=()
  case "$mode:$#:${1:-}:${2:-}:${3:-}" in
    --check:0:::)
      RUN_APPROVED_TARGET_ARGUMENTS=(--check)
      ;;
    --apply:0:::)
      RUN_APPROVED_TARGET_ARGUMENTS=(--apply)
      ;;
    --check:2:--stage=180:--source-recovery-sha=*:)
      source_sha=${2#--source-recovery-sha=}
      [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--check "--source-recovery-sha=${source_sha}")
      ;;
    --apply:2:--stage=180:--operation=initialize:)
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--initialize)
      ;;
    --apply:2:--stage=180:--operation=configure:)
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--configure)
      ;;
    --apply:2:--stage=180:--operation=accept:)
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--accept)
      ;;
    --apply:3:--stage=180:--operation=recover-start:--source-recovery-sha=*)
      source_sha=${3#--source-recovery-sha=}
      [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--recover-start "--source-recovery-sha=${source_sha}")
      ;;
    --apply:3:--stage=180:--operation=recover-verify:--source-recovery-sha=*)
      source_sha=${3#--source-recovery-sha=}
      [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--recover-verify "--source-recovery-sha=${source_sha}")
      ;;
    *) return 2 ;;
  esac
}
