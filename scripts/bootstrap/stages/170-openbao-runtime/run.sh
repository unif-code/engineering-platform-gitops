#!/bin/bash -p
set -Eeuo pipefail
export LC_ALL=C
umask 077
readonly PHASE=openbao-runtime
readonly BUSINESS_STAGE=170
export PHASE BUSINESS_STAGE
stage_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${stage_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/openbao-runtime.sh"
openbao_stage_main "$@"
