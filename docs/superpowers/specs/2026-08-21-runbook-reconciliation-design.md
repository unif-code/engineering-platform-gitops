# Runbook 与今日行为变更对账设计（子项目 C）

## Context

子项目 C「runbook 梳理」在 2026-08-18 与 2026-08-19 两份 spec 里都被登记并推迟。
今天（2026-08-21）落地的两个子项目改变了**运维实际会看到的东西**，runbook 随之出现
若干处失配。这些失配的共同危害是：**错误的运维文档比没有文档更危险**——运维照着
runbook 找不到自己屏幕上那行字，只能猜。

逐条核对 `runbook/01-bootstrap.md`（336 行）与 `runbook/README.md`（29 行）后，
确认的失配有六处。路径类失配不在其中：`stages/<NN-name>/run.sh` 已在子项目 E 一并更新过。

### 1. `RESULT=STOP_STAGE` 未登记

编排器新增的顶层结果。stage 停止时输出
`RESULT=STOP_STAGE` 与 `REASON=stage-NN-{check,apply,postcheck}-stopped`。
runbook 的固定退出码一节只写了 stage 自己的 10/20/30/40/50，没有这一层。

### 2. 失败时的摘要与尾块未说明

「可恢复的一次性执行合同」要求回填 `RESULT`/`REASON`/`NEXT`/证据路径与 SHA-256。
在今天之前，stage 停止时这些**根本不会被打印**（失败路径是死代码）。现在会打印
已完成 stage 的全部摘要加尾块——运维需要知道该回填哪些、以及失败时同样有得填。

### 3. 进度行与心跳未说明

`[n/8] stage NN op ...` 与 `... Ns elapsed` 走 **stderr**，不属于 stdout 的证据契约。
不写清楚，运维会把它们当成需要回填的证据，或反过来因为 stdout 里没有而困惑。

### 4. `gateway-cilium-cluster-state-unknown` 不在已知 STOP 表里

2026-08-21 真实发生并耗费了一轮人工普查的 STOP，表里没有。现在它自带分量报告
（`CLUSTER_STATE=` / `HELM_SECRET_STATE=` 等），处置方式与表中其他条目不同：
先读分量、再定位，不需要额外的普查命令。

### 5. 外来 Helm release 的新语义未说明

判定收窄后，集群里其他运维装的 Helm release **不再**让 stage 60/90 变红。这是运维
需要知道的行为变更；同时仍被抓的三种情形（cilium 被 upgrade、装到错误 namespace、
同名影子 release）也要写清，否则会被误读成「helm 不再检查了」。

### 6. `origin/validated` 落后时的处置未覆盖

runbook 把显式传 SHA 描述成「需要部署某个更早的已批准提交时」。但现实是
`validation-gate` 因 GitHub Actions 计费额度用尽而无法运行，`origin/validated` 停在
迁移前，**不带 SHA 会部署旧版本**。这是当前唯一可用的路径，却被写成了例外情况。

## Decision

只做**对账**，不重构 runbook 结构：把上述六处失配补齐，其余一字不动。

理由：runbook 的结构（证据索引 + 一次性执行合同 + 单阶段诊断 + 已知 STOP 表）经过
多轮实战，本身没有暴露问题；今天的失配全部来自行为变更，不是结构缺陷。趁机重排结构
会把「文档是否正确」与「文档是否好读」两件事混在一起，前者可判红、后者只能靠品味。

各 stage 的完整 STOP 原因清单**不复制进 runbook**，改为指向
`scripts/bootstrap/stages/<NN-name>/README.md`——那些文件由源码生成、有
`StageReadmeTest` 防漂移；复制一份进 runbook 等于新增一处必然漂移的副本。
runbook 的已知 STOP 表只保留「实际遇到过且处置方式不显然」的条目。

## Scope

不在范围内：

- runbook 结构调整、章节重排、文风统一
- `02`–`10` 各篇（今天的改动不触及它们）
- 新手册（子项目 B）——形态未定，需先与用户确认定位
- 任何代码变更
