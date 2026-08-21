# 编排器进度与失败路径证据保全设计（子项目 A）

## Context

子项目 A 在 `2026-08-18` 与 `2026-08-19` 两份 spec 里都被登记为「每 gate 一行进度
与终端 UX（建立在 E 之上）」并两度推迟。E 已于 2026-08-20 交付，A 解锁。

现场暴露出三个彼此独立的问题，都指向同一件事：**证据在最需要的时候不可见**。

### 1. 失败路径直接丢弃已积累的摘要

`bootstrap-all.sh` 把每个 stage 的结果缓冲进 `SUMMARY_*` 数组，只有
`finish_orchestrator()` 会把它们打印出来。但 stage 返回非零时走的是三处裸 `exit`：

```bash
(( rc == 0 )) || exit "$rc"        # 主循环、apply 后、post-check 后各一处
```

它们绕开 `finish_orchestrator`，于是：

- `STAGE_00_RESULT` … `STAGE_50_RESULT` 全部丢失
- 每个 stage 的 `EVIDENCE` 路径与 `SHA256` 全部丢失
- `PHASE=bootstrap-all` / `RESULT` / `REASON` / `GIT_COMMIT` / `EXIT_CODE` 尾块没有

对比之下，`stop_orchestrator`（编排器**自身**发现的问题）是经过
`finish_orchestrator` 的，摘要完整。也就是说方向反了：**编排器自己出错时报告详尽，
stage 出错时——也就是绝大多数真实情况——什么都不打印。**

2026-08-21 服务器 stage 60 停止时，00–50 的证据路径与摘要就是这样丢掉的。

### 2. 全程没有任何进度输出

8 个 stage 的完整 `--apply` 在真实主机上耗时以分钟计，期间 stdout 上只有各 stage
自己的输出，编排器不打印「开始 / 结束 / 第几个」。运维无法判断当前在哪一步，
也无法区分「正在装 containerd」与「卡住了」。

### 3. 复合判定把多个子状态坍缩成一个 REASON

Stage 60 的 `load_cluster_state` 汇总七个子状态，任何混合形态都产出同一个
`REASON=gateway-cilium-cluster-state-unknown`；而全部 `log_evidence` 调用都排在
判定全绿之后，因此停止时**七个子状态一个都没被记录**。

2026-08-21 为了定位到底是哪一个，必须在服务器上另跑一轮只读普查。这一轮本可以
由 stage 自己在停止时输出。

## Decision

三条改动，共用一个原则：**stdout 是机器契约，stderr 是人看的**。

### A-1 输出分流

- stdout 继续只承载既有的结构化字段（`STAGE_*_RESULT` / `PHASE=` / `RESULT=` …），
  逐字节不变。
- 进度写 stderr，且**不使用 `STAGE_NN_` 前缀**，避免与摘要字段混淆：

  ```
  [3/8] stage 30 check ...
  [3/8] stage 30 check -> ALREADY_COMPLIANT
  ```

  这样既有断言 `assertNotIn('STAGE_40_', result.stdout + result.stderr)` 的语义
  完全保留：它钉的是「失败的 stage 不得出现摘要行」，与进度行无关。

### A-2 失败路径经由 finish_orchestrator

三处 `(( rc == 0 )) || exit "$rc"` 改为经 `finish_orchestrator` 退出，沿用 stage
自己的退出码，REASON 由编排器自己生成（只含编排器掌握的 stage 编号，不回显
stage 输出，保持既有的不泄漏契约）。

失败的 stage 本身**不**记入摘要——`record_stage_summary` 仍然只在成功分支调用，
因此 `assertNotIn('STAGE_40_', …)` 依旧成立，而 00–30 的摘要得以保全。

### A-3 复合判定停止时输出子状态

`CLUSTER_STATE=UNKNOWN` 时，把七个子状态各记一行再停止。字段名沿用既有大写
下划线风格，值域限定在 `COMPLIANT|MISSING|UNKNOWN` 三个字面量，不含任何来自
集群的自由文本，因此不扩大泄漏面。

Stage 90 的复合判定同理。

## Scope

不在范围内：

- 判定标准本身的任何变更（属 `2026-08-21-helm-release-scope-narrowing`）
- 彩色输出、终端宽度自适应、进度条——纯装饰，且会破坏日志可 grep 性
- 新手册与 runbook 梳理（子项目 B/C）
