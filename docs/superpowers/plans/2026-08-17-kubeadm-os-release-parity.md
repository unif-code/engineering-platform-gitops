# Kubeadm OS Release Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Stage 50 accept the exact canonical Ubuntu `/etc/os-release -> ../usr/lib/os-release` layout that Stage 00 already accepts, while keeping every noncanonical or unreadable shape fail-closed.

**Architecture:** Extract Stage 00's existing OS release path resolution into one shared Bash predicate that returns the trusted regular file path. Source it from Stage 00 and Stage 50; each stage retains its own result/reason mapping and its existing Ubuntu 24.04 content check.

**Tech Stack:** Bash 3.2-compatible shell, Python `unittest`, fake host fixtures in `scripts/test_bootstrap.py`, ShellCheck.

**Spec:** `docs/superpowers/specs/2026-08-11-bootstrap-orchestration-validation-design.md`

## Global Constraints

- Accept a regular `/etc/os-release`, preserving the current Stage 00 contract.
- Accept a symlink only when its literal link text is exactly `../usr/lib/os-release` and `/usr/lib/os-release` is a regular, non-symlink file.
- Broken, absolute, chained, or otherwise noncanonical symlinks remain fail-closed.
- The helper only resolves the trusted path; callers continue to require `ID=ubuntu` and `VERSION_ID=24.04*` and keep their existing stop result and reason.
- Work on the current `main` branch under the repository's already-approved direct-main deployment batch; use only normal push and never rewrite history.
- Do not resume server deployment until GitHub `validation-gate` succeeds for the exact pushed commit.

---

### Task 1: Reproduce the Stage 50 false positive

**Files:**
- Modify: `scripts/test_bootstrap.py`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `KubeadmInitTest.make_environment()` and its fake host `/etc/os-release`.
- Produces: `KubeadmInitTest.test_check_accepts_canonical_ubuntu_os_release_symlink()`.

- [ ] **Step 1: Add the server-shape regression**

Add next to the existing Stage 50 host input checks:

```python
def test_check_accepts_canonical_ubuntu_os_release_symlink(self) -> None:
    """捕获 Stage 50 误拒绝 Ubuntu 标准 os-release 符号链接。"""
    environment, host, command_log = self.make_environment()
    canonical = host / 'usr/lib/os-release'
    canonical.parent.mkdir(parents=True)
    (host / 'etc/os-release').replace(canonical)
    (host / 'etc/os-release').symlink_to('../usr/lib/os-release')

    result = self.run_stage(environment)

    self.assertEqual(
        result.returncode,
        0,
        f'stdout:\n{result.stdout}\nstderr:\n{result.stderr}',
    )
    self.assertIn('RESULT=PASS_KUBEADM_CHECK', result.stdout)
    self.assertNotIn('kubeadm ', command_log.read_text(encoding='utf-8'))
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_check_accepts_canonical_ubuntu_os_release_symlink
```

Expected: FAIL because Stage 50 returns exit `10`, `RESULT=STOP_PRECONDITION`, and `REASON=os-release-unsafe`. The failure must not be a fixture, import, or syntax error.

---

### Task 2: Share the exact OS release path contract

**Files:**
- Create: `scripts/bootstrap/lib/os-release.sh`
- Modify: `scripts/bootstrap/00-preflight.sh`
- Modify: `scripts/bootstrap/50-kubeadm-init.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: caller-provided `host_path(path)` and system `readlink`.
- Produces: `ubuntu_os_release_path() -> trusted path|nonzero`, sourced by both stages.

- [ ] **Step 1: Create the shared resolver**

Create `scripts/bootstrap/lib/os-release.sh`:

```bash
#!/usr/bin/env bash

ubuntu_os_release_path() {
  local os_release canonical_os_release os_release_link
  os_release=$(host_path /etc/os-release)
  canonical_os_release=$(host_path /usr/lib/os-release)
  if [[ -L "$os_release" ]]; then
    os_release_link=$(readlink -- "$os_release" 2>/dev/null) || return 1
    if [[ "$os_release_link" != ../usr/lib/os-release ||
          ! -f "$canonical_os_release" || -L "$canonical_os_release" ]]; then
      return 1
    fi
    os_release=$canonical_os_release
  elif [[ ! -f "$os_release" ]]; then
    return 1
  fi
  printf '%s\n' "$os_release"
}
```

- [ ] **Step 2: Source the helper from both stages**

Add after `common.sh` in `00-preflight.sh` and `50-kubeadm-init.sh`:

```bash
# shellcheck disable=SC1091
source "${script_dir}/lib/os-release.sh"
```

- [ ] **Step 3: Replace only the duplicate path-resolution blocks**

In Stage 00 use:

```bash
os_release=$(ubuntu_os_release_path) ||
  complete STOP_HOST_IDENTITY os-release-missing "$EXIT_PRECONDITION" NONE
```

In Stage 50 use:

```bash
os_release=$(ubuntu_os_release_path) ||
  complete STOP_PRECONDITION os-release-unsafe "$EXIT_PRECONDITION" NONE
```

Keep both callers' existing `ID` and `VERSION_ID` parsing and mismatch reasons unchanged.

- [ ] **Step 4: Run focused GREEN and retained boundaries**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
  scripts.test_bootstrap.KubeadmInitTest.test_check_accepts_canonical_ubuntu_os_release_symlink \
  scripts.test_bootstrap.PreflightTest.test_accepts_canonical_ubuntu_os_release_symlink \
  scripts.test_bootstrap.PreflightTest.test_rejects_noncanonical_os_release_symlink
```

Expected: all three methods pass; both stages accept the exact canonical layout and Stage 00 retains the noncanonical rejection boundary.

- [ ] **Step 5: Declare the shared resolver's command dependency**

Add `readlink` to Stage 50's `required_command` list and retain a focused contract test asserting that declaration. A missing command must stop as `missing-command-readlink` before host gates invoke the shared resolver.

---

### Task 3: Validate, review, and prepare delivery

**Files:**
- Verify: `scripts/bootstrap/lib/os-release.sh`
- Verify: `scripts/bootstrap/00-preflight.sh`
- Verify: `scripts/bootstrap/50-kubeadm-init.sh`
- Verify: `scripts/test_bootstrap.py`
- Verify: `.github/workflows/validate.yml`

- [ ] **Step 1: Run repository validation**

Run:

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n scripts/bootstrap/lib/os-release.sh \
  scripts/bootstrap/00-preflight.sh \
  scripts/bootstrap/50-kubeadm-init.sh
shellcheck scripts/bootstrap/lib/*.sh scripts/bootstrap/*.sh
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 2: Review the complete patch**

Review the diff against base commit `37855cf6fe7342111825f1942fc6e0fcc8bb24dd`. Treat any Critical or Important finding as blocking; fix it test-first and rerun the affected and full gates.

- [ ] **Step 3: Commit without pushing**

After fresh verification, create one linear commit:

```bash
git add docs/superpowers/plans/2026-08-17-kubeadm-os-release-parity.md \
  scripts/bootstrap/lib/os-release.sh \
  scripts/bootstrap/00-preflight.sh \
  scripts/bootstrap/50-kubeadm-init.sh \
  scripts/test_bootstrap.py
git commit -m 'fix(bootstrap): share os-release resolution gate'
```

Stop before `git push` until the user explicitly authorizes this new commit's push.

- [ ] **Step 4: Gate the server handoff**

After an authorized normal push, require `origin/main`, GitHub's checked commit, and the exact commit SHA to match, then wait for that SHA's final `validation-gate=success`. Only then provide one pinned server sync plus `bootstrap-all.sh --check` command and wait for the complete receipt.
