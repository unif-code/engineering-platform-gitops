#!/bin/bash
# 运维一行入口：校验已批准的 SHA 与仓库状态后，在干净环境中执行 bootstrap-all。
# 用法：scripts/bootstrap/run-approved.sh <approved-sha> --check|--apply
# 门禁与既往人工粘贴的脚本一致（SHA、origin、main、干净树、ff-only、helm 残留、
# umask 022），并用 env -i 白名单环境启动 bootstrap-all，杜绝交互 shell 遗留变量
# 触发 stage 的 untrusted-environment-override 拒绝。
set -Eeuo pipefail
export LC_ALL=C
umask 022

usage() {
  printf 'usage: %s <approved-sha> --check|--apply\n' "${0##*/}" >&2
  exit 2
}

[[ $# -eq 2 ]] || usage
approved_sha=$1
mode=$2
case "$mode" in
  --check|--apply) ;;
  *) usage ;;
esac
[[ "$approved_sha" =~ ^[0-9a-f]{40}$ ]] || {
  echo 'STOP: invalid approved SHA'
  exit 90
}
if [[ "$mode" == --apply && "$EUID" -ne 0 ]]; then
  echo 'STOP: --apply must run as root'
  exit 91
fi

script_source=${BASH_SOURCE[0]}
case "$script_source" in
  /*) ;;
  *) script_source="$PWD/$script_source" ;;
esac
script_dir=$(cd "${script_source%/*}" && pwd -P)
repo=$(cd "${script_dir}/../.." && pwd -P)

[[ -d "$repo/.git" && ! -L "$repo" ]] || {
  echo 'STOP: repository is missing or unsafe'
  exit 92
}
origin_url=$(/usr/bin/git -C "$repo" remote get-url origin)
case "$origin_url" in
  *unif-code/engineering-platform-gitops.git) ;;
  *)
    printf 'STOP: unexpected origin: %s\n' "$origin_url"
    exit 93
    ;;
esac
[[ "$(/usr/bin/git -C "$repo" branch --show-current)" == main ]] || {
  echo 'STOP: current branch is not main'
  exit 94
}

worktree=$(/usr/bin/git -C "$repo" status --porcelain=v1 --untracked-files=all)
[[ -z "$worktree" ]] || {
  echo 'STOP: worktree is not clean'
  printf '%s\n' "$worktree"
  exit 95
}

/usr/bin/git -C "$repo" fetch --prune origin main
[[ "$(/usr/bin/git -C "$repo" rev-parse origin/main)" == "$approved_sha" ]] || {
  echo 'STOP: origin/main SHA mismatch'
  exit 96
}
/usr/bin/git -C "$repo" merge --ff-only "$approved_sha"
[[ "$(/usr/bin/git -C "$repo" rev-parse HEAD)" == "$approved_sha" ]] || {
  echo 'STOP: local HEAD SHA mismatch'
  exit 97
}

# 上次运行被中断留下的 helm kubeconfig 残留：只检测并停止，由运维检查后手工清理。
if [[ "$EUID" -eq 0 ]]; then
  for residue in /root/.helm-kubeconfig.*; do
    [[ -e "$residue" || -L "$residue" ]] || continue
    printf 'STOP: helm kubeconfig residue present: %s\n' "$residue"
    exit 98
  done
fi

set +e
/usr/bin/env -i HOME="${HOME:-/root}" PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /bin/bash -p "$repo/scripts/bootstrap/bootstrap-all.sh" "$mode"
rc=$?
set -e
printf 'COMMAND_EXIT_CODE=%s\n' "$rc"
exit "$rc"
