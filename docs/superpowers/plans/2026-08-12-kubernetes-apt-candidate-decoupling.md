# Kubernetes APT Candidate Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Stage 40 在批准仓库同时发布多个版本或 Candidate 前移时，仍只安装四个锁定版本，同时继续对 signed Packages index、下载物和安装事务 fail closed。

**Architecture:** 删除 `apt-cache policy` Candidate Gate，把唯一信任边界固定为隔离 APT 配置绑定的 signed Packages index。测试 fixture 必须拒绝任何未显式携带批准 `=version` 的下载请求，并用真实多版本 policy 与更新版本 stanza 证明 Stage 40 不再依赖 Candidate。

**Tech Stack:** Bash 3.2-compatible shell、Python 3 `unittest`、ShellCheck、GitHub Actions

## Global Constraints

- 四个批准版本保持不变：`kubeadm=1.36.3-1.1`、`kubectl=1.36.3-1.1`、`kubelet=1.36.3-1.1`、`kubernetes-cni=1.9.1-1.1`。
- 仓库、keyring、`.deb` Size/SHA256/Depends 与 CNI/package provenance 合同不得修改。
- `signed_index_record()` 对锁定 package/version/amd64 stanza 必须保持“恰好一条”的要求。
- second indextarget、unknown source、duplicate locked stanza、extra download、non-exact transaction 必须继续 STOP。
- 不修改 Stage 00、10、20、30、50、60、90。
- 本地只运行受影响 focused tests、`validate-fast.sh` 和 `validate-static.sh`；完整 `KubernetesInstallTest` 由普通 push 后的 GitHub `validation-gate` 执行。
- GitHub `validation-gate` 全绿前不得继续服务器 mutation。

---

### Task 1: 建立真实多版本仓库 RED 与下载版本钉死合同

**Files:**
- Modify: `scripts/test_bootstrap.py:3980-4135`
- Modify: `scripts/test_bootstrap.py:4661-4680`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `KubernetesInstallTest.make_environment()`、`KubernetesInstallTest.run_stage()`、fixture 环境变量 `FAKE_CANDIDATE_VERSION`。
- Produces: fixture 开关 `FAKE_POLICY_MULTIVERSION=1` 与 `FAKE_INDEX_NEWER_VERSION=1`；测试 `test_apply_ignores_candidate_and_uses_only_locked_artifacts`；严格的 fake `apt-get download package=version` 边界。

- [ ] **Step 1: 让 fake policy 能表示服务器的多版本输出**

在 fake `apt-cache` 的 `policy)` 分支中，将单版本输出替换为下面的条件输出。默认行为保持单版本；设置 `FAKE_POLICY_MULTIVERSION=1` 时，同一个批准 URL 至少出现四次：

```sh
candidate=${FAKE_CANDIDATE_VERSION:-$default_candidate}
printf '%s:\n  Installed: (none)\n  Candidate: %s\n' "$2" "$candidate"
printf '  Version table:\n'
if [ "${FAKE_POLICY_MULTIVERSION:-0}" = 1 ] && [ "$2" != kubernetes-cni ]; then
  for version in "$candidate" 1.36.3-1.1 1.36.2-2.1 1.36.1-1.1; do
    printf '     %s 500\n' "$version"
    printf '        500 https://pkgs.k8s.io/core:/stable:/v1.36/deb  Packages\n'
  done
else
  printf ' *** %s 100\n' "$candidate"
  printf '        100 https://pkgs.k8s.io/core:/stable:/v1.36/deb  Packages\n'
fi
```

- [ ] **Step 2: 让 signed Packages index 同时包含更新版和锁定版**

在 fake `apt-get update` 把 `FAKE_PACKAGES_INDEX` 复制到 private lists 后、其他 drift mutation 前，加入一个不匹配锁定版本的完整 stanza：

```sh
if [ "${FAKE_INDEX_NEWER_VERSION:-0}" = 1 ]; then
  cat >>"$lists/kubernetes_Packages" <<'INDEX'

Package: kubeadm
Version: 1.36.4-1.1
Architecture: amd64
Filename: amd64/kubeadm_1.36.4-1.1_amd64.deb
Size: 1
SHA256: 1111111111111111111111111111111111111111111111111111111111111111
Depends: cri-tools (>= 1.30.0)
INDEX
fi
```

该 stanza 只能证明 index 可含其他版本；下载 fixture 不得为它生成 `.deb`，生产仍必须选择唯一锁定 stanza。

- [ ] **Step 3: 强化 fake download，拒绝未钉死或错误版本**

把 fake `apt-get` 的 `download` 分支改为先提取完整请求，再用 exact allowlist 映射 package。不要先截掉 `=version`：

```sh
request=
for argument in "$@"; do
  case "$argument" in
    kubeadm=*|kubectl=*|kubelet=*|kubernetes-cni=*) request=$argument ;;
  esac
done
case "$request" in
  kubeadm=1.36.3-1.1)
    package=kubeadm; version=1.36.3-1.1; size=12558824
    ;;
  kubectl=1.36.3-1.1)
    package=kubectl; version=1.36.3-1.1; size=11766348
    ;;
  kubelet=1.36.3-1.1)
    package=kubelet; version=1.36.3-1.1; size=13386608
    ;;
  kubernetes-cni=1.9.1-1.1)
    package=kubernetes-cni; version=1.9.1-1.1; size=38991216
    ;;
  *) exit 64 ;;
esac
```

保留已有的 `FAKE_APT_UPDATED`、文件生成和 `FAKE_DOWNLOAD_EXTRA` 逻辑。

- [ ] **Step 4: 写 load-bearing 行为测试**

把旧 `test_rejects_candidate_installed_and_hold_drift` 中的 `candidate` case 删除，并重命名为 `test_rejects_installed_and_hold_drift`。新增以下测试；它既模拟当前服务器同源多版本 policy，也模拟将来 Candidate 前移：

```python
def test_apply_ignores_candidate_and_uses_only_locked_artifacts(self) -> None:
    environment, _, command_log = self.make_environment()
    environment['FAKE_POLICY_MULTIVERSION'] = '1'
    environment['FAKE_INDEX_NEWER_VERSION'] = '1'
    environment['FAKE_CANDIDATE_VERSION'] = '1.36.4-1.1'

    result = self.run_stage(environment, '--apply')

    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('RESULT=PASS_KUBERNETES_INSTALLED', result.stdout)
    commands = command_log.read_text(encoding='utf-8')
    self.assertNotIn('apt-cache policy', commands)
    for request in (
        'kubeadm=1.36.3-1.1',
        'kubectl=1.36.3-1.1',
        'kubelet=1.36.3-1.1',
        'kubernetes-cni=1.9.1-1.1',
    ):
        matching_downloads = [
            line
            for line in commands.splitlines()
            if line.startswith('apt-get ') and ' download ' in line and request in line
        ]
        self.assertEqual(len(matching_downloads), 1, commands)
```

- [ ] **Step 5: 运行 RED，确认失败来自旧 Candidate Gate**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_ignores_candidate_and_uses_only_locked_artifacts
```

Expected: `FAIL`；Stage 40 返回 `30`，输出含 `RESULT=STOP_UNKNOWN_STATE` 与 `REASON=candidate-drift-kubeadm`。不得出现 fixture error。

---

### Task 2: 删除 Candidate 依赖并保持 locked artifact fail closed

**Files:**
- Modify: `scripts/bootstrap/40-install-kubernetes.sh:365-374`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh:763-764`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh:906-910`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `package_version()`、`bound_packages_index()`、`signed_index_record()` 和 Task 1 的严格 fake download。
- Produces: Stage 40 不调用 `apt-cache`，且只按 signed index 中的锁定 stanza 下载 `package=version`。

- [ ] **Step 1: 删除无安全作用的 Candidate parser**

从 `40-install-kubernetes.sh` 完整删除：

```bash
candidate_is_exact() {
  local package=$1 apt_config=$2 expected output candidate repo_count
  expected=$(package_version "$package")
  output=$(APT_CONFIG="$apt_config" apt-cache policy "$package" 2>/dev/null) || return 1
  candidate=$(awk '/^[[:space:]]*Candidate:/ {print $2; count++} END {exit count != 1}' <<<"$output") || return 1
  [[ "$candidate" == "$expected" ]] || return 1
  repo_count=$(grep -Fc "${REPOSITORY_URL%/}" <<<"$output")
  [[ "$repo_count" == 1 ]]
}
```

- [ ] **Step 2: 删除 command allowlist 与主流程中的 apt-cache Gate**

将 required commands 从：

```bash
for required_command in apt-cache apt-config apt-get apt-mark awk ...
```

改为：

```bash
for required_command in apt-config apt-get apt-mark awk ...
```

并删除 `packages_index=$(bound_packages_index ...)` 后面的整个 loop：

```bash
for package in "${PACKAGES[@]}"; do
  candidate_is_exact "$package" "$apt_config" || complete STOP_UNKNOWN_STATE "candidate-drift-${package}" "$EXIT_UNKNOWN_STATE" NONE
done
```

不要改动随后 `signed_index_record()`、`${package}=${version}` 下载、`.deb` 校验、simulation/install/hold 逻辑。

- [ ] **Step 3: 运行新测试，确认 GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_ignores_candidate_and_uses_only_locked_artifacts \
  test_bootstrap.KubernetesInstallTest.test_rejects_installed_and_hold_drift
```

Expected: `Ran 2 tests`、`OK`、exit `0`。

- [ ] **Step 4: 运行供应链 focused regression**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_accepts_real_flat_repository_indextarget_shape \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_missing_or_duplicate_index_stanza_and_extra_download \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_second_packages_indextarget \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_deb_metadata_and_signed_index_digest_drift \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_non_exact_simulated_transaction
```

Expected: `Ran 5 tests`、`OK`、exit `0`。其中 duplicate/digest/second index/extra download/non-exact transaction 必须继续返回原有 STOP 分类。

- [ ] **Step 5: 静态确认 Candidate 已完全退出生产路径**

Run:

```bash
! rg -n 'candidate_is_exact|apt-cache policy|candidate-drift-' scripts/bootstrap/40-install-kubernetes.sh
rg -n 'apt-get download "\$\{package\}=\$\{version\}"|signed_index_record' scripts/bootstrap/40-install-kubernetes.sh
```

Expected: 第一条无匹配且 exit `0`；第二条同时找到 locked download 和 signed index Gate。

---

### Task 3: 本地门禁、提交、普通 push 与服务器恢复

**Files:**
- Modify: `docs/superpowers/plans/2026-08-12-kubernetes-apt-candidate-decoupling.md`（勾选完成项）
- Verify: `scripts/bootstrap/40-install-kubernetes.sh`
- Verify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: Tasks 1–2 的 GREEN 实现。
- Produces: 一个 Conventional Commit、GitHub 全绿证据，以及服务器安全恢复命令。

- [ ] **Step 1: 运行本地 fast/static 门禁**

Run:

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
git diff --check
```

Expected: 三条命令均 exit `0`；fast profile 全部测试 `OK`，static manifest 与 ShellCheck 无 diagnostics。

- [ ] **Step 2: 做范围和敏感信息自审**

Run:

```bash
git status --short
git diff -- scripts/bootstrap/40-install-kubernetes.sh scripts/test_bootstrap.py
git diff --name-only
git diff -- . ':!docs/superpowers/specs/2026-08-12-kubernetes-apt-candidate-decoupling-design.md' \
  | rg -n '(BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|password=|token=|kubeconfig)' || true
```

Expected: 行为改动只涉及 `40-install-kubernetes.sh` 与 `test_bootstrap.py`；另有本设计与计划文档；secret scan 无输出。

- [ ] **Step 3: 提交实现**

```bash
git add \
  docs/superpowers/plans/2026-08-12-kubernetes-apt-candidate-decoupling.md \
  scripts/bootstrap/40-install-kubernetes.sh \
  scripts/test_bootstrap.py
git commit -m "fix(bootstrap): decouple apt candidate from locked artifacts"
```

Expected: commit 成功，worktree clean。

- [ ] **Step 4: 普通 push 并等待 GitHub 全分片**

```bash
git fetch --prune origin main
git merge-base --is-ancestor origin/main HEAD
git push origin main
gh run list --workflow validate.yml --branch main --limit 1
gh run watch --exit-status "$(gh run list --workflow validate.yml --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
```

Expected: 普通 push 成功；`validation-gate` 及其所有 shards 通过。GitHub 的 `kubernetes` shard 是本次完整 `KubernetesInstallTest` 的权威重验证。

- [ ] **Step 5: GitHub 全绿后给服务器恢复命令**

服务器只执行固定 commit 同步和同一 orchestrator：

```bash
cd /opt/uni-code/engineering-platform-gitops
git status --short --branch
git fetch origin main
git merge --ff-only origin/main
git rev-parse HEAD
./scripts/bootstrap/bootstrap-all.sh --apply
rc=$?
echo "COMMAND_EXIT_CODE=$rc"
exit "$rc"
```

Expected: Stage 00–30 报 `ALREADY_COMPLIANT`，Stage 40 不再因多版本 policy 停止；之后按真实状态继续 Stage 50、60、90。任一非零立即停止并贴回完整结构化输出。
