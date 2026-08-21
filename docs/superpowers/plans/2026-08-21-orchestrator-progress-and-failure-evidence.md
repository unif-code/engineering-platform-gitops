# 编排器进度与失败路径证据保全 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 bootstrap 在运行中可见、在失败时留证：编排器每个 stage 打一行进度到 stderr；stage 停止时仍输出已积累的摘要与尾块；复合判定停止时输出各子状态。

**Architecture:** stdout 逐字节不变（机器契约），进度与诊断走 stderr。失败路径改为经 `finish_orchestrator` 退出，失败的 stage 本身不记入摘要。

**Tech Stack:** Bash 3.2 兼容、Python 3、shellcheck 0.9.0（CI pin）与 0.11.0 双版本、unittest。

**Spec:** `docs/superpowers/specs/2026-08-21-orchestrator-progress-and-failure-evidence-design.md`

## Global Constraints

- Bash 3.2 兼容；shellcheck 0.9.0 与 0.11.0 双版本干净。
- **stdout 逐字节不变**：任何既有 stdout 断言都不得修改。
- 既有断言 `assertNotIn('STAGE_40_', stdout + stderr)` 必须原样保留并仍然通过——
  它钉的是「失败的 stage 不得出现摘要行」，是本次最容易被误伤的断言。
- 进度行不得回显任何来自 stage 或集群的自由文本（既有 canary 不泄漏契约）。
- fail-closed 与固定退出码不变；stage 的原始退出码必须原样传递。
- 每条改动配变异证明。

---

### Task 1: 失败路径经由 finish_orchestrator（A-2）

**Files:** `scripts/bootstrap/bootstrap-all.sh`、`scripts/test_bootstrap.py`

**Steps:**
- [x] 三处 `(( rc == 0 )) || exit "$rc"` 改为经 `finish_orchestrator` 退出，沿用 rc
- [x] 用例：stage 40 停止时，00–30 的 `STAGE_*_RESULT/EVIDENCE/SHA256` 仍在 stdout
- [x] 用例：stage 40 停止时，`STAGE_40_` 仍**不**出现（既有断言原样保留）
- [x] 用例：stage 的原始退出码原样传递（取 10/50 两个边界值；20 由既有用例覆盖）
- [x] 用例：尾块 `PHASE=bootstrap-all` 与 `EXIT_CODE=` 在失败路径上存在
- [x] 变异：**已由真实 CI 实验证明**——run 32455632083 在 errexit 泄漏未修时跑过，红在 `AssertionError: 'STAGE_00_RESULT=PASS_PREFLIGHT' not found in 'stage-40-stdout-stop\n…'`。该轮同时证明了原来那三行 `|| exit "$rc"` 是死代码。

### Task 2: 每 stage 一行进度到 stderr（A-1）

**Files:** `scripts/bootstrap/bootstrap-all.sh`、`scripts/test_bootstrap.py`

**Steps:**
- [x] 每个 stage 开始/结束各一行进度到 stderr，含序号 `[n/8]`
- [ ] 用例：stdout 逐字节与改动前一致（用既有全绿 fixture 做基线比对）
- [x] 用例：进度行出现在 stderr 且含 stage 编号与序号
- [x] 用例：进度行不含 canary、不含 ANSI 转义
- [x] 变异（两轮）：① 进度全改 stdout → 红在 stderr 断言；② stderr 照旧但**额外**漏一份到 stdout → 红在 `'[1/8]' unexpectedly found in …`。第二轮单独证明了 stdout 守卫本身不是空转（第一轮先被 stderr 断言拦下，证不到这一点）。

### Task 3: 复合判定停止时输出子状态（A-3）

**Files:** `stages/60-install-cilium/run.sh`、`scripts/test_bootstrap.py`

计划原写「90 同理」，据代码更正：stage 90 有 28 个各自独立的 REASON，是一 gate 一
REASON，不存在把多个分量坍缩成一句的问题。只有 60 的 `load_cluster_state` 是复合判定。

**Steps:**
- [x] `CLUSTER_STATE=UNKNOWN` 时输出七个子状态各一行
- [x] 值域限定 `COMPLIANT|MISSING|UNKNOWN`，不含集群自由文本
- [x] 用例：单个子状态为 UNKNOWN 时，输出能指认是哪一个
- [x] 用例：不泄漏 canary
- [ ] 变异：删掉某一个子状态的输出，对应用例必须变红
