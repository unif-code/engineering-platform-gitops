#!/bin/bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)

command -v python3 >/dev/null 2>&1 || {
  echo 'ERROR: python3 is required for validation.' >&2
  exit 1
}

command -v kubectl >/dev/null 2>&1 || {
  echo 'ERROR: kubectl is required for Kustomize validation.' >&2
  exit 1
}

command -v shellcheck >/dev/null 2>&1 || {
  echo 'ERROR: shellcheck is required for bootstrap validation.' >&2
  exit 1
}

# CI 钉死 shellcheck 0.9.0（.github/workflows/validate.yml）。本地版本不同的诊断集
# 会导致「本地绿、CI 红」，因此这里打印实际版本并在不一致时提示对齐方式，但不阻断
# 本地运行——权威门禁始终是 CI。
readonly EXPECTED_SHELLCHECK_VERSION=0.9.0
shellcheck_version=$(shellcheck --version | awk '/^version:/ {print $2}')
printf 'shellcheck %s (CI pins %s)\n' \
  "$shellcheck_version" "$EXPECTED_SHELLCHECK_VERSION"
if [[ "$shellcheck_version" != "$EXPECTED_SHELLCHECK_VERSION" ]]; then
  printf 'WARNING: 本地 shellcheck 与 CI 不一致；如需完全对齐可运行\n' >&2
  printf '  python3 -m venv /tmp/sc && /tmp/sc/bin/pip install shellcheck-py==%s.6\n' \
    "$EXPECTED_SHELLCHECK_VERSION" >&2
fi

PYTHONDONTWRITEBYTECODE=1 python3 -c 'import yaml'
PYTHONDONTWRITEBYTECODE=1 python3 "$repo_root/scripts/validate.py"
shellcheck \
  "$repo_root"/scripts/bootstrap/lib/*.sh \
  "$repo_root"/scripts/bootstrap/*.sh
