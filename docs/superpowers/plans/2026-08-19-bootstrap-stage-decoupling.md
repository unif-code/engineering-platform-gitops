# Bootstrap Stage 目录拆分与判定去重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 8 个平铺的 stage 脚本改成 `stages/<NN-name>/{run.sh,gates.sh,README.md}`，并把 23 个跨 stage 同名函数收敛到 `lib/`，同时补齐被 `source` 文件的供应链门禁。

**Architecture:** 先补门禁（避免搬迁期间扩大未校验面），再自底向上上提共享判定，最后才移动目录并切换编排器映射。每一步独立提交、全量绿后再进行下一步。

**Tech Stack:** Bash 3.2 兼容、Python 3（测试与 check_cidrs）、shellcheck 0.9.0（CI pin）与 0.11.0 双版本、unittest。

**Spec:** `docs/superpowers/specs/2026-08-19-bootstrap-stage-decoupling-design.md`

## Global Constraints

- Bash 3.2 兼容：禁止 `declare -A`、`mapfile`、`${var^^}`、负数组下标。
- shellcheck 必须在 **0.9.0（CI pin）与 0.11.0** 两个版本下都干净；解释性注释不得以 `shellcheck` 一词开头（会被当成指令解析）。
- 既有 383 个测试全部保持绿；**不得放宽任何既有断言**来让迁移通过。
- 每个新增/上提的函数都要有测试，并用变异证明非空转（改坏实现必须变红）。
- fail-closed：任何门禁不通过都以既有 STOP 形态与固定退出码停止（10 前置条件 / 20 供应链 / 30 未知或漂移 / 40 apply 失败 / 50 verify 失败），不得降级为告警。
- `--check` 零写入；唯一文档化例外是 Stage 60/90 的瞬态 helm kubeconfig。
- 语义差异只能依据服务器实测证据或真实工具输出裁决，**不得依据现有 fixture**。
- 禁止提交 Secret、Token、私钥、kubeconfig 或密码库导出内容。
- **每新增一个测试类，必须同步登记到 `scripts/validation_catalog.py`**（`contracts` 分片
  与 `FAST_SELECTORS`）。`run_validation.py` 先跑 `--validate-catalog`，未登记的类会让
  CI 以 `missing=[...]` 硬失败——本地跑单个类却完全正常，是典型的"本地绿、CI 红"。
- 既有断言的**位置**可以随被测对象迁移而重锚，但重锚后的断言不得比原断言弱：
  必须仍能捕获原断言覆盖的缺陷类，并用变异证明。仅当原断言钉住的事实本身
  因迁移而消失（如已不再需要的 shellcheck 抑制）时，方可删除该部分。
- 生产环境测试变量守卫是 `for test_override in "${!BOOTSTRAP_TEST_@}"` 前缀通配，与变量名无关——上提测试缝不会新增覆盖面，但不得删除该守卫。

---

## File Structure

**新增：**
- `scripts/bootstrap/lib/path-facts.sh` — 路径属性判定
- `scripts/bootstrap/lib/exec-safety.sh` — 受控外部命令与目录/文件安全判定
- `scripts/bootstrap/lib/archive.sh` — 归档校验族
- `scripts/bootstrap/lib/kubectl.sh` — kubectl 调用与 admin.conf 门禁
- `scripts/bootstrap/lib/helm.sh` — helm 调用与瞬态 kubeconfig 生命周期
- `scripts/bootstrap/stages/<NN-name>/{run.sh,gates.sh,README.md}` × 8

**修改：**
- `scripts/bootstrap/lib/common.sh` — 承载 `host_path`、`complete`
- `scripts/bootstrap/bootstrap-all.sh` — `stage_path` 映射、被 source 文件门禁
- `scripts/test_bootstrap.py` — stage 路径 helper 集中
- `runbook/01-bootstrap.md`、`AGENTS.md` — 路径更新

**删除：** `scripts/bootstrap/[0-9]*.sh`（迁移完成后）

---

### Task 1: 被 source 文件的供应链门禁

**Files:**
- Modify: `scripts/bootstrap/bootstrap-all.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Produces: `safe_owned_directory`/`safe_owned_file` 对 `lib/` 及 `lib/*.sh` 的强制校验；后续任务新增的 `stages/` 目录复用同一门禁。

现状缺口：`bootstrap-all.sh:381` 校验 `$stage_dir`（非递归）与 8 个 stage 脚本文件，但 `lib/` 目录及其 `*.sh` 从未校验，而每个 stage 都以 root `source` 它们。

- [ ] **Step 1: 写失败测试**

在 `scripts/test_bootstrap.py` 的编排器测试类中新增：

```python
def test_orchestrator_rejects_unsafe_library_directory(self) -> None:
    """捕获 lib/ 或其 *.sh 未经属主与权限校验即被 root source 的缺陷。"""
    for target, mode in (
        ('lib', 0o777),
        ('lib/common.sh', 0o666),
    ):
        with self.subTest(target=target):
            root = self.write_orchestrator_fixture()
            victim = root / 'scripts/bootstrap' / target
            victim.chmod(mode)
            result = self.run_orchestrator(root, '--check')
            self.assertEqual(result.returncode, 30, result.stdout)
            self.assertIn('REASON=unsafe-library-file', result.stdout)
            self.assertNotIn('PHASE=preflight', result.stdout)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd scripts && python3 -m unittest test_bootstrap.OrchestratorTest.test_orchestrator_rejects_unsafe_library_directory -v`
Expected: FAIL（当前无该门禁，编排器会继续执行到 preflight）

- [ ] **Step 3: 实现门禁**

在 `bootstrap-all.sh` 中 stage 脚本校验循环之前插入：

```bash
library_dir="${stage_dir}/lib"
safe_owned_directory "$library_dir" "$expected_stage_uid" ||
  stop_orchestrator unsafe-library-file 30
for library_file in "$library_dir"/*.sh; do
  [[ -e "$library_file" ]] || stop_orchestrator unsafe-library-file 30
  safe_owned_file "$library_file" "$expected_stage_uid" ||
    stop_orchestrator unsafe-library-file 30
done
```

- [ ] **Step 4: 运行确认通过并跑全量**

Run: `cd scripts && python3 -m unittest test_bootstrap -v 2>&1 | tail -5`
Expected: OK，既有用例无回归

- [ ] **Step 5: 变异证明非空转**

把 `safe_owned_directory "$library_dir" ...` 临时改成 `true`，重跑该用例，必须变红；恢复。

- [ ] **Step 6: 提交**

```bash
git add scripts/bootstrap/bootstrap-all.sh scripts/test_bootstrap.py
git commit -m "fix(bootstrap): gate library files before sourcing them as root"
```

---

### Task 2: lib/path-facts.sh

**Files:**
- Create: `scripts/bootstrap/lib/path-facts.sh`
- Modify: `scripts/bootstrap/{20,30,40,50,60,90}-*.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Produces: `path_owner <path>` → `uid:gid`；`path_mode <path>` → 八进制；`path_size <path>` → 字节数；`owned_by_expected <path>` → 0/1

`path_owner`、`path_mode`、`path_size` 三者各副本字节一致，机械上提。`owned_by_expected` 有三种实现，差异**仅在测试缝**：

- 20：含 `BOOTSTRAP_TEST_OWNER_DRIFT_PATH`
- 30：含上者 **加** `BOOTSTRAP_TEST_DEFERRED_OWNER_DRIFT_PATH` + `BOOTSTRAP_TEST_OWNER_DRIFT_AFTER_MARKER`
- 40/50/60/90：两者皆无

上提版本取**并集**（即 30 的实现）。安全性依据：生产守卫是 `${!BOOTSTRAP_TEST_@}` 前缀通配，任何 `BOOTSTRAP_TEST_*` 变量在生产环境出现都会以 `test-override-in-production` 退出 10，与变量名无关，因此并集不新增生产可利用面。

- [ ] **Step 1: 写 lib 级失败测试**

```python
class PathFactsTest(BootstrapTestCase):
    def test_owned_by_expected_honours_deferred_drift_seam(self) -> None:
        """并集实现必须同时支持即时漂移与标记触发的延迟漂移。"""
        library = self.repo_root / 'scripts/bootstrap/lib/path-facts.sh'
        target = self.test_root / 'probe'
        target.write_text('x', encoding='utf-8')
        marker = self.test_root / 'marker'
        script = (
            f'source {library!s}\n'
            'owned_by_expected "$1" && echo BASELINE_OK\n'
            'BOOTSTRAP_TEST_OWNER_DRIFT_PATH="$1" owned_by_expected "$1" || echo IMMEDIATE_DRIFT\n'
            'BOOTSTRAP_TEST_DEFERRED_OWNER_DRIFT_PATH="$1" '
            'BOOTSTRAP_TEST_OWNER_DRIFT_AFTER_MARKER="$2" '
            'owned_by_expected "$1" && echo DEFERRED_INACTIVE\n'
        )
        output = self.run_bash(script, str(target), str(marker),
                              env={'BOOTSTRAP_TEST_MODE': '1'})
        self.assertIn('BASELINE_OK', output)
        self.assertIn('IMMEDIATE_DRIFT', output)
        self.assertIn('DEFERRED_INACTIVE', output)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd scripts && python3 -m unittest test_bootstrap.PathFactsTest -v`
Expected: FAIL with "No such file or directory: lib/path-facts.sh"

- [ ] **Step 3: 创建 lib 并从 30 迁入并集实现**

`lib/path-facts.sh` 内容为 30 的 `owned_by_expected` 与任一副本的 `path_owner`/`path_mode`/`path_size`，文件头写 `# shellcheck shell=bash`。

- [ ] **Step 4: 从 6 个 stage 删除本地定义并改为 source**

每个 stage 在既有 `source "${script_dir}/lib/common.sh"` 之后追加：

```bash
# shellcheck disable=SC1091
source "${script_dir}/lib/path-facts.sh"
```

- [ ] **Step 5: 全量验证**

Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
Expected: Ran 383+ tests, OK

- [ ] **Step 6: 变异证明**

把 `lib/path-facts.sh` 的 `owned_by_expected` 最后一行比较改成恒真，重跑 stage 20/30 的属主漂移用例，必须变红；恢复。

- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
shellcheck -x $(git ls-files '*.sh')
"$SC090/bin/shellcheck" -x $(git ls-files '*.sh')
git commit -am "refactor(bootstrap): share path fact predicates across stages"
```

---

### Task 3: lib/exec-safety.sh

**Files:**
- Create: `scripts/bootstrap/lib/exec-safety.sh`
- Modify: `scripts/bootstrap/{60,90}-*.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `path_mode`、`owned_by_expected`（Task 2）
- Produces: `python_isolated`、`tar_safe`、`safe_directory <path> <mode>`、`safe_file <path> <mode>`

`python_isolated`、`tar_safe`、`safe_directory` 三者在 60/90 字节一致。`safe_file` 目前只存在于 90，是 90 用来抽掉「正规文件 + 非符号链接 + 模式匹配 + 属主符合」四项检查的通用判定；一并上提，供 Task 5/6 使用。

**先决改动（Task 1 复评的前瞻发现，必须在本任务内先做）：**

`scripts/test_bootstrap.py:2800-2807` 有一条断言「lib/ 下的文件不 source 任何东西」。
本任务是第一个引入**跨 lib 依赖**的任务（`exec-safety.sh` 的 `safe_file` 消费
`path_owner`），一旦 `exec-safety.sh` source `path-facts.sh`，该断言就会变红，
而门禁前提其实仍然成立。

- 放宽为：任何 `source` 目标的父目录必须等于被门禁覆盖的 lib 目录（而非「不得 source」）。
- 同时修 `scripts/test_bootstrap.py:33-35` 的 `source` 正则：当前漏掉
  `if source`、`elif source`、`while .`、`! source`、`command source` 等形态，
  会让门禁前提断言**失败开放**（今天仓库里不存在这些写法，但不能留口子）。

- [ ] **Step 1: 写失败测试**

```python
class ExecSafetyTest(BootstrapTestCase):
    def test_safe_file_rejects_symlink_and_wrong_mode(self) -> None:
        library = self.repo_root / 'scripts/bootstrap/lib/exec-safety.sh'
        good = self.test_root / 'good'
        good.write_text('x', encoding='utf-8')
        good.chmod(0o600)
        link = self.test_root / 'link'
        link.symlink_to(good)
        loose = self.test_root / 'loose'
        loose.write_text('x', encoding='utf-8')
        loose.chmod(0o644)
        script = (
            f'source {library!s}\n'
            'source "$3"\n'
            'safe_file "$1" 600 && echo GOOD_OK\n'
            'safe_file "$2" 600 || echo SYMLINK_REJECTED\n'
            'safe_file "$4" 600 || echo MODE_REJECTED\n'
        )
        output = self.run_bash(
            script, str(good), str(link),
            str(self.repo_root / 'scripts/bootstrap/lib/path-facts.sh'), str(loose),
            env={'BOOTSTRAP_TEST_MODE': '1'})
        self.assertIn('GOOD_OK', output)
        self.assertIn('SYMLINK_REJECTED', output)
        self.assertIn('MODE_REJECTED', output)
```

- [ ] **Step 2: 运行确认失败** — Run: `cd scripts && python3 -m unittest test_bootstrap.ExecSafetyTest -v`
- [ ] **Step 3: 创建 lib 并迁入四个函数**（`safe_file` 取 90 的实现）
- [ ] **Step 4: 60/90 删除本地定义、改为 source**
- [ ] **Step 5: 全量验证** — Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
- [ ] **Step 6: 变异证明**（把 `safe_file` 的 `! -L` 去掉，符号链接用例必须变红）
- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): share controlled execution and path safety helpers"
```

---

### Task 4: lib/archive.sh（含真语义裁决 1/2）

**Files:**
- Create: `scripts/bootstrap/lib/archive.sh`
- Modify: `scripts/bootstrap/{10,30}-*.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `python_isolated`（Task 3）
- Produces: `array_contains`、`safe_archive_member`、`safe_symlink_target`、`approved_record <name>`、`validate_archive <name> <archive>`、`regular_archive_member <archive> <member>`

**裁决（语义差异，必须实现为并集）：** `validate_archive` 两份实现功能不同，不是写法差异：

| 能力 | 10 | 30 | 合并后 |
| --- | --- | --- | --- |
| 硬链接条目（`h*` / `' link to '`） | 支持 | 不支持 | **支持** |
| 归档族 | helm、gateway-api、cilium-chart | containerd、crictl | **全部** |
| 成员必须是正规文件 | 仅 crictl 检查 | 全部检查 | **全部检查** |

依据：两份都在生产跑通过，各自覆盖不同归档族；取交集会让某一族失去校验，取并集才不放宽任何既有断言。`approved_record` 同理取并集（10 含 `BOOTSTRAP_TEST_APPROVED_LOCK_FILE` 测试缝，30 无）。

- [ ] **Step 1: 写失败测试**

```python
class ArchiveLibraryTest(BootstrapTestCase):
    def test_validate_archive_rejects_unsafe_hardlink_target(self) -> None:
        """合并实现必须同时校验符号链接与硬链接目标，且覆盖两个 stage 的归档族。"""
        library = self.repo_root / 'scripts/bootstrap/lib/archive.sh'
        archive = self.make_archive_with_hardlink_escape(self.test_root)
        script = (
            f'source {library!s}\n'
            'validate_archive containerd "$1" || echo HARDLINK_REJECTED\n'
            'validate_archive helm "$2" && echo HELM_FAMILY_KNOWN\n'
        )
        output = self.run_bash(script, str(archive), str(self.make_helm_archive()),
                               env={'BOOTSTRAP_TEST_MODE': '1'})
        self.assertIn('HARDLINK_REJECTED', output)
        self.assertIn('HELM_FAMILY_KNOWN', output)
```

- [ ] **Step 2: 运行确认失败** — 两条断言都必须失败（当前无合并实现，且 30 不认 helm 族）
- [ ] **Step 3: 实现并集**，`approved_record` 的 `case` 覆盖全部 6 个制品
- [ ] **Step 4: 10/30 删除本地定义、改为 source**
- [ ] **Step 5: 全量验证** — 特别确认 stage 10 与 30 的既有归档用例全部仍绿
- [ ] **Step 6: 变异证明** — 去掉硬链接分支，Step 1 首条断言必须变红
- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): merge archive validation into one shared contract"
```

---

### Task 5: lib/kubectl.sh（含真语义裁决 2/2）

**Files:**
- Create: `scripts/bootstrap/lib/kubectl.sh`
- Modify: `scripts/bootstrap/{50,60,90}-*.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `safe_file`（Task 3）、`admin_conf_json_is_exact`（既有 `lib/admin-conf.sh`）
- Produces: `admin_conf_metadata_is_safe`、`admin_conf_is_safe`、`capture_admin_conf`、`kubectl_run`、`kubectl_query_is_empty`

**裁决：** `admin_conf_gate`(60) 与 `admin_conf_is_safe`(90) 是**同一判定的两个名字**；`admin_conf_metadata_gate`(60) 与 `admin_conf_metadata_is_safe`(90) 也是——90 只是把四项检查抽成了 `safe_file`。统一采用 90 的命名与抽取。因此 `kubectl_run`、`capture_admin_conf`、`helm_cluster_run` 的差异全部降级为命名差异，机械统一。

**唯一真正改变行为的地方：** `kubectl_query_is_empty`

- 50 现状：`"$kubectl_binary" --kubeconfig "$admin_conf" --namespace kube-system "$@"` —— 直接读磁盘上的 kubeconfig 文件，硬编码 namespace。
- 90 现状：`kubectl_run "$@"` —— 读**已捕获内容**（`--kubeconfig <(printf '%s' "$ADMIN_CONF_CONTENT")`），并在调用前后各做一次 `admin_conf_is_safe`（含 `cmp -s` 比对磁盘文件与捕获内容），namespace 由调用方显式传入。
- 裁决：统一到 90 的形态。它是严格更强的 TOCTOU 防护，且不放宽任何既有断言。
- **代价：stage 50 当前完全不捕获 `ADMIN_CONF_CONTENT`**，必须先采纳 `capture_admin_conf`，并把 3 个调用点（`50-kubeadm-init.sh:524,526,528`）补上 `--namespace kube-system`。

- [ ] **Step 1: 写失败测试**

```python
def test_stage_50_kube_proxy_probe_detects_admin_conf_tampering(self) -> None:
    """捕获 Stage 50 在读取 kubeconfig 期间文件被替换却仍判定通过的缺陷。"""
    root = self.write_stage_fixture('50')
    self.arm_admin_conf_swap_during_kubectl(root)
    result = self.run_stage(root, '50', '--check')
    self.assertEqual(result.returncode, 30, result.stdout)
    self.assertIn('REASON=admin-conf-content-or-structure-drift', result.stdout)
```

- [ ] **Step 2: 运行确认失败** — 当前 50 读磁盘文件，替换后不会被发现，用例必须失败
- [ ] **Step 3: 创建 lib/kubectl.sh**，采用 90 的命名与实现
- [ ] **Step 4: stage 50 采纳 `capture_admin_conf` 并补 `--namespace kube-system`**
- [ ] **Step 5: 60/90 删除本地定义、改为 source**（60 的 `admin_conf_gate` 调用点全部改名）
- [ ] **Step 6: 全量验证** — Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
- [ ] **Step 7: 变异证明** — 删掉 `kubectl_run` 调用后的第二次 `admin_conf_is_safe`，Step 1 用例必须变红
- [ ] **Step 8: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): share kubectl gate and harden stage 50 against admin.conf swaps"
```

---

### Task 6: lib/helm.sh

**Files:**
- Create: `scripts/bootstrap/lib/helm.sh`
- Modify: `scripts/bootstrap/{60,90}-*.sh`
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `safe_file`、`safe_directory`（Task 3）、`admin_conf_is_safe`（Task 5）
- Produces: `helm_run`、`helm_cluster_run`、`cleanup_helm_kubeconfig`、`helm_kubeconfig_residue_exists`、`helm_values_json_is_exact`、`helm_archive_is_safe <archive>`

`helm_run`、`cleanup_helm_kubeconfig`、`helm_kubeconfig_residue_exists`、`helm_values_json_is_exact` 四者字节一致。`helm_cluster_run` 仅差网关名与 `safe_file` 抽取（取 90），并保留 60 更完整的 trap 注释（说明为何只在子 shell 内补装）。`helm_archive_is_safe` 改为必须显式传参，两个调用方各自传入自己的变量。

- [ ] **Step 1: 写失败测试**

```python
class HelmLibraryTest(BootstrapTestCase):
    def test_transient_kubeconfig_is_locked_down_and_always_removed(self) -> None:
        """捕获瞬态 kubeconfig 权限过宽或函数返回后未清理的缺陷。"""
        library = self.repo_root / 'scripts/bootstrap/lib/helm.sh'
        script = (
            f'source {library!s}\n'
            'helm_cluster_run version --short\n'
            'helm_kubeconfig_residue_exists && echo RESIDUE_LEFT || echo RESIDUE_CLEAN\n'
        )
        output = self.run_bash(script, env=self.helm_stub_environment())
        self.assertIn('KUBECONFIG_DIR_MODE=700', output)
        self.assertIn('KUBECONFIG_FILE_MODE=600', output)
        self.assertIn('RESIDUE_CLEAN', output)
```
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 创建 lib/helm.sh**
- [ ] **Step 4: 60/90 删除本地定义、改为 source**
- [ ] **Step 5: 全量验证**
- [ ] **Step 6: 变异证明** — 去掉 `trap 'cleanup_helm_kubeconfig || :' EXIT`，残留用例必须变红
- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): share helm invocation and transient kubeconfig lifecycle"
```

---

### Task 7: lib/common.sh 扩充（host_path 与 complete）

**Files:**
- Modify: `scripts/bootstrap/lib/common.sh`、全部 8 个 stage
- Test: `scripts/test_bootstrap.py`

**Interfaces:**
- Produces: `host_path <absolute>`、`complete <result> <reason> <code> [next]`

`host_path` 8 份中 7 份字节一致，00 仅差 `== "1"` 与 `== 1`（`[[ ]]` 内语义相同），取多数版本。

`complete` 三种形态的裁决依据：
- 00+20+30 与 40+50+60+90 只差 `local` 声明写法，两者都委托 `finish_phase`。
- **stage 10 是唯一不委托的**：它内联打印并硬编码 `EVIDENCE=NONE`、`SHA256=NONE`。
- 已确认 stage 10 **从不设置 `EVIDENCE_FILE`**，而 `finish_phase` 在未开证据文件时输出 `EVIDENCE=${EVIDENCE_FILE:-NONE}` = `NONE` 与 `SHA256=NONE`，与内联版本逐字段一致。
- 裁决：统一为委托 `finish_phase`，`next` 默认值取 10 的 `${4:-NONE}`（更宽松，不破坏其余 7 个总是传参的调用方）。

- [ ] **Step 1: 写失败测试**

```python
def test_stage_10_completion_block_is_byte_identical_after_unification(self) -> None:
    """统一 complete 后，Stage 10 的完成块必须与迁移前逐字节一致。"""
    root = self.write_stage_fixture('10')
    result = self.run_stage(root, '10', '--check')
    self.assertEqual(
        [line for line in result.stdout.splitlines() if '=' in line][-8:],
        ['PHASE=stage-artifacts', 'MODE=CHECK', 'RESULT=PASS_STAGE_ARTIFACTS',
         'REASON=NONE', 'EVIDENCE=NONE', 'EXIT_CODE=0', 'NEXT=NONE', 'SHA256=NONE'],
    )
```

- [ ] **Step 2: 运行确认通过（这是迁移前基线）**，随后再改实现，确保输出不变
- [ ] **Step 3: 上提 `host_path` 与 `complete` 到 `lib/common.sh`**
- [ ] **Step 4: 8 个 stage 删除本地定义**
- [ ] **Step 5: 全量验证** — 完成块必须逐字节不变
- [ ] **Step 6: 变异证明** — 把 `next` 默认值去掉，stage 10 不传第 4 参的调用必须变红
- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): share host path helper and completion block"
```

---

### Task 8: 测试侧 stage 路径集中

**Files:**
- Modify: `scripts/test_bootstrap.py`、`scripts/validate.py`、`scripts/test_validate.py`

**Interfaces:**
- Produces: `BootstrapTestCase.stage_script(stage: str) -> Path`，26 处硬编码路径全部改为调用它。

先集中再迁移，目录移动才只需改一处。

- [ ] **Step 1: 写失败测试** — 断言 `stage_script('60')` 指向的文件存在且可执行
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 实现 helper 并替换 26 处引用**

```python
STAGE_SCRIPTS = {
    '00': 'stages/00-preflight/run.sh',
    '10': 'stages/10-stage-artifacts/run.sh',
    '20': 'stages/20-prepare-kernel/run.sh',
    '30': 'stages/30-install-containerd/run.sh',
    '40': 'stages/40-install-kubernetes/run.sh',
    '50': 'stages/50-kubeadm-init/run.sh',
    '60': 'stages/60-install-cilium/run.sh',
    '90': 'stages/90-verify/run.sh',
}
```

本任务先让 helper 返回**当前**平铺路径，Task 9-11 迁移时只改这张表。

- [ ] **Step 4: 全量验证**
- [ ] **Step 5: 提交**

```bash
git commit -am "test(bootstrap): route every stage path through one helper"
```

---

### Task 9: 迁移小体量 stage（00 10 20 30）

**Files:**
- Create: `scripts/bootstrap/stages/{00-preflight,10-stage-artifacts,20-prepare-kernel,30-install-containerd}/{run.sh,gates.sh,README.md}`
- Delete: 对应的平铺 `.sh`

四个 stage 形态相同，作为一批处理。每个 stage：

- [ ] **Step 1: `git mv` 保留历史**

```bash
mkdir -p scripts/bootstrap/stages/00-preflight
git mv scripts/bootstrap/00-preflight.sh scripts/bootstrap/stages/00-preflight/run.sh
```

- [ ] **Step 2: 修正 `script_dir` 推导**

`run.sh` 深了一层，`source` 路径由 `${script_dir}/lib/` 改为：

```bash
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/common.sh"
```

- [ ] **Step 3: 拆出 `gates.sh`** — 判定函数移入，`run.sh` 顶部 source 它（同样走 Task 1 的门禁）
- [ ] **Step 4: 写 `README.md`** — 本 stage 做什么 / 会停在哪些 REASON / 证据路径
- [ ] **Step 5: 更新 Task 8 的路径表与 `bootstrap-all.sh` 的 `stage_path` 对应行**
- [ ] **Step 6: 全量验证后提交**（四个 stage 一次提交）

```bash
git commit -am "refactor(bootstrap): move preflight through containerd stages into directories"
```

---

### Task 10: 迁移 50 与 40

同 Task 9 的步骤，逐个进行；40 有 1199 行，`gates.sh` 承载其包校验与 CNI 判定族。

#### 50-kubeadm-init

- [ ] **Step 1: `git mv` 保留历史**

```bash
mkdir -p scripts/bootstrap/stages/50-kubeadm-init
git mv scripts/bootstrap/50-kubeadm-init.sh scripts/bootstrap/stages/50-kubeadm-init/run.sh
```

- [ ] **Step 2: 修正 `script_dir` 推导**

```bash
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/common.sh"
```

原文件里每一处 `${script_dir}/lib/` 都要改成 `${bootstrap_dir}/lib/`。

`script_dir` **不只用于 source**，以下引用必须一并顺延（迁移前实测得出）：

| 位置 | 现状 | 迁移后 |
| --- | --- | --- |
| `00`/`10`/`30` | `repo_root=$(cd "${script_dir}/../.." && pwd -P)` | `../../..` |
| `00:185` | `python3 "${script_dir}/check_cidrs.py"` | `${bootstrap_dir}/check_cidrs.py` |
| `50:565-568` | `${script_dir}/{20,30,40}-*.sh`、`check_cidrs.py` | `${bootstrap_dir}/stages/<NN-name>/run.sh`、`${bootstrap_dir}/check_cidrs.py` |
| `90:120-122` | `cd "$script_dir"`、`${script_dir}/30-install-containerd.sh` | `cd "$bootstrap_dir"`、`${bootstrap_dir}/stages/30-install-containerd/run.sh` |

**Ruling R1（预检裁定）：** 移动 20/30/40 时，`50` 与 `90` 此刻仍是平铺文件，
但它们按路径引用被移动方，因此**必须在同一个提交内**更新其引用，否则本任务落地即红。

**Ruling R2（预检裁定）：** `check_cidrs.py` 留在 `scripts/bootstrap/`，不随 stage 进目录。
本地 fixture 因 `BOOTSTRAP_TEST_ROOT` 隔离可能掩盖路径推导错误，验证步骤必须包含
一次真实路径断言（`test -x` 目标脚本、`test -f` check_cidrs.py），不得只依赖 fixture。

- [ ] **Step 3: 拆出 `gates.sh`**

判定函数移入 `stages/50-kubeadm-init/gates.sh`，`run.sh` 在 lib 之后 source 它：

```bash
# shellcheck disable=SC1091
source "${script_dir}/gates.sh"
```

`gates.sh` 必须可被测试单独 source 且无副作用（顶层只有函数定义与 `readonly` 常量）。

**已知会变红的两处（Task 1 复评实测，必须在本步一并处理）：**

1. `source "${script_dir}/gates.sh"` 会触发门禁前提断言——`gates.sh` 不在 `lib/` 下。
   须把允许集扩展为「`lib/` 下的文件，或本 stage 目录下的 `gates.sh`」，并为 `gates.sh`
   补上与 lib 同级的属主/权限门禁（Task 12 覆盖三层，此处先保证不失败开放）。
2. 迁移后 `scripts/bootstrap/[0-9]*.sh` 通配为空，任何依赖该通配枚举 stage 的测试
   都会**静默通过 0 个文件**。须改为从 `STAGE_SCRIPTS` 表枚举，并断言数量为 8。

- [ ] **Step 4: 写 `stages/50-kubeadm-init/README.md`**

三节：本 stage 做什么、会停在哪些 `REASON`（逐条给出处置）、证据文件路径。

- [ ] **Step 5: 更新路径表与编排器映射**

改 `scripts/test_bootstrap.py` 的 `STAGE_SCRIPTS['50']` 与
`bootstrap-all.sh` 中 `stage_path` 的对应 `50)` 分支。

- [ ] **Step 6: 全量验证**

Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
Expected: Ran 383+ tests, OK；该 stage 的完成块必须逐字段与迁移前一致

- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): move kubeadm-init stage into its directory"
```

#### 40-install-kubernetes

- [ ] **Step 1: `git mv` 保留历史**

```bash
mkdir -p scripts/bootstrap/stages/40-install-kubernetes
git mv scripts/bootstrap/40-install-kubernetes.sh scripts/bootstrap/stages/40-install-kubernetes/run.sh
```

- [ ] **Step 2: 修正 `script_dir` 推导**

```bash
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/common.sh"
```

原文件里每一处 `${script_dir}/lib/` 都要改成 `${bootstrap_dir}/lib/`。

`script_dir` **不只用于 source**，以下引用必须一并顺延（迁移前实测得出）：

| 位置 | 现状 | 迁移后 |
| --- | --- | --- |
| `00`/`10`/`30` | `repo_root=$(cd "${script_dir}/../.." && pwd -P)` | `../../..` |
| `00:185` | `python3 "${script_dir}/check_cidrs.py"` | `${bootstrap_dir}/check_cidrs.py` |
| `50:565-568` | `${script_dir}/{20,30,40}-*.sh`、`check_cidrs.py` | `${bootstrap_dir}/stages/<NN-name>/run.sh`、`${bootstrap_dir}/check_cidrs.py` |
| `90:120-122` | `cd "$script_dir"`、`${script_dir}/30-install-containerd.sh` | `cd "$bootstrap_dir"`、`${bootstrap_dir}/stages/30-install-containerd/run.sh` |

**Ruling R1（预检裁定）：** 移动 20/30/40 时，`50` 与 `90` 此刻仍是平铺文件，
但它们按路径引用被移动方，因此**必须在同一个提交内**更新其引用，否则本任务落地即红。

**Ruling R2（预检裁定）：** `check_cidrs.py` 留在 `scripts/bootstrap/`，不随 stage 进目录。
本地 fixture 因 `BOOTSTRAP_TEST_ROOT` 隔离可能掩盖路径推导错误，验证步骤必须包含
一次真实路径断言（`test -x` 目标脚本、`test -f` check_cidrs.py），不得只依赖 fixture。

- [ ] **Step 3: 拆出 `gates.sh`**

判定函数移入 `stages/40-install-kubernetes/gates.sh`，`run.sh` 在 lib 之后 source 它：

```bash
# shellcheck disable=SC1091
source "${script_dir}/gates.sh"
```

`gates.sh` 必须可被测试单独 source 且无副作用（顶层只有函数定义与 `readonly` 常量）。

**已知会变红的两处（Task 1 复评实测，必须在本步一并处理）：**

1. `source "${script_dir}/gates.sh"` 会触发门禁前提断言——`gates.sh` 不在 `lib/` 下。
   须把允许集扩展为「`lib/` 下的文件，或本 stage 目录下的 `gates.sh`」，并为 `gates.sh`
   补上与 lib 同级的属主/权限门禁（Task 12 覆盖三层，此处先保证不失败开放）。
2. 迁移后 `scripts/bootstrap/[0-9]*.sh` 通配为空，任何依赖该通配枚举 stage 的测试
   都会**静默通过 0 个文件**。须改为从 `STAGE_SCRIPTS` 表枚举，并断言数量为 8。

- [ ] **Step 4: 写 `stages/40-install-kubernetes/README.md`**

三节：本 stage 做什么、会停在哪些 `REASON`（逐条给出处置）、证据文件路径。

- [ ] **Step 5: 更新路径表与编排器映射**

改 `scripts/test_bootstrap.py` 的 `STAGE_SCRIPTS['40']` 与
`bootstrap-all.sh` 中 `stage_path` 的对应 `40)` 分支。

- [ ] **Step 6: 全量验证**

Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
Expected: Ran 383+ tests, OK；该 stage 的完成块必须逐字段与迁移前一致

- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): move kubernetes stage into its directory"
```


---

### Task 11: 迁移 60 与 90

两个最大的 stage（1315 / 1122 行），放在最后，此时共享判定已全部上提，剩余体量最小。

#### 60-install-cilium

- [ ] **Step 1: `git mv` 保留历史**

```bash
mkdir -p scripts/bootstrap/stages/60-install-cilium
git mv scripts/bootstrap/60-install-cilium.sh scripts/bootstrap/stages/60-install-cilium/run.sh
```

- [ ] **Step 2: 修正 `script_dir` 推导**

```bash
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/common.sh"
```

原文件里每一处 `${script_dir}/lib/` 都要改成 `${bootstrap_dir}/lib/`。

`script_dir` **不只用于 source**，以下引用必须一并顺延（迁移前实测得出）：

| 位置 | 现状 | 迁移后 |
| --- | --- | --- |
| `00`/`10`/`30` | `repo_root=$(cd "${script_dir}/../.." && pwd -P)` | `../../..` |
| `00:185` | `python3 "${script_dir}/check_cidrs.py"` | `${bootstrap_dir}/check_cidrs.py` |
| `50:565-568` | `${script_dir}/{20,30,40}-*.sh`、`check_cidrs.py` | `${bootstrap_dir}/stages/<NN-name>/run.sh`、`${bootstrap_dir}/check_cidrs.py` |
| `90:120-122` | `cd "$script_dir"`、`${script_dir}/30-install-containerd.sh` | `cd "$bootstrap_dir"`、`${bootstrap_dir}/stages/30-install-containerd/run.sh` |

**Ruling R1（预检裁定）：** 移动 20/30/40 时，`50` 与 `90` 此刻仍是平铺文件，
但它们按路径引用被移动方，因此**必须在同一个提交内**更新其引用，否则本任务落地即红。

**Ruling R2（预检裁定）：** `check_cidrs.py` 留在 `scripts/bootstrap/`，不随 stage 进目录。
本地 fixture 因 `BOOTSTRAP_TEST_ROOT` 隔离可能掩盖路径推导错误，验证步骤必须包含
一次真实路径断言（`test -x` 目标脚本、`test -f` check_cidrs.py），不得只依赖 fixture。

- [ ] **Step 3: 拆出 `gates.sh`**

判定函数移入 `stages/60-install-cilium/gates.sh`，`run.sh` 在 lib 之后 source 它：

```bash
# shellcheck disable=SC1091
source "${script_dir}/gates.sh"
```

`gates.sh` 必须可被测试单独 source 且无副作用（顶层只有函数定义与 `readonly` 常量）。

**已知会变红的两处（Task 1 复评实测，必须在本步一并处理）：**

1. `source "${script_dir}/gates.sh"` 会触发门禁前提断言——`gates.sh` 不在 `lib/` 下。
   须把允许集扩展为「`lib/` 下的文件，或本 stage 目录下的 `gates.sh`」，并为 `gates.sh`
   补上与 lib 同级的属主/权限门禁（Task 12 覆盖三层，此处先保证不失败开放）。
2. 迁移后 `scripts/bootstrap/[0-9]*.sh` 通配为空，任何依赖该通配枚举 stage 的测试
   都会**静默通过 0 个文件**。须改为从 `STAGE_SCRIPTS` 表枚举，并断言数量为 8。

- [ ] **Step 4: 写 `stages/60-install-cilium/README.md`**

三节：本 stage 做什么、会停在哪些 `REASON`（逐条给出处置）、证据文件路径。

- [ ] **Step 5: 更新路径表与编排器映射**

改 `scripts/test_bootstrap.py` 的 `STAGE_SCRIPTS['60']` 与
`bootstrap-all.sh` 中 `stage_path` 的对应 `60)` 分支。

- [ ] **Step 6: 全量验证**

Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
Expected: Ran 383+ tests, OK；该 stage 的完成块必须逐字段与迁移前一致

- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): move cilium stage into its directory"
```

#### 90-verify

- [ ] **Step 1: `git mv` 保留历史**

```bash
mkdir -p scripts/bootstrap/stages/90-verify
git mv scripts/bootstrap/90-verify.sh scripts/bootstrap/stages/90-verify/run.sh
```

- [ ] **Step 2: 修正 `script_dir` 推导**

```bash
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap_dir=$(cd "${script_dir}/../.." && pwd -P)
# shellcheck disable=SC1091
source "${bootstrap_dir}/lib/common.sh"
```

原文件里每一处 `${script_dir}/lib/` 都要改成 `${bootstrap_dir}/lib/`。

`script_dir` **不只用于 source**，以下引用必须一并顺延（迁移前实测得出）：

| 位置 | 现状 | 迁移后 |
| --- | --- | --- |
| `00`/`10`/`30` | `repo_root=$(cd "${script_dir}/../.." && pwd -P)` | `../../..` |
| `00:185` | `python3 "${script_dir}/check_cidrs.py"` | `${bootstrap_dir}/check_cidrs.py` |
| `50:565-568` | `${script_dir}/{20,30,40}-*.sh`、`check_cidrs.py` | `${bootstrap_dir}/stages/<NN-name>/run.sh`、`${bootstrap_dir}/check_cidrs.py` |
| `90:120-122` | `cd "$script_dir"`、`${script_dir}/30-install-containerd.sh` | `cd "$bootstrap_dir"`、`${bootstrap_dir}/stages/30-install-containerd/run.sh` |

**Ruling R1（预检裁定）：** 移动 20/30/40 时，`50` 与 `90` 此刻仍是平铺文件，
但它们按路径引用被移动方，因此**必须在同一个提交内**更新其引用，否则本任务落地即红。

**Ruling R2（预检裁定）：** `check_cidrs.py` 留在 `scripts/bootstrap/`，不随 stage 进目录。
本地 fixture 因 `BOOTSTRAP_TEST_ROOT` 隔离可能掩盖路径推导错误，验证步骤必须包含
一次真实路径断言（`test -x` 目标脚本、`test -f` check_cidrs.py），不得只依赖 fixture。

- [ ] **Step 3: 拆出 `gates.sh`**

判定函数移入 `stages/90-verify/gates.sh`，`run.sh` 在 lib 之后 source 它：

```bash
# shellcheck disable=SC1091
source "${script_dir}/gates.sh"
```

`gates.sh` 必须可被测试单独 source 且无副作用（顶层只有函数定义与 `readonly` 常量）。

**已知会变红的两处（Task 1 复评实测，必须在本步一并处理）：**

1. `source "${script_dir}/gates.sh"` 会触发门禁前提断言——`gates.sh` 不在 `lib/` 下。
   须把允许集扩展为「`lib/` 下的文件，或本 stage 目录下的 `gates.sh`」，并为 `gates.sh`
   补上与 lib 同级的属主/权限门禁（Task 12 覆盖三层，此处先保证不失败开放）。
2. 迁移后 `scripts/bootstrap/[0-9]*.sh` 通配为空，任何依赖该通配枚举 stage 的测试
   都会**静默通过 0 个文件**。须改为从 `STAGE_SCRIPTS` 表枚举，并断言数量为 8。

- [ ] **Step 4: 写 `stages/90-verify/README.md`**

三节：本 stage 做什么、会停在哪些 `REASON`（逐条给出处置）、证据文件路径。

- [ ] **Step 5: 更新路径表与编排器映射**

改 `scripts/test_bootstrap.py` 的 `STAGE_SCRIPTS['90']` 与
`bootstrap-all.sh` 中 `stage_path` 的对应 `90)` 分支。

- [ ] **Step 6: 全量验证**

Run: `python3 scripts/run_validation.py --profile full 2>&1 | tail -5`
Expected: Ran 383+ tests, OK；该 stage 的完成块必须逐字段与迁移前一致

- [ ] **Step 7: 双版本 shellcheck 与提交**

```bash
git commit -am "refactor(bootstrap): move verify stage into its directory"
```


---

### Task 12: 编排器门禁覆盖 stages/ 与文档更新

**Files:**
- Modify: `scripts/bootstrap/bootstrap-all.sh`、`runbook/01-bootstrap.md`、`AGENTS.md`
- Test: `scripts/test_bootstrap.py`

- [ ] **Step 1: 写失败测试** — `stages/`、`stages/<NN>/`、`gates.sh` 任一属主或权限不符，编排器必须以 30 停止且不进入任何 PHASE
- [ ] **Step 2: 运行确认失败**
- [ ] **Step 3: 扩展 Task 1 的门禁循环覆盖 `stages/` 三层**
- [ ] **Step 4: 更新 runbook 与 AGENTS.md 中的脚本路径**
- [ ] **Step 5: 全量验证 + 双版本 shellcheck**
- [ ] **Step 6: 提交**

```bash
git commit -am "fix(bootstrap): gate stage directories and refresh operator paths"
```

---

## 收尾

全部任务完成后：

- [ ] `python3 scripts/run_validation.py --profile full` 全绿（≥383 tests）
- [ ] `shellcheck -x $(git ls-files '*.sh')` 在 0.9.0 与 0.11.0 下都干净
- [ ] `./scripts/validate-static.sh` 通过
- [ ] push 后等待 GitHub `validation-gate` 与 `publish-validated` 全绿
- [ ] 服务器执行 `scripts/bootstrap/run-approved.sh --check`，输出必须与迁移前的基线逐字段一致（PHASE/RESULT/REASON/EXIT_CODE），不得出现任何新的 STOP
