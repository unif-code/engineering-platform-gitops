# Helm 判定作用域收窄 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 stage 60 与 90 的 Helm release 判定从「全集群恰好一个 release」收窄为「我们的 cilium release 恰好一条且逐字段正确」，使外来 Helm release 不再让 bootstrap 变红，同时不引入「cilium 被 upgrade」的检测盲区。

**Architecture:** 服务端 selector 先按 Helm 的 `name` label 筛（`owner=helm,name=cilium`），客户端保留既有的 label / 字段逐条断言作为第二道。`helm list` 侧在 Python 里按 `name == "cilium"` 过滤后再计数。两个 stage 对称改动，一次一个 stage、独立提交、全绿后再进行下一个。

**Tech Stack:** Bash 3.2 兼容、Python 3、shellcheck 0.9.0（CI pin）与 0.11.0 双版本、unittest。

**Spec:** `docs/superpowers/specs/2026-08-21-helm-release-scope-narrowing-design.md`

## Global Constraints

- Bash 3.2 兼容：禁止 `declare -A`、`mapfile`、`${var^^}`、负数组下标。
- shellcheck 必须在 0.9.0 与 0.11.0 下都干净。
- 既有 430 个测试全部保持绿；**不得放宽任何既有断言**来让本次收窄通过。
- 收窄是**削弱作用域**的改动，因此每一处放宽都必须配一条证明「没放宽过头」的用例，
  并用变异证明非空转：把实现改成「按对象名过滤」时，用例 2 必须变红。
- fail-closed：判定不通过仍以既有 STOP 形态与固定退出码停止，不得降级为告警。
- `--check` 零写入。
- 语义差异只能依据服务器实测证据裁决，不得依据现有 fixture。
- 禁止提交 Secret、Token、私钥、kubeconfig 或密码库导出内容。
- 不新增测试类（用例并入既有 `CiliumInstallTest` / `FinalVerifyTest`），
  故无需改 `scripts/validation_catalog.py`；若最终新增了类，必须同步登记。

---

## File Structure

**修改：**
- `scripts/bootstrap/stages/60-install-cilium/gates.sh` — `helm_secret_state`、`helm_list_json_state`
- `scripts/bootstrap/stages/90-verify/gates.sh` — `helm_release_is_exact` 的 secret 段与 list 段
- `scripts/test_bootstrap.py` — fake kubectl 路由 key ×2、新增边界用例 ×3（两个 stage 各一组）

**新增：** 无
**删除：** `test_bootstrap.py` 中无生产调用方的 `('get', 'secrets', …)` 死路由

---

### Task 1: Stage 60 判定收窄

**Files:**
- Modify: `scripts/bootstrap/stages/60-install-cilium/gates.sh`
- Test: `scripts/test_bootstrap.py`（`CiliumInstallTest`）

**Interfaces:**
- Changes: `helm_secret_state` 发出的 selector 由 `owner=helm` 改为 `owner=helm,name=cilium`
- Changes: `helm_list_json_state` 在 `len(items)` 判定前按 `name == "cilium"` 过滤
- Preserves: `helm_secret_json_state` 的 label / 字段断言原样保留（第二道）

**Steps:**
- [x] 改 `helm_secret_state` 的 selector
- [x] 改 `helm_list_json_state`：先过滤后计数
- [x] 同步 fake kubectl 路由 key（`test_bootstrap.py:11913`）
- [x] 用例：外来 release 存在时 `CLUSTER_STATE` 仍为 COMPLIANT
- [x] 用例：存在 `…cilium.v2`（label `name=cilium version=2`）时仍为 UNKNOWN
- [x] 用例：cilium release 在非 `kube-system` namespace 时仍为 UNKNOWN
- [x] 变异证明：把过滤改成按对象名匹配 `sh.helm.release.v1.cilium.v1`，用例 2 必须变红
- [ ] `shellcheck` 双版本干净；`CiliumInstallTest` 全绿

### Task 2: Stage 90 判定收窄（与 60 对称）

**Files:**
- Modify: `scripts/bootstrap/stages/90-verify/gates.sh`
- Test: `scripts/test_bootstrap.py`（`FinalVerifyTest`）

**Interfaces:**
- Changes: `helm_release_is_exact` 的 secret 段 selector 与 list 段过滤，与 Task 1 等价

**Steps:**
- [x] 改 secret 段 selector
- [x] 改 list 段：先过滤后计数
- [x] 同步 fake kubectl 路由 key（`test_bootstrap.py:14181`）
- [x] 三条边界用例与 Task 1 同构
- [x] 用例：60 与 90 两处判定的 selector 与过滤条件保持一致（防两边漂移）
- [ ] `shellcheck` 双版本干净；`FinalVerifyTest` 全绿

### Task 3: 清理与验收

**Files:**
- Modify: `scripts/test_bootstrap.py`

**Steps:**
- [x] 删除 `('get', 'secrets', '--all-namespaces', …)` 死路由（两处 fake）
- [ ] `./scripts/validate-fast.sh` 通过
- [ ] 全量 430+ 用例通过（交 CI，不在本机跑全量）
- [ ] 【运维】给出服务器 `--check` 完整命令并等待回执；期望 stage 60 不再以
      `gateway-cilium-cluster-state-unknown` 停止

---

## 风险

- **最大风险是收窄过头**：按对象名过滤会放行被 upgrade 过的 cilium。用例 2 是
  专门针对该风险的区分力用例，必须先看到它在错误实现下变红，才算有效。
- 两个 stage 的判定是近似重复而非共享函数（60 返回状态字符串，90 返回 0/1），
  子项目 E 因形态差异未收敛它们；本次必须**对称**改动，并由 Task 2 的一致性
  用例防止单边漂移。
