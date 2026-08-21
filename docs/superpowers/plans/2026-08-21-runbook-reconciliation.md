# Runbook 与今日行为变更对账 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-08-21 两个子项目造成的六处 runbook 失配补齐，使运维屏幕上看到的每一种输出都能在 runbook 里查到。

**Architecture:** 只对账、不重构。各 stage 的完整 STOP 清单指向由源码生成的 per-stage README，不在 runbook 里复制副本。

**Tech Stack:** Markdown；无代码变更。

**Spec:** `docs/superpowers/specs/2026-08-21-runbook-reconciliation-design.md`

## Global Constraints

- **不改任何代码**：本子项目只动 `runbook/*.md`。
- 不复制会漂移的副本：stage 的 STOP 清单指向 `stages/<NN-name>/README.md`。
- 不得写入 Secret、Token、私钥、kubeconfig 或真实密钥材料。
- 表述必须与**实际输出逐字一致**：写进 runbook 的每个字面量（`RESULT=` 值、
  `REASON=` 值、分量字段名）都要能在源码里找到出处。
- runbook 结构、章节顺序、其余各篇一字不动。

---

### Task 1: 编排器层的新输出

**Files:** `runbook/01-bootstrap.md`

**Steps:**
- [x] 固定退出码一节补 `RESULT=STOP_STAGE` 与 `REASON=stage-NN-{check,apply,postcheck}-stopped`
- [x] 说明失败时同样输出已完成 stage 的摘要与尾块，回填要求不变
- [x] 说明进度行与心跳走 stderr，**不属于**需要回填的证据契约
- [x] 核对写入的每个字面量都能在 `bootstrap-all.sh` 里找到出处

### Task 2: stage 60 的新 STOP 与 helm 语义

**Files:** `runbook/01-bootstrap.md`

**Steps:**
- [x] 已知 STOP 表补 `gateway-cilium-cluster-state-unknown`，处置写「先读分量报告」
- [x] 列出分量字段名，核对与 `stages/60-install-cilium/run.sh` 的 `report_cluster_state` 一致
- [x] 说明外来 Helm release 不再判死；同时列出仍被抓的三种情形
- [x] 已知 STOP 表补一句指向 per-stage README 的完整清单

### Task 3: validated 落后时的部署路径

**Files:** `runbook/01-bootstrap.md`

**Steps:**
- [x] 把显式传 SHA 从「例外情况」改为「`origin/validated` 不可用/落后时的正规路径」
- [x] 写明当前 `validation-gate` 因计费无法运行、`origin/validated` 停在迁移前
- [x] 保留原有「部署更早的已批准提交」用法，不删

### Task 4: 交叉核对

**Steps:**
- [x] 用 `git grep` 逐个核对新写入的字面量在源码中存在
- [x] 本机跑了受影响的两个契约类：`test_validate.BootstrapContractTest`（20 例）与
      `RepositoryProfileContractTest`（6 例），均通过——它们是 fast profile 里唯一读
      `runbook/01-bootstrap.md` 的部分。完整 fast profile 与全量一并交 CI。
- [ ] 全量交 CI
