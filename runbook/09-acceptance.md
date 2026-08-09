# V0.1 DEV 验收对照

GitOps commit / PR：
PCS Candidate：`pcs/candidate-1.md`
验收人：
验收时间（含时区）：

| # | 验收标准 | 证据 | 状态 |
| --- | --- | --- | --- |
| 1 | main 受保护、Flux 单向 Reconcile，带外扩容被纠正 | PR/branch protection、Flux 输出、扩容前后输出 | PENDING |
| 2 | frontend/backend 按 digest，经 Gateway 单入口通过三条 Smoke | `runbook/06-apps.md` | BLOCKED（等待 Task 7 digest） |
| 3 | PG PITR 与 etcd 隔离 restore 各完成一次 | `runbook/07-restore-drill.md` | PENDING |
| 4 | 三 bucket Versioning/Object Lock 通过，DEV-001 醒目标注 | `runbook/03-minio-verify.md`、`runbook/README.md` | BLOCKED（MinIO 供应链决策） |
| 5 | PCS 与部署版本/Image ID 一致 | `pcs/candidate-1.md` 与抽查输出 | PENDING |
| 6 | 容量表完成，整机重启后全栈自愈 | `runbook/08-capacity.md`、`runbook/07-restore-drill.md` | PENDING |

架构差异：`stateful-rwo-lowlatency` 由计划指定的 local-path provisioner 映射，无法履行目标架构的在线扩容 Contract；当前清单明确设置 `allowVolumeExpansion=false`。正式验收前必须关联已批准的决策/Deviation，不得把未实现能力记录为通过。

## Git 唯一 Desired State 演示

只在所有应用 Ready 后，由运维将 backend 临时扩为 2 副本；不得提交清单变更。记录 Flux 下一次 Reconcile 恢复 1 副本的时间和输出。

```text
待运维回填。
```

最终结论：`PASS / FAIL / BLOCKED`
DEV-001 状态：`ACTIVE`
关闭负责人 / 截止 Gate：`待登记 / V0.5 Production Candidate 前`
