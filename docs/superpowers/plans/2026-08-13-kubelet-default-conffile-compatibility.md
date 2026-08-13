# kubelet 官方 default conffile 兼容实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Stage 40 严格识别 kubelet `1.36.3-1.1` 未修改的官方 `/etc/default/kubelet` conffile，并从服务器当前已安装、hold、kubelet inactive 的状态安全恢复。

**Architecture:** 保留 `kubelet_operator_override_is_pristine()` 作为唯一入口，把 nonempty 分支收紧为“固定 bytes + 固定 SHA-256 + kubelet 唯一 ownership + 固定 conffile MD5 + 当前文件 MD5”五重绑定。missing 与安全空文件沿用现有快速路径；官方文件只读验真后继续现有 `START_REQUIRED` 状态机，CHECK 零写，APPLY 只 restart/复验，不触发 APT。

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
