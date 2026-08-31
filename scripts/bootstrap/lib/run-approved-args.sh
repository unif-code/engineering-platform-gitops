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
  case "$mode:$#" in
    --check:0)
      RUN_APPROVED_TARGET_ARGUMENTS=(--check)
      ;;
    --apply:0)
      RUN_APPROVED_TARGET_ARGUMENTS=(--apply)
      ;;
    --check:2)
      [[ "$1" == --stage=180 && "$2" == --source-recovery-sha=* ]] || return 2
      source_sha=${2#--source-recovery-sha=}
      [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
      RUN_APPROVED_TARGET=openbao-initialize
      RUN_APPROVED_TARGET_ARGUMENTS=(--check "--source-recovery-sha=${source_sha}")
      ;;
    --apply:2)
      [[ "$1" == --stage=180 ]] || return 2
      RUN_APPROVED_TARGET=openbao-initialize
      case "$2" in
        --operation=initialize) RUN_APPROVED_TARGET_ARGUMENTS=(--initialize) ;;
        --operation=configure) RUN_APPROVED_TARGET_ARGUMENTS=(--configure) ;;
        --operation=accept) RUN_APPROVED_TARGET_ARGUMENTS=(--accept) ;;
        *) return 2 ;;
      esac
      ;;
    --apply:3)
      [[ "$1" == --stage=180 ]] || return 2
      [[ "$3" == --source-recovery-sha=* ]] || return 2
      source_sha=${3#--source-recovery-sha=}
      [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
      RUN_APPROVED_TARGET=openbao-initialize
      case "$2" in
        --operation=recover-start)
          RUN_APPROVED_TARGET_ARGUMENTS=(--recover-start "--source-recovery-sha=${source_sha}")
          ;;
        --operation=recover-verify)
          RUN_APPROVED_TARGET_ARGUMENTS=(--recover-verify "--source-recovery-sha=${source_sha}")
          ;;
        *) return 2 ;;
      esac
      ;;
    *) return 2 ;;
  esac
}
