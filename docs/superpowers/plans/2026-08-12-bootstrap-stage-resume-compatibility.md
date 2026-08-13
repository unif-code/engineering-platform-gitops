# Bootstrap Stage Resume Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 bootstrap 在任意合法完成 checkpoint 上都能从真实状态恢复，早期 stage 不再拒绝后续 stage 拥有的合规状态，同时保留 owner stage 的 fail-closed 验真。

**Architecture:** 使用 owner-scoped stage contract：stage 00 不再判断 stage 30 的 containerd 目标，stage 40 仅在 fresh package 安装路径要求 kubelet pre-init pristine，编排器继续按 00～90 固定顺序调用各 owner。恢复正确性通过 stage 单测与 prefix checkpoint matrix 共同证明，不引入 progress file 或跨 stage 递归调用。

**Tech Stack:** Bash 3.2-compatible stage scripts、Python 3 `unittest` fixture、ShellCheck、GitHub Actions validation shards。

## Global Constraints

- 目标主机固定为 `retail-test-workflow`、Ubuntu 24.04、`linux/amd64`。
- stage 顺序固定为 `00,10,20,30,40,50,60,90`。
- `--check` 必须零安装、零删除、零自动修复；服务器现有 `/etc/containerd` 不清理。
- 每个 stage 只拥有并验真自身 Desired State；后续 owner 的状态不得成为早期 `ALREADY_COMPLIANT` 的“必须不存在”条件。
- `PARTIAL`、`DRIFT`、`UNKNOWN` 继续结构化 STOP；不得以存在性、evidence 或 progress file 代替验真。
- Docker、Caddy、Node、旧 workflow、端口 3001 与 `containerd.io` package 的 legacy Gate 不放宽。
- 本地运行受影响 focused tests、`validate-fast.sh`、ShellCheck 与 diff check；重型全量验证交给 GitHub shards。
- GitHub `validation-gate` 成功前不得继续服务器 mutation。

---

### Task 1: 把 stage 30 的目标状态移出 preflight legacy Gate

**Files:**
- Modify: `scripts/test_bootstrap.py`（`PreflightTest`）
- Modify: `scripts/bootstrap/00-preflight.sh`（旧运行时检查区段）

**Interfaces:**
- Consumes: stage 00 公开结果 `PASS_PREFLIGHT` / `STOP_OLD_RUNTIME`。
- Produces: stage 00 只判断 baseline 与 legacy conflict；containerd 目标状态留给后续 stage 30 `--check`。

- [ ] **Step 1: 写目标状态兼容与 legacy 拒绝的失败测试**

将原 containerd 存在即 STOP 的测试替换成以下两个合同：

```python
def test_stage30_owned_runtime_footprint_does_not_fail_preflight(self) -> None:
    environment, host = self.make_environment()
    fake_bin = Path(environment['PATH'].split(os.pathsep, 1)[0])
    for name in ('containerd', 'runc'):
        self.write_executable(fake_bin / name, '#!/bin/sh\nexit 0\n')
    for relative in ('etc/containerd', 'opt/containerd', 'var/lib/containerd'):
        (host / relative).mkdir(parents=True)

    result = self.run_command(
        ['/bin/bash', str(PREFLIGHT), '--check'], env=environment
    )

    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertIn('RESULT=PASS_PREFLIGHT', result.stdout)

def test_legacy_runtime_conflicts_still_fail_preflight(self) -> None:
    environment, _ = self.make_environment()
    fake_bin = Path(environment['PATH'].split(os.pathsep, 1)[0])
    self.write_executable(fake_bin / 'docker', '#!/bin/sh\nexit 0\n')

    result = self.run_command(
        ['/bin/bash', str(PREFLIGHT), '--check'], env=environment
    )

    self.assertEqual(result.returncode, 30)
    self.assertIn('REASON=unexpected-binary-docker', result.stdout)
```

- [ ] **Step 2: 运行 RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.PreflightTest.test_stage30_owned_runtime_footprint_does_not_fail_preflight \
  test_bootstrap.PreflightTest.test_legacy_runtime_conflicts_still_fail_preflight
```

Expected: 第一项 FAIL，旧实现返回 `STOP_OLD_RUNTIME`；第二项 PASS，证明 legacy Gate 仍 load-bearing。

- [ ] **Step 3: 最小修改 production owner boundary**

将 binary allowlist 收紧为 `caddy docker dockerd node npm npx pnpm`；path allowlist 收紧为 `/data/workflow /etc/caddy /etc/docker /usr/local/lib/node-v24.18.0 /var/lib/docker`；systemd 查询仅保留 Caddy/Docker。`containerd.io` package Gate 原样保留，不从 stage 00 调用 stage 30。

- [ ] **Step 4: 运行 GREEN 与完整 Preflight 回归**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v test_bootstrap.PreflightTest
shellcheck scripts/bootstrap/00-preflight.sh
git diff --check
```

Expected: 全部 PASS，且 Docker、Node、CIDR、cleanup evidence 负向用例继续通过。

- [ ] **Step 5: 提交 Task 1**

```bash
git add scripts/bootstrap/00-preflight.sh scripts/test_bootstrap.py
git commit -m "fix(bootstrap): scope preflight to legacy runtime"
```

### Task 2: 将 kubelet fresh-only Gate 限定在 stage 40 安装路径

**Files:**
- Modify: `scripts/test_bootstrap.py`（`KubernetesInstallTest`；复用 `KubeadmInitTest` 安全回归）
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`

**Interfaces:**
- Consumes: stage 40 的 package/source/hold/CNI/binary/unit provenance；stage 50 的 `FRESH`/`CANDIDATE` 状态机。
- Produces: `verify_installed_package_state()` 只验证 stage 40 自有状态；`kubelet_mutable_inputs_are_pristine()` 只保护首次 package apply 与竞态窗口。

- [ ] **Step 1: 写 fresh 拒绝与 completed handoff 的失败测试**

```python
def test_fresh_install_rejects_preexisting_kubeadm_generated_state(self) -> None:
    environment, host, command_log = self.make_environment()
    kubelet_root = host / 'var/lib/kubelet'
    kubelet_root.mkdir(parents=True)
    (kubelet_root / 'config.yaml').write_text('stale\n', encoding='utf-8')

    result = self.run_stage(environment, '--apply')

    self.assertEqual(result.returncode, 30, result.stderr)
    self.assertIn('REASON=kubelet-pre-init-inputs-not-pristine', result.stdout)
    self.assertNotIn('apt-get ', command_log.read_text(encoding='utf-8'))

def test_exact_packages_allow_kubeadm_owned_generated_state(self) -> None:
    environment, host, _ = self.make_environment()
    self.install_repository_contract(host)
    environment['FAKE_INSTALLED_STATE'] = 'exact'
    Path(environment['FAKE_PACKAGES_HELD']).touch()
    self.install_cni_contract(host)
    kubelet_root = host / 'var/lib/kubelet'
    kubelet_root.mkdir(parents=True)
    for name in ('config.yaml', 'instance-config.yaml', 'kubeadm-flags.env'):
        (kubelet_root / name).write_text('kubeadm-owned\n', encoding='utf-8')

    result = self.run_stage(environment)

    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    self.assertIn('RESULT=ALREADY_COMPLIANT', result.stdout)
```

原 non-pristine mutation 改用未安装 packages 的 fresh fixture，保留 mode、symlink、unknown entry 等分支。

- [ ] **Step 2: 运行 RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_fresh_install_rejects_preexisting_kubeadm_generated_state \
  test_bootstrap.KubernetesInstallTest.test_exact_packages_allow_kubeadm_owned_generated_state
```

Expected: fresh 负向 PASS；completed handoff FAIL，旧实现返回 `kubelet-pre-init-inputs-not-pristine`。

- [ ] **Step 3: 拆分 installed 与 fresh Gate**

把 verifier 改为：

```bash
verify_installed_package_state() {
  verify_package_selection_and_holds || return "$?"
  kubernetes_shadow_paths_absent || return 1
  managed_kubernetes_binaries_are_exact || return 1
  [[ "$(cni_directory_state "$(host_path /opt/cni/bin)")" == COMPLIANT ]] ||
    return 1
  kubelet_pre_init_state_is_expected
}
```

删除入口处无条件的 `kubelet_mutable_inputs_are_pristine`。在 `installed_count == 0` 分支、返回 `PASS_KUBERNETES_CHECK` 之前调用它；apply simulation 后的竞态复验保持原位。installed 分支与 post-install verification 使用 `verify_installed_package_state`。

- [ ] **Step 4: 运行 owner handoff GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_fresh_install_rejects_preexisting_kubeadm_generated_state \
  test_bootstrap.KubernetesInstallTest.test_exact_packages_allow_kubeadm_owned_generated_state \
  test_bootstrap.KubernetesInstallTest.test_apply_rechecks_cni_ancestry_after_simulation \
  test_bootstrap.KubernetesInstallTest.test_apply_rechecks_cni_ancestry_after_install_before_hold \
  test_bootstrap.KubeadmInitTest.test_check_rejects_non_pristine_kubelet_pre_init_inputs \
  test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write \
  test_bootstrap.KubeadmInitTest.test_initialized_candidate_drift_stops_unknown
```

Expected: 全部 PASS；fresh partial 仍由 stage 50 STOP，initialized candidate 仍需完整 runtime/manifest Gate。

- [ ] **Step 5: 运行完整 Kubernetes shard class 并提交**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v test_bootstrap.KubernetesInstallTest
shellcheck scripts/bootstrap/40-install-kubernetes.sh
git diff --check
git add scripts/bootstrap/40-install-kubernetes.sh scripts/test_bootstrap.py
git commit -m "fix(bootstrap): hand off kubelet state to kubeadm"
```

### Task 3: 用 checkpoint matrix 锁定编排器全阶段恢复

**Files:**
- Modify: `scripts/test_bootstrap.py`（`BootstrapOrchestratorTest`）

**Interfaces:**
- Consumes: orchestrator 固定顺序、`check_result_is_complete()` 与 `check_result_requires_apply()`。
- Produces: 每个合法 prefix 的 `NEXT_STAGE` 合同，以及 completed replay 零 apply 证明。

- [ ] **Step 1: 增加合法 checkpoint 参数化测试**

```python
def test_check_resumes_from_every_legal_checkpoint(self) -> None:
    cases = (
        ((), '10', 'PASS_BOOTSTRAP_CHECK'),
        (('10',), '20', 'PASS_BOOTSTRAP_CHECK'),
        (('10', '20'), '30', 'PASS_BOOTSTRAP_CHECK'),
        (('10', '20', '30'), '40', 'PASS_BOOTSTRAP_CHECK'),
        (('10', '20', '30', '40'), '50', 'PASS_BOOTSTRAP_CHECK'),
        (('10', '20', '30', '40', '50'), '60', 'PASS_BOOTSTRAP_CHECK'),
        (('10', '20', '30', '40', '50', '60'), 'NONE',
         'PASS_BOOTSTRAP_ALL_CHECK'),
    )
    for completed, next_stage, result_name in cases:
        with self.subTest(completed=completed):
            self.reset_fixture()
            for stage in completed:
                (self.state_dir / stage).touch()
            result = self.run_orchestrator('--check')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f'RESULT={result_name}', result.stdout)
            self.assertIn(f'NEXT_STAGE={next_stage}', result.stdout)
            self.assertNotIn(
                '--apply', self.command_log.read_text(encoding='utf-8')
            )
```

- [ ] **Step 2: 增加 fully complete `--apply` replay-only 测试**

```python
def test_apply_on_fully_complete_state_performs_no_stage_apply(self) -> None:
    for stage in ('10', '20', '30', '40', '50', '60'):
        (self.state_dir / stage).touch()

    result = self.run_orchestrator('--apply')

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('RESULT=PASS_BOOTSTRAP_ALL', result.stdout)
    commands = self.command_log.read_text(encoding='utf-8')
    self.assertIn('90 --check', commands)
    self.assertNotIn('--apply', commands)
```

- [ ] **Step 3: 运行 matrix GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.BootstrapOrchestratorTest.test_check_resumes_from_every_legal_checkpoint \
  test_bootstrap.BootstrapOrchestratorTest.test_apply_on_fully_complete_state_performs_no_stage_apply
```

Expected: PASS。若失败，只修复 RESULT/next-stage 状态机；不得新增 progress file 或跳过真实 stage check。

- [ ] **Step 4: 运行完整 orchestrator 回归并提交**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v test_bootstrap.BootstrapOrchestratorTest
shellcheck scripts/bootstrap/bootstrap-all.sh
git diff --check
git add scripts/test_bootstrap.py
git commit -m "test(bootstrap): cover every resume checkpoint"
```

### Task 4: 冻结代码、完成门禁并恢复服务器只读验收

**Files:**
- Verify: `scripts/bootstrap/00-preflight.sh`
- Verify: `scripts/bootstrap/30-install-containerd.sh`
- Verify: `scripts/bootstrap/40-install-kubernetes.sh`
- Verify: `scripts/bootstrap/50-kubeadm-init.sh`
- Verify: `scripts/bootstrap/bootstrap-all.sh`
- Verify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: Tasks 1～3 的 owner contracts 与 checkpoint tests。
- Produces: clean `main`、GitHub validation evidence，以及服务器 stage 40 的只读恢复回执。

- [ ] **Step 1: 运行最终 focused owner suites**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.PreflightTest \
  test_bootstrap.BootstrapOrchestratorTest

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_fresh_install_rejects_preexisting_kubeadm_generated_state \
  test_bootstrap.KubernetesInstallTest.test_exact_packages_allow_kubeadm_owned_generated_state \
  test_bootstrap.KubeadmInitTest.test_check_rejects_non_pristine_kubelet_pre_init_inputs \
  test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write \
  test_bootstrap.KubeadmInitTest.test_initialized_candidate_drift_stops_unknown
```

Expected: 两条命令都 exit 0。

- [ ] **Step 2: 运行本地 fast/static Gate**

```bash
./scripts/validate-fast.sh
shellcheck scripts/bootstrap/lib/common.sh scripts/bootstrap/*.sh
git diff --check
git status --short --branch
```

Expected: fast profile、manifest validation、ShellCheck、diff check 全绿；worktree clean。

- [ ] **Step 3: 普通 push 并等待 GitHub 门禁**

```bash
git push origin main
```

只读检查最终 commit 的 GitHub Actions；全部 shards 与 `validation-gate` 必须 success。任何失败先本地复现并 fix-forward，不继续服务器操作。

- [ ] **Step 4: GitHub 全绿后执行服务器精确同步与只读 check**

服务器同步命令固定本批最终 40-char commit，验证 root、origin、main、clean worktree、remote commit 后 `--ff-only`；最终只执行：

```bash
/opt/uni-code/engineering-platform-gitops/scripts/bootstrap/bootstrap-all.sh --check
```

Expected terminal contract:

```text
STAGE_00_RESULT=PASS_PREFLIGHT
STAGE_10_RESULT=ALREADY_COMPLIANT
STAGE_20_RESULT=ALREADY_COMPLIANT
STAGE_30_RESULT=ALREADY_COMPLIANT
STAGE_40_RESULT=PASS_KUBERNETES_CHECK
RESULT=PASS_BOOTSTRAP_CHECK
NEXT_STAGE=40
EXIT_CODE=0
```

- [ ] **Step 5: 审核回执后再批准 mutation**

只读结果精确一致时，才单独提供 `bootstrap-all.sh --apply` 命令。任一 stage STOP 时不清理、不 apply，按对应 owner stage 诊断。
