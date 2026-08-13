# Kubernetes Local DEB Cache Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Ubuntu 24.04 APT 2.8.3 在禁止补下载的前提下，从 private archives cache 模拟并安装四个已验证 Kubernetes package。

**Architecture:** 下载目录仍负责接收和验证 signed repository payload；验证完成后，以 no-clobber 方式把精确四包发布到本次 APT workspace 的 private archives cache。simulation 和真实 install 都只提交精确 `package=version`，由 `--no-download` 强制只消费已验证 cache。

**Tech Stack:** Bash 3.2、APT 2.8.3、Python `unittest` fixture、ShellCheck。

## Global Constraints

- 四个版本固定为 `kubeadm/kubectl/kubelet=1.36.3-1.1` 与 `kubernetes-cni=1.9.1-1.1`。
- 不得删除 `--no-download` 或允许 APT 获取第五个 package。
- cache 只能出现四个批准 basename，文件必须 regular、non-symlink、`0600`、expected owner，且 size/SHA-256 精确匹配。
- 所有 production 改动必须先取得 load-bearing RED。
- 本地只跑 focused tests、`validate-fast.sh` 与 static checks；普通 push 后由 GitHub 跑完整 shards。

---

### Task 1: 建立真实 APT cache 行为回归

**Files:**
- Modify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `KubernetesInstallTest` fake `apt-get` 与现有 package metadata。
- Produces: 成功路径必须使用 private cache、精确 `package=version` 和 `--no-download` 的行为合同。

- [ ] **Step 1: 写 failing test 与严格 fake**

让 fake 在 simulation/install 收到外部 `.deb` argv、缺少 `--no-download`、非精确
`package=version` 或 private archives 不含精确四包时失败；成功测试断言两次 APT
transaction argv 均为四个固定 selection。

- [ ] **Step 2: 运行 focused test 验证 RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_installs_exact_local_debs_then_holds_and_records_evidence
```

Expected: `FAIL`，原因是 production 仍传外部 `.deb` 路径且 cache 为空。

### Task 2: 发布并复验 private archives

**Files:**
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `downloaded_debs_are_exact()`、`package_version()`、`package_size()`、`package_sha256()`。
- Produces: `cached_debs_are_exact()` 与精确 `package=version` transaction argv。

- [ ] **Step 1: 实现最小 cache publication**

在四包完成 metadata/dependency 校验后，将其发布到 `${apt_workspace}/archives`；
每个目标以批准 basename 命名并在使用前重新核验集合、metadata 与 digest。

- [ ] **Step 2: simulation/install 改用精确 package selections**

两次命令均保留 `--no-install-recommends --no-download`，argv 只允许四个
`package=version`；simulation 后再次执行 download/cache exact Gates。

- [ ] **Step 3: 运行 focused GREEN**

Run Task 1 的命令。Expected: `OK`。

### Task 3: 锁定 transaction、race 与供应链负向边界

**Files:**
- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`

**Interfaces:**
- Consumes: private archive publication seam。
- Produces: 非精确 transaction、post-simulation cache race 与 CNI race 的结构化 STOP。

- [ ] **Step 1: 运行既有 load-bearing mutation regressions**

覆盖第五个 package/configure、remove、upgrade、错误 version、cache 额外 entry、
simulation 后 CNI ancestry race 与 install 后/hold 前 CNI race。

- [ ] **Step 2: 保持最小 GREEN**

只增加对应 path/content/re-Gate，不放宽 signed index、downloaded deb 或 transaction parser。

- [ ] **Step 3: 运行受影响 focused regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_uses_managed_isolated_apt_context \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_non_exact_simulated_transaction \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_private_archive_cache_race \
  test_bootstrap.KubernetesInstallTest.test_apply_rechecks_cni_ancestry_after_simulation \
  test_bootstrap.KubernetesInstallTest.test_apply_rechecks_cni_ancestry_after_install_before_hold
```

Expected: `Ran 5 tests` / `OK`。完整 Kubernetes shard 交给 push 后的 GitHub gate。

### Task 4: 本地门禁、提交和 GitHub gate

**Files:**
- Verify only: all changed files。

**Interfaces:**
- Consumes: Task 1-3 GREEN diff。
- Produces: 可供服务器固定 commit 同步的绿色 main。

- [ ] **Step 1: 运行本地门禁**

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
shellcheck scripts/bootstrap/40-install-kubernetes.sh
git diff --check
```

- [ ] **Step 2: 提交并普通 push**

使用 Conventional Commit；确认 worktree clean 和 remote commit 一致。

- [ ] **Step 3: 等待 GitHub `validation-gate` 全绿**

只有全部 GitHub shards 通过后，才给服务器固定 commit sync 命令并恢复
`bootstrap-all.sh --apply`。
