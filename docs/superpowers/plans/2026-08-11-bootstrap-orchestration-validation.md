# Bootstrap Orchestration and Layered Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Kubernetes flat APT repository 识别，增加可恢复的一次性 bootstrap 编排，并把本地快速验证与 GitHub 全量门禁分层。

**Architecture:** 保留 `00`～`90` stage scripts 为唯一部署实现，新增薄 `bootstrap-all.sh` 严格消费阶段结果。新增 Python validation catalog/runner 作为 fast profile、full profile 与 GitHub matrix 的单一测试清单，Shell wrappers 只组合测试与静态校验。

**Tech Stack:** Bash 3.2-compatible shell、Python 3.12 standard library `unittest`、PyYAML 6.0.3、ShellCheck 0.9.0、kubectl 1.36.3、GitHub Actions Ubuntu 24.04。

## Global Constraints

- 只修改 `engineering-platform-gitops`，不得触碰同级 frontend、backend 或 docs 仓。
- 本批次已获准直接在 `main` 提交；保持线性历史，普通 push，禁止 force push。
- 当前起点为设计提交 `f042c238abbe0dd1dd67bcfca45cabbd49153ff9`，另有 stage 40 APT 修复及测试两个未提交文件；Task 1 必须先收拢它们。
- 禁止提交 Secret、Token、私钥、kubeconfig 或密码库导出内容；测试只使用明显的 fake/canary 值。
- Image、Chart、Manifest 和 CI 外部工具必须使用精确版本或 digest，禁止 `latest` 与浮动 tag。
- 所有服务器【运维】命令继续遵循“先给完整命令并停止，等待服务器回执”；本计划实施期间不执行服务器 mutation。
- 本地提交前只运行 fast profile 和受影响的 focused tests；完整重型 class 由 GitHub `validation-gate` 运行。
- `scripts/validate.sh` 保持完整顺序验证兼容入口，但不作为本批次每次本地提交的强制命令。
- `bootstrap-all.sh` 不保存进度文件、不执行 git pull/reset、不运行 kubeadm reset，也不复制 stage 内部实现。
- 所有 Bash 新代码保持 macOS `/bin/bash` 3.2 语法兼容；生产执行目标仍为 Ubuntu 24.04。

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `scripts/bootstrap/40-install-kubernetes.sh` | 绑定真实 flat APT Packages target，保留 package 级供应链校验 |
| `scripts/bootstrap/50-kubeadm-init.sh` | 区分 fresh、exact initialized、partial/unknown 三态 |
| `scripts/bootstrap/bootstrap-all.sh` | 顺序调用、结果解析、resume、lock 与非敏感摘要 |
| `scripts/validation_catalog.py` | full shard、fast profile、concrete test class 覆盖的单一事实源 |
| `scripts/run_validation.py` | catalog CLI、matrix 输出与 unittest 执行器 |
| `scripts/validate-static.sh` | manifest validation、依赖检查与 ShellCheck |
| `scripts/validate-fast.sh` | 本地 fast tests + static validation |
| `scripts/validate.sh` | full sequential tests + static validation 兼容入口 |
| `.github/workflows/validate.yml` | Ubuntu 24.04 动态 matrix、static job 与 `validation-gate` |
| `scripts/test_bootstrap.py` | flat APT、kubeadm idempotency、orchestrator 行为测试 |
| `scripts/test_validate.py` | catalog、wrappers、workflow 与文档合同测试 |
| `AGENTS.md` | 本地 fast 与 push 后 GitHub gate 治理规则 |
| `README.md` | fast/full/CI 使用说明 |
| `runbook/01-bootstrap.md` | 一次性 check/apply、恢复语义与单阶段应急入口 |

---

### Task 1: 收拢 Flat APT Repository 修复

**Files:**
- Modify: `scripts/bootstrap/40-install-kubernetes.sh:366-383`
- Modify: `scripts/test_bootstrap.py:3125-3155,4095-4117`

**Interfaces:**
- Consumes: APT 2.8.3 `indextargets` 的 `IDENTIFIER`、`URI`、`FILENAME`。
- Produces: `bound_packages_index(apt_config: str) -> stdout path / nonzero`；调用方继续使用返回的唯一 private Packages 文件。

- [x] **Step 1: 写入真实 flat repository shape 的失败测试**

测试已经加入 `KubernetesInstallTest.test_apply_accepts_real_flat_repository_indextarget_shape`，fixture 在旧六字段请求下返回：

```text
Packages|https://pkgs.k8s.io/core:/stable:/v1.36/deb/Packages|$(SUITE)|$(COMPONENT)|$(ARCHITECTURE)|/private/lists/kubernetes_Packages
```

- [x] **Step 2: 观察 RED 并确认失败类别**

已观察旧实现返回 `20 / STOP_SUPPLY_CHAIN_MISMATCH / packages-index-provenance-invalid`；fixture setup 无错误。

- [x] **Step 3: 实现最小三字段绑定**

生产实现已经改为：

```bash
output=$(APT_CONFIG="$apt_config" apt-get indextargets \
  --format '$(IDENTIFIER)|$(URI)|$(FILENAME)' 2>/dev/null) || return 1
IFS='|' read -r identifier uri filename extra <<<"$line"
[[ -z "$extra" && "$identifier" == Packages &&
   "$uri" == "${REPOSITORY_URL}Packages" ]] || return 1
```

Packages 文件的 private path、regular/non-symlink、mode、owner 与 package stanza 校验保持原样。

- [x] **Step 4: 运行 focused 与完整 class GREEN**

已取得以下未再修改生产代码后的证据：

```text
related focused tests: 5 tests / 123.608s / OK
KubernetesInstallTest: 40 tests / 958.491s / OK
ShellCheck bootstrap scripts: exit 0
git diff --check: exit 0
```

- [ ] **Step 5: 重新运行最小回归确认当前 diff 未漂移**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_accepts_real_flat_repository_indextarget_shape \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_second_packages_indextarget
```

Expected: `Ran 2 tests`，`OK`。

- [ ] **Step 6: 提交独立 bugfix**

```bash
git add scripts/bootstrap/40-install-kubernetes.sh scripts/test_bootstrap.py
git diff --cached --check
git commit -m "fix(bootstrap): accept canonical flat apt index"
```

Expected: commit 只包含上述两个文件。

---

### Task 2: 建立 Validation Catalog、Runner 与 Fast Profile

**Files:**
- Create: `scripts/validation_catalog.py`
- Create: `scripts/run_validation.py`
- Create: `scripts/validate-static.sh`
- Create: `scripts/validate-fast.sh`
- Modify: `scripts/validate.sh`
- Modify: `scripts/test_validate.py:297-386`

**Interfaces:**
- Produces: `validation_catalog.SHARDS: dict[str, tuple[str, ...]]`。
- Produces: `validation_catalog.FAST_SHARDS: tuple[str, ...]`。
- Produces: `validate_catalog() -> None`、`selectors_for_profile(name) -> tuple[str, ...]`、`selectors_for_shard(name) -> tuple[str, ...]`、`matrix_document() -> dict[str, list[dict[str, str]]]`。
- Produces CLI: `run_validation.py --profile {fast,full}`、`--shard NAME`、`--matrix`、`--validate-catalog`。
- Consumed by: local wrappers and Task 3 GitHub Actions。

- [ ] **Step 1: 写 catalog 与 wrapper 的 RED tests**

在 `scripts/test_validate.py` 新增 `ValidationCatalogTest`。imports 必须放在 test method 内，使缺文件表现为预期 RED，而不是 test module loader error：

```python
class ValidationCatalogTest(unittest.TestCase):
    def test_catalog_covers_every_concrete_test_case_once(self) -> None:
        import validation_catalog

        validation_catalog.validate_catalog()

    def test_fast_profile_excludes_heavy_bootstrap_classes(self) -> None:
        import validation_catalog

        selectors = set(validation_catalog.selectors_for_profile('fast'))
        heavy = {
            'test_bootstrap.ArtifactStageTest',
            'test_bootstrap.KernelStageTest',
            'test_bootstrap.ContainerdInstallTest',
            'test_bootstrap.KubernetesInstallTest',
            'test_bootstrap.KubeadmInitTest',
            'test_bootstrap.CiliumInstallTest',
            'test_bootstrap.FinalVerifyTest',
        }
        self.assertTrue(selectors)
        self.assertTrue(selectors.isdisjoint(heavy))

    def test_catalog_rejects_missing_and_duplicate_selectors(self) -> None:
        import validation_catalog
        from unittest import mock

        missing = dict(validation_catalog.SHARDS)
        missing['contracts'] = missing['contracts'][1:]
        with mock.patch.object(validation_catalog, 'SHARDS', missing):
            with self.assertRaisesRegex(ValueError, 'missing'):
                validation_catalog.validate_catalog()

        duplicate = dict(validation_catalog.SHARDS)
        duplicate['artifacts'] = (
            *duplicate['artifacts'], duplicate['contracts'][0]
        )
        with mock.patch.object(validation_catalog, 'SHARDS', duplicate):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                validation_catalog.validate_catalog()
```

扩展 `ValidateEntrypointTest`，让 temp fixture 复制五个 validation entry，并断言：

```python
self.assertIn('run_validation.py\t--profile\tfast', command_log)
self.assertIn('run_validation.py\t--profile\tfull', command_log)
self.assertNotIn('--apply', command_log)
```

- [ ] **Step 2: 运行 RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_validate.ValidationCatalogTest \
  test_validate.ValidateEntrypointTest
```

Expected: FAIL，原因只包括 `validation_catalog`、`run_validation.py`、`validate-fast.sh` 或 `validate-static.sh` 尚不存在/未被调用。

- [ ] **Step 3: 实现 catalog 的精确 shard 清单**

`scripts/validation_catalog.py` 以以下数据为唯一清单：

```python
SHARD_ORDER = (
    'contracts', 'artifacts', 'kernel', 'containerd',
    'kubernetes', 'kubeadm', 'cilium', 'final-verify',
)

SHARDS = {
    'contracts': (
        'test_validate.ProfileValidationTest',
        'test_validate.RepositoryProfileContractTest',
        'test_validate.ActiveRootIsolationTest',
        'test_validate.BootstrapContractTest',
        'test_validate.ValidateEntrypointTest',
        'test_validate.ValidationCatalogTest',
        'test_bootstrap.CommonLibraryTest',
        'test_bootstrap.CidrCheckTest',
        'test_bootstrap.PreflightTest',
        'test_bootstrap.BootstrapEntrySecurityTest',
    ),
    'artifacts': ('test_bootstrap.ArtifactStageTest',),
    'kernel': ('test_bootstrap.KernelStageTest',),
    'containerd': ('test_bootstrap.ContainerdInstallTest',),
    'kubernetes': ('test_bootstrap.KubernetesInstallTest',),
    'kubeadm': ('test_bootstrap.KubeadmInitTest',),
    'cilium': ('test_bootstrap.CiliumInstallTest',),
    'final-verify': ('test_bootstrap.FinalVerifyTest',),
}

FAST_SHARDS = ('contracts',)
```

实现动态覆盖校验：

```python
def discover_concrete_test_cases() -> tuple[str, ...]:
    loader = unittest.defaultTestLoader
    discovered: list[str] = []
    for module_name in ('test_validate', 'test_bootstrap'):
        module = importlib.import_module(module_name)
        for class_name, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate.__module__ != module_name:
                continue
            if not issubclass(candidate, unittest.TestCase):
                continue
            if not loader.getTestCaseNames(candidate):
                continue
            discovered.append(f'{module_name}.{class_name}')
    return tuple(sorted(discovered))


def validate_catalog() -> None:
    assigned = [selector for name in SHARD_ORDER for selector in SHARDS[name]]
    counts = collections.Counter(assigned)
    duplicate = sorted(name for name, count in counts.items() if count != 1)
    discovered = set(discover_concrete_test_cases())
    unknown = sorted(set(assigned) - discovered)
    missing = sorted(discovered - set(assigned))
    empty = sorted(name for name in SHARD_ORDER if not SHARDS.get(name))
    if duplicate or unknown or missing or empty or set(SHARDS) != set(SHARD_ORDER):
        raise ValueError(
            f'catalog invalid: duplicate={duplicate}; unknown={unknown}; '
            f'missing={missing}; empty={empty}'
        )
```

`selectors_for_profile('full')` 按 `SHARD_ORDER` 展平；`fast` 只展平 `FAST_SHARDS`。未知 profile/shard 必须抛 `ValueError`。

- [ ] **Step 4: 实现 runner CLI**

`scripts/run_validation.py` 必须先调用 `validate_catalog()`，再执行请求：

```python
def run_selectors(selectors: tuple[str, ...]) -> int:
    loader = unittest.defaultTestLoader
    suite = loader.loadTestsFromNames(list(selectors))
    if loader.errors:
        for error in loader.errors:
            print(error, file=sys.stderr)
        return 2
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def matrix_document() -> dict[str, list[dict[str, str]]]:
    return {'include': [{'shard': name} for name in SHARD_ORDER]}
```

`matrix_document()` 位于 `validation_catalog.py`；`run_validation.py --matrix` 只负责调用并用 `json.dumps(..., separators=(',', ':'))` 输出单行 JSON。

CLI 规则：

```text
--profile fast|full  运行 profile
--shard NAME         运行一个精确 shard
--matrix             单行 JSON 输出 matrix
--validate-catalog   只校验目录
```

这四种操作必须互斥；无参数或组合参数返回 argparse exit `2`。

- [ ] **Step 5: 拆分 static 与 wrapper**

`scripts/validate-static.sh` 顺序执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import yaml'
PYTHONDONTWRITEBYTECODE=1 python3 "$repo_root/scripts/validate.py"
shellcheck \
  "$repo_root/scripts/bootstrap/lib/common.sh" \
  "$repo_root"/scripts/bootstrap/*.sh
```

它在运行前逐个检查 `python3`、`kubectl`、`shellcheck`；任一缺失立即非零退出。

`scripts/validate-fast.sh`：

```bash
PYTHONDONTWRITEBYTECODE=1 \
  python3 "$repo_root/scripts/run_validation.py" --profile fast
"$repo_root/scripts/validate-static.sh"
```

`scripts/validate.sh` 保持 full compatibility：

```bash
PYTHONDONTWRITEBYTECODE=1 \
  python3 "$repo_root/scripts/run_validation.py" --profile full
"$repo_root/scripts/validate-static.sh"
```

所有四个 entry 文件设置 executable bit。

- [ ] **Step 6: 运行 GREEN 与时间 Gate**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_validate.ValidationCatalogTest \
  test_validate.ValidateEntrypointTest
python3 scripts/run_validation.py --validate-catalog
/usr/bin/time -p ./scripts/validate-fast.sh
```

Expected: tests `OK`；catalog exit `0`；fast exit `0`，`real` 目标小于 `120` 秒。

- [ ] **Step 7: 静态检查并提交**

```bash
shellcheck scripts/validate.sh scripts/validate-fast.sh scripts/validate-static.sh
git diff --check
git add \
  scripts/validation_catalog.py \
  scripts/run_validation.py \
  scripts/validate-static.sh \
  scripts/validate-fast.sh \
  scripts/validate.sh \
  scripts/test_validate.py
git commit -m "refactor(validation): split fast and full profiles"
```

---

### Task 3: 增加 GitHub Actions Full Validation Gate

**Files:**
- Create: `.github/workflows/validate.yml`
- Modify: `scripts/test_validate.py` (`ValidationCatalogTest`)

**Interfaces:**
- Consumes: `python3 scripts/run_validation.py --matrix` 和 `--shard NAME`。
- Produces: GitHub check `validation-gate`。
- Pinned checkout: `actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10` (`v6.0.3`)。
- Pinned kubectl: `v1.36.3`, linux/amd64 SHA-256 `ebbd080e7c2e275093b55915722043257eb24004363e20acb3c4d71919f88336`。

- [ ] **Step 1: 写 workflow contract RED test**

在 `ValidationCatalogTest` 增加：

```python
def test_github_workflow_has_dynamic_full_gate(self) -> None:
    workflow_path = validator.ROOT / '.github/workflows/validate.yml'
    self.assertTrue(workflow_path.is_file())
    document = yaml.load(
        workflow_path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader
    )
    self.assertEqual(document['permissions'], {'contents': 'read'})
    self.assertEqual(
        set(document['jobs']), {'plan', 'tests', 'static', 'validation-gate'}
    )
    self.assertEqual(
        set(document['jobs']['validation-gate']['needs']),
        {'plan', 'tests', 'static'},
    )
    workflow_text = workflow_path.read_text(encoding='utf-8')
    self.assertIn('fromJSON(needs.plan.outputs.matrix)', workflow_text)
    self.assertIn(
        'actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10',
        workflow_text,
    )
    self.assertNotRegex(workflow_text, r'uses:\s+[^\s]+@(main|master|v\d+)\s*$')
```

另断言 trigger 含 `push.main`、`pull_request.main`、`workflow_dispatch`，所有执行 job 使用 `ubuntu-24.04`，tests 有 `fail-fast: false` 和 `timeout-minutes: 45`。

- [ ] **Step 2: 运行 RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_validate.ValidationCatalogTest.test_github_workflow_has_dynamic_full_gate
```

Expected: FAIL，原因是 `.github/workflows/validate.yml` 不存在。

- [ ] **Step 3: 实现 workflow header、plan 与 tests jobs**

`.github/workflows/validate.yml` 的固定头部：

```yaml
name: validate

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

每个 checkout step 使用：

```yaml
- uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6.0.3
  with:
    persist-credentials: false
```

`plan` 使用以下精确步骤创建 venv、安装 `PyYAML==6.0.3` 并让后续 step 使用该 Python：

```yaml
- name: Install Python validation dependency
  run: |
    python3 -m venv "$RUNNER_TEMP/validation-venv"
    "$RUNNER_TEMP/validation-venv/bin/python" -m pip install \
      --disable-pip-version-check PyYAML==6.0.3
    echo "$RUNNER_TEMP/validation-venv/bin" >>"$GITHUB_PATH"
```

随后执行 catalog 校验，并通过单行 JSON 写 `$GITHUB_OUTPUT`：

```yaml
- id: matrix
  run: echo "matrix=$(python3 scripts/run_validation.py --matrix)" >>"$GITHUB_OUTPUT"
```

`tests` 使用：

```yaml
needs: plan
strategy:
  fail-fast: false
  matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}
timeout-minutes: 45
```

安装同一 `PyYAML==6.0.3` 后执行：

```yaml
- run: python3 scripts/run_validation.py --shard "${{ matrix.shard }}"
  env:
    PYTHONDONTWRITEBYTECODE: "1"
```

- [ ] **Step 4: 实现 static job 的精确工具链**

`static` 安装并验证：

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends shellcheck=0.9.0-1
test "$(shellcheck --version | awk '/^version:/ {print $2}')" = 0.9.0
curl --fail --location --silent --show-error \
  --output "$RUNNER_TEMP/kubectl" \
  https://dl.k8s.io/release/v1.36.3/bin/linux/amd64/kubectl
printf '%s  %s\n' \
  ebbd080e7c2e275093b55915722043257eb24004363e20acb3c4d71919f88336 \
  "$RUNNER_TEMP/kubectl" | sha256sum --check --status
install -d "$RUNNER_TEMP/bin"
install -m 0755 "$RUNNER_TEMP/kubectl" "$RUNNER_TEMP/bin/kubectl"
echo "$RUNNER_TEMP/bin" >>"$GITHUB_PATH"
```

下一 step 执行 `./scripts/validate-static.sh`。不使用任何 repository Secret。

- [ ] **Step 5: 实现总 Gate**

`validation-gate` 必须无条件汇总：

```yaml
validation-gate:
  if: ${{ always() }}
  needs: [plan, tests, static]
  runs-on: ubuntu-24.04
  steps:
    - name: Require every validation job
      env:
        PLAN_RESULT: ${{ needs.plan.result }}
        TESTS_RESULT: ${{ needs.tests.result }}
        STATIC_RESULT: ${{ needs.static.result }}
      run: |
        test "$PLAN_RESULT" = success
        test "$TESTS_RESULT" = success
        test "$STATIC_RESULT" = success
```

- [ ] **Step 6: 运行 workflow contract GREEN**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v test_validate.ValidationCatalogTest
python3 scripts/run_validation.py --matrix
git diff --check
```

Expected: tests `OK`；matrix 为单行、包含八个 shard；diff check exit `0`。

- [ ] **Step 7: 提交 CI**

```bash
git add .github/workflows/validate.yml scripts/test_validate.py
git commit -m "ci(validation): shard full bootstrap tests"
```

---

### Task 4: 让 Kubeadm Stage 严格识别已初始化状态

**Files:**
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:102-126,240-319,350-454`
- Modify: `scripts/test_bootstrap.py:4373-5298`

**Interfaces:**
- Produces: `root_is_safe_directory(path, expected_mode) -> boolean`、`root_is_missing_or_safe_empty(path) -> boolean`。
- Produces: `initialization_state() -> FRESH | CANDIDATE | UNKNOWN` on stdout。
- Produces: `initialized_control_plane_gate(result: str, code: int) -> exit via complete on drift`。
- Changes: `50-kubeadm-init.sh --check|--apply` on exact initialized host returns `ALREADY_COMPLIANT` with reason `control-plane-initialized` and no new evidence。

- [ ] **Step 1: 写 exact initialized 与 drift RED tests**

让 fake kubeadm 成功 init 时同时创建 API listener marker：

```sh
: >"$FAKE_LISTENER_MARKER"
```

新增测试：

```python
def test_exact_initialized_state_is_already_compliant_and_zero_write(self) -> None:
    environment, host, command_log = self.make_environment()
    applied = self.run_stage(environment, '--apply')
    self.assertEqual(applied.returncode, 0, applied.stderr)
    before = self.tree_snapshot(host)
    command_log.write_text('', encoding='utf-8')

    checked = self.run_stage(environment, '--check')

    self.assertEqual(checked.returncode, 0, checked.stderr)
    self.assertIn('RESULT=ALREADY_COMPLIANT', checked.stdout)
    self.assertIn('REASON=control-plane-initialized', checked.stdout)
    self.assertEqual(self.tree_snapshot(host), before)
    self.assertNotIn('kubeadm init', command_log.read_text(encoding='utf-8'))

def test_apply_on_exact_initialized_state_never_reinitializes(self) -> None:
    environment, _, command_log = self.make_environment()
    self.assertEqual(self.run_stage(environment, '--apply').returncode, 0)
    command_log.write_text('', encoding='utf-8')

    repeated = self.run_stage(environment, '--apply')

    self.assertEqual(repeated.returncode, 0, repeated.stderr)
    self.assertIn('RESULT=ALREADY_COMPLIANT', repeated.stdout)
    self.assertNotIn('kubeadm init', command_log.read_text(encoding='utf-8'))
```

增加完整 drift test：

```python
def test_initialized_candidate_drift_stops_unknown(self) -> None:
    for case in ('listener', 'manifest', 'runtime', 'kube-proxy'):
        with self.subTest(case=case):
            environment, host, command_log = self.make_environment()
            applied = self.run_stage(environment, '--apply')
            self.assertEqual(applied.returncode, 0, applied.stderr)
            command_log.write_text('', encoding='utf-8')
            if case == 'listener':
                Path(environment['FAKE_LISTENER_MARKER']).unlink()
            elif case == 'manifest':
                unknown = host / 'etc/kubernetes/manifests/unknown.yaml'
                unknown.write_text('unknown\n', encoding='utf-8')
                unknown.chmod(0o600)
            elif case == 'runtime':
                payload = json.loads(environment['FAKE_CRICTL_JSON'])
                payload['containers'].pop()
                environment['FAKE_CRICTL_JSON'] = json.dumps(payload)
            else:
                environment['FAKE_KUBE_PROXY_DAEMONSET'] = (
                    'daemonset.apps/kube-proxy\n'
                )

            checked = self.run_stage(environment, '--check')

            self.assertEqual(checked.returncode, 30, checked.stderr)
            self.assertIn('RESULT=STOP_UNKNOWN_STATE', checked.stdout)
            self.assertNotIn('PASS_KUBEADM_CHECK', checked.stdout)
            self.assertNotIn('kubeadm init', command_log.read_text(encoding='utf-8'))
```

- [ ] **Step 2: 运行 RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write \
  test_bootstrap.KubeadmInitTest.test_apply_on_exact_initialized_state_never_reinitializes \
  test_bootstrap.KubeadmInitTest.test_initialized_candidate_drift_stops_unknown
```

Expected: FAIL；旧实现把已生成 `/etc/kubernetes`、`/var/lib/etcd` 判为 `STOP_ALREADY_INITIALIZED`。

- [ ] **Step 3: 把初始化形态判断改为三态**

用以下两个精确 helper 保留 root type/mode/owner 与空目录 Gate：

```bash
root_is_safe_directory() {
  local root=$1 expected_mode=$2
  [[ -d "$root" && ! -L "$root" &&
     "$(path_mode "$root")" == "$expected_mode" ]] &&
    owned_by_expected "$root"
}

root_is_missing_or_safe_empty() {
  local root=$1 first_entry
  if [[ ! -e "$root" && ! -L "$root" ]]; then
    return 0
  fi
  root_is_safe_directory "$root" 755 || return 1
  first_entry=$(find "$root" -mindepth 1 -print -quit 2>/dev/null) || return 1
  [[ -z "$first_entry" ]]
}
```

再用 `initialization_state()` 替换当前直接 `complete` 的 `initialization_state_gate()`：

```bash
initialization_state() {
  local kubernetes_root etcd_root listener
  kubernetes_root=$(host_path /etc/kubernetes)
  etcd_root=$(host_path /var/lib/etcd)
  listener=$(ss -H -ltn 'sport = :6443' 2>/dev/null) || return "$EXIT_PRECONDITION"

  if root_is_missing_or_safe_empty "$kubernetes_root" &&
     root_is_missing_or_safe_empty "$etcd_root" &&
     [[ -z "$listener" ]]; then
    printf 'FRESH\n'
    return 0
  fi
  if root_is_safe_directory "$kubernetes_root" 755 &&
     root_is_safe_directory "$etcd_root" 700 &&
     [[ -f "${kubernetes_root}/admin.conf" &&
        -d "${kubernetes_root}/manifests" &&
        -d "${etcd_root}/member" && -n "$listener" ]]; then
    printf 'CANDIDATE\n'
    return 0
  fi
  printf 'UNKNOWN\n'
}
```

`root_is_missing_or_safe_empty` 的任何读取失败都会使状态落入 UNKNOWN；broken symlink 也属于 UNKNOWN。fresh 安全空目录保持 `0755`；精确已初始化状态要求 `/etc/kubernetes=0755`、`/var/lib/etcd=0700`。fake kubeadm 成功创建 `member` 后也必须把 fake `/var/lib/etcd` 设为 `0700`，使 fixture 与生产合同一致。

- [ ] **Step 4: 抽取并复用 initialized control-plane Gate**

把现有 post-init lines 383-437 的 admin.conf、exact four manifests、etcd member、kubelet active、crictl four containers、kube-proxy absence、certificate/SAN/checkend 校验移动到：

```bash
initialized_control_plane_gate() {
  local failure_result=$1 failure_code=$2 listener

  managed_kubernetes_clients_gate
  host_and_dependency_gates
  config_file_is_safe "$config_source" 644 ||
    complete "$failure_result" kubeadm-config-contract-drift "$failure_code" NONE

  listener=$(ss -H -ltn 'sport = :6443' 2>/dev/null) ||
    complete "$failure_result" apiserver-listener-state-unreadable \
      "$failure_code" NONE
  [[ -n "$listener" ]] ||
    complete "$failure_result" apiserver-listener-missing "$failure_code" NONE
}
```

上述 listener Gate 后，把当前 lines 383-437 的代码原样移入同一函数，只做以下机械替换，不删除任何检查：

| Existing check | Retained failure reason |
| --- | --- |
| admin.conf regular/root/0600 | `admin-conf-metadata-drift` |
| exact four static manifests + metadata | `static-manifest-state-unreadable` / `static-manifest-set-drift` / per-component drift |
| etcd member | `etcd-member-missing` |
| kubelet active | `kubelet-inactive` |
| crictl/kubectl metadata | `post-init-client-unsafe` / owner drift |
| exact four Running control-plane containers | `control-plane-runtime-query-failed` / set drift |
| kube-proxy DS/Pod/ConfigMap absent | existing three kube-proxy failure reasons |
| apiserver cert checkend/SAN/subject/expiry | existing certificate failure reasons |

每个原 `complete STOP_VERIFY_FAILED ... "$EXIT_VERIFY_FAILED"` 改为 `complete "$failure_result" ... "$failure_code"`。`admin_conf`、`certificate_subject`、`certificate_expiry` 保持主流程可见变量，使 apply 成功 evidence 继续使用原值。

这里不是新增宽松路径：原有每一项 post-init Gate 都必须保留，另加入 API `6443` listener 必须非空。

- [ ] **Step 5: 接入 fresh/candidate 主流程**

主流程必须是：

```bash
state=$(initialization_state) ||
  complete STOP_PRECONDITION initialized-state-unreadable "$EXIT_PRECONDITION" NONE
case "$state" in
  FRESH)
    fresh_pre_init_gates
    ;;
  CANDIDATE)
    initialized_control_plane_gate STOP_UNKNOWN_STATE "$EXIT_UNKNOWN_STATE"
    complete ALREADY_COMPLIANT control-plane-initialized 0 \
      '60-install-cilium.sh --check'
    ;;
  UNKNOWN)
    complete STOP_ALREADY_INITIALIZED initialized-or-partial-state-present \
      "$EXIT_UNKNOWN_STATE" NONE
    ;;
esac
```

`fresh_pre_init_gates` 的完整定义为：

```bash
fresh_pre_init_gates() {
  local current_state
  current_state=$(initialization_state) ||
    complete STOP_PRECONDITION initialized-state-unreadable \
      "$EXIT_PRECONDITION" NONE
  [[ "$current_state" == FRESH ]] ||
    complete STOP_ALREADY_INITIALIZED initialized-or-partial-state-present \
      "$EXIT_UNKNOWN_STATE" NONE
  kubelet_pre_init_inputs_gate
  managed_kubernetes_clients_gate
  config_file_is_safe "$config_source" 644 ||
    complete STOP_PRECONDITION kubeadm-config-contract-drift \
      "$EXIT_PRECONDITION" NONE
  if [[ -n "$config_snapshot" ]]; then
    config_file_is_safe "$config_snapshot" 600 ||
      complete STOP_UNKNOWN_STATE kubeadm-config-snapshot-drift \
        "$EXIT_UNKNOWN_STATE" NONE
  fi
  host_and_dependency_gates
}
```

成功 init 后使用同一 `initialized_control_plane_gate STOP_VERIFY_FAILED "$EXIT_VERIFY_FAILED"`，通过后才开 evidence。

- [ ] **Step 6: 运行 GREEN 与旧边界回归**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write \
  test_bootstrap.KubeadmInitTest.test_apply_on_exact_initialized_state_never_reinitializes \
  test_bootstrap.KubeadmInitTest.test_initialized_candidate_drift_stops_unknown \
  test_bootstrap.KubeadmInitTest.test_check_rejects_any_initialized_or_partial_state \
  test_bootstrap.KubeadmInitTest.test_init_failure_does_not_leak_raw_output_or_claim_success \
  test_bootstrap.KubeadmInitTest.test_apply_uses_only_fixed_config_sequence_and_redacts_raw_output
shellcheck scripts/bootstrap/50-kubeadm-init.sh
```

Expected: focused tests `OK`；ShellCheck 无 diagnostics。

- [ ] **Step 7: 提交 kubeadm resume 合同**

```bash
git add scripts/bootstrap/50-kubeadm-init.sh scripts/test_bootstrap.py
git diff --cached --check
git commit -m "feat(bootstrap): make kubeadm init resumable"
```

---

### Task 5: 实现一次性 Bootstrap Orchestrator

**Files:**
- Create: `scripts/bootstrap/bootstrap-all.sh`
- Modify: `scripts/test_bootstrap.py` (new `BootstrapOrchestratorTest`)
- Modify: `scripts/validation_catalog.py` (`contracts` shard)

**Interfaces:**
- CLI: `bootstrap-all.sh --check|--apply`，其他参数 exit `10`。
- Produces check stop: `PASS_BOOTSTRAP_CHECK / apply-required / NEXT_STAGE=<NN>`。
- Produces check complete: `PASS_BOOTSTRAP_ALL_CHECK`。
- Produces apply complete: `PASS_BOOTSTRAP_ALL`。
- Produces malformed-output stop: orchestrator exit `30`。
- Consumes only exact stage RESULT table from approved design spec。
- Produces helpers: `stage_path(stage) -> absolute path`、`check_result_is_complete(stage,result) -> bool`、`check_result_requires_apply(stage,result) -> bool`、`apply_result_is_success(stage,result) -> bool`。
- Produces terminal helpers: `finish_orchestrator(result,reason,code,next_stage)` and `stop_orchestrator(reason,code)`。
- Produces per-stage summary fields: `STAGE_<NN>_RESULT`、`STAGE_<NN>_EVIDENCE`、`STAGE_<NN>_SHA256`。

- [ ] **Step 1: 写 fake-stage RED test harness**

新增 `BootstrapOrchestratorTest`，fixture 创建 `00`～`90` fake scripts。每个 mutating fake stage：

```sh
if [ "$1" = --check ]; then
  if [ -f "$ORCHESTRATOR_STATE_DIR/$stage" ]; then
    result=ALREADY_COMPLIANT
    reason=stage-ready
  else
    result="$check_result"
    reason=apply-required
  fi
else
  : >"$ORCHESTRATOR_STATE_DIR/$stage"
  result="$apply_result"
  reason=stage-ready
fi
printf 'PHASE=%s\nMODE=%s\nRESULT=%s\nREASON=%s\nEVIDENCE=NONE\nEXIT_CODE=0\nNEXT=NONE\nSHA256=NONE\n' \
  "$stage" "$mode" "$result" "$reason"
```

fixture 同时写 command log，并提供 fake `git`、`flock`。测试环境只通过以下 test seam 注入：

```text
BOOTSTRAP_ORCHESTRATOR_TEST_MODE=1
BOOTSTRAP_ORCHESTRATOR_TEST_STAGE_DIR=str(self.stage_dir)
BOOTSTRAP_ORCHESTRATOR_TEST_LOCK_FILE=str(self.lock_file)
```

生产模式必须拒绝所有 `BOOTSTRAP_ORCHESTRATOR_TEST_*`。
测试模式只能在 `EUID != 0` 时启用，且注入的 stage directory、state directory 与 lock path 必须是 absolute、non-symlink、当前 uid 所有的临时路径；这个 seam 仅用于 fixture，不能放宽生产 `--apply` 的 root Gate。

- [ ] **Step 2: 写核心 RED cases**

新增以下四个核心 test methods：

```python
def test_check_stops_read_only_at_first_apply_required_stage(self) -> None:
    result = self.run_orchestrator('--check')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('RESULT=PASS_BOOTSTRAP_CHECK', result.stdout)
    self.assertIn('NEXT_STAGE=10', result.stdout)
    self.assertEqual(list(self.state_dir.iterdir()), [])

def test_apply_resumes_at_40_and_reaches_final_verify(self) -> None:
    for stage in ('10', '20', '30'):
        (self.state_dir / stage).touch()
    result = self.run_orchestrator('--apply')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('RESULT=PASS_BOOTSTRAP_ALL', result.stdout)
    log = self.command_log.read_text(encoding='utf-8')
    self.assertNotIn('10 --apply', log)
    self.assertNotIn('20 --apply', log)
    self.assertNotIn('30 --apply', log)
    self.assertIn('40 --apply', log)

def test_nonzero_stage_exit_is_preserved(self) -> None:
    self.environment['FAKE_STAGE_STOP'] = '40:20'
    result = self.run_orchestrator('--apply')
    self.assertEqual(result.returncode, 20)

def test_zero_exit_with_malformed_result_stops_unknown(self) -> None:
    self.environment['FAKE_STAGE_MALFORMED'] = '40:duplicate-result'
    result = self.run_orchestrator('--apply')
    self.assertEqual(result.returncode, 30)
    self.assertIn('RESULT=STOP_ORCHESTRATOR', result.stdout)
```

其余边界用以下两个 table-driven tests 覆盖：

```python
def test_structured_output_and_postcheck_fail_closed(self) -> None:
    cases = (
        ('FAKE_POSTCHECK_STALE', '40', 'post-apply-check-not-compliant'),
        ('FAKE_STAGE_MALFORMED', '40:exit-mismatch', 'invalid-stage-output'),
        ('FAKE_STAGE_MALFORMED', '40:unknown-result', 'invalid-stage-result'),
    )
    for variable, value, reason in cases:
        with self.subTest(variable=variable, value=value):
            self.reset_fixture()
            self.environment[variable] = value
            result = self.run_orchestrator('--apply')
            self.assertEqual(result.returncode, 30)
            self.assertIn('RESULT=STOP_ORCHESTRATOR', result.stdout)
            self.assertIn(f'REASON={reason}', result.stdout)

def test_apply_requires_main_clean_repo_and_exclusive_lock(self) -> None:
    cases = (
        ('FAKE_GIT_BRANCH', 'feature', 'current-branch-not-main'),
        ('FAKE_GIT_DIRTY', '1', 'worktree-not-clean'),
        ('FAKE_FLOCK_FAIL', '1', 'concurrent-run'),
    )
    for variable, value, reason in cases:
        with self.subTest(variable=variable):
            self.reset_fixture()
            self.environment[variable] = value
            result = self.run_orchestrator('--apply')
            self.assertEqual(result.returncode, 30)
            self.assertIn(f'REASON={reason}', result.stdout)

def test_check_all_complete_reaches_final_verify(self) -> None:
    for stage in ('10', '20', '30', '40', '50', '60'):
        (self.state_dir / stage).touch()
    result = self.run_orchestrator('--check')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('RESULT=PASS_BOOTSTRAP_ALL_CHECK', result.stdout)
    self.assertIn('90 --check', self.command_log.read_text(encoding='utf-8'))
```

- [ ] **Step 3: 运行 RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v test_bootstrap.BootstrapOrchestratorTest
```

Expected: loader FAIL，原因是 `scripts/bootstrap/bootstrap-all.sh` 不存在。

- [ ] **Step 4: 实现入口安全、stage map 与 strict parser**

脚本固定数组：

```bash
readonly -a STAGES=(00 10 20 30 40 50 60 90)
readonly -a MUTATING_STAGES=(10 20 30 40 50 60)
```

`stage_path` 使用以下 exact case，禁止从 `NEXT` 拼接命令：

```bash
stage_path() {
  case "$1" in
    00) printf '%s/00-preflight.sh\n' "$stage_dir" ;;
    10) printf '%s/10-stage-artifacts.sh\n' "$stage_dir" ;;
    20) printf '%s/20-prepare-kernel.sh\n' "$stage_dir" ;;
    30) printf '%s/30-install-containerd.sh\n' "$stage_dir" ;;
    40) printf '%s/40-install-kubernetes.sh\n' "$stage_dir" ;;
    50) printf '%s/50-kubeadm-init.sh\n' "$stage_dir" ;;
    60) printf '%s/60-install-cilium.sh\n' "$stage_dir" ;;
    90) printf '%s/90-verify.sh\n' "$stage_dir" ;;
    *) return 30 ;;
  esac
}
```

三类结果 helper 使用完整 allowlist：

```bash
check_result_is_complete() {
  case "$1:$2" in
    00:PASS_PREFLIGHT|10:ALREADY_COMPLIANT|20:ALREADY_COMPLIANT|\
    30:ALREADY_COMPLIANT|40:ALREADY_COMPLIANT|50:ALREADY_COMPLIANT|\
    60:ALREADY_COMPLIANT|90:PASS_BOOTSTRAP_VERIFIED) return 0 ;;
    *) return 1 ;;
  esac
}

check_result_requires_apply() {
  case "$1:$2" in
    10:PASS_ARTIFACTS_CHECK|20:PASS_KERNEL_CHECK|\
    30:PASS_CONTAINERD_CHECK|40:PASS_KUBERNETES_CHECK|\
    50:PASS_KUBEADM_CHECK|60:PASS_CILIUM_CHECK) return 0 ;;
    *) return 1 ;;
  esac
}

apply_result_is_success() {
  case "$1:$2" in
    10:PASS_ARTIFACTS_STAGED|20:PASS_KERNEL_PREPARED|\
    30:PASS_CONTAINERD_INSTALLED|40:PASS_KUBERNETES_INSTALLED|\
    50:PASS_KUBEADM_INITIALIZED|60:PASS_CILIUM_INSTALLED|\
    10:ALREADY_COMPLIANT|20:ALREADY_COMPLIANT|30:ALREADY_COMPLIANT|\
    40:ALREADY_COMPLIANT|50:ALREADY_COMPLIANT|60:ALREADY_COMPLIANT) return 0 ;;
    *) return 1 ;;
  esac
}
```

终端输出 helper 必须固定字段且不接收任意 key：

```bash
finish_orchestrator() {
  local result=$1 reason=$2 code=$3 next_stage=$4
  printf 'PHASE=bootstrap-all\nMODE=%s\nRESULT=%s\nREASON=%s\n' \
    "$MODE" "$result" "$reason"
  printf 'GIT_COMMIT=%s\nNEXT_STAGE=%s\nEXIT_CODE=%s\n' \
    "$git_commit" "$next_stage" "$code"
  exit "$code"
}

stop_orchestrator() {
  finish_orchestrator STOP_ORCHESTRATOR "$1" "$2" NONE
}
```

`run_stage` 必须保留真实非零退出码，只对 exit 0 严格解析：

```bash
run_stage() {
  local stage=$1 operation=$2 script captured rc result_count exit_count
  local evidence_count sha_count
  script=$(stage_path "$stage") || return 30
  set +e
  captured=$(env -u BASH_ENV -u ENV \
    /bin/bash -p "$script" "--${operation}" 2>&1)
  rc=$?
  set -e
  printf '%s\n' "$captured"
  (( rc == 0 )) || return "$rc"

  result_count=$(printf '%s\n' "$captured" | awk -F= '$1=="RESULT" {count++} END {print count+0}')
  exit_count=$(printf '%s\n' "$captured" | awk -F= '$1=="EXIT_CODE" && $2=="0" {count++} END {print count+0}')
  evidence_count=$(printf '%s\n' "$captured" | awk -F= '$1=="EVIDENCE" {count++} END {print count+0}')
  sha_count=$(printf '%s\n' "$captured" | awk -F= '$1=="SHA256" {count++} END {print count+0}')
  [[ "$result_count" == 1 && "$exit_count" == 1 &&
     "$evidence_count" == 1 && "$sha_count" == 1 ]] || return 30
  STAGE_RESULT=$(printf '%s\n' "$captured" | awk -F= '$1=="RESULT" {print substr($0,8)}')
  STAGE_EVIDENCE=$(printf '%s\n' "$captured" | awk -F= '$1=="EVIDENCE" {print substr($0,10)}')
  STAGE_SHA256=$(printf '%s\n' "$captured" | awk -F= '$1=="SHA256" {print substr($0,8)}')
}
```

`STAGE_SHA256` 只接受 `NONE` 或 64 位小写 hex；`STAGE_EVIDENCE` 只接受 `NONE` 或不含控制字符的 absolute path。每次成功 check/apply 后调用：

```bash
record_stage_summary() {
  SUMMARY_STAGE[$SUMMARY_COUNT]=$1
  SUMMARY_RESULT[$SUMMARY_COUNT]=$STAGE_RESULT
  SUMMARY_EVIDENCE[$SUMMARY_COUNT]=$STAGE_EVIDENCE
  SUMMARY_SHA256[$SUMMARY_COUNT]=$STAGE_SHA256
  SUMMARY_COUNT=$((SUMMARY_COUNT + 1))
}
```

`finish_orchestrator` 在终端字段前以 `%s` 逐项输出三个 `STAGE_<NN>_*` 字段；不得用 `%b` 解释 stage 值。测试断言 fake git 的 40 位 commit 及 stage 40 summary 均存在，且 canary 不出现在输出。

生产 stage files 必须位于自身 `script_dir`、regular/non-symlink/executable、root-owned；test mode 只接受 absolute、owned、non-symlink temporary stage dir。`git_commit` 由 `git -C "$repo_root" rev-parse HEAD` 取得并验证为 40 位小写 hex；脚本不得 fetch 或比较远端。

- [ ] **Step 5: 实现 check/apply state machine 与 lock**

生产 lock path 固定 `/run/lock/engineering-platform-bootstrap.lock`。生产 APPLY 前执行：

```bash
[[ "$EUID" -eq 0 ]] || stop_orchestrator not-root 10
[[ "$(git -C "$repo_root" branch --show-current)" == main ]] ||
  stop_orchestrator current-branch-not-main 30
[[ -z "$(git -C "$repo_root" status --porcelain=v1 --untracked-files=all)" ]] ||
  stop_orchestrator worktree-not-clean 30
exec 9>"$lock_file"
flock -n 9 || stop_orchestrator concurrent-run 30
```

仅当上述严格 test mode 合同成立时，fixture 才可以在非 root 进程中用临时 lock path 执行 `--apply`；生产模式不得绕过 `EUID == 0`。

状态机使用以下明确分支：

```bash
for stage in "${STAGES[@]}"; do
  set +e
  run_stage "$stage" check
  rc=$?
  set -e
  (( rc == 0 )) || exit "$rc"

  if check_result_is_complete "$stage" "$STAGE_RESULT"; then
    continue
  fi
  if [[ "$MODE" == CHECK ]] && check_result_requires_apply "$stage" "$STAGE_RESULT"; then
    finish_orchestrator PASS_BOOTSTRAP_CHECK apply-required 0 "$stage"
  fi
  if [[ "$MODE" == APPLY ]] && check_result_requires_apply "$stage" "$STAGE_RESULT"; then
    set +e
    run_stage "$stage" apply
    rc=$?
    set -e
    (( rc == 0 )) || exit "$rc"
    apply_result_is_success "$stage" "$STAGE_RESULT" ||
      stop_orchestrator invalid-apply-result 30
    set +e
    run_stage "$stage" check
    rc=$?
    set -e
    (( rc == 0 )) || exit "$rc"
    [[ "$STAGE_RESULT" == ALREADY_COMPLIANT ]] ||
      stop_orchestrator post-apply-check-not-compliant 30
    continue
  fi
  stop_orchestrator invalid-stage-result 30
done
```

Stage `00` 完成值为 `PASS_PREFLIGHT`，stage `90` 完成值为 `PASS_BOOTSTRAP_VERIFIED`；它们从不 APPLY。不得创建 progress file。

- [ ] **Step 6: 加入 catalog 并运行 GREEN**

在 `SHARDS['contracts']` 追加：

```python
'test_bootstrap.BootstrapOrchestratorTest',
```

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v test_bootstrap.BootstrapOrchestratorTest
python3 scripts/run_validation.py --validate-catalog
shellcheck scripts/bootstrap/bootstrap-all.sh
```

Expected: orchestrator tests `OK`；catalog exit `0`；ShellCheck 无 diagnostics。

- [ ] **Step 7: 提交 orchestrator**

```bash
git add \
  scripts/bootstrap/bootstrap-all.sh \
  scripts/test_bootstrap.py \
  scripts/validation_catalog.py
git diff --cached --check
git commit -m "feat(bootstrap): add resumable stage orchestrator"
```

---

### Task 6: 更新治理与 Runbook

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `runbook/01-bootstrap.md`
- Modify: `scripts/test_validate.py` (`RepositoryProfileContractTest`)

**Interfaces:**
- Produces governance: local `validate-fast.sh` before commit；GitHub `validation-gate` before deployment。
- Produces runbook: one-shot normal path + individual-stage emergency path。

- [ ] **Step 1: 写文档合同 RED tests**

在 `RepositoryProfileContractTest` 增加：

```python
def test_validation_and_orchestrator_are_documented(self) -> None:
    agents = (validator.ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    readme = (validator.ROOT / 'README.md').read_text(encoding='utf-8')
    runbook = (validator.ROOT / 'runbook/01-bootstrap.md').read_text(
        encoding='utf-8'
    )
    self.assertIn('./scripts/validate-fast.sh', agents)
    self.assertIn('validation-gate', agents)
    self.assertNotIn('提交前运行 `./scripts/validate.sh`', agents)
    self.assertIn('./scripts/validate-fast.sh', readme)
    self.assertIn('./scripts/validate.sh', readme)
    self.assertIn('bootstrap-all.sh --check', runbook)
    self.assertIn('bootstrap-all.sh --apply', runbook)
    self.assertIn('ALREADY_COMPLIANT', runbook)
```

- [ ] **Step 2: 运行 RED**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_validate.RepositoryProfileContractTest.test_validation_and_orchestrator_are_documented
```

Expected: FAIL，文档尚未包含新入口或仍要求本地 full。

- [ ] **Step 3: 更新 AGENTS 与 README**

`AGENTS.md` 的验证规则明确改为：

```text
提交前运行 ./scripts/validate-fast.sh 和受影响的 focused tests；普通 push 后必须等待 GitHub validation-gate 全部通过，才可继续服务器部署或验收。./scripts/validate.sh 保留为人工完整验证入口，不再要求每次本地提交运行。
```

`README.md` 分别说明：

```bash
./scripts/validate-fast.sh  # 本地提交前，目标两分钟内
./scripts/validate.sh       # 人工 full sequential diagnostic
```

并说明 GitHub `validation-gate` 才是完整 suite 的部署门禁。本批次 direct-main 是用户明确批准的例外，失败只允许 fix-forward。

- [ ] **Step 4: 更新 Runbook 执行合同**

在 `runbook/01-bootstrap.md` 的 stage 表前新增正常路径：

```bash
./scripts/bootstrap/bootstrap-all.sh --check
./scripts/bootstrap/bootstrap-all.sh --apply
```

文字必须明确：

- `--check` 在第一个 apply-required stage 停止，不执行 APPLY。
- `--apply` 每个阶段先 check，跳过 `ALREADY_COMPLIANT`，apply 后必须 post-check compliant。
- 失败后重跑同一命令，从真实状态恢复，不读取 progress file。
- 当前服务器应跳过 `00`～`30` 并从 `40` 继续。
- 原 stage 表保留为诊断和人工应急入口。
- stage 50 通过结果更新为 `PASS_KUBEADM_INITIALIZED` 或 `ALREADY_COMPLIANT`。
- 每次服务器执行仍需先给完整命令并等待回执。

- [ ] **Step 5: 运行 GREEN、fast 与提交**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_validate.RepositoryProfileContractTest.test_validation_and_orchestrator_are_documented
./scripts/validate-fast.sh
git diff --check
```

Expected: test 与 fast 均 exit `0`。

```bash
git add AGENTS.md README.md runbook/01-bootstrap.md scripts/test_validate.py
git commit -m "docs(runbook): document resumable bootstrap workflow"
```

---

### Task 7: Final Local Verification、Push 与 GitHub Gate

**Files:**
- Verify only: all files changed by Tasks 1-6
- No server files or external runtime state are modified in this task

**Interfaces:**
- Consumes: local fast/focused tests and GitHub workflow。
- Produces: clean `main` commit and successful `validation-gate` run。

- [ ] **Step 1: 校验 catalog 与 fast profile**

Run:

```bash
python3 scripts/run_validation.py --validate-catalog
/usr/bin/time -p ./scripts/validate-fast.sh
```

Expected: both exit `0`；fast `real` 目标小于 `120` 秒。

- [ ] **Step 2: 运行本批次 focused regression**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/scripts" \
python3 -m unittest -v \
  test_bootstrap.KubernetesInstallTest.test_apply_accepts_real_flat_repository_indextarget_shape \
  test_bootstrap.KubernetesInstallTest.test_apply_rejects_second_packages_indextarget \
  test_bootstrap.KubeadmInitTest.test_exact_initialized_state_is_already_compliant_and_zero_write \
  test_bootstrap.KubeadmInitTest.test_apply_on_exact_initialized_state_never_reinitializes \
  test_bootstrap.KubeadmInitTest.test_initialized_candidate_drift_stops_unknown \
  test_bootstrap.BootstrapOrchestratorTest \
  test_validate.ValidationCatalogTest \
  test_validate.RepositoryProfileContractTest
```

Expected: all selected tests `OK`。

- [ ] **Step 3: 运行所有 Bash 静态检查和 Git hygiene**

Run:

```bash
shellcheck \
  scripts/validate.sh \
  scripts/validate-fast.sh \
  scripts/validate-static.sh \
  scripts/bootstrap/lib/common.sh \
  scripts/bootstrap/*.sh
git diff --check
git status --short --branch
```

Expected: ShellCheck/diff exit `0`；worktree clean；`main` 仅领先 `origin/main`，无未提交文件。

- [ ] **Step 4: 审查提交序列和敏感内容**

Run:

```bash
git log --oneline origin/main..HEAD
git diff --name-status origin/main..HEAD
git diff origin/main..HEAD -- . ':!docs/superpowers/specs/*' ':!docs/superpowers/plans/*' |
  rg -n 'BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|ghp_|github_pat_|password[=:]|token[=:]'
```

Expected: commit 均为 Conventional Commits；文件范围符合本计划；最后一个 secret scan 命令 exit `1` 且无匹配输出。

- [ ] **Step 5: 普通 push main**

```bash
git push origin main
```

Expected: fast-forward push success；禁止 `--force`。

- [ ] **Step 6: 等待当前 commit 的 GitHub validation-gate**

```bash
head_sha=$(git rev-parse HEAD)
run_id=$(gh run list \
  --workflow validate.yml \
  --branch main \
  --commit "$head_sha" \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')
test -n "$run_id"
gh run watch "$run_id" --exit-status
gh run view "$run_id" --json conclusion,headSha,url \
  --jq '{conclusion,headSha,url}'
```

Expected: `conclusion=success`，`headSha` 等于本地 `HEAD`。若失败，立即暂停部署，只用新的 fix-forward commit 修复并重新等待 gate；不得 force push。

- [ ] **Step 7: 交付 gate 证据并停止在服务器操作前**

最终回报必须包含：

```text
LOCAL_FAST=PASS
FOCUSED_TESTS=PASS
GITHUB_VALIDATION_GATE=PASS
GIT_COMMIT=<40-character HEAD>
WORKFLOW_URL=<GitHub Actions run URL>
SERVER_NEXT_EXPECTED_STAGE=40
```

此处停止。下一轮再生成完整的服务器同步与 `bootstrap-all.sh --check`【运维】命令，并等待用户返回服务器回执。
