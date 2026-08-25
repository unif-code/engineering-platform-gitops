# V0.1 DEV 验收对照

GitOps commit / PR：business-ready 候选 Desired State 已形成，合并 SHA、CI 与运行证据待回填

PCS Candidate：`pcs/candidate-2.md`

验收人：尚未登记

验收时间（含时区）：`NOT_EXECUTED`

## 当前 DEV Runtime 观测

`2026-08-24 12:16:47Z` 的历史证据已验收 Flux Phase A 四 Controller 基础层；Git sync、
`platform`、`openbao`、备份和应用仍未激活，因此以下端到端验收项继续 fail-closed 为
`BLOCKED`。该记录不代表 2026-08-25 实时状态。
上层 `run-approved.sh --check` 对集群和主机配置只读，但会 `fetch` 并以 `ff-only` 更新服务器 Git checkout。

仓库候选现已覆盖公共 `validated` sync、无备份 foundation/cert-manager/CNPG、单实例 PostgreSQL、
不可变 migration/frontend/backend 与 HTTPS Gateway，并以 Stage 110–160 做 fail-closed 编排。
这只是静态候选，不改变下表运行状态；OpenBao、MinIO、备份/恢复、observability、容量/重启
验收与账号初始化明确不在本次 business-ready 运行闭环中。

| 字段 | 值 |
| --- | --- |
| 采样时间 | `2026-08-24 12:16:47Z` |
| GIT_COMMIT | `685198db15299fdb6b8cdffd72162a4864c8666b` |
| RESULT | `PASS_FLUX_PHASE_A` |
| REASON | `four-controller-runtime-accepted` |
| FLUX_CHECK | `all checks passed` |
| CONTROLLERS | `source v1.9.3/kustomize v1.9.4/helm v1.6.3/notification v1.9.2` |
| FLUX_CRD_COUNT | `11` |
| SECRET_COUNT | `0` |
| SYNC_INVENTORY | `empty` |
| DOWNSTREAM_NAMESPACE_INVENTORY | `empty` |
| NETWORK_PROBE_V2 | `PASS` |
| EVIDENCE | `/root/dev-infra-evidence/15-flux-phase-a-20260824T105630Z.txt` |
| EVIDENCE SHA256 | `2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7` |
| OPENBAO | `NOT_EXECUTED` |
| BACKUPS | `NOT_EXECUTED` |
| NEXT_STAGE | `PHASE_B_REQUIRES_SEPARATE_APPROVAL` |
| EXIT_CODE | `0` |

| # | 验收标准 | 证据 | 状态 |
| --- | --- | --- | --- |
| 1 | main 受保护、Flux 单向 Reconcile，带外扩容被纠正 | PR/branch protection、Flux 输出、扩容前后输出 | BLOCKED（候选已形成；Git sync、运行 Reconcile 与漂移演示尚未验收） |
| 2 | frontend/backend 按 digest，经 Gateway 单入口通过页面/API Smoke | `runbook/06-apps.md` | BLOCKED（候选清单已锁定；Deployment、migration、账号初始化与 Smoke 均未执行） |
| 3 | PG PITR 与 etcd 隔离 restore 各完成一次 | `runbook/07-restore-drill.md` | BLOCKED（依赖 Flux sync、MinIO 可用存储与单独备份批准；均未满足） |
| 4 | 三 bucket Versioning/Object Lock 通过，DEV-001 醒目标注 | `runbook/03-minio-verify.md`、`runbook/README.md` | BLOCKED（MinIO 供应链决策） |
| 5 | PCS 与部署版本/Image ID 一致 | `pcs/candidate-2.md` 与抽查输出 | BLOCKED（平台尚未部署，无法与运行 Image ID 对齐） |
| 6 | DEV-002 容量包络、Metrics API 与 80%/90% Gate 有证据，整机重启后全栈自愈 | `runbook/08-capacity.md`、`runbook/07-restore-drill.md` | BLOCKED（容量与重启验收依赖 Flux 激活和 MinIO 可用存储；两者当前均 BLOCKED） |

已批准的 DEV-only 差异：`stateful-rwo-lowlatency` 由 local-path provisioner 映射，无法履行目标架构的在线扩容或实际字节硬 quota Contract；清单明确设置 `allowVolumeExpansion=false`，并由 DEV-002 的 bucket quota、Prometheus 保留上限、ResourceQuota、80% 告警与 90% Stop Gate 补偿。不得把这些补偿控制表述为物理硬隔离。

## 未关闭 Stop Gates

- [ ] MinIO 供应链风险已由批准 Decision 或内部构建 digest 关闭。
- [x] Docker/containerd 共存路径已由用户批准并有运行证据。
- [ ] `dev-cp.unif.internal` 稳定解析已落地。
- [x] frontend 当前 Source Commit 的 CI provenance、OCI index digest 与 nginx / 80 启动契约已核验。
- [x] frontend 当前 `linux/amd64` manifest digest 已由 workflow、CI log 与 attestation 核验。
- [x] backend Source `4aaf721fa91abd729b33765e4e329b02aa2ece02` 的 CI 与不可变 OCI index digest 已核验。
- [ ] frontend/backend Deployment 实际 Image ID 与 GitOps digest 已对齐。
- [ ] kubelet serving certificate、metrics-server APIService 与 `kubectl top` 均通过安全 TLS 验证。

## Git 唯一 Desired State 演示

只在所有应用 Ready 后，由运维将 backend 临时扩为 2 副本；不得提交清单变更。记录 Flux 下一次 Reconcile 恢复 1 副本的时间和输出。

```text
待运维回填。
```

最终结论：`BLOCKED`（bootstrap/Flux Phase A 已验证；business-ready 候选不等于运行通过，
完整 V0.1 的备份、恢复、observability、容量与重启 Gate 也未闭环）

DEV-001 状态：`ACTIVE`

DEV-002 状态：`ACTIVE`

关闭负责人：尚未登记（事实缺口）

截止 Gate：`V0.5 Production Candidate` 前
