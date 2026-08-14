# Kubelet Package Footprint Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage 50 recognize the exact Ubuntu 24.04 `kubelet` package footprints under both `/etc/kubernetes` and `/var/lib/kubelet` as pristine, fail-closed kubeadm state without deleting or weakening package-owned files.

**Architecture:** Add small Stage 50 helpers that bind directory/file metadata and exact `dpkg-query -S` ownership to logical Kubernetes paths. Reuse those helpers in fresh-state classification, kubelet pre-init validation, and initialized-state verification, while keeping the existing missing/empty contracts and repeated pre-init gates intact.

**Tech Stack:** Bash 3.2-compatible shell, Python `unittest`, fake host/tool fixtures in `scripts/test_bootstrap.py`, ShellCheck, repository validation wrappers.

## Global Constraints

- Work directly on the current `main` branch, as explicitly requested by the user.
- Preserve `/etc/kubernetes/manifests/.kubelet-keep`; do not delete or rewrite package-owned state.
- Preserve `/var/lib/kubelet/.kubelet-keep`; do not chmod, delete, or rewrite the package-owned root or placeholder.
- Accept mode `0775` only for exact root-owned paths with the exact `kubelet` package ownership record.
- The placeholder must be regular, non-symlink, `0644`, root-owned, zero bytes, and SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- `--check` remains zero-write; every mutation, extra entry, unreadable query, or provenance drift remains fail-closed.
- Do not continue server deployment until the ordinary push's GitHub `validation-gate` is green for the exact commit.

---

### Task 1: Make the test fixture model the official package footprint

**Files:**
- Modify: `scripts/test_bootstrap.py:6276-6640`

**Interfaces:**
- Consumes: `KubeadmInitTest.make_environment()` and its fake `dpkg-query`, `stat`, `kubeadm`, and command log.
- Produces: `KubeadmInitTest.seed_official_kubelet_package_footprint(host: Path) -> None`; fake ownership controls `FAKE_KUBELET_FOOTPRINT_OWNER_DRIFT` and `FAKE_KUBELET_FOOTPRINT_OWNER_FAIL`; fake init control `FAKE_PRESERVE_PACKAGE_DIRECTORY_MODES`.

- [ ] **Step 1: Add a fixture helper for the exact server-observed footprint**

Add this method next to `write_executable`:

```python
def seed_official_kubelet_package_footprint(self, host: Path) -> None:
    kubernetes_root = host / 'etc/kubernetes'
    manifests = kubernetes_root / 'manifests'
    manifests.mkdir(parents=True)
    kubernetes_root.chmod(0o775)
    manifests.chmod(0o775)
    keep = manifests / '.kubelet-keep'
    keep.write_bytes(b'')
    keep.chmod(0o644)
```

- [ ] **Step 2: Extend the fake package owner query without weakening client checks**

Extend the fake `dpkg-query -S` case statement to return `kubelet` only for these exact logical paths:

```sh
/etc/kubernetes|/etc/kubernetes/manifests|/etc/kubernetes/manifests/.kubelet-keep)
  package=kubelet
  ;;
```

Before printing, make query failure and owner drift target-specific:

```sh
[ "${FAKE_KUBELET_FOOTPRINT_OWNER_FAIL:-}" != "$2" ] || exit 1
[ "${FAKE_KUBELET_FOOTPRINT_OWNER_DRIFT:-}" != "$2" ] || package=unapproved
```

Keep the existing `/usr/bin/kubeadm` and `/usr/bin/kubectl` behavior unchanged.

- [ ] **Step 3: Let the fake kubeadm preserve package directory modes when requested**

Replace the unconditional root/manifests chmod calls in fake successful init with guarded calls:

```sh
if [ "${FAKE_PRESERVE_PACKAGE_DIRECTORY_MODES:-0}" != 1 ]; then
  chmod 0700 "$FAKE_HOST_ROOT/etc/kubernetes/manifests"
  chmod 0755 "$FAKE_HOST_ROOT/etc/kubernetes"
fi
```

Do not remove `.kubelet-keep`; the fake init must model kubeadm writing the four YAML files alongside it.

- [ ] **Step 4: Run fixture syntax/static checks**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write
```

Expected: existing test stays PASS before any production change.

---

### Task 2: RED — lock the fresh and initialized compatibility contract

**Files:**
- Modify: `scripts/test_bootstrap.py:6640-7310`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `seed_official_kubelet_package_footprint`, `run_stage`, `tree_snapshot`, fake mutation variables from Task 1.
- Produces: four new `KubeadmInitTest` regression methods whose names are used by all focused verification commands below.

- [ ] **Step 1: Write the official fresh/apply positive regression**

Add `test_accepts_exact_official_kubelet_package_footprint`:

```python
def test_accepts_exact_official_kubelet_package_footprint(self) -> None:
    environment, host, command_log = self.make_environment()
    self.seed_official_kubelet_package_footprint(host)
    before = self.tree_snapshot(host)

    checked = self.run_stage(environment, '--check')

    self.assertEqual(checked.returncode, 0, checked.stderr)
    self.assertIn('RESULT=PASS_KUBEADM_CHECK', checked.stdout)
    self.assertEqual(self.tree_snapshot(host), before)

    environment['FAKE_PRESERVE_PACKAGE_DIRECTORY_MODES'] = '1'
    applied = self.run_stage(environment, '--apply')
    self.assertEqual(applied.returncode, 0, applied.stderr)
    self.assertIn('RESULT=PASS_KUBEADM_INITIALIZED', applied.stdout)
    self.assertTrue(
        (host / 'etc/kubernetes/manifests/.kubelet-keep').is_file()
    )
    self.assertIn('kubeadm init --config ', command_log.read_text(encoding='utf-8'))
```

- [ ] **Step 2: Write load-bearing fresh footprint drift subtests**

Add `test_rejects_official_kubelet_package_footprint_drift`. For every case, first create and assert a separate exact baseline returns 0, then create a new environment, seed the footprint, apply exactly one mutation, and assert return 30 with no `kubeadm init --config`:

```python
mutations = {
    'extra-root-entry': lambda host, env: (host / 'etc/kubernetes/pki').mkdir(),
    'extra-manifest-entry': lambda host, env: (
        host / 'etc/kubernetes/manifests/unknown.yaml'
    ).write_text('unknown\n', encoding='utf-8'),
    'root-mode': lambda host, env: (host / 'etc/kubernetes').chmod(0o755),
    'manifest-mode': lambda host, env: (
        host / 'etc/kubernetes/manifests'
    ).chmod(0o755),
    'keep-mode': lambda host, env: (
        host / 'etc/kubernetes/manifests/.kubelet-keep'
    ).chmod(0o600),
    'keep-bytes': lambda host, env: (
        host / 'etc/kubernetes/manifests/.kubelet-keep'
    ).write_bytes(b'drift\n'),
    'root-owner-record': lambda host, env: env.__setitem__(
        'FAKE_KUBELET_FOOTPRINT_OWNER_DRIFT', '/etc/kubernetes'
    ),
    'keep-owner-query': lambda host, env: env.__setitem__(
        'FAKE_KUBELET_FOOTPRINT_OWNER_FAIL',
        '/etc/kubernetes/manifests/.kubelet-keep',
    ),
    'listener': lambda host, env: env.__setitem__('FAKE_6443_LISTENER', '1'),
}
```

Use explicit code, rather than lambdas, for symlink cases so the original path is removed first. Include root-directory, manifest-directory, and placeholder symlink mutations. The exact baseline assertion makes the negative test fail if production regresses to rejecting every package footprint.

- [ ] **Step 3: Write repeated-gate and initialized-placeholder regressions**

Add `test_regates_official_kubelet_package_footprint_before_init`:

```python
environment, host, command_log = self.make_environment()
self.seed_official_kubelet_package_footprint(host)
environment['FAKE_PREINIT_RACE'] = 'manifest'
result = self.run_stage(environment, '--apply')
self.assertEqual(result.returncode, 30, result.stderr)
self.assertNotIn('kubeadm init --config ', command_log.read_text(encoding='utf-8'))
```

Add `test_initialized_state_accepts_only_exact_package_placeholder` with independent subtests:

1. Seed official state, preserve `0775`, apply, then `--check` must be `ALREADY_COMPLIANT` with the exact placeholder.
2. Seed, apply, remove only `.kubelet-keep`, then `--check` must still be `ALREADY_COMPLIANT` for the exact four YAML set.
3. Seed, apply, add a fifth unknown entry; `--check` must return 30.
4. Seed, apply, replace the placeholder bytes, mode, symlink, or ownership record one at a time; `--check` must return 30.

- [ ] **Step 4: Run the four new methods and verify a valid RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_accepts_exact_official_kubelet_package_footprint \
  scripts.test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_package_footprint_drift \
  scripts.test_bootstrap.KubeadmInitTest.test_regates_official_kubelet_package_footprint_before_init \
  scripts.test_bootstrap.KubeadmInitTest.test_initialized_state_accepts_only_exact_package_placeholder
```

Expected: FAIL because the current production script returns `STOP_ALREADY_INITIALIZED` for the exact official baseline. There must be no loader, fixture, or syntax error.

---

### Task 3: GREEN — implement exact package-owned state helpers

**Files:**
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:38-140`
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:365-400`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `host_path`, `path_mode`, `owned_by_expected`, `sha256_file`, `dpkg-query`, `find`, and `sort`.
- Produces: `package_owner_is_exact(logical, package)`, `package_directory_is_safe(logical, target, normal_mode)`, `kubelet_keep_is_exact()`, and `kubelet_package_footprint_is_fresh(kubernetes_root)` Bash predicates.

- [ ] **Step 1: Add the approved placeholder constant and exact owner helper**

Add:

```bash
readonly KUBELET_KEEP_SHA256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

package_owner_is_exact() {
  local logical=$1 package=$2 ownership
  local ownership_sentinel=__KUBELET_FOOTPRINT_OWNERSHIP_END__
  ownership=$(
    dpkg-query -S "$logical" 2>/dev/null &&
      printf '%s' "$ownership_sentinel"
  ) || return 1
  [[ "$ownership" == "${package}: ${logical}"$'\n'"$ownership_sentinel" ]]
}
```

Do not use substring matching. The sentinel must remain in the same successful command substitution so duplicate lines, trailing blank lines, extra records, and non-zero commands with output are all rejected.

- [ ] **Step 2: Add package-bound directory and placeholder predicates**

Implement:

```bash
package_directory_is_safe() {
  local logical=$1 target=$2 normal_mode=$3 mode
  [[ -d "$target" && ! -L "$target" ]] || return 1
  owned_by_expected "$target" || return 1
  mode=$(path_mode "$target") || return 1
  if [[ "$mode" == "$normal_mode" ]]; then
    return 0
  fi
  [[ "$mode" == 775 ]] || return 1
  package_owner_is_exact "$logical" kubelet
}

kubelet_keep_is_exact() {
  local logical=/etc/kubernetes/manifests/.kubelet-keep target digest
  target=$(host_path "$logical")
  [[ -f "$target" && ! -L "$target" && ! -s "$target" &&
     "$(path_mode "$target")" == 644 ]] || return 1
  owned_by_expected "$target" || return 1
  package_owner_is_exact "$logical" kubelet || return 1
  digest=$(sha256_file "$target") || return 1
  [[ "$digest" == "$KUBELET_KEEP_SHA256" ]]
}
```

The normal mode is accepted only where the caller already has an initialized-state or existing empty-root contract. Mode `0775` always requires exact package ownership.

- [ ] **Step 3: Add exact fresh package footprint recognition**

Use the repository's portable `find ... -print | sed | sort` pattern:

```bash
kubelet_package_footprint_is_fresh() {
  local kubernetes_root=$1 manifests root_entries manifest_entries
  manifests="${kubernetes_root}/manifests"
  package_directory_is_safe /etc/kubernetes "$kubernetes_root" 775 || return 1
  package_owner_is_exact /etc/kubernetes kubelet || return 1
  root_entries=$(find "$kubernetes_root" -mindepth 1 -maxdepth 1 -print 2>/dev/null |
    sed 's#.*/##' | sort) || return 1
  [[ "$root_entries" == manifests ]] || return 1
  package_directory_is_safe /etc/kubernetes/manifests "$manifests" 775 || return 1
  package_owner_is_exact /etc/kubernetes/manifests kubelet || return 1
  manifest_entries=$(find "$manifests" -mindepth 1 -maxdepth 1 -print 2>/dev/null |
    sed 's#.*/##' | sort) || return 1
  [[ "$manifest_entries" == .kubelet-keep ]] || return 1
  kubelet_keep_is_exact
}
```

Because fresh package state requires `0775`, the repeated explicit owner calls are intentional and make future helper changes unable to silently remove package provenance.

- [ ] **Step 4: Wire fresh and candidate classification**

Change `initialization_state` so candidate root mode `0775` is accepted only through `package_directory_is_safe /etc/kubernetes ... 755`. For fresh state, use this exact grouping:

```bash
if { root_is_missing_or_safe_empty "$kubernetes_root" ||
     kubelet_package_footprint_is_fresh "$kubernetes_root"; } &&
   root_is_missing_or_safe_empty "$etcd_root"; then
  # existing listener query and FRESH result
fi
```

Do not treat arbitrary non-empty or `0775` directories as empty.

- [ ] **Step 5: Wire post-init directory and manifest-set verification**

At the start of `initialized_control_plane_gate`, revalidate `/etc/kubernetes` with normal mode `0755` or exact package-owned `0775`. Validate the manifests directory with normal mode `0700` or exact package-owned `0775`.

Accept only these two sorted entry sets:

```bash
expected_manifests=$'etcd.yaml\nkube-apiserver.yaml\nkube-controller-manager.yaml\nkube-scheduler.yaml'
expected_manifests_with_keep=$'.kubelet-keep\netcd.yaml\nkube-apiserver.yaml\nkube-controller-manager.yaml\nkube-scheduler.yaml'
```

If the second set is present, call `kubelet_keep_is_exact` before checking the four YAML files. Any other set returns the existing `static-manifest-set-drift` failure.

- [ ] **Step 6: Run the four new methods and verify GREEN**

Run the exact RED command from Task 2.

Expected: `Ran 4 tests`, `OK`, exit 0.

- [ ] **Step 7: Commit the complete RED/GREEN change**

```bash
git add scripts/bootstrap/50-kubeadm-init.sh scripts/test_bootstrap.py
git diff --cached --check
git commit -m "fix(bootstrap): accept official kubelet package footprint"
```

---

### Task 4: Verify affected state-machine behavior and delivery gates

**Files:**
- Verify: `scripts/bootstrap/50-kubeadm-init.sh`
- Verify: `scripts/test_bootstrap.py`
- Verify: `.github/workflows/validate.yml`

**Interfaces:**
- Consumes: the Task 3 commit and repository validation catalog.
- Produces: final local evidence, review closure, pushed commit, green GitHub gate, and the exact server-sync SHA.

- [ ] **Step 1: Run the affected Kubeadm regression set**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_accepts_exact_official_kubelet_package_footprint \
  scripts.test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_package_footprint_drift \
  scripts.test_bootstrap.KubeadmInitTest.test_regates_official_kubelet_package_footprint_before_init \
  scripts.test_bootstrap.KubeadmInitTest.test_initialized_state_accepts_only_exact_package_placeholder \
  scripts.test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write \
  scripts.test_bootstrap.KubeadmInitTest.test_apply_on_exact_initialized_state_never_reinitializes \
  scripts.test_bootstrap.KubeadmInitTest.test_initialized_marker_live_symlinks_are_untrusted_footprint \
  scripts.test_bootstrap.KubeadmInitTest.test_initialized_candidate_drift_stops_unknown \
  scripts.test_bootstrap.KubeadmInitTest.test_check_rejects_every_initialized_or_partial_marker_before_gates \
  scripts.test_bootstrap.KubeadmInitTest.test_check_rejects_any_existing_kubernetes_or_etcd_state \
  scripts.test_bootstrap.KubeadmInitTest.test_apply_reruns_complete_gate_set_after_validate_and_preflight \
  scripts.test_bootstrap.KubeadmInitTest.test_apply_uses_only_fixed_config_sequence_and_redacts_raw_output
```

Expected: `Ran 12 tests`, `OK`, exit 0.

- [ ] **Step 2: Run repository gates**

Run in order:

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n scripts/bootstrap/50-kubeadm-init.sh
shellcheck scripts/bootstrap/lib/common.sh scripts/bootstrap/50-kubeadm-init.sh
git diff --check
git show --check --stat HEAD
```

Expected: all commands exit 0; `validate-fast.sh` reports its test count and successful manifest validation.

- [ ] **Step 3: Perform focused code review**

Review the final diff against `docs/superpowers/specs/2026-08-14-kubelet-package-footprint-design.md`. Block delivery for any Critical or Important finding, especially broad `0775` acceptance, missing ownership binding, weak entry-set comparison, or a re-gate that can be bypassed.

- [ ] **Step 4: Push the current main branch normally**

```bash
git status --short --branch
git push origin main
```

Do not force push. Record the exact 40-character commit SHA.

- [ ] **Step 5: Wait for the exact GitHub run**

Use `gh run list`/`gh run view` to bind the run to the pushed SHA, then wait for `static`, every test shard, `final-verify`, and `validation-gate` to report `success`.

- [ ] **Step 6: Resume the server only after CI is green**

On `retail-test-workflow`, verify a clean `main`, fetch the exact commit, fast-forward, and run:

```bash
./scripts/bootstrap/bootstrap-all.sh --apply
```

Capture the complete terminal result and `COMMAND_EXIT_CODE`. Do not manually delete `.kubelet-keep` or any Kubernetes state.

---

### Task 5: Accept the exact `/var/lib/kubelet` package footprint

**Files:**
- Modify: `scripts/test_bootstrap.py:6270-7200`
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:110-230`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `package_owner_is_exact(logical, package)`, `owned_by_expected(target)`, `path_mode(target)`, `sha256_file(target)`, and the repeated `fresh_pre_init_gates` calls.
- Produces: `package_placeholder_is_exact(logical)`, `kubelet_state_package_footprint_is_pristine(kubelet_root)`, and three load-bearing `KubeadmInitTest` methods.

- [ ] **Step 1: Extend the fixture with the exact server-observed package payload**

Add beside `seed_official_kubelet_package_footprint`:

```python
def seed_official_kubelet_state_footprint(self, host: Path) -> None:
    kubelet_root = host / 'var/lib/kubelet'
    kubelet_root.mkdir(parents=True)
    kubelet_root.chmod(0o775)
    keep = kubelet_root / '.kubelet-keep'
    keep.write_bytes(b'')
    keep.chmod(0o644)
```

Extend only the fake `dpkg-query -S` path case:

```sh
/var/lib/kubelet|/var/lib/kubelet/.kubelet-keep)
  package=kubelet
  ;;
```

Reuse the existing target-specific query failure, package drift, and malformed-output controls. Add this exact fake kubeadm mutation case inside `apply_drift`:

```sh
kubelet-package-footprint)
  printf 'raced\n' >"$FAKE_HOST_ROOT/var/lib/kubelet/unknown-state"
  ;;
```

Make the existing fake SHA mutation targetable without weakening its prior default behavior:

```sh
if [ "${last##*/}" = .kubelet-keep ] &&
   { [ -z "${FAKE_KUBELET_KEEP_SHA256_TARGET:-}" ] ||
     [ "$FAKE_KUBELET_KEEP_SHA256_TARGET" = "$last" ]; }; then
  [ "${FAKE_KUBELET_KEEP_SHA256_FAIL:-0}" != 1 ] || exit 1
  if [ "${FAKE_KUBELET_KEEP_SHA256_DRIFT:-0}" = 1 ]; then
    printf '%064d  %s\n' 0 "$last"
    exit 0
  fi
fi
```

The new `/var/lib/kubelet` digest subtests must set `FAKE_KUBELET_KEEP_SHA256_TARGET` to the mapped `/var/lib/kubelet/.kubelet-keep` path so they cannot pass by corrupting the `/etc/kubernetes` placeholder instead.

- [ ] **Step 2: Write the three behavior regressions before changing production**

Add `test_accepts_exact_official_kubelet_state_footprint`. Seed both official package footprints, snapshot the host tree, and assert `--check` returns `PASS_KUBEADM_CHECK` without tree changes. Then set `FAKE_PRESERVE_PACKAGE_DIRECTORY_MODES=1`, run `--apply`, and assert `PASS_KUBEADM_INITIALIZED` plus a logged approved `kubeadm init --config` command.

Add `test_rejects_official_kubelet_state_footprint_drift` with independent environments for these exact cases:

```python
cases = (
    'extra-entry', 'root-mode', 'root-filesystem-owner',
    'root-package-owner', 'root-package-query', 'root-owner-shape',
    'root-symlink', 'keep-mode', 'keep-bytes',
    'keep-filesystem-owner', 'keep-package-owner', 'keep-package-query',
    'keep-owner-shape', 'keep-sha256-drift', 'keep-sha256-fail',
    'keep-symlink',
)
```

For `root-owner-shape` and `keep-owner-shape`, iterate the existing `duplicate`, `trailing-blank`, `extra`, and `nonzero-output` fake shapes. Every drift must return 30, include `RESULT=STOP_ALREADY_INITIALIZED`, and never log `kubeadm init --config`.

Add `test_regates_official_kubelet_state_footprint_before_init`. For `FAKE_DRIFT_AFTER_VALIDATE=kubelet-package-footprint` and `FAKE_DRIFT_AFTER_PREFLIGHT=kubelet-package-footprint`, start from both exact package footprints, run `--apply`, and assert return 30 with no `kubeadm init --config` consumption.

- [ ] **Step 3: Run the three new methods and verify a valid RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" python3 -m unittest -v \
  test_bootstrap.KubeadmInitTest.test_accepts_exact_official_kubelet_state_footprint \
  test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_state_footprint_drift \
  test_bootstrap.KubeadmInitTest.test_regates_official_kubelet_state_footprint_before_init
```

Expected: test failures because the current Stage 50 rejects the exact baseline with `kubelet-root-mode-unsafe`. There must be no loader, fixture, syntax, or setup error.

- [ ] **Step 4: Generalize exact placeholder validation and add the package-root predicate**

Replace the hardcoded placeholder body with:

```bash
package_placeholder_is_exact() {
  local logical=$1 target digest
  target=$(host_path "$logical")
  [[ -f "$target" && ! -L "$target" && ! -s "$target" &&
     "$(path_mode "$target")" == 644 ]] || return 1
  owned_by_expected "$target" || return 1
  package_owner_is_exact "$logical" kubelet || return 1
  digest=$(sha256_file "$target") || return 1
  [[ "$digest" == "$KUBELET_KEEP_SHA256" ]]
}

kubelet_keep_is_exact() {
  package_placeholder_is_exact \
    /etc/kubernetes/manifests/.kubelet-keep
}

kubelet_state_package_footprint_is_pristine() {
  local kubelet_root=$1 entries
  [[ -d "$kubelet_root" && ! -L "$kubelet_root" &&
     "$(path_mode "$kubelet_root")" == 775 ]] || return 1
  owned_by_expected "$kubelet_root" || return 1
  package_owner_is_exact /var/lib/kubelet kubelet || return 1
  entries=$(find "$kubelet_root" -mindepth 1 -maxdepth 1 -print 2>/dev/null |
    sed 's#.*/##' | sort) || return 1
  [[ "$entries" == .kubelet-keep ]] || return 1
  package_placeholder_is_exact /var/lib/kubelet/.kubelet-keep
}
```

The predicate must not accept mode `0775` when the directory is empty, contains any additional entry, or has an inexact package owner record.

- [ ] **Step 5: Wire the predicate without weakening existing safe-empty states**

In `kubelet_pre_init_inputs_gate`, retain the existing missing-root behavior. For an existing root, first accept `kubelet_state_package_footprint_is_pristine "$kubelet_root"`; otherwise execute the existing real-directory, root-owner, mode `0700/0750/0755`, and completely-empty checks unchanged:

```bash
if [[ -e "$kubelet_root" || -L "$kubelet_root" ]]; then
  if kubelet_state_package_footprint_is_pristine "$kubelet_root"; then
    :
  else
    if [[ ! -d "$kubelet_root" || -L "$kubelet_root" ]] ||
       ! owned_by_expected "$kubelet_root"; then
      complete STOP_ALREADY_INITIALIZED kubelet-root-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
    fi
    root_mode=$(path_mode "$kubelet_root") ||
      complete STOP_ALREADY_INITIALIZED kubelet-root-unreadable \
        "$EXIT_UNKNOWN_STATE" NONE
    [[ "$root_mode" == 700 || "$root_mode" == 750 ||
       "$root_mode" == 755 ]] ||
      complete STOP_ALREADY_INITIALIZED kubelet-root-mode-unsafe \
        "$EXIT_UNKNOWN_STATE" NONE
    first_entry=$(find "$kubelet_root" -mindepth 1 -print -quit 2>/dev/null) ||
      complete STOP_ALREADY_INITIALIZED kubelet-root-unreadable \
        "$EXIT_UNKNOWN_STATE" NONE
    [[ -z "$first_entry" ]] ||
      complete STOP_ALREADY_INITIALIZED kubelet-generated-state-present \
        "$EXIT_UNKNOWN_STATE" NONE
  fi
fi
```

Keep the subsequent explicit sensitive-path loop and `/etc/default/kubelet` contract unchanged. Because `fresh_pre_init_gates` already runs before validate, after validate, after preflight, and immediately before init, do not add a new execution path.

- [ ] **Step 6: Run the RED command and verify GREEN**

Run the exact command from Step 3.

Expected: `Ran 3 tests`, `OK`, exit 0.

- [ ] **Step 7: Run the affected pre-init regression set**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" python3 -m unittest -v \
  test_bootstrap.KubeadmInitTest.test_accepts_exact_official_kubelet_state_footprint \
  test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_state_footprint_drift \
  test_bootstrap.KubeadmInitTest.test_regates_official_kubelet_state_footprint_before_init \
  test_bootstrap.KubeadmInitTest.test_check_rejects_non_pristine_kubelet_pre_init_inputs \
  test_bootstrap.KubeadmInitTest.test_check_allows_secure_kubelet_root_and_empty_operator_file \
  test_bootstrap.KubeadmInitTest.test_apply_reruns_complete_gate_set_after_validate_and_preflight
```

Expected: `Ran 6 tests`, `OK`, exit 0.

---

### Task 6: Review, validate, deliver, and resume the server

**Files:**
- Verify: `scripts/bootstrap/50-kubeadm-init.sh`
- Verify: `scripts/test_bootstrap.py`
- Verify: `docs/superpowers/specs/2026-08-14-kubelet-package-footprint-design.md`

**Interfaces:**
- Consumes: Task 5 GREEN tree and the repository validation catalog.
- Produces: reviewed commits, green latest-main GitHub `validation-gate`, and a server deployment receipt beyond Stage 50.

- [ ] **Step 1: Run local delivery gates**

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n scripts/bootstrap/50-kubeadm-init.sh
shellcheck scripts/bootstrap/lib/common.sh scripts/bootstrap/50-kubeadm-init.sh
git diff --check
```

Expected: every command exits 0; fast/static report successful manifest validation.

- [ ] **Step 2: Review the exact fail-closed boundary**

Review the final diff against the approved design. Block delivery if mode `0775` is accepted without exact filesystem owner, exact single-entry set, exact placeholder metadata/digest, and exact sentinel-bound package ownership. Require zero Critical and zero Important findings.

- [ ] **Step 3: Commit and push normally**

```bash
git add scripts/bootstrap/50-kubeadm-init.sh scripts/test_bootstrap.py
git diff --cached --check
git commit -m "fix(bootstrap): accept kubelet state package footprint"
git push origin main
```

Do not force push. Record the exact 40-character commit SHA and verify the worktree is clean.

- [ ] **Step 4: Wait for the latest-main GitHub gate**

Bind the GitHub run to the pushed SHA. Do not resume the server until static, every dynamic test shard, final-verify, and `validation-gate` all report `success`.

- [ ] **Step 5: Resume only from the verified SHA**

On `retail-test-workflow`, verify a clean `main`, fetch and fast-forward to the exact green SHA, then run:

```bash
./scripts/bootstrap/bootstrap-all.sh --apply
rc=$?
echo "COMMAND_EXIT_CODE=$rc"
```

Capture the complete output. Do not delete or chmod `/var/lib/kubelet` or either package placeholder.
