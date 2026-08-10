#!/usr/bin/env bash
set -Eeuo pipefail
export LC_ALL=C
umask 077

if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
  if [[ "$EUID" -eq 0 ]]; then
    printf 'RESULT=STOP_TEST_MODE\nREASON=test-mode-is-for-unprivileged-tests-only\n' >&2
    exit 10
  fi
  if [[ -z "${BOOTSTRAP_TEST_ROOT:-}" || "$BOOTSTRAP_TEST_ROOT" != /* || "$BOOTSTRAP_TEST_ROOT" == / || ! -d "$BOOTSTRAP_TEST_ROOT" || -L "$BOOTSTRAP_TEST_ROOT" || ! -O "$BOOTSTRAP_TEST_ROOT" ]]; then
    printf 'RESULT=STOP_TEST_MODE\nREASON=test-root-must-be-isolated\n' >&2
    exit 10
  fi
else
  export PATH=/usr/sbin:/usr/bin:/sbin:/bin
  for test_override in "${!BOOTSTRAP_TEST_@}"; do
    : "$test_override"
    printf 'RESULT=STOP_TEST_OVERRIDE\nREASON=test-override-in-production\n' >&2
    exit 10
  done
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${script_dir}/lib/common.sh"

# PHASE 由公共 evidence helper 间接读取。
# shellcheck disable=SC2034
readonly PHASE=install-kubernetes
readonly REPOSITORY_URL='https://pkgs.k8s.io/core:/stable:/v1.36/deb/'
readonly RELEASE_KEY_URL="${REPOSITORY_URL}Release.key"
readonly RELEASE_KEY_SHA256=7627818cf7bae52f9008c93e8b1f961f53dea11d40891778de216fb1b43be54d
readonly RELEASE_KEY_FINGERPRINT=DE15B14486CD377B9E876E1A234654DA9A296436
readonly SOURCE_CONTENT='deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /'
readonly -a PACKAGES=(kubeadm kubectl kubelet kubernetes-cni)
readonly -a BASE_DEPENDENCIES=(iptables mount util-linux libc6)

host_path() {
  local absolute=$1
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 ]]; then
    printf '%s%s\n' "${BOOTSTRAP_TEST_ROOT:?}" "$absolute"
  else
    printf '%s\n' "$absolute"
  fi
}

complete() {
  local result=$1 reason=$2 code=$3 next=$4
  finish_phase "$result" "$reason" "$code" "$next"
  exit "$code"
}

path_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null
}

path_owner() {
  stat -c '%u:%g' "$1" 2>/dev/null || stat -f '%u:%g' "$1" 2>/dev/null
}

path_size() {
  stat -c '%s' "$1" 2>/dev/null || stat -f '%z' "$1" 2>/dev/null
}

owned_by_expected() {
  local expected_uid=0 expected_gid=0
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 && "$EUID" -ne 0 ]]; then
    expected_uid=$EUID
    expected_gid=${GROUPS[0]}
  fi
  [[ "$(path_owner "$1")" == "${expected_uid}:${expected_gid}" ]]
}

managed_parent_safe() {
  [[ -d "$1" && ! -L "$1" && "$(path_mode "$1")" == 755 ]] && owned_by_expected "$1"
}

download_parent_safe() {
  local mode
  mode=$(path_mode "$1") || return 1
  [[ -d "$1" && ! -L "$1" && -k "$1" && ( "$mode" == 1777 || "$mode" == 777 ) ]] && owned_by_expected "$1"
}

package_version() {
  case "$1" in
    kubeadm|kubectl|kubelet) printf '1.36.3-1.1\n' ;;
    kubernetes-cni) printf '1.9.1-1.1\n' ;;
    *) return 1 ;;
  esac
}

package_sha256() {
  case "$1" in
    kubeadm) printf '7225b4b7928de8bb9b7a69b75524c2df1a6f78fcbb40724f7e5b49926119c2af\n' ;;
    kubectl) printf '22c1bbcecfdee50ad013ab7ab9e90ea9d3aaa01d3ac38ac578534976f856c330\n' ;;
    kubelet) printf '99c77d7c814ac0b0f1f346c11074160fbbab8243c27ba4236f84f2e536c8eaca\n' ;;
    kubernetes-cni) printf '4cd72d8cef4499d3dc410874287b40e8b4241e0772938c5820cbee37986c1d93\n' ;;
    *) return 1 ;;
  esac
}

package_size() {
  case "$1" in
    kubeadm) printf '12558824\n' ;;
    kubectl) printf '11766348\n' ;;
    kubelet) printf '13386608\n' ;;
    kubernetes-cni) printf '38991216\n' ;;
    *) return 1 ;;
  esac
}

package_filename() {
  local package=$1
  printf 'amd64/%s_%s_amd64.deb\n' "$package" "$(package_version "$package")"
}

cni_manifest() {
  cat <<'EOF'
LICENSE	644	11357	b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1
README.md	644	2343	43c32d29316a4a9fe23af500917bd89e51d6a84fa0dcbfcc75b5fbd834c3145a
bandwidth	755	5042926	01c59cee777ade0608361d94bf3bfe01bda82bc8da276d8be917e225aa660639
bridge	755	5698763	3553f5e8f47ed62aec728ab6f7444f6bf1624f916769852c6deb52cd216e22ba
dhcp	755	13725422	bf0552ff2ef54fbd8846b21ffe149f4de63dcd98d86d6b91de5e0bd94473870d
dummy	755	5251069	88f9c9d018681a2b806db2c33184a0a4a532773cb71a60e975a9bf2f017199f6
firewall	755	5702145	ecbd112d77192a125e85ab1fa4ded6cfaf4e9732172e072ee248caa81eba7aed
host-device	755	5159967	a891bd77c5e25b6c4dfa65c8b78cf7f0a00be5ba5d5bbeccd902c08d7f0ea7f3
host-local	755	4350778	ac5ff19b1120bd1d58203b20d45165f244691fcf9776ba55d6dd1747f043c90f
ipvlan	755	5274322	40ceded59770a0f28e7a45a0ed5f8c49044e786bc728f34d6c9de7bc5d3fb660
loopback	755	4302030	02956bdd03b9b71693b3efd72afce88384e4472b644a1c6410fe817f618c1a83
macvlan	755	5307111	33d2730d229dea786c56465a1a96db84ca27b3d5ac552bbc9aa5cdc942622814
portmap	755	5108385	10cc11a28d9c16465889eb59968be76cf04fa884939edf70c27b722cec2c0156
ptp	755	5475470	1cbbce28e96accfef5fe6021762a55ad2b114705f410b8837361a201df6c0b03
sbr	755	4525826	bb886c24182afbad535f158b585524b08a9f1cf0618679987d6b0e11ebf50bb5
static	755	3776708	7bf980bedb303f6d314239413fd4aca5479a9affcd38509057ae203b0da67058
tap	755	5453308	ebff11573fa4ed5793cc08776b8811a3c0f44705b2b530fd5014e6bf69275c1a
tuning	755	4389084	4659e9129d8c669c21c932cd778dc1ac17a717d100768ea23242883401cbb536
vlan	755	5267679	5f6973d15ad2b0d44d1dc0e59982ed05e34e4709630ecd367f766202f9034ac8
vrf	755	4685012	3f3363182c4777bd0d3ead028147f9ecebd60bb32f2d47b7c181877a00ae049b
EOF
}

source_state() {
  local target=$1 actual
  if [[ ! -e "$target" && ! -L "$target" ]]; then
    printf 'MISSING\n'
    return
  fi
  if [[ -L "$target" || ! -f "$target" || "$(path_mode "$target")" != 644 ]] || ! owned_by_expected "$target"; then
    printf 'UNKNOWN\n'
    return
  fi
  actual=$(<"$target") || {
    printf 'UNKNOWN\n'
    return
  }
  if [[ "$actual" == "$SOURCE_CONTENT" && "$(wc -l <"$target" | tr -d ' ')" == 1 ]]; then
    printf 'COMPLIANT\n'
  else
    printf 'UNKNOWN\n'
  fi
}

keyring_fingerprint() {
  gpg --batch --no-options --no-autostart --show-keys --with-colons --fingerprint "$1" 2>/dev/null |
    awk -F: '$1 == "fpr" {print $10}'
}

keyring_state() {
  local target=$1 fingerprints
  if [[ ! -e "$target" && ! -L "$target" ]]; then
    printf 'MISSING\n'
    return
  fi
  if [[ -L "$target" || ! -f "$target" || "$(path_mode "$target")" != 644 ]] || ! owned_by_expected "$target"; then
    printf 'UNKNOWN\n'
    return
  fi
  fingerprints=$(keyring_fingerprint "$target") || {
    printf 'UNKNOWN\n'
    return
  }
  if [[ "$fingerprints" == "$RELEASE_KEY_FINGERPRINT" ]]; then
    printf 'COMPLIANT\n'
  else
    printf 'UNKNOWN\n'
  fi
}

publish_new_file() {
  local source=$1 target=$2 mode=$3 temporary
  managed_parent_safe "${target%/*}" || return "$EXIT_UNKNOWN_STATE"
  temporary=$(mktemp "${target}.tmp.XXXXXX") || return "$EXIT_APPLY_FAILED"
  if ! install -m "$mode" "$source" "$temporary" || ! sync "$temporary"; then
    rm -f -- "$temporary"
    return "$EXIT_APPLY_FAILED"
  fi
  if ! managed_parent_safe "${target%/*}" || ! owned_by_expected "$temporary"; then
    rm -f -- "$temporary"
    return "$EXIT_UNKNOWN_STATE"
  fi
  if ! ln "$temporary" "$target" 2>/dev/null; then
    rm -f -- "$temporary"
    return "$EXIT_UNKNOWN_STATE"
  fi
  rm -f -- "$temporary"
}

publish_source() {
  local target=$1 temporary
  managed_parent_safe "${target%/*}" || return "$EXIT_UNKNOWN_STATE"
  temporary=$(mktemp "${target}.content.XXXXXX") || return "$EXIT_APPLY_FAILED"
  if ! printf '%s\n' "$SOURCE_CONTENT" >"$temporary" || ! chmod 0644 "$temporary" || ! sync "$temporary"; then
    rm -f -- "$temporary"
    return "$EXIT_APPLY_FAILED"
  fi
  if ! managed_parent_safe "${target%/*}" || ! owned_by_expected "$temporary"; then
    rm -f -- "$temporary"
    return "$EXIT_UNKNOWN_STATE"
  fi
  if ! ln "$temporary" "$target" 2>/dev/null; then
    rm -f -- "$temporary"
    return "$EXIT_UNKNOWN_STATE"
  fi
  rm -f -- "$temporary"
}

installed_record() {
  dpkg-query -W -f='${Status}\t${Version}\t${Architecture}\n' "$1" 2>/dev/null
}

candidate_is_exact() {
  local package=$1 expected output candidate repo_count
  expected=$(package_version "$package")
  output=$(apt-cache policy "$package" 2>/dev/null) || return 1
  candidate=$(awk '/^[[:space:]]*Candidate:/ {print $2; count++} END {exit count != 1}' <<<"$output") || return 1
  [[ "$candidate" == "$expected" ]] || return 1
  repo_count=$(grep -Fc "${REPOSITORY_URL%/}" <<<"$output")
  [[ "$repo_count" == 1 ]]
}

signed_index_record() {
  local package=$1 version output
  version=$(package_version "$package")
  output=$(apt-cache show --no-all-versions "${package}=${version}" 2>/dev/null) || return 1
  awk '
    /^Package: / {package=$2; packages++}
    /^Version: / {version=$2; versions++}
    /^Architecture: / {architecture=$2; architectures++}
    /^Filename: / {filename=$2; filenames++}
    /^Size: / {size=$2; sizes++}
    /^SHA256: / {sha256=$2; digests++}
    END {
      if (packages != 1 || versions != 1 || architectures != 1 ||
          filenames != 1 || sizes != 1 || digests != 1) exit 1
      print package "\t" version "\t" architecture "\t" filename "\t" size "\t" sha256
    }
  ' <<<"$output"
}

cni_directory_state() {
  local root=$1 logical_root=/opt/cni/bin actual_names expected_names
  local name mode size digest target actual_digest ownership
  if [[ ! -e "$root" && ! -L "$root" ]]; then
    printf 'MISSING\n'
    return
  fi
  if [[ -L "$root" || ! -d "$root" || "$(path_mode "$root")" != 755 ]] || ! owned_by_expected "$root"; then
    printf 'UNKNOWN\n'
    return
  fi
  actual_names=$(find "$root" -mindepth 1 -maxdepth 1 -print 2>/dev/null | sed 's#.*/##' | sort) || {
    printf 'UNKNOWN\n'
    return
  }
  expected_names=$(cni_manifest | awk -F '\t' '{print $1}' | sort)
  if [[ "$actual_names" != "$expected_names" ]]; then
    printf 'UNKNOWN\n'
    return
  fi
  while IFS=$'\t' read -r name mode size digest; do
    target="${root}/${name}"
    if [[ -L "$target" || ! -f "$target" || "$(path_mode "$target")" != "$mode" || "$(path_size "$target")" != "$size" ]] || ! owned_by_expected "$target"; then
      printf 'UNKNOWN\n'
      return
    fi
    actual_digest=$(sha256_file "$target") || {
      printf 'UNKNOWN\n'
      return
    }
    [[ "$actual_digest" == "$digest" ]] || {
      printf 'UNKNOWN\n'
      return
    }
    ownership=$(dpkg-query -S "${logical_root}/${name}" 2>/dev/null) || {
      printf 'UNKNOWN\n'
      return
    }
    [[ "$ownership" == "kubernetes-cni: ${logical_root}/${name}" ]] || {
      printf 'UNKNOWN\n'
      return
    }
  done < <(cni_manifest)
  printf 'COMPLIANT\n'
}

target_holds() {
  apt-mark showhold 2>/dev/null |
    awk '$1 == "kubeadm" || $1 == "kubectl" || $1 == "kubelet" || $1 == "kubernetes-cni" {print}' |
    sort
}

verify_installed_state() {
  local package expected record holds
  for package in "${PACKAGES[@]}"; do
    expected=$(package_version "$package")
    record=$(installed_record "$package") || return 1
    [[ "$record" == $'install ok installed\t'"${expected}"$'\tamd64' ]] || return 1
    candidate_is_exact "$package" || return 1
  done
  holds=$(target_holds)
  [[ "$holds" == $'kubeadm\nkubectl\nkubelet\nkubernetes-cni' ]] || return 1
  [[ "$(cni_directory_state "$(host_path /opt/cni/bin)")" == COMPLIANT ]]
}

download_directory_exact() {
  local directory=$1
  shift
  local actual expected path
  actual=$(find "$directory" -mindepth 1 -maxdepth 1 -print 2>/dev/null | sed 's#.*/##' | sort) || return 1
  expected=$(printf '%s\n' "$@" | sort)
  [[ "$actual" == "$expected" ]] || return 1
  while IFS= read -r path; do
    [[ -f "$path" && ! -L "$path" ]] || return 1
    owned_by_expected "$path" || return 1
  done < <(find "$directory" -mindepth 1 -maxdepth 1 -print 2>/dev/null | sort)
}

parse_mode "$@" || exit "$?"
require_root || complete STOP_PRECONDITION not-root "$EXIT_PRECONDITION" NONE
for required_command in apt-cache apt-get apt-mark awk cat chmod curl date dpkg-deb dpkg-query find gpg grep id install ln mktemp rm sed sort stat sync tr wc; do
  require_command "$required_command" || complete STOP_PRECONDITION "missing-command-${required_command}" "$EXIT_PRECONDITION" NONE
done
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  complete STOP_PRECONDITION missing-command-sha256 "$EXIT_PRECONDITION" NONE
fi

for dependency in "${BASE_DEPENDENCIES[@]}"; do
  dependency_state=$(dpkg-query -W -f='${Status}\n' "$dependency" 2>/dev/null) || complete STOP_UNKNOWN_STATE "base-dependency-missing-${dependency}" "$EXIT_UNKNOWN_STATE" NONE
  [[ "$dependency_state" == 'install ok installed' ]] || complete STOP_UNKNOWN_STATE "base-dependency-drift-${dependency}" "$EXIT_UNKNOWN_STATE" NONE
done
if dpkg-query -W -f='${Status}\t${Version}\t${Architecture}\n' cri-tools >/dev/null 2>&1; then
  complete STOP_UNKNOWN_STATE cri-tools-package-forbidden "$EXIT_UNKNOWN_STATE" NONE
fi
if apt-mark showhold 2>/dev/null | grep -Fxq cri-tools; then
  complete STOP_UNKNOWN_STATE cri-tools-hold-forbidden "$EXIT_UNKNOWN_STATE" NONE
fi

keyring_target=$(host_path /etc/apt/keyrings/kubernetes-apt-keyring.gpg)
source_target=$(host_path /etc/apt/sources.list.d/kubernetes.list)
for parent in "${keyring_target%/*}" "${source_target%/*}"; do
  managed_parent_safe "$parent" || complete STOP_UNKNOWN_STATE apt-parent-unsafe "$EXIT_UNKNOWN_STATE" NONE
done
while IFS= read -r source_file; do
  if [[ -L "$source_file" || ! -f "$source_file" ]]; then
    complete STOP_UNKNOWN_STATE apt-source-file-unsafe "$EXIT_UNKNOWN_STATE" NONE
  fi
  if [[ "$source_file" != "$source_target" ]] && grep -Eiq 'pkgs\.k8s\.io|apt\.kubernetes\.io|packages\.cloud\.google\.com.*kubernetes|kubernetes' "$source_file"; then
    complete STOP_UNKNOWN_STATE unapproved-kubernetes-source "$EXIT_UNKNOWN_STATE" NONE
  fi
done < <(find "$(host_path /etc/apt)" -maxdepth 2 \( -name '*.list' -o -name '*.sources' \) -print 2>/dev/null | sort)

source_contract=$(source_state "$source_target")
keyring_contract=$(keyring_state "$keyring_target")
[[ "$source_contract" != UNKNOWN ]] || complete STOP_UNKNOWN_STATE kubernetes-source-unknown "$EXIT_UNKNOWN_STATE" NONE
[[ "$keyring_contract" != UNKNOWN ]] || complete STOP_UNKNOWN_STATE kubernetes-keyring-unknown "$EXIT_UNKNOWN_STATE" NONE
[[ "$source_contract" == "$keyring_contract" ]] || complete STOP_UNKNOWN_STATE partial-repository-contract "$EXIT_UNKNOWN_STATE" NONE

installed_count=0
for package in "${PACKAGES[@]}"; do
  if record=$(installed_record "$package"); then
    expected=$(package_version "$package")
    [[ "$record" == $'install ok installed\t'"${expected}"$'\tamd64' ]] || complete STOP_UNKNOWN_STATE "installed-package-drift-${package}" "$EXIT_UNKNOWN_STATE" NONE
    ((installed_count += 1))
  fi
done
(( installed_count == 0 || installed_count == ${#PACKAGES[@]} )) || complete STOP_UNKNOWN_STATE partial-kubernetes-installation "$EXIT_UNKNOWN_STATE" NONE
holds=$(target_holds)
hold_count=$(awk 'NF {count++} END {print count+0}' <<<"$holds")
(( hold_count == 0 || hold_count == ${#PACKAGES[@]} )) || complete STOP_UNKNOWN_STATE partial-kubernetes-hold "$EXIT_UNKNOWN_STATE" NONE
if (( installed_count == 0 && hold_count != 0 )); then
  complete STOP_UNKNOWN_STATE orphan-kubernetes-hold "$EXIT_UNKNOWN_STATE" NONE
fi
cni_state=$(cni_directory_state "$(host_path /opt/cni/bin)")
if (( installed_count == 0 )); then
  [[ "$cni_state" == MISSING ]] || complete STOP_UNKNOWN_STATE preexisting-cni-directory "$EXIT_UNKNOWN_STATE" NONE
else
  [[ "$source_contract" == COMPLIANT && "$hold_count" == "${#PACKAGES[@]}" && "$cni_state" == COMPLIANT ]] || complete STOP_UNKNOWN_STATE partial-kubernetes-contract "$EXIT_UNKNOWN_STATE" NONE
  verify_installed_state || complete STOP_VERIFY_FAILED kubernetes-package-verification-failed "$EXIT_VERIFY_FAILED" NONE
  complete ALREADY_COMPLIANT kubernetes-packages-ready 0 '50-kubeadm-init.sh --check'
fi

if [[ "$source_contract" == COMPLIANT ]]; then
  for package in "${PACKAGES[@]}"; do
    candidate_is_exact "$package" || complete STOP_UNKNOWN_STATE "candidate-drift-${package}" "$EXIT_UNKNOWN_STATE" NONE
  done
fi

# MODE 由公共 parse_mode helper 赋值。
# shellcheck disable=SC2153
if [[ "$MODE" == CHECK ]]; then
  complete PASS_KUBERNETES_CHECK apply-required 0 '40-install-kubernetes.sh --apply'
fi

if [[ "$source_contract" == MISSING ]]; then
  armored_key=$(mktemp "${keyring_target}.armored.XXXXXX") || complete STOP_APPLY_FAILED key-download-temp-failed "$EXIT_APPLY_FAILED" NONE
  decoded_key=$(mktemp "${keyring_target}.decoded.XXXXXX") || complete STOP_APPLY_FAILED key-decode-temp-failed "$EXIT_APPLY_FAILED" NONE
  if ! curl --fail --location --proto '=https' --tlsv1.2 --output "$armored_key" "$RELEASE_KEY_URL" >/dev/null 2>&1; then
    rm -f -- "$armored_key" "$decoded_key"
    complete STOP_APPLY_FAILED release-key-download-failed "$EXIT_APPLY_FAILED" NONE
  fi
  armored_digest=$(sha256_file "$armored_key") || true
  [[ "$armored_digest" == "$RELEASE_KEY_SHA256" ]] || {
    rm -f -- "$armored_key" "$decoded_key"
    complete STOP_SUPPLY_CHAIN_MISMATCH release-key-digest-mismatch "$EXIT_SUPPLY_CHAIN" NONE
  }
  armored_fingerprints=$(keyring_fingerprint "$armored_key") || true
  [[ "$armored_fingerprints" == "$RELEASE_KEY_FINGERPRINT" ]] || {
    rm -f -- "$armored_key" "$decoded_key"
    complete STOP_SUPPLY_CHAIN_MISMATCH release-key-fingerprint-mismatch "$EXIT_SUPPLY_CHAIN" NONE
  }
  if ! gpg --batch --no-options --no-autostart --yes --dearmor --output "$decoded_key" "$armored_key" >/dev/null 2>&1; then
    rm -f -- "$armored_key" "$decoded_key"
    complete STOP_APPLY_FAILED release-key-dearmor-failed "$EXIT_APPLY_FAILED" NONE
  fi
  publish_result=0
  publish_new_file "$decoded_key" "$keyring_target" 0644 || publish_result=$?
  rm -f -- "$armored_key" "$decoded_key"
  (( publish_result == 0 )) || {
    (( publish_result == EXIT_UNKNOWN_STATE )) && complete STOP_UNKNOWN_STATE keyring-publish-raced "$EXIT_UNKNOWN_STATE" NONE
    complete STOP_APPLY_FAILED keyring-publish-failed "$EXIT_APPLY_FAILED" NONE
  }
  publish_result=0
  publish_source "$source_target" || publish_result=$?
  (( publish_result == 0 )) || {
    (( publish_result == EXIT_UNKNOWN_STATE )) && complete STOP_UNKNOWN_STATE source-publish-raced "$EXIT_UNKNOWN_STATE" NONE
    complete STOP_APPLY_FAILED source-publish-failed "$EXIT_APPLY_FAILED" NONE
  }
fi

[[ "$(keyring_state "$keyring_target")" == COMPLIANT && "$(source_state "$source_target")" == COMPLIANT ]] || complete STOP_VERIFY_FAILED repository-contract-verification-failed "$EXIT_VERIFY_FAILED" NONE
apt-get -o APT::Update::Error-Mode=any update >/dev/null 2>&1 || complete STOP_APPLY_FAILED apt-update-failed "$EXIT_APPLY_FAILED" NONE
for package in "${PACKAGES[@]}"; do
  candidate_is_exact "$package" || complete STOP_UNKNOWN_STATE "candidate-drift-${package}" "$EXIT_UNKNOWN_STATE" NONE
done

download_parent=$(host_path /var/tmp)
download_parent_safe "$download_parent" || complete STOP_UNKNOWN_STATE download-parent-unsafe "$EXIT_UNKNOWN_STATE" NONE
download_dir=$(mktemp -d "${download_parent}/.kubernetes-debs.XXXXXX") || complete STOP_APPLY_FAILED download-directory-create-failed "$EXIT_APPLY_FAILED" NONE
if [[ "$(path_mode "$download_dir")" != 700 ]] || ! owned_by_expected "$download_dir"; then
  complete STOP_UNKNOWN_STATE download-directory-unsafe "$EXIT_UNKNOWN_STATE" NONE
fi
download_directory_exact "$download_dir" || complete STOP_UNKNOWN_STATE download-directory-not-empty "$EXIT_UNKNOWN_STATE" NONE
declare -a debs=() deb_basenames=()
for package in "${PACKAGES[@]}"; do
  version=$(package_version "$package")
  expected_filename=$(package_filename "$package")
  expected_size=$(package_size "$package")
  expected_digest=$(package_sha256 "$package")
  IFS=$'\t' read -r index_package index_version index_architecture index_filename index_size index_digest < <(signed_index_record "$package") || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "signed-index-metadata-invalid-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  [[ "$index_package" == "$package" && "$index_version" == "$version" && "$index_architecture" == amd64 && "$index_filename" == "$expected_filename" && "$index_size" == "$expected_size" && "$index_digest" == "$expected_digest" ]] || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "signed-index-metadata-drift-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  (cd "$download_dir" && apt-get download "${package}=${version}" >/dev/null 2>&1) || {
    rm -r -- "$download_dir"
    complete STOP_APPLY_FAILED "package-download-failed-${package}" "$EXIT_APPLY_FAILED" NONE
  }
  deb_basename="${package}_${version}_amd64.deb"
  deb_basenames+=("$deb_basename")
  download_directory_exact "$download_dir" "${deb_basenames[@]}" || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH download-directory-extra-entry "$EXIT_SUPPLY_CHAIN" NONE
  }
  deb="${download_dir}/${deb_basename}"
  [[ "$(path_size "$deb")" == "$expected_size" ]] || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-size-drift-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  deb_package=$(dpkg-deb -f "$deb" Package 2>/dev/null) || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-metadata-unreadable-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  deb_version=$(dpkg-deb -f "$deb" Version 2>/dev/null) || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-metadata-unreadable-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  deb_architecture=$(dpkg-deb -f "$deb" Architecture 2>/dev/null) || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-metadata-unreadable-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  [[ "$deb_package" == "$package" && "$deb_version" == "$version" && "$deb_architecture" == amd64 ]] || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-metadata-drift-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  actual_digest=$(sha256_file "$deb") || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-digest-unreadable-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  [[ "$actual_digest" == "$expected_digest" && "$actual_digest" == "$index_digest" ]] || {
    rm -r -- "$download_dir"
    complete STOP_SUPPLY_CHAIN_MISMATCH "deb-digest-drift-${package}" "$EXIT_SUPPLY_CHAIN" NONE
  }
  debs+=("$deb")
done

evidence_dir=$(host_path /root/dev-infra-evidence)
open_evidence 11-kubernetes "$evidence_dir" || {
  rm -r -- "$download_dir"
  complete STOP_EVIDENCE evidence-open-failed "$EXIT_UNKNOWN_STATE" NONE
}
apt-get install -y --no-install-recommends --no-download "${debs[@]}" >/dev/null 2>&1 || {
  rm -r -- "$download_dir"
  complete STOP_APPLY_FAILED local-deb-install-failed "$EXIT_APPLY_FAILED" NONE
}
rm -r -- "$download_dir"
apt-mark hold "${PACKAGES[@]}" >/dev/null 2>&1 || complete STOP_APPLY_FAILED package-hold-failed "$EXIT_APPLY_FAILED" NONE
verify_installed_state || complete STOP_VERIFY_FAILED kubernetes-package-verification-failed "$EXIT_VERIFY_FAILED" NONE
if dpkg-query -W -f='${Status}\n' cri-tools >/dev/null 2>&1; then
  complete STOP_VERIFY_FAILED cri-tools-package-installed "$EXIT_VERIFY_FAILED" NONE
fi

log_evidence REPOSITORY_MINOR=v1.36
log_evidence RELEASE_KEY_SHA256="$RELEASE_KEY_SHA256"
log_evidence RELEASE_KEY_FINGERPRINT="$RELEASE_KEY_FINGERPRINT"
for package in "${PACKAGES[@]}"; do
  package_upper=$(printf '%s' "$package" | tr '[:lower:]-' '[:upper:]_')
  log_evidence "PACKAGE_${package_upper}_VERSION=$(package_version "$package")"
  log_evidence "PACKAGE_${package_upper}_SHA256=$(package_sha256 "$package")"
done
log_evidence PACKAGE_HOLD=kubeadm,kubectl,kubelet,kubernetes-cni
log_evidence CNI_FILE_COUNT=20
log_evidence CNI_OWNERSHIP=kubernetes-cni
complete PASS_KUBERNETES_INSTALLED kubernetes-packages-ready 0 '50-kubeadm-init.sh --check'
