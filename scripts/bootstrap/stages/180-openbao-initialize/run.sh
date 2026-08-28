#!/bin/bash -p
set -Eeuo pipefail
export LC_ALL=C
umask 077
readonly PHASE=openbao-initialize
export PHASE
stage_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${stage_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/openbao-initialize.sh"
openbao_initialize_main "$@"
