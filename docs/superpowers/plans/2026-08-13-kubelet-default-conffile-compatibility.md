# kubelet 官方 default conffile 兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Stage 40 与 Stage 50 通过同一个严格 validator 识别 kubelet `1.36.3-1.1` 未修改的官方 `/etc/default/kubelet` conffile，并从服务器当前已安装、hold、kubelet inactive 的状态安全恢复到 kubeadm init。

**Architecture:** 已完成的 Stage 40 五重绑定迁入 `scripts/bootstrap/lib/kubelet-default.sh`，Stage 40 与 Stage 50 都只调用 `kubelet_default_conffile_is_pristine()`。missing、安全空文件与精确官方 conffile 使用同一事实源；共享 library 不决定业务 RESULT/退出码。Stage 40 保持 installed-state 50 分类，Stage 50 保持 pre-init 30 分类，并在 validate、preflight 与真正 init 前重复验真。

**Tech Stack:** Bash 3.2、GNU `md5sum`、`sha256sum`、dpkg-query、Python `unittest` fixture、ShellCheck。

## Global Constraints

- 仅允许 missing、安全空文件，或精确 `KUBELET_EXTRA_ARGS=\n` 的官方 conffile。
- 官方文件固定 SHA-256 为 `2737f011e1fc6995aeeb6a2071e268e37b1437481bbdb205f5075939f40d7ae7`。
- 官方 `${Conffiles}` MD5 固定为 `9ba5cd2e9a1e368fa51e13f1dd6a5ec1`，当前文件 MD5 必须与它一致。
- `/etc/default/kubelet` 必须 regular、non-symlink、root:root、0644；测试模式使用现有 expected owner 映射。
- `dpkg-query -S /etc/default/kubelet` 必须成功且 stdout 精确为唯一一行 `kubelet: /etc/default/kubelet`。
- `${Conffiles}` 中目标路径必须恰好一条；缺失、重复、格式错误、digest 漂移或 command failure 均失败。
- 不执行 shell 语义解析，不接受空格、注释、额外换行、额外行或其他等价写法。
- CHECK 不 restart、不写 evidence；installed resume 不执行任何 APT、download、install 或 hold mutation。
- 本地只运行受影响 focused tests、`validate-fast.sh` 与 static checks；完整动态 shard 由普通 push 后 GitHub `validation-gate` 执行。

## 执行状态（2026-08-14）

- Task 1 的 Stage 40 官方 conffile 兼容已在 main 完成，并在真实 Ubuntu 24.04 主机通过；以下 Task 1 步骤保留为历史设计与证据，不重复执行。
- Task 2 已推进到服务器 Stage 50；真实 Stop Gate 为 `kubelet-operator-override-present`，由 Stage 50 未复用 Stage 40 合同导致。
- 本轮只执行新增 Task 3/4；不重装 Stage 40 package，不修改服务器 `/etc/default/kubelet`。

---

### Task 1: 两轮 TDD 实现严格官方 conffile 恢复

**Files:**
- Modify: `scripts/test_bootstrap.py:3718-5625`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh:38-150`

**Interfaces:**
- Consumes: `KubernetesInstallTest.make_environment()`、`install_repository_contract()`、`install_cni_contract()`、`run_stage()`。
- Produces: `install_official_kubelet_default_conffile(host)` fixture helper、两个 load-bearing regression methods，以及完整 `kubelet_operator_override_is_pristine()`。

- [ ] **Step 1: 加入精确官方 conffile fixture helper**

在 `KubernetesInstallTest` 中加入：

```python
kubelet_default_sha256 = (
    '2737f011e1fc6995aeeb6a2071e268e37b1437481bbdb205f5075939f40d7ae7'
)
kubelet_default_md5 = '9ba5cd2e9a1e368fa51e13f1dd6a5ec1'

def install_official_kubelet_default_conffile(self, host: Path) -> Path:
    target = host / 'etc/default/kubelet'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'KUBELET_EXTRA_ARGS=\n')
    target.chmod(0o644)
    return target
```

扩展 fake `dpkg-query`：

```sh
if [ "$#" = 3 ] && [ "$1" = -W ] && [ "$2" = '-f=${Conffiles}' ] && [ "$3" = kubelet ]; then
  printf 'dpkg-query %s\n' "$*" >>"$FAKE_COMMAND_LOG"
  [ "${FAKE_KUBELET_CONFFILES_QUERY_FAIL:-0}" != 1 ] || exit 1
  case "${FAKE_KUBELET_CONFFILES_SHAPE:-exact}" in
    exact) printf ' /etc/default/kubelet 9ba5cd2e9a1e368fa51e13f1dd6a5ec1\n' ;;
    missing) printf '' ;;
    duplicate)
      printf ' /etc/default/kubelet 9ba5cd2e9a1e368fa51e13f1dd6a5ec1\n'
      printf ' /etc/default/kubelet 9ba5cd2e9a1e368fa51e13f1dd6a5ec1\n'
      ;;
    malformed) printf ' /etc/default/kubelet not-a-digest extra\n' ;;
    digest-drift) printf ' /etc/default/kubelet 00000000000000000000000000000000\n' ;;
    *) exit 64 ;;
  esac
  exit 0
fi
```

在 fake `dpkg-query -S` 的 logical path case 中加入 `/etc/default/kubelet`，并用
`FAKE_KUBELET_DEFAULT_OWNER_SHAPE=fail|other|duplicate` 生成 query failure、错误 package
或两行输出；默认只输出 `kubelet: /etc/default/kubelet`。

加入 fake `md5sum`，默认只接受 mapped `/etc/default/kubelet`，输出当前批准 MD5；
`FAKE_KUBELET_DEFAULT_MD5_FAIL=1` 返回非零，
`FAKE_KUBELET_DEFAULT_MD5_DRIFT=1` 输出 32 个 `0`。为 fake `sha256sum` 加
`FAKE_KUBELET_DEFAULT_SHA256_FAIL=1`，只在 basename 为 `kubelet` 且路径结尾为
`/etc/default/kubelet` 时返回非零；其他文件维持既有实现。

- [ ] **Step 2: 写 installed/resume 正向 RED**

新增 `test_accepts_unmodified_official_kubelet_default_conffile`：

```python
environment, host, command_log = self.make_environment()
self.install_repository_contract(host)
environment['FAKE_INSTALLED_STATE'] = 'exact'
Path(environment['FAKE_PACKAGES_HELD']).touch()
self.install_cni_contract(host)
self.install_official_kubelet_default_conffile(host)
environment['FAKE_KUBELET_ACTIVE_STATE'] = 'inactive'
environment['FAKE_KUBELET_SUB_STATE'] = 'dead'
environment['FAKE_KUBELET_RESULT'] = 'success'

check = self.run_stage(environment)
self.assertEqual(check.returncode, 0, check.stderr)
self.assertIn('RESULT=PASS_KUBERNETES_CHECK', check.stdout)
self.assertIn('REASON=apply-required', check.stdout)
self.assertNotIn('systemctl restart', command_log.read_text(encoding='utf-8'))
self.assertEqual(
    list((host / 'root/dev-infra-evidence').glob('11-kubernetes-*.txt')),
    [],
)

apply = self.run_stage(environment, '--apply')
self.assertEqual(apply.returncode, 0, apply.stderr)
self.assertIn('RESULT=PASS_KUBERNETES_INSTALLED', apply.stdout)
self.assertEqual(
    command_log.read_text(encoding='utf-8').count(
        'systemctl restart kubelet.service'
    ),
    1,
)
self.assertNotIn('apt-get ', command_log.read_text(encoding='utf-8'))

repeated = self.run_stage(environment, '--apply')
self.assertEqual(repeated.returncode, 0, repeated.stderr)
self.assertIn('RESULT=ALREADY_COMPLIANT', repeated.stdout)
self.assertEqual(
    command_log.read_text(encoding='utf-8').count(
        'systemctl restart kubelet.service'
    ),
    1,
)
```

- [ ] **Step 3: 运行并确认 official shape RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_accepts_unmodified_official_kubelet_default_conffile
```

Expected: `Ran 1 test`、FAIL、exit 1；实际 Stage 40 因现有 `path_size == 0` 返回 50。
不得出现 loader、fixture 或 syntax error。

- [ ] **Step 4: 实现仅足以通过正向的固定 bytes Gate**

在 package 常量旁加入：

```bash
readonly KUBELET_DEFAULT_CONTENT='KUBELET_EXTRA_ARGS='
readonly KUBELET_DEFAULT_SIZE=20
readonly KUBELET_DEFAULT_SHA256=2737f011e1fc6995aeeb6a2071e268e37b1437481bbdb205f5075939f40d7ae7
readonly KUBELET_DEFAULT_MD5=9ba5cd2e9a1e368fa51e13f1dd6a5ec1
```

只把 `kubelet_operator_override_is_pristine()` 的最后一行临时替换为以下最小分支：

```bash
  local size actual_sha256
  size=$(path_size "$default_file") || return 1
  [[ "$size" == 0 ]] && return 0
  [[ "$size" == "$KUBELET_DEFAULT_SIZE" ]] || return 1
  [[ "$(cat "$default_file")" == "$KUBELET_DEFAULT_CONTENT" ]] || return 1
  actual_sha256=$(sha256_file "$default_file") || return 1
  [[ "$actual_sha256" == "$KUBELET_DEFAULT_SHA256" ]]
```

这只是同一工作树中的 TDD 中间态，不提交、不 push、不用于服务器部署；它故意尚未满足
ownership/conffile/MD5 合同，使 Task 2 的 provenance tests 能真实失败。

- [ ] **Step 5: 运行正向 test，确认最小 GREEN**

重复 Step 3 命令。Expected: `Ran 1 test`、`OK`、exit 0；CHECK/apply/repeated apply
断言全部成立。

- [ ] **Step 6: 写 fail-closed provenance RED**

新增 `test_rejects_kubelet_default_conffile_provenance_drift`，每个 subtest 都从 exact
installed/hold/CNI/official conffile 开始，并覆盖：

```python
cases = (
    ('directory', {}),
    ('symlink', {}),
    ('mode', {}),
    ('owner', {'FAKE_STAT_OWNER_DRIFT': 'TARGET'}),
    ('content-argument', {}),
    ('content-comment', {}),
    ('content-whitespace', {}),
    ('content-extra-newline', {}),
    ('ownership-query-fail', {'FAKE_KUBELET_DEFAULT_OWNER_SHAPE': 'fail'}),
    ('ownership-other', {'FAKE_KUBELET_DEFAULT_OWNER_SHAPE': 'other'}),
    ('ownership-duplicate', {'FAKE_KUBELET_DEFAULT_OWNER_SHAPE': 'duplicate'}),
    ('conffile-query-fail', {'FAKE_KUBELET_CONFFILES_QUERY_FAIL': '1'}),
    ('conffile-missing', {'FAKE_KUBELET_CONFFILES_SHAPE': 'missing'}),
    ('conffile-duplicate', {'FAKE_KUBELET_CONFFILES_SHAPE': 'duplicate'}),
    ('conffile-malformed', {'FAKE_KUBELET_CONFFILES_SHAPE': 'malformed'}),
    ('conffile-digest', {'FAKE_KUBELET_CONFFILES_SHAPE': 'digest-drift'}),
    ('md5-command-fail', {'FAKE_KUBELET_DEFAULT_MD5_FAIL': '1'}),
    ('md5-drift', {'FAKE_KUBELET_DEFAULT_MD5_DRIFT': '1'}),
    ('sha256-command-fail', {'FAKE_KUBELET_DEFAULT_SHA256_FAIL': '1'}),
)
```

`TARGET` 在 test setup 时替换成 mapped 文件路径。内容 mutations 分别写入：

```python
b'KUBELET_EXTRA_ARGS=--config=/tmp/evil\n'
b'# package default\nKUBELET_EXTRA_ARGS=\n'
b'KUBELET_EXTRA_ARGS= \n'
b'KUBELET_EXTRA_ARGS=\n\n'
```

每个 subtest 必须断言 exit 50、`RESULT=STOP_VERIFY_FAILED`、无 restart、无 APT、无
success evidence。现有 missing、empty、operator override tests 不修改期望。

- [ ] **Step 7: 运行并确认 provenance RED**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubelet_default_conffile_provenance_drift
```

Expected: metadata/content/SHA subtests 继续正确拒绝；ownership、`${Conffiles}` 与 MD5
subtests 对 Task 1 的最小实现产生 assertion failures（实际错误返回 0）。整组 exit 1，且不得
出现 loader、fixture 或 syntax error。

- [ ] **Step 8: 加入 md5sum precondition 与唯一 conffile record parser**

在 required command loop 中加入 `md5sum`。Ubuntu 24.04 production 必须使用 GNU
`md5sum`；测试模式通过 Task 1 fake 隔离，不依赖 macOS host utility。

加入 helper：

```bash
kubelet_registered_default_md5() {
  local conffiles
  conffiles=$(dpkg-query -W -f='${Conffiles}' kubelet 2>/dev/null) || return 1
  awk '
    NF == 0 {next}
    $1 != "/etc/default/kubelet" {next}
    NF != 2 || $2 !~ /^[0-9a-f]{32}$/ || seen++ {exit 1}
    {digest=$2}
    END {
      if (seen != 1) exit 1
      print digest
    }
  ' <<<"$conffiles"
}
```

该 parser 允许 kubelet package 未来存在其他 conffile 记录，但目标路径必须唯一且格式精确。

- [ ] **Step 9: 收紧 nonempty 分支**

将 `kubelet_operator_override_is_pristine()` 改为：

```bash
kubelet_operator_override_is_pristine() {
  local default_file size actual_sha256 ownership registered_md5 actual_md5
  default_file=$(host_path /etc/default/kubelet)
  if [[ ! -e "$default_file" && ! -L "$default_file" ]]; then
    return 0
  fi
  [[ -f "$default_file" && ! -L "$default_file" && "$(path_mode "$default_file")" == 644 ]] || return 1
  owned_by_expected "$default_file" || return 1
  size=$(path_size "$default_file") || return 1
  [[ "$size" == 0 ]] && return 0
  [[ "$size" == "$KUBELET_DEFAULT_SIZE" ]] || return 1
  [[ "$(cat "$default_file")" == "$KUBELET_DEFAULT_CONTENT" ]] || return 1
  actual_sha256=$(sha256_file "$default_file") || return 1
  [[ "$actual_sha256" == "$KUBELET_DEFAULT_SHA256" ]] || return 1
  ownership=$(dpkg-query -S /etc/default/kubelet 2>/dev/null) || return 1
  [[ "$ownership" == 'kubelet: /etc/default/kubelet' ]] || return 1
  registered_md5=$(kubelet_registered_default_md5) || return 1
  [[ "$registered_md5" == "$KUBELET_DEFAULT_MD5" ]] || return 1
  actual_md5=$(md5sum "$default_file" 2>/dev/null) || return 1
  [[ "$actual_md5" == "${registered_md5}  ${default_file}" ]] || return 1
  [[ -f "$default_file" && ! -L "$default_file" && "$(path_mode "$default_file")" == 644 ]] || return 1
  owned_by_expected "$default_file" || return 1
  [[ "$(path_size "$default_file")" == "$KUBELET_DEFAULT_SIZE" ]] || return 1
  [[ "$(sha256_file "$default_file")" == "$KUBELET_DEFAULT_SHA256" ]]
}
```

末尾重复 metadata/size/SHA gate 用于捕获验证期间的状态变化；不创建 snapshot、不修改 conffile。

- [ ] **Step 10: 运行两轮 focused tests，确认完整 GREEN**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_accepts_unmodified_official_kubelet_default_conffile \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubelet_default_conffile_provenance_drift
```

Expected: `Ran 2 tests`、`OK`、exit 0。

- [ ] **Step 11: 运行既有 missing/empty/operator/fresh Gate regressions**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_exact_packages_still_reject_kubelet_operator_override \
  test_bootstrap.KubernetesInstallTest.test_allows_secure_kubelet_root_and_empty_operator_override \
  test_bootstrap.KubernetesInstallTest.test_rejects_non_pristine_kubelet_pre_init_mutable_inputs \
  test_bootstrap.KubernetesInstallTest.test_resumes_exact_installed_inactive_kubelet_without_reinstall
```

Expected: `Ran 4 tests`、`OK`、exit 0。测试必须证明 CHECK 无 restart/evidence、resume 无 APT、重复 APPLY 不重复 restart。

- [ ] **Step 12: 运行受影响的 Kubernetes focused set**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_accepts_unmodified_official_kubelet_default_conffile \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubelet_default_conffile_provenance_drift \
  test_bootstrap.KubernetesInstallTest.test_exact_packages_still_reject_kubelet_operator_override \
  test_bootstrap.KubernetesInstallTest.test_allows_secure_kubelet_root_and_empty_operator_override \
  test_bootstrap.KubernetesInstallTest.test_rejects_non_pristine_kubelet_pre_init_mutable_inputs \
  test_bootstrap.KubernetesInstallTest.test_resumes_exact_installed_inactive_kubelet_without_reinstall \
  test_bootstrap.KubernetesInstallTest.test_dpkg_verify_accepts_only_declared_doc_exclusions \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubernetes_binary_or_package_provenance_drift
```

Expected: `Ran 8 tests`、`OK`、exit 0。

- [ ] **Step 13: 运行提交前 fast/static 门禁**

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n scripts/bootstrap/40-install-kubernetes.sh
shellcheck scripts/bootstrap/40-install-kubernetes.sh
git diff --check
```

所有命令必须 exit 0；不在本地运行完整 Kubernetes shard 或 `validate.sh`。

- [ ] **Step 14: 自审并提交实现**

确认 production diff 只放宽设计批准的官方 conffile，全部既有 negative Gate 保留；确认
`git diff --check`、tracked file scope 与 `git status`。提交：

```bash
git add scripts/bootstrap/40-install-kubernetes.sh scripts/test_bootstrap.py
git commit -m 'fix(bootstrap): accept official kubelet default conffile'
git show --check --stat HEAD
```

### Task 2: 审查、发布与服务器交接

**Files:**
- Verify: `scripts/bootstrap/40-install-kubernetes.sh`
- Verify: `scripts/test_bootstrap.py`
- Verify: `docs/superpowers/specs/2026-08-13-kubelet-default-conffile-design.md`
- Verify: `docs/superpowers/plans/2026-08-13-kubelet-default-conffile-compatibility.md`

**Interfaces:**
- Consumes: Task 1 已提交且 task review、whole-branch review 均 clean。
- Produces: GitHub 全绿的 main commit，以及服务器 Stage 40 resume 回执。

- [ ] **Step 1: 普通 push 并等待 GitHub validation-gate**

```bash
git push origin main
head_sha=$(git rev-parse HEAD)
run_id=$(gh run list --workflow validate.yml --branch main --commit "$head_sha" \
  --limit 1 --json databaseId --jq '.[0].databaseId')
[[ -n "$run_id" ]]
gh run watch "$run_id" --exit-status
```

只有该 commit 的 `validation-gate` 全部成功后，才允许服务器 fetch/fast-forward。

- [ ] **Step 2: 在服务器从真实状态恢复 Stage 40**

先按 runbook 验证 origin、branch、clean worktree 与 expected commit，fast-forward 后执行：

```bash
cd /opt/uni-code/engineering-platform-gitops
./scripts/bootstrap/bootstrap-all.sh --apply
rc=$?
echo "COMMAND_EXIT_CODE=$rc"
```

Expected: Stage 40 不再重新下载/安装四包；只 restart kubelet、完整复验并继续 Stage 50，或在下一个真实 Stop Gate 精确停止。

---

### Task 3: 抽取共享 validator 并修复 Stage 50 重复误判

**Files:**
- Create: `scripts/bootstrap/lib/kubelet-default.sh`
- Modify: `scripts/bootstrap/40-install-kubernetes.sh`
- Modify: `scripts/bootstrap/50-kubeadm-init.sh`
- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/validate-static.sh`

**Interfaces:**
- Produces: `kubelet_default_conffile_is_pristine <mapped-path>` 与内部 `${Conffiles}` parser。
- Consumes: 调用 Stage 提供的 `path_mode`、`path_size`、`owned_by_expected`，以及 common 的 `sha256_file`。
- Invariant: shared library 不调用 `complete`、不输出 RESULT、不缓存文件状态，也不修改目标文件。

- [ ] **Step 1: 给 Stage 50 fixture 增加真实官方 conffile 边界**

在 `KubeadmInitTest` 中新增 `seed_official_kubelet_default_conffile(host)`，只创建：

```python
target = host / 'etc/default/kubelet'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(b'KUBELET_EXTRA_ARGS=\n')
target.chmod(0o644)
```

扩展 fake tools，但不改变既有 `/etc/kubernetes` 与 `/var/lib/kubelet` package-footprint fixture：

- `dpkg-query -S /etc/default/kubelet` 默认只输出
  `kubelet: /etc/default/kubelet`；支持 fail、other、duplicate、无终止换行和尾随空行。
- `dpkg-query -W -f='${Conffiles}' kubelet` 默认只输出唯一批准记录；支持 command fail、missing、duplicate、malformed 与 digest drift。
- fake `md5sum` 默认返回批准 MD5；支持 command fail 与 digest drift。
- fake `sha256sum` 对 default conffile 支持 command fail 与 digest drift，同时保持 `.kubelet-keep` 既有行为。
- fake kubeadm 的 validate/preflight seam 支持
  `FAKE_DRIFT_AFTER_VALIDATE=kubelet-default-conffile` 与
  `FAKE_DRIFT_AFTER_PREFLIGHT=kubelet-default-conffile`。

- [ ] **Step 2: 写 Stage 50 official conffile 正向 RED**

新增：

```text
KubeadmInitTest.test_accepts_exact_official_kubelet_default_conffile
```

每次 setup 同时 seed 已批准的 `/etc/kubernetes` package footprint、`/var/lib/kubelet`
package footprint 与官方 `/etc/default/kubelet`。断言：

- `--check` exit 0、`RESULT=PASS_KUBEADM_CHECK`、tree byte/metadata snapshot 完全不变；
- `--apply` exit 0、`RESULT=PASS_KUBEADM_INITIALIZED`，且只调用批准的 kubeadm sequence；
- init 前没有删除、清空、chmod 或重写 `/etc/default/kubelet`。

运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubeadmInitTest.test_accepts_exact_official_kubelet_default_conffile
```

Expected RED: `Ran 1 test`、FAIL、exit 1；旧 Stage 50 对 nonempty 文件返回 30。不得出现 loader、fixture 或 syntax error。

- [ ] **Step 3: 写 Stage 50 provenance 与 race RED**

新增：

```text
KubeadmInitTest.test_rejects_official_kubelet_default_conffile_drift
KubeadmInitTest.test_regates_official_kubelet_default_conffile_before_init
```

第一个 method 的每个 subtest 必须先证明 exact baseline 能通过，再分别破坏：

- type/symlink、mode、owner、size；
- bytes、无终止换行、尾随空行；
- package ownership query fail/other/duplicate/no-final-newline/trailing-blank；
- `${Conffiles}` query fail/missing/duplicate/malformed/digest drift；
- MD5 command fail/digest drift；
- mode/content command 输出批准值后非零退出；
- final size/SHA-256 command 输出批准值后非零退出；
- SHA-256 command fail/digest drift。

全部必须 exit 30、`REASON=kubelet-operator-override-present`，并证明没有执行
`kubeadm init`、没有 success evidence、目标文件未被生产代码修复。

第二个 method 分别在 config validate 后、preflight 后，以及最后一轮 CIDR Gate
返回 PASS 后把 exact conffile 改成非批准 bytes。除 exit 30、reason 和 no-init 外，
还必须断言：

- after-validate case 的 command log 已出现 `kubeadm config validate`，但没有 preflight/init；
- after-preflight case 已出现 validate 与 `kubeadm init phase preflight`，但没有真正 init。
- after-CIDR case 只在第三次 CIDR 调用漂移，已完成 validate/preflight，但仍没有真正 init。

这样旧 Stage 50 在初始 nonempty Gate 提前返回同样的 rc/reason 时，测试仍会 RED，不能假绿。

先在旧 production 上运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_default_conffile_drift \
  test_bootstrap.KubeadmInitTest.test_regates_official_kubelet_default_conffile_before_init
```

Expected RED: exact baseline 或 race 分类产生 load-bearing assertion failures、exit 1；不得以 fixture error 充当 RED。

- [ ] **Step 4: 写单一事实源静态 RED**

新增：

```text
CommonLibraryTest.test_kubernetes_stages_share_kubelet_default_validator
```

断言必须同时成立：

- Stage 40 与 Stage 50 都精确 source `lib/kubelet-default.sh`；
- 两个 Stage 都调用 `kubelet_default_conffile_is_pristine`；
- approved content/SHA/MD5 常量与 `${Conffiles}` parser 只存在于 shared library；
- Stage 40 不再定义 `kubelet_operator_override_is_pristine`；
- Stage 50 不再以 `-s /etc/default/kubelet` 作为 nonempty 拒绝规则；
- `validate-static.sh` 的 ShellCheck scope 覆盖 `scripts/bootstrap/lib/*.sh`。

运行该 method，Expected RED 为 missing shared library/source，exit 1。

- [ ] **Step 5: 创建 shared library**

`scripts/bootstrap/lib/kubelet-default.sh` 必须逐行迁移当前 Stage 40 已验证的实现，并只把
target 改为显式参数：

```bash
#!/usr/bin/env bash

readonly KUBELET_DEFAULT_CONTENT='KUBELET_EXTRA_ARGS='
readonly KUBELET_DEFAULT_SIZE=20
readonly KUBELET_DEFAULT_SHA256=2737f011e1fc6995aeeb6a2071e268e37b1437481bbdb205f5075939f40d7ae7
readonly KUBELET_DEFAULT_MD5=9ba5cd2e9a1e368fa51e13f1dd6a5ec1

kubelet_registered_default_md5() {
  local conffiles
  conffiles=$(dpkg-query -W -f='${Conffiles}' kubelet 2>/dev/null) || return 1
  awk '
    NF == 0 {next}
    $1 != "/etc/default/kubelet" {next}
    NF != 2 || $2 !~ /^[0-9a-f]{32}$/ || seen++ {exit 1}
    {digest=$2}
    END {
      if (seen != 1) exit 1
      print digest
    }
  ' <<<"$conffiles"
}

kubelet_default_conffile_is_pristine() {
  local default_file=$1 mode size content actual_sha256 ownership
  local registered_md5 actual_md5
  local ownership_sentinel=__KUBELET_DEFAULT_OWNERSHIP_END__
  if [[ ! -e "$default_file" && ! -L "$default_file" ]]; then
    return 0
  fi
  [[ -f "$default_file" && ! -L "$default_file" ]] || return 1
  mode=$(path_mode "$default_file") || return 1
  [[ "$mode" == 644 ]] || return 1
  owned_by_expected "$default_file" || return 1
  size=$(path_size "$default_file") || return 1
  [[ "$size" == 0 ]] && return 0
  [[ "$size" == "$KUBELET_DEFAULT_SIZE" ]] || return 1
  content=$(cat "$default_file") || return 1
  [[ "$content" == "$KUBELET_DEFAULT_CONTENT" ]] || return 1
  actual_sha256=$(sha256_file "$default_file") || return 1
  [[ "$actual_sha256" == "$KUBELET_DEFAULT_SHA256" ]] || return 1
  ownership=$(
    dpkg-query -S /etc/default/kubelet 2>/dev/null &&
      printf '%s' "$ownership_sentinel"
  ) || return 1
  [[ "$ownership" == $'kubelet: /etc/default/kubelet\n'"$ownership_sentinel" ]] || return 1
  registered_md5=$(kubelet_registered_default_md5) || return 1
  [[ "$registered_md5" == "$KUBELET_DEFAULT_MD5" ]] || return 1
  actual_md5=$(md5sum "$default_file" 2>/dev/null) || return 1
  [[ "$actual_md5" == "${registered_md5}  ${default_file}" ]] || return 1
  [[ -f "$default_file" && ! -L "$default_file" ]] || return 1
  mode=$(path_mode "$default_file") || return 1
  [[ "$mode" == 644 ]] || return 1
  owned_by_expected "$default_file" || return 1
  size=$(path_size "$default_file") || return 1
  [[ "$size" == "$KUBELET_DEFAULT_SIZE" ]] || return 1
  actual_sha256=$(sha256_file "$default_file") || return 1
  [[ "$actual_sha256" == "$KUBELET_DEFAULT_SHA256" ]]
}
```

实现必须保留 Stage 40 现有 load-bearing 边界：

- metadata、size、bytes、SHA、唯一 package owner、唯一 conffile record、registered MD5、current MD5；
- command substitution 的 sentinel 逻辑，严格区分终止换行、无终止换行和额外空行；
- mode、content、size、SHA 等 helper 的 stdout 与退出码必须分别验证，禁止把
  command substitution 直接嵌入 `[[ ... ]]` 而吞掉非零退出；
- 完成验证后再次检查 metadata、size 与 SHA，捕获验证期间 drift。

library 不自行寻找 host path；调用者传入 mapped target。不要复制或缓存 target。

- [ ] **Step 6: Stage 40 改为只调用 shared validator**

在 `common.sh` 后 source 新 library，并：

- 删除 Stage 40 内重复的 content/SHA/MD5 常量；
- 删除 Stage 40 内 `${Conffiles}` parser 与
  `kubelet_operator_override_is_pristine()` 实现；
- installed-state 与 post-install Gate 改为调用：

```bash
kubelet_default_conffile_is_pristine "$(host_path /etc/default/kubelet)"
```

失败仍按 Stage 40 原逻辑返回 `STOP_VERIFY_FAILED` / 50，不改变状态机与 restart 行为。

- [ ] **Step 7: Stage 50 改为只调用 shared validator**

在 `common.sh` 后 source 新 library；补齐 `path_size()`，并把 `cat`、`md5sum` 加入
Stage 50 required commands。将 `kubelet_pre_init_inputs_gate()` 中 default-file 分支替换为：

```bash
kubelet_default_conffile_is_pristine "$(host_path /etc/default/kubelet)" ||
  complete STOP_ALREADY_INITIALIZED kubelet-operator-override-present "$EXIT_UNKNOWN_STATE" NONE
```

必须复用 `fresh_pre_init_gates` 的三个现有执行点（初始、validate 后、preflight 后），
并在最后一次 config snapshot 复验之后、真正 `kubeadm init` 之前直接再执行一次
shared conffile validator，闭合最后一轮 host/CIDR Gate 内的漂移窗口；不新增缓存变量。
失败继续返回 30，不改变其他 package footprint、listener、manifest、etcd 或 kubeadm
state Gate。

- [ ] **Step 8: 扩展 static scope 并运行完整 focused GREEN**

把 `validate-static.sh` 的 ShellCheck 输入从单个 `lib/common.sh` 扩展为
`scripts/bootstrap/lib/*.sh`，然后运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.CommonLibraryTest.test_kubernetes_stages_share_kubelet_default_validator \
  test_bootstrap.KubeadmInitTest.test_accepts_exact_official_kubelet_default_conffile \
  test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_default_conffile_drift \
  test_bootstrap.KubeadmInitTest.test_regates_official_kubelet_default_conffile_before_init
```

Expected GREEN: `Ran 4 tests`、`OK`、exit 0。

- [ ] **Step 9: 运行 Stage 40/50 受影响回归集**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
  python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_accepts_unmodified_official_kubelet_default_conffile \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubelet_default_conffile_provenance_drift \
  test_bootstrap.KubernetesInstallTest.test_exact_packages_still_reject_kubelet_operator_override \
  test_bootstrap.KubernetesInstallTest.test_allows_secure_kubelet_root_and_empty_operator_override \
  test_bootstrap.KubernetesInstallTest.test_rejects_kubelet_default_conffile_drift_during_validation \
  test_bootstrap.KubernetesInstallTest.test_rechecks_installed_payload_before_kubelet_restart \
  test_bootstrap.KubeadmInitTest.test_check_allows_secure_kubelet_root_and_empty_operator_file \
  test_bootstrap.KubeadmInitTest.test_rejects_official_kubelet_state_footprint_drift \
  test_bootstrap.KubeadmInitTest.test_apply_reruns_complete_gate_set_after_validate_and_preflight
```

Expected: `Ran 9 tests`、`OK`、exit 0。若实际 method 名因当前 main 有精确重命名，只允许映射到语义相同的现有 method，并在报告记录映射；不得删减覆盖。

- [ ] **Step 10: 运行提交前 fast/static 门禁**

```bash
./scripts/validate-fast.sh
./scripts/validate-static.sh
bash -n \
  scripts/bootstrap/lib/kubelet-default.sh \
  scripts/bootstrap/40-install-kubernetes.sh \
  scripts/bootstrap/50-kubeadm-init.sh
shellcheck \
  scripts/bootstrap/lib/*.sh \
  scripts/bootstrap/40-install-kubernetes.sh \
  scripts/bootstrap/50-kubeadm-init.sh
git diff --check
```

所有命令必须 exit 0。按治理约定不在本机重跑完整 Kubernetes/Kubeadm shard 或
`validate.sh`。

- [ ] **Step 11: 独立 review、单一实现提交**

独立 review 必须确认 Critical=0、Important=0，并核对：

- shared validator 没有丢失 Stage 40 的 sentinel/TOCTOU Gate；
- Stage 50 三个 fresh Gate 执行点都真实复验，且最后一次紧邻真正 init；
- missing/empty 合同未变；
- error code 50/30 未串线；
- fixture 负向 mutation 不能绕过 shared function。

若 review 有 finding，逐项 RED→GREEN 后重跑受影响 focused/static。全部 clean 后一次提交所有实现：

```bash
git add \
  scripts/bootstrap/lib/kubelet-default.sh \
  scripts/bootstrap/40-install-kubernetes.sh \
  scripts/bootstrap/50-kubeadm-init.sh \
  scripts/test_bootstrap.py \
  scripts/validate-static.sh
git commit -m 'fix(bootstrap): share kubelet default conffile gate'
git show --check --stat HEAD
```

### Task 4: GitHub 门禁与服务器继续部署

**Files:**
- Verify only: Task 3 commit and GitHub workflow output
- Server state: `/opt/uni-code/engineering-platform-gitops`

- [ ] **Step 1: 普通 push 并等待该 SHA 的 GitHub validation-gate**

```bash
git push origin main
head_sha=$(git rev-parse HEAD)
run_id=
for _ in {1..30}; do
  run_id=$(gh run list --workflow validate.yml --branch main --commit "$head_sha" \
    --limit 1 --json databaseId --jq '.[0].databaseId')
  [[ -z "$run_id" ]] || break
  sleep 10
done
[[ -n "$run_id" ]]
gh run watch "$run_id" --exit-status
printf 'CI_VERIFIED_HEAD_SHA=%s\n' "$head_sha"
printf '%s\n' 'MATERIALIZED_SERVER_PREFIX_BEGIN'
printf "APPROVED_SHA=%s bash <<'EOF'\n" "$head_sha"
printf '%s\n' 'MATERIALIZED_SERVER_PREFIX_END'
```

只有该 SHA 的 gate 全绿后才给服务器同步命令。若 CI 失败，只做 fix-forward，不重写 main 历史。

- [ ] **Step 2: 服务器安全 fast-forward 并先 CHECK**

服务器命令必须把 Step 1 打印的 `CI_VERIFIED_HEAD_SHA` 物化为首行
`APPROVED_SHA=<实际40字符SHA>`（不得保留 `$head_sha`、shell substitution 或从服务器
`origin/main` 动态推导）。Step 1 已打印包含实际 literal 的
`MATERIALIZED_SERVER_PREFIX`；下面 code fence 展示跟在该 prefix 后的 script body。执行
agent 必须把两部分拼成一个完整命令再交付，且检查最终文本不含 `$head_sha`。完整脚本检查
root、repo、origin、main、clean worktree、remote SHA 与 merge 后 local SHA：

```bash
set -Eeuo pipefail
export LC_ALL=C

repo=/opt/uni-code/engineering-platform-gitops
expected=${APPROVED_SHA:?}
expected_origin=git@github-unif-code:unif-code/engineering-platform-gitops.git

[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || { echo 'STOP: invalid approved SHA'; exit 90; }
[[ "$(id -u)" == 0 ]] || { echo 'STOP: must run as root'; exit 91; }
[[ -d "$repo/.git" && ! -L "$repo" ]] || { echo 'STOP: repository is missing or unsafe'; exit 92; }
[[ "$(/usr/bin/git -C "$repo" remote get-url origin)" == "$expected_origin" ]] || { echo 'STOP: unexpected origin'; exit 93; }
[[ "$(/usr/bin/git -C "$repo" branch --show-current)" == main ]] || { echo 'STOP: current branch is not main'; exit 94; }
worktree=$(/usr/bin/git -C "$repo" status --porcelain=v1 --untracked-files=all)
[[ -z "$worktree" ]] || { echo 'STOP: worktree is not clean'; printf '%s\n' "$worktree"; exit 95; }

/usr/bin/git -C "$repo" fetch --prune origin main
[[ "$(/usr/bin/git -C "$repo" rev-parse origin/main)" == "$expected" ]] || { echo 'STOP: origin/main SHA mismatch'; exit 96; }
/usr/bin/git -C "$repo" merge --ff-only origin/main
[[ "$(/usr/bin/git -C "$repo" rev-parse HEAD)" == "$expected" ]] || { echo 'STOP: local HEAD SHA mismatch'; exit 97; }

set +e
"$repo/scripts/bootstrap/bootstrap-all.sh" --check
rc=$?
set -e
echo "COMMAND_EXIT_CODE=$rc"
exit "$rc"
EOF
```

Expected: Stage 50 不再以 `kubelet-operator-override-present` 停止；CHECK 到下一真实状态或返回 apply-required。

- [ ] **Step 3: 用户确认后继续 APPLY**

即使用户已重连，也必须再次把同一个 CI-verified SHA 物化为
`APPROVED_SHA=<实际40字符SHA>`；不得依赖 Step 2 的 shell 变量。APPLY 前重新验证
root、repo、origin、main、clean 与 local HEAD，且不再 fetch 或 merge。与 Step 2 相同，
下面是 script body；交付时必须把首行渲染为包含实际 literal 的
`APPROVED_SHA=<实际40字符SHA> bash <<'EOF'`：

```bash
set -Eeuo pipefail
export LC_ALL=C

repo=/opt/uni-code/engineering-platform-gitops
expected=${APPROVED_SHA:?}
expected_origin=git@github-unif-code:unif-code/engineering-platform-gitops.git

[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || { echo 'STOP: invalid approved SHA'; exit 90; }
[[ "$(id -u)" == 0 ]] || { echo 'STOP: must run as root'; exit 91; }
[[ -d "$repo/.git" && ! -L "$repo" ]] || { echo 'STOP: repository is missing or unsafe'; exit 92; }
[[ "$(/usr/bin/git -C "$repo" remote get-url origin)" == "$expected_origin" ]] || { echo 'STOP: unexpected origin'; exit 93; }
[[ "$(/usr/bin/git -C "$repo" branch --show-current)" == main ]] || { echo 'STOP: current branch is not main'; exit 94; }
worktree=$(/usr/bin/git -C "$repo" status --porcelain=v1 --untracked-files=all)
[[ -z "$worktree" ]] || { echo 'STOP: worktree is not clean'; printf '%s\n' "$worktree"; exit 95; }
[[ "$(/usr/bin/git -C "$repo" rev-parse HEAD)" == "$expected" ]] || { echo 'STOP: local HEAD SHA mismatch'; exit 96; }

set +e
"$repo/scripts/bootstrap/bootstrap-all.sh" --apply
rc=$?
set -e
echo "COMMAND_EXIT_CODE=$rc"
exit "$rc"
EOF
```

Expected: Stage 40 保持 already compliant；Stage 50 在 exact official conffile 下执行批准的 kubeadm sequence，或在下一个独立真实 Stop Gate 精确停止。记录完整 terminal block、exit code 与 evidence SHA，作为下一轮服务器验收输入。
