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

PYTHONDONTWRITEBYTECODE=1 python3 -c 'import yaml'
PYTHONDONTWRITEBYTECODE=1 python3 "$repo_root/scripts/validate.py"
shellcheck \
  "$repo_root"/scripts/bootstrap/lib/*.sh \
  "$repo_root"/scripts/bootstrap/*.sh
