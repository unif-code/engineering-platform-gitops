#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)

command -v kubectl >/dev/null 2>&1 || {
  echo 'ERROR: kubectl is required for Kustomize validation.' >&2
  exit 1
}

python3 -c 'import yaml' >/dev/null 2>&1 || {
  echo 'ERROR: PyYAML is required (python3 -m pip install PyYAML==6.0.3).' >&2
  exit 1
}

python3 "$repo_root/scripts/validate.py"
