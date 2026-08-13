# Kubernetes Post-Install Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Stage 40 在 Ubuntu 24.04 官方 package 安装后识别 usrmerge、dpkg doc exclusion 与未启动 kubelet 的合法中间态，并从当前已安装/hold 状态安全恢复。

**Architecture:** 将现有综合验证拆为三个可独立判定的边界：package payload、unit static provenance、kubelet runtime state。CHECK 对 `START_REQUIRED` 保持零写，APPLY 只执行一次固定 kubelet restart，再复用完整 Gate；fresh install 与 resume 共享同一启动和成功 evidence 路径。

**Tech Stack:** Bash 3.2、systemd、dpkg/dpkg-query、Python `unittest` fixture、ShellCheck。

## Global Constraints

- 不重装已精确安装并 hold 的四个 Kubernetes package。
- 不放宽 binary、CNI、unit、version、architecture、hold 或 package ownership Gate。
- usrmerge fallback 只允许两个固定 `/usr/lib/systemd/system` unit path。
- dpkg verify 只允许空输出，或与精确 doc exclusion 配套的两个批准 missing 文档。
- CHECK 不得 restart、写 evidence 或修改任何 host state。
- APPLY 只对 `enabled + inactive/dead + Result=success` 执行 restart。
- 本地运行 focused tests、`validate-fast.sh` 与 static checks；完整重 shard 由普通 push 后 GitHub 执行。

---

### Task 1: 绑定 Ubuntu usrmerge unit ownership

**Files:**
- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`

**Interfaces:**
- Consumes: systemd `FragmentPath` / `DropInPaths`，`host_path()`，`dpkg-query -S`。
- Produces: `unit_package_ownership_is_exact(logical_path, package)`，返回 0/1。

- [ ] **Step 1: 写 official usrmerge failing test**

新增 `test_usrmerge_unit_paths_preserve_package_ownership`：fixture 令 systemd 输出
`/usr/lib/systemd/system/...`，dpkg-query 只接受 `/lib/systemd/system/...`；test root
中的 `/lib` 必须是 root/expected-owner symlink `usr/lib`。当前 production 应因直接查询
`/usr/lib` ownership 而 FAIL。

同时加入 subtests：`/lib` 非 symlink、指向其他目录、alias 与 canonical 不同文件、
错误 package owner，均必须失败。

- [ ] **Step 2: 运行 test 验证 RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_usrmerge_unit_paths_preserve_package_ownership
```

Expected: official shape failure，旧实现返回 `STOP_VERIFY_FAILED`。

- [ ] **Step 3: 实现 exact-path usrmerge fallback**

增加 `readlink` required command。`unit_package_ownership_is_exact()` 先验证原 logical
path；只有它是两个批准 `/usr/lib/...` 之一且 dpkg 原路径查询失败时，才允许 `/lib/...`
fallback。fallback 必须验证 mapped `/lib` 是 expected-owner symlink、link text 精确
`usr/lib`、canonical/alias `readlink -f` 完全相同、目标 regular/non-symlink/0644，且
dpkg-query 返回精确 `package: /lib/...`。

- [ ] **Step 4: 运行 GREEN**

重新运行 Step 2；Expected: `OK`，所有负向 subtests 仍 STOP。

### Task 2: 精确允许 dpkg doc exclusion 输出

**Files:**
- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`

**Interfaces:**
- Consumes: `/etc/dpkg/dpkg.cfg.d/excludes` 与 `dpkg --verify package`。
- Produces: `dpkg_package_verification_is_exact(package)`，返回 0/1。

- [ ] **Step 1: 写 representation-complete RED**

新增 `test_dpkg_verify_accepts_only_declared_doc_exclusions`。正向 fixture 必须同时具备：

```text
path-exclude=/usr/share/doc/*
missing /usr/share/doc/<package>/LICENSE
missing /usr/share/doc/<package>/README.md
```

四包 verify 均 exit 0。旧 production 因 stdout 非空而 FAIL。

负向 subtests：excludes 缺失/symlink/unsafe mode/owner、只缺一项、额外 missing binary、
checksum drift、重复行、其他 package doc、verify 非零；全部必须 STOP。

- [ ] **Step 2: 运行 test 验证 RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_dpkg_verify_accepts_only_declared_doc_exclusions
```

Expected: official shape FAIL，原因是当前 `[[ -z "$verification" ]]`。

- [ ] **Step 3: 实现严格 parser**

`dpkg_package_verification_is_exact()` 必须先保存 rc 与 stdout；rc 非 0 直接失败，空
stdout 通过。非空 stdout 仅在 mapped excludes 为 regular、non-symlink、0644、
expected-owner，且 `path-exclude=/usr/share/doc/*` 恰好一条时解析。AWK 必须要求恰好
两行、无重复、package 名完全等于参数、basename 只为 LICENSE/README.md；其他字符、
字段或路径全部失败。

将 `managed_kubernetes_binaries_are_exact()` 的 package verify loop 改为调用该 helper。

- [ ] **Step 4: 运行 GREEN 与既有 payload drift regression**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_dpkg_verify_accepts_only_declared_doc_exclusions \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubernetes_binary_or_package_provenance_drift
```

Expected: `Ran 2 tests` / `OK`。

### Task 3: 引入 kubelet READY/START_REQUIRED/UNKNOWN 状态机

**Files:**
- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`

**Interfaces:**
- Consumes: exact unit static provenance、systemd 7-field show output。
- Produces: `kubelet_unit_state()` 输出 `READY`、`START_REQUIRED` 或 `UNKNOWN`；`restart_kubelet_and_verify()` 返回 0/1/2（ready/apply failure/verify failure）。

- [ ] **Step 1: 写 installed resume RED**

新增 `test_resumes_exact_installed_inactive_kubelet_without_reinstall`：安装 repository、
四包 exact hold、CNI exact、doc exclusions 与 usrmerge unit fixture。初始 systemd 为
`loaded/enabled/inactive/dead/Result=success`。

断言：

- CHECK exit 0、`PASS_KUBERNETES_CHECK/apply-required`，无 restart/evidence/APT；
- APPLY 只执行一次 `systemctl restart kubelet.service`，fake 随后变为
  `activating/auto-restart`，返回 `PASS_KUBERNETES_INSTALLED`；
- 再次 APPLY 返回 `ALREADY_COMPLIANT`，不重复 restart。

当前 production 应在 CHECK 直接 `STOP_VERIFY_FAILED`。

- [ ] **Step 2: 写 fresh install/restart failure RED**

新增 `test_fresh_install_explicitly_starts_kubelet`，让 fake package install 后仍
inactive；只有收到 exact restart 才进入 READY。再加 restart command failure、restart
后仍 inactive、failed state 三个负向 subtests，断言 exit40/50/50、无成功 evidence。

- [ ] **Step 3: 运行 RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_resumes_exact_installed_inactive_kubelet_without_reinstall \
  test_bootstrap.KubernetesInstallTest.test_fresh_install_explicitly_starts_kubelet
```

Expected: 两个 methods 均 load-bearing FAIL，无 fixture error。

- [ ] **Step 4: 拆分 static provenance 与 runtime classification**

将当前 `kubelet_pre_init_state_is_expected()` 拆为：

- static 解析：LoadState、UnitFileState、FragmentPath、DropInPaths 与 Task 1 ownership；
- runtime 解析：ActiveState、SubState、Result；
- `READY` 只允许 activating/auto-restart 或 active/running；
- `START_REQUIRED` 只允许 inactive/dead/Result=success；
- 其他输出 `UNKNOWN`。

字段必须恰好七项、每项唯一、无未知字段。

- [ ] **Step 5: 实现 CHECK/APPLY resume 与 fresh restart**

抽取 package/static verification，installed branch 先判 runtime：READY 维持
ALREADY；START_REQUIRED 在 CHECK 返回 apply-required，在 APPLY 执行 exact restart 并
完整复验后写 success evidence；UNKNOWN STOP_VERIFY。

fresh install 在 hold/CNI/static Gate 后显式 restart，再完成完整验证。把现有 evidence
写入抽为单一 helper，fresh/resume 共用，避免成功输出分叉。

- [ ] **Step 6: 运行 GREEN**

重新运行 Step 3；Expected: `Ran 2 tests` / `OK`。

### Task 4: Regression、local gate 与交付

**Files:**
- Verify: `scripts/bootstrap/40-install-kubernetes.sh`
- Verify: `scripts/test_bootstrap.py`
- Verify: 本 spec 与 design。

**Interfaces:**
- Consumes: Task 1–3 GREEN。
- Produces: GitHub 全绿的固定 main commit 与服务器 resume 命令。

- [ ] **Step 1: 运行受影响 focused regression set**

至少包含：成功 install、idempotency、unit state drift、unit metadata/ownership、package
payload drift、CNI drift、failed init boundary，以及 Task 1–3 新 tests。

- [ ] **Step 2: 运行本地门禁**

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n scripts/bootstrap/40-install-kubernetes.sh
shellcheck scripts/bootstrap/40-install-kubernetes.sh
git diff --check
```

- [ ] **Step 3: 自审与提交**

确认 diff 仅 design/plan、Stage 40、test fixture；使用 Conventional Commit，确认
`git show --check` 与 clean worktree。

- [ ] **Step 4: 普通 push 并等待 GitHub gate**

只在 `static`、所有 dynamic shards 与最终 `validation-gate` 全绿后，给服务器固定
commit sync 命令。服务器从 exact installed/held 状态恢复，不清 package、不重装。
