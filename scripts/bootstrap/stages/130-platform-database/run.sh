#!/bin/bash -p
set -Eeuo pipefail
export LC_ALL=C
umask 077
readonly PHASE=platform-database
readonly BUSINESS_STAGE=130
export PHASE BUSINESS_STAGE
stage_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${stage_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/business-ready.sh"
business_stage_main "$@"
