#!/usr/bin/env bash

# stage 60/90 共用的 helm 调用与瞬态 kubeconfig 生命周期。
# helm 无法从管道读 kubeconfig，只能落到 /root 下的私有临时文件；该文件是
# `--check` 零写入原则唯一文档化的例外，因此目录 700、文件 600、内容与
# ADMIN_CONF_CONTENT 逐字节一致、退出时必被清理，四者都必须成立。
# helm_archive_is_safe 改为必须显式传参：60 有 staged 与 apply 快照两个来源，
# 默认参数会让调用点看不出用的是哪一个。
# 依赖：safe_file/safe_directory/python_isolated（lib/exec-safety.sh）、
# ADMIN_CONF_CONTENT（lib/kubectl.sh），以及各 stage 声明的 $helm_binary 与
# $HELM_MEMBER。同 exec-safety.sh 的契约：缺失时 set -u 直接报未绑定变量。
# SC2154 只对小写变量告警（全大写被当成环境变量豁免），故显式关闭。
# shellcheck disable=SC2154
helm_lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${helm_lib_dir}/exec-safety.sh"
# shellcheck disable=SC1091
source "${helm_lib_dir}/kubectl.sh"

helm_run() {
  PYTHONDONTWRITEBYTECODE=1 KUBECACHEDIR=/dev/null "$helm_binary" "$@"
}

# 当前 helm kubeconfig 临时目录；EXIT trap 据此清理，成功 rmdir 后清空。
helm_kubeconfig_dir=

cleanup_helm_kubeconfig() {
  local parent
  [[ -n "$helm_kubeconfig_dir" ]] || return 0
  parent=$(host_path /root)
  [[ "${helm_kubeconfig_dir%/*}" == "$parent" &&
      "${helm_kubeconfig_dir##*/}" == .helm-kubeconfig.* ]] || return 1
  [[ -d "$helm_kubeconfig_dir" && ! -L "$helm_kubeconfig_dir" ]] || return 1
  rm -f -- "${helm_kubeconfig_dir}/config" || return 1
  rmdir -- "$helm_kubeconfig_dir" || return 1
  helm_kubeconfig_dir=
}

helm_cluster_run() {
  local exit_code=0 parent kubeconfig_dir kubeconfig
  admin_conf_is_safe || return 1
  parent=$(host_path /root)
  safe_directory "$parent" 700 || return 1
  kubeconfig_dir=$(mktemp -d "${parent}/.helm-kubeconfig.XXXXXX") || return 1
  helm_kubeconfig_dir=$kubeconfig_dir
  # 命令替换子 shell 会把 EXIT trap 重置为继承值，主 shell 的 trap 看不到子 shell
  # 里的目录名；只在子 shell 内补装，避免覆盖主 shell 的 APPLY trap。
  (( BASH_SUBSHELL == 0 )) || trap 'cleanup_helm_kubeconfig || :' EXIT
  kubeconfig="${kubeconfig_dir}/config"
  if ! safe_directory "$kubeconfig_dir" 700 ||
     ! printf '%s' "$ADMIN_CONF_CONTENT" >"$kubeconfig" ||
     ! safe_file "$kubeconfig" 600 ||
     ! cmp -s "$kubeconfig" <(printf '%s' "$ADMIN_CONF_CONTENT"); then
    rm -f -- "$kubeconfig"
    if rmdir -- "$kubeconfig_dir" 2>/dev/null; then
      helm_kubeconfig_dir=
    fi
    return 1
  fi
  PYTHONDONTWRITEBYTECODE=1 KUBECACHEDIR=/dev/null "$helm_binary" \
    --kubeconfig "$kubeconfig" "$@" || exit_code=$?
  rm -f -- "$kubeconfig" || return 1
  rmdir -- "$kubeconfig_dir" || return 1
  helm_kubeconfig_dir=
  admin_conf_is_safe || return 1
  return "$exit_code"
}

helm_kubeconfig_residue_exists() (
  local entry
  shopt -s nullglob dotglob
  for entry in "$(host_path /root)"/.helm-kubeconfig.*; do
    : "$entry"
    exit 0
  done
  exit 1
)

helm_values_json_state() {
  python_isolated -c '
import json
import sys

desired = {
    "kubeProxyReplacement": True,
    "k8sServiceHost": sys.argv[1],
    "k8sServicePort": 6443,
    "cgroup": {
        "autoMount": {"enabled": False},
        "hostRoot": "/sys/fs/cgroup",
    },
    "gatewayAPI": {"enabled": True, "hostNetwork": {"enabled": True}},
    "envoy": {
        "enabled": True,
        "securityContext": {
            "capabilities": {
                "keepCapNetBindService": True,
                "envoy": ["NET_ADMIN", "SYS_ADMIN", "NET_BIND_SERVICE"],
            },
        },
    },
    "hubble": {"enabled": False},
    "image": {
        "digest": "sha256:383968cd5e8873f7976fa76aa6196045643558f4cc9518a207b9335cb24a0e93",
        "useDigest": True,
    },
    "ipam": {"mode": "kubernetes"},
    "operator": {
        "rollOutPods": True,
        "image": {
            "genericDigest": "sha256:80744a8cc7c91c2f9e6347629406844eb35d79b30a732c6d41c15b17232a74f3",
            "useDigest": True,
        },
        "replicas": 1,
    },
}
pre_rollout = dict(desired)
pre_rollout["operator"] = dict(desired["operator"])
del pre_rollout["operator"]["rollOutPods"]
legacy = dict(pre_rollout)
legacy["gatewayAPI"] = {"enabled": True}
del legacy["envoy"]

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

def reject_constant(_value):
    raise ValueError("non-finite number")

def exactly_equal(actual, wanted):
    if type(actual) is not type(wanted):
        return False
    if isinstance(wanted, dict):
        return set(actual) == set(wanted) and all(
            exactly_equal(actual[key], wanted[key]) for key in wanted
        )
    if isinstance(wanted, list):
        return len(actual) == len(wanted) and all(
            exactly_equal(left, right) for left, right in zip(actual, wanted)
        )
    return actual == wanted

try:
    actual = json.load(
        sys.stdin,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
except (TypeError, ValueError):
    print("UNKNOWN")
    raise SystemExit(0)
if exactly_equal(actual, desired):
    print("DESIRED")
elif exactly_equal(actual, pre_rollout):
    print("PRE_ROLLOUT")
elif exactly_equal(actual, legacy):
    print("LEGACY")
else:
    print("UNKNOWN")
' "$HOST_NODE_IP" 2>/dev/null
}

helm_values_json_is_exact() {
  [[ "$(helm_values_json_state)" == DESIRED ]]
}

helm_values_json_is_legacy() {
  [[ "$(helm_values_json_state)" == LEGACY ]]
}

helm_values_json_is_pre_rollout() {
  [[ "$(helm_values_json_state)" == PRE_ROLLOUT ]]
}

helm_cilium_revision_values_state() {
  local output revision=$1 state
  [[ "$revision" == 1 || "$revision" == 2 || "$revision" == 3 ]] || {
    printf 'UNKNOWN\n'
    return
  }
  output=$(helm_cluster_run get values cilium \
    --namespace kube-system --revision "$revision" --output json 2>/dev/null) || {
    printf 'UNKNOWN\n'
    return
  }
  state=$(printf '%s' "$output" | helm_values_json_state) || state=UNKNOWN
  printf '%s\n' "$state"
}

# 只接受仓库曾明确交付过的 Cilium values 血统；Secret 标签只能证明 revision
# 号码，不能证明各 revision 实际使用了哪组 values。
helm_cilium_values_lineage_state() {
  local current=$1 revision_one revision_two revision_three
  [[ "$current" == 1 || "$current" == 2 || "$current" == 3 ]] || {
    printf 'UNKNOWN\n'
    return
  }
  revision_one=$(helm_cilium_revision_values_state 1)
  case "$current" in
    1)
      case "$revision_one" in
        DESIRED) printf 'DESIRED_REVISION_1\n' ;;
        LEGACY) printf 'LEGACY_REVISION_1\n' ;;
        *) printf 'UNKNOWN\n' ;;
      esac
      ;;
    2)
      revision_two=$(helm_cilium_revision_values_state 2)
      if [[ "$revision_one" == LEGACY && "$revision_two" == DESIRED ]]; then
        printf 'DESIRED_REVISION_2\n'
      elif [[ "$revision_one" == LEGACY && "$revision_two" == PRE_ROLLOUT ]]; then
        printf 'PRE_ROLLOUT_REVISION_2\n'
      else
        printf 'UNKNOWN\n'
      fi
      ;;
    3)
      revision_two=$(helm_cilium_revision_values_state 2)
      revision_three=$(helm_cilium_revision_values_state 3)
      if [[ "$revision_one" == LEGACY && "$revision_two" == PRE_ROLLOUT &&
            "$revision_three" == DESIRED ]]; then
        printf 'DESIRED_REVISION_3\n'
      else
        printf 'UNKNOWN\n'
      fi
      ;;
  esac
}

# Cilium 1.20.0 的 operator.rollOutPods 注解是 cilium-configmap.yaml 渲染结果
# 的 SHA-256。用已钉死的本地 Chart 与 values 离线重放同一模板，并显式固定
# Kubernetes capability；只接受唯一、带双引号的 64 位小写摘要。
helm_rendered_cilium_operator_checksum() {
  local chart=$1 output values=$2
  output=$(helm_run template cilium "$chart" \
    --namespace kube-system \
    --values "$values" \
    --kube-version v1.36.3 \
    --show-only templates/cilium-operator/deployment.yaml 2>/dev/null) || return 1
  printf '%s' "$output" | python_isolated -c '
import re
import sys
document = sys.stdin.read()
matches = re.findall(
    r"^[ \t]*cilium\.io/cilium-configmap-checksum:[ \t]*\"([0-9a-f]{64})\"[ \t]*$",
    document,
    flags=re.MULTILINE,
)
identity = (
    len(re.findall(r"^apiVersion:[ \t]*apps/v1[ \t]*$", document, re.MULTILINE)) == 1 and
    len(re.findall(r"^kind:[ \t]*Deployment[ \t]*$", document, re.MULTILINE)) == 1 and
    len(re.findall(r"^[ ]{2}name:[ \t]*cilium-operator[ \t]*$", document, re.MULTILINE)) == 1 and
    len(re.findall(r"^[ ]{2}namespace:[ \t]*kube-system[ \t]*$", document, re.MULTILINE)) == 1
)
if len(matches) != 1 or not identity:
    raise SystemExit(1)
print(matches[0])
' 2>/dev/null
}

helm_archive_is_safe() {
  local archive=$1
  python_isolated - "$archive" "$HELM_MEMBER" <<'PY' >/dev/null 2>&1
import pathlib
import sys
import tarfile

archive_path, expected_member = sys.argv[1:]
try:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        matches = []
        for member in archive.getmembers():
            path = pathlib.PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not member.name:
                raise SystemExit(1)
            if not (member.isfile() or member.isdir()):
                raise SystemExit(1)
            if member.name == expected_member:
                matches.append(member)
        if len(matches) != 1 or not matches[0].isfile():
            raise SystemExit(1)
        if matches[0].mode & 0o111 == 0:
            raise SystemExit(1)
except (OSError, tarfile.TarError):
    raise SystemExit(1)
PY
}
