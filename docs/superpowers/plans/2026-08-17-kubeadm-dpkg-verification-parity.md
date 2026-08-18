# Kubeadm Dpkg Verification Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage 50 accept the same exact Ubuntu dpkg document-exclusion verification shape that Stage 40 already accepts, without weakening any package payload or provenance gate.

**Architecture:** Extract the existing `dpkg_package_verification_is_exact(package)` predicate from Stage 40 into one shared Bash library and source it from both Stage 40 and Stage 50. Reproduce the server-observed `kubeadm`/`kubectl` output in the Stage 50 fixture before changing production code, then retain the existing Stage 40 positive and negative coverage as the shared predicate's fail-closed boundary.

**Tech Stack:** Bash 3.2-compatible shell, Python `unittest`, fake host/tool fixtures in `scripts/test_bootstrap.py`, ShellCheck.

**Spec:** `docs/superpowers/specs/2026-08-13-kubernetes-post-install-resume-design.md`

## Global Constraints

- The approved server shape is exactly two order-independent records per package: `missing /usr/share/doc/<package>/LICENSE` and `missing /usr/share/doc/<package>/README.md`.
- The exception is valid only when `dpkg --verify` exits `0` and `/etc/dpkg/dpkg.cfg.d/excludes` is a root-owned, regular, non-symlink `0644` file containing exactly one `path-exclude=/usr/share/doc/*` rule.
- A `grep` read or execution error must fail closed even if it emits a seemingly valid count before returning nonzero.
- Any additional, duplicate, checksum, mode, owner, binary, unit, CNI, or nonzero verification result remains fail-closed.
- Stage 50 continues to validate only `kubeadm` and `kubectl`; Stage 40 continues to validate all four locked Kubernetes packages.
- Work on the current `main` branch under the repository's already-approved direct-main deployment batch; use only normal push and never rewrite history.
- Do not resume server deployment until GitHub `validation-gate` succeeds for the exact pushed commit.

---

### Task 1: Reproduce the Stage 50 false positive

**Files:**
- Modify: `scripts/test_bootstrap.py:6717-6727`
- Modify: `scripts/test_bootstrap.py:7734-7770`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `KubeadmInitTest.make_environment()` and its fake `dpkg` executable.
- Produces: fake control `FAKE_CLIENT_PACKAGE_VERIFY_DOC_EXCLUDES=1` and regression `test_check_accepts_declared_client_doc_exclusions()`.

- [ ] **Step 1: Extend only the Stage 50 fake dpkg output shape**

After the existing nonzero drift branch in the fake `dpkg`, add:

```sh
if [ "${FAKE_CLIENT_PACKAGE_VERIFY_DOC_EXCLUDES:-0}" = 1 ]; then
  printf 'missing     /usr/share/doc/%s/LICENSE\n' "$2"
  printf 'missing     /usr/share/doc/%s/README.md\n' "$2"
fi
```

The fake must exit `0` for this shape, matching the server evidence.

- [ ] **Step 2: Add the Stage 50 server-shape regression**

Add next to the existing client provenance test:

```python
def test_check_accepts_declared_client_doc_exclusions(self) -> None:
    """捕获 Stage 50 把官方 dpkg 文档排除输出误判为 payload 漂移。"""
    environment, host, command_log = self.make_environment()
    excludes = host / 'etc/dpkg/dpkg.cfg.d/excludes'
    excludes.parent.mkdir(parents=True)
    excludes.write_text(
        'path-exclude=/usr/share/man/*\n'
        'path-exclude=/usr/share/doc/*\n'
        'path-include=/usr/share/doc/*/copyright\n'
        'path-include=/usr/share/doc/*/changelog.*\n',
        encoding='utf-8',
    )
    excludes.chmod(0o644)
    environment['FAKE_CLIENT_PACKAGE_VERIFY_DOC_EXCLUDES'] = '1'

    result = self.run_stage(environment)

    self.assertEqual(
        result.returncode,
        0,
        f'stdout:\n{result.stdout}\nstderr:\n{result.stderr}',
    )
    self.assertIn('RESULT=PASS_KUBEADM_CHECK', result.stdout)
    self.assertNotIn(
        'kubeadm ', command_log.read_text(encoding='utf-8')
    )
```

The production mutation caught by this test is replacing the shared exact predicate with Stage 50's current `[[ -z "$verification" ]]` requirement.

- [ ] **Step 3: Run the new test and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_check_accepts_declared_client_doc_exclusions
```

Expected: FAIL because Stage 50 returns exit `30`, `RESULT=STOP_UNKNOWN_STATE`, and `REASON=kubernetes-client-package-content-drift`. The failure must not be a fixture, import, or syntax error.

---

### Task 2: Share the exact dpkg verification contract

**Files:**
- Create: `scripts/bootstrap/lib/dpkg-package-verification.sh`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh:31-36,148-170`
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:32-37,246-266`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: caller-provided `host_path(path)`, `path_mode(path)`, and `owned_by_expected(path)` Bash functions plus system `dpkg`, `grep`, and `awk`.
- Produces: `dpkg_package_verification_is_exact(package) -> 0|1` sourced by both stages; fake control `FAKE_DPKG_EXCLUDES_GREP_ERROR=1`; regression `test_check_rejects_dpkg_excludes_grep_error()`.

- [ ] **Step 1: Add a fail-closed grep-error regression before changing the helper**

Add a fake `grep` in `KubeadmInitTest.make_environment()` that delegates normally but, when `FAKE_DPKG_EXCLUDES_GREP_ERROR=1`, prints `1` and exits `2` for the exact document-exclusion count query. Add:

```python
def test_check_rejects_dpkg_excludes_grep_error(self) -> None:
    """grep 输出合法计数但读取失败时仍必须 fail closed。"""
    environment, host, _ = self.make_environment()
    excludes = host / 'etc/dpkg/dpkg.cfg.d/excludes'
    excludes.parent.mkdir(parents=True)
    excludes.write_text(
        'path-exclude=/usr/share/doc/*\n', encoding='utf-8'
    )
    excludes.chmod(0o644)
    environment['FAKE_CLIENT_PACKAGE_VERIFY_DOC_EXCLUDES'] = '1'
    environment['FAKE_DPKG_EXCLUDES_GREP_ERROR'] = '1'

    result = self.run_stage(environment)

    self.assertEqual(result.returncode, 30, result.stderr)
    self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
    self.assertIn(
        'REASON=kubernetes-client-package-content-drift', result.stdout
    )
```

- [ ] **Step 2: Run the grep-error regression and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_check_rejects_dpkg_excludes_grep_error
```

Expected: FAIL with `0 != 30` because the inherited `grep ... || true` accepts a count emitted before exit `2`.

- [ ] **Step 3: Create the shared library with the corrected Stage 40 predicate**

Create `scripts/bootstrap/lib/dpkg-package-verification.sh`:

```bash
#!/usr/bin/env bash

dpkg_package_verification_is_exact() {
  local package=$1 verification excludes exclude_count
  verification=$(dpkg --verify "$package" 2>/dev/null) || return 1
  [[ -n "$verification" ]] || return 0
  excludes=$(host_path /etc/dpkg/dpkg.cfg.d/excludes)
  [[ -f "$excludes" && ! -L "$excludes" && "$(path_mode "$excludes")" == 644 ]] || return 1
  owned_by_expected "$excludes" || return 1
  exclude_count=$(grep -Fxc 'path-exclude=/usr/share/doc/*' "$excludes") || return 1
  [[ "$exclude_count" == 1 ]] || return 1
  awk -v package="$package" '
    BEGIN {
      license="/usr/share/doc/" package "/LICENSE"
      readme="/usr/share/doc/" package "/README.md"
    }
    NF != 2 || $1 != "missing" {exit 1}
    $2 == license {if (seen_license++) exit 1; lines++; next}
    $2 == readme {if (seen_readme++) exit 1; lines++; next}
    {exit 1}
    END {
      if (lines != 2 || seen_license != 1 || seen_readme != 1) exit 1
    }
  ' <<<"$verification"
}
```

- [ ] **Step 4: Source the helper from both stages**

Add after `common.sh` in both Stage 40 and Stage 50:

```bash
# shellcheck disable=SC1091
source "${script_dir}/lib/dpkg-package-verification.sh"
```

Keep the existing `kubelet-default.sh` source in both files.

- [ ] **Step 5: Remove the duplicate Stage 40 definition**

Delete only the local `dpkg_package_verification_is_exact()` definition from `40-install-kubernetes.sh`. Do not change its four-package call loop.

- [ ] **Step 6: Replace Stage 50's local verification parsing**

Change `managed_kubernetes_clients_gate()` to remove the `verification` local and replace:

```bash
verification=$(dpkg --verify "$package" 2>/dev/null) ||
  complete STOP_UNKNOWN_STATE kubernetes-client-package-verification-failed "$EXIT_UNKNOWN_STATE" NONE
[[ -z "$verification" ]] ||
  complete STOP_UNKNOWN_STATE kubernetes-client-package-content-drift "$EXIT_UNKNOWN_STATE" NONE
```

with:

```bash
dpkg_package_verification_is_exact "$package" ||
  complete STOP_UNKNOWN_STATE kubernetes-client-package-content-drift "$EXIT_UNKNOWN_STATE" NONE
```

Use the existing content-drift reason for every predicate failure; Stage 50 remains fail-closed and exposes no raw dpkg output.

- [ ] **Step 7: Run focused GREEN and retained negative boundaries**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_check_accepts_declared_client_doc_exclusions \
  scripts.test_bootstrap.KubeadmInitTest.test_check_rejects_dpkg_excludes_grep_error \
  scripts.test_bootstrap.KubeadmInitTest.test_check_rejects_client_provenance_or_usr_sbin_shadow \
  scripts.test_bootstrap.KubernetesInstallTest.test_dpkg_verify_accepts_only_declared_doc_exclusions \
  scripts.test_bootstrap.KubernetesInstallTest.test_dpkg_verify_rejects_unsafe_doc_exclusion_shapes
```

Expected: five methods pass; the Stage 50 positive returns `PASS_KUBEADM_CHECK`, the synthetic `grep` error returns `STOP_UNKNOWN_STATE`, and all existing unsafe shapes remain rejected.

---

### Task 3: Validate, review, and deliver

**Files:**
- Verify: `scripts/bootstrap/lib/dpkg-package-verification.sh`
- Verify: `scripts/bootstrap/40-install-kubernetes.sh`
- Verify: `scripts/bootstrap/50-kubeadm-init.sh`
- Verify: `scripts/test_bootstrap.py`
- Verify: `.github/workflows/validate.yml`

**Interfaces:**
- Consumes: the GREEN implementation from Task 2.
- Produces: local gate evidence, one normal commit, a pushed exact SHA, a green GitHub `validation-gate`, and the next server-safe synchronization command.

- [ ] **Step 1: Run the repository delivery gates copied from CI and repository rules**

Run:

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n scripts/bootstrap/lib/dpkg-package-verification.sh
bash -n scripts/bootstrap/40-install-kubernetes.sh
bash -n scripts/bootstrap/50-kubeadm-init.sh
shellcheck scripts/bootstrap/lib/*.sh scripts/bootstrap/*.sh
git diff --check
```

Expected: every command exits `0` with no warnings or errors.

- [ ] **Step 2: Perform a focused read-only review**

Compare the final diff with `docs/superpowers/specs/2026-08-13-kubernetes-post-install-resume-design.md`. Block delivery if the helper accepts a nonzero dpkg result, a missing/symlink/writable/unowned excludes file, a duplicate rule, fewer or more than the exact two records, another package's paths, or any checksum/payload drift.

- [ ] **Step 3: Commit the self-contained fix**

Run:

```bash
git add \
  docs/superpowers/plans/2026-08-17-kubeadm-dpkg-verification-parity.md \
  scripts/bootstrap/lib/dpkg-package-verification.sh \
  scripts/bootstrap/40-install-kubernetes.sh \
  scripts/bootstrap/50-kubeadm-init.sh \
  scripts/test_bootstrap.py
git diff --cached --check
git commit -m "fix(bootstrap): share dpkg package verification gate"
```

- [ ] **Step 4: Push normally and wait for the exact SHA**

Run:

```bash
git push origin main
head_sha=$(git rev-parse HEAD)
run_id=$(gh run list --workflow validate.yml --commit "$head_sha" --limit 1 --json databaseId --jq '.[0].databaseId')
test -n "$run_id"
gh run watch "$run_id" --exit-status
```

Expected: the exact pushed commit's `validation-gate` succeeds. On failure, use only a new fix-forward commit; never force push or rewrite history.

- [ ] **Step 5: Stop before server mutation**

Materialize the green 40-character SHA into one server command that safely fast-forwards `/opt/uni-code/engineering-platform-gitops` and runs only `bootstrap-all.sh --check`. Wait for the complete server transcript before approving `--apply`.
