#!/bin/bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)

PYTHONDONTWRITEBYTECODE=1 \
  python3 "$repo_root/scripts/run_validation.py" --profile fast
"$repo_root/scripts/validate-static.sh"
