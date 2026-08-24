# V0.1 DEV 验收对照

GitOps commit / PR：尚未形成可部署的完整 Desired State

PCS Candidate：`pcs/candidate-2.md`

验收人：尚未登记

验收时间（含时区）：`NOT_EXECUTED`

## 当前 DEV Runtime 观测

`2026-08-24 03:42Z` 的上层 `run-approved.sh --check` 对集群和主机配置只读，但会 `fetch` 并以 `ff-only` 更新服务器 Git checkout；它已验证 bootstrap。Runtime inventory 没有 `flux-system`、`platform` 或 `openbao`，GitRepository 查询为空，因此以下验收项继续 fail-closed 为 `BLOCKED`。

| 字段 | 值 |
| --- | --- |
| 采样时间 | `2026-08-24 03:42Z` |
| GIT_COMMIT | `1c5034b9a9c29ab72fde63644c57fa88604c45b6` |
| RESULT | `PASS_BOOTSTRAP_ALL_CHECK` |
| REASON | `bootstrap-check-complete` |
| STAGE_00 | `PASS_PREFLIGHT` |
| STAGE_00 evidence | `/root/dev-infra-evidence/07-preflight-20260824T034100Z.txt` |
| STAGE_00 SHA256 | `14e4ca38101d8aead55c5a28a19ddd495a7bb94f5b736cc432bbd8fe5d55361a` |
| STAGE_10-60 | `ALREADY_COMPLIANT` |
| STAGE_90 | `PASS_BOOTSTRAP_VERIFIED` |
| STAGE_90 evidence | `/root/dev-infra-evidence/14-verify-20260824T034246Z.txt` |
| STAGE_90 SHA256 | `0064b11860ec708491f290b7fb0594e02fcbc0737aed7674690ae1ded82ce4d5` |
| NEXT_STAGE | `NONE` |
| EXIT_CODE | `0` |
| COMMAND_EXIT_CODE | `0` |
| Namespace inventory | `cilium-secrets/default/gitlab-runner/kube-node-lease/kube-public/kube-system` |
| Pod inventory | `gitlab-runner and kube-system control plane/Cilium/CoreDNS only` |
| Inactive inventory | `flux-system/platform/openbao absent; GitRepository query empty` |

| # | 验收标准 | 证据 | 状态 |
| --- | --- | --- | --- |
| 1 | main 受保护、Flux 单向 Reconcile，带外扩容被纠正 | PR/branch protection、Flux 输出、扩容前后输出 | BLOCKED（DEV 尚无 Flux CRD 或 `flux-system`） |
| 2 | frontend/backend 按 digest，经 Gateway 单入口通过页面/API Smoke | `runbook/06-apps.md` | BLOCKED（backend digest、应用 Desired State、migration 与 Smoke 均未闭环） |
| 3 | PG PITR 与 etcd 隔离 restore 各完成一次 | `runbook/07-restore-drill.md` | BLOCKED（依赖 Flux 激活与 MinIO 可用存储；两者当前均 BLOCKED） |
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
- [ ] backend 当前 Source Commit image digest 已核验。
- [ ] frontend/backend Deployment 实际 Image ID 与 GitOps digest 已对齐。
- [ ] kubelet serving certificate、metrics-server APIService 与 `kubectl top` 均通过安全 TLS 验证。

## Git 唯一 Desired State 演示

只在所有应用 Ready 后，由运维将 backend 临时扩为 2 副本；不得提交清单变更。记录 Flux 下一次 Reconcile 恢复 1 副本的时间和输出。

```text
待运维回填。
```

最终结论：`BLOCKED`（bootstrap 已验证；Flux、平台基础设施、应用与 V0.1 Release Gate 证据未闭环）

DEV-001 状态：`ACTIVE`

DEV-002 状态：`ACTIVE`

关闭负责人：尚未登记（事实缺口）

截止 Gate：`V0.5 Production Candidate` 前
