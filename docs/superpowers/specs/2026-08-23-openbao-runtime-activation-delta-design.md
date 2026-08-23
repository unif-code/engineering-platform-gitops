# OpenBao Runtime 激活实施差异设计

## 目的

本文不是新的 OpenBao 目标架构。OpenBao、Agent Injector、Secret、数据库凭据、
Audit、网络、容量与恢复的 canonical Contract 仍由 engineering-platform-docs 的
architecture/08-security-audit-governance.md、
architecture/09-infrastructure-operations.md 与
architecture/appendix-parameters.md 拥有。

本文只固定当前单用户 DEV 的实施边界：

- OpenBao 本体继续部署，作为 DEV 的实际 Secret Provider；
- 当前 DEV 选择 Launch Profile：单 OpenBao Server、单 Agent Injector，明确标记
  NON_HA；
- DEV、后续 TEST/PROD 使用相同 Chart、Kustomize Base、配置结构、Secret 文件接口和
  验证脚本，环境 overlay 只调整规模与环境绑定值；
- OpenBao Backup/Restore 作为后续独立批次交付；
- Backup/Restore 未完成前可以形成 OpenBao Runtime 证据，但 V0.1 Release Gate 保持
  BLOCKED。

## 当前事实基线

本次设计收敛的输入基线为：

- 收敛开始前，GitOps main 与 origin/validated 均指向
  75f97f216aaf8227e18fd35e1dd53bc669eef6c5；主仓已公开，GitHub Actions
  run 32696143419 的第二次执行已通过 plan、static、8 个测试分片、
  validation-gate 与 publish-validated。
- clusters/dev/flux-system 已包含 Flux Phase A 四 Controller 的 Desired State，
  但服务器 Runtime 仍须按 runbook 独立验证；仓库和 CI 通过不等于服务器已部署。
- apps.yaml 与 infrastructure.yaml 仍未激活下游 Desired State；当前 main 没有
  OpenBao、Agent Injector、初始化或恢复清单。
- OpenBao Server 固定为 2.6.1，官方 Helm Chart 固定为 0.28.6；Chart、Server 与
  Injector 的精确 digest 必须在 PCS 通过后才能进入 Desired State。
- 架构安全文档允许 Launch Profile 对 OpenBao 采用单实例并在故障时安全停止；
  多 Voting Server、故障切换与更高可用性属于 Hardened Target。当前单机 DEV
  没有伪造多节点故障域的条件，因此明确使用单节点 NON_HA。
- Backend 与数据库凭据接入必须以实施时的最新代码重新核验。本设计不把
  2026-08-23 的旧代码快照当作当前实现事实。

## 已锁定决策

### 1. DEV Launch Profile

DEV 使用：

- OpenBao Server：1 个副本；
- Agent Injector：1 个副本；
- Integrated Storage：Raft，单节点 quorum 为 1；
- Raft Data PVC：10 GiB；
- Audit PVC：5 GiB；
- HPA：禁用；
- Availability：NON_HA。

单节点只降低连续可用性，不降低 TLS、Audit、Workload Identity、Secret 文件注入、
最小权限、离线恢复材料与 Fail Closed 要求。Server 或 PVC 故障时允许 DEV 安全停止，
不得回退到明文 Secret、普通环境变量或长期高权 Token。

Hardened 环境仍按 canonical 参数使用多 Voting Server。DEV、TEST、PROD 不复制不同
实现；它们复用同一 Helm/Kustomize 结构，副本、资源、PVC Ceiling、StorageClass、
域名、证书、镜像 digest 和 Secret path 前缀由环境 overlay 固定。

### 2. Namespace、容量与存储

OpenBao 使用独立 openbao Namespace，不占用 platform Namespace 的 PostgreSQL PVC
配额。初始实际申请为 2 个 PVC、合计 15 GiB：

- Raft Data：1 × 10 GiB；
- Audit：1 × 5 GiB。

openbao Namespace 必须拥有独立 ResourceQuota。精确 quota ceiling 在 PCS 和部署计划
中基于当时服务器容量锁定，但不得低于上述申请，也不得通过修改 platform Quota
掩盖 OpenBao 容量。激活前必须重新汇总所有活跃 Namespace、恢复态空间和主机保留量，
证明 DEV-002 的物理容量边界未被突破。

Raft 与 Audit 使用独立 RWO PVC。PVC 可按阈值在线扩容、不可缩容；任何 StorageClass、
加密、Retain 或实际容量事实不满足目标 Contract 时停止部署。

### 3. OpenBao Desired State

新增内容按职责分层：

1. Runtime 层：Namespace、HelmRelease、固定版本与 digest、Server/Injector 副本、
   Resource Request/Limit、PVC、Pod Security、ServiceAccount、TLS、Service、
   NetworkPolicy 与 Audit 配置。
2. Configuration 层：只保存非敏感 HCL、Policy、Auth Role 模板和 Secret path
   contract。
3. Bootstrap Runbook：完成初始化、解封、Raft 状态、Audit、Kubernetes Auth、
   Policy 与首批 Secret 写入。

Git 不保存 Token、密码、Shamir 分片、Root Token、私钥、kubeconfig 或 Secret 值。
HelmRelease Ready 也不等于 OpenBao Runtime 已可用。

### 4. Security Floor

- 每个环境独立实例化 OpenBao、Raft、Auth Role、Policy、Token、PKI、Audit 与恢复材料。
- Shamir 初始化固定为 5/3；分片与初始 Root Token 使用离线 OpenPGP 加密带外保管。
- Root Token 不作为日常身份，初始化和受控 Break-glass 完成后必须回收日常使用路径。
- API 只以 TLS ClusterIP 暴露。8200 仅允许 Injector、获准 Workload 与受控运维入口；
  8201 仅允许 OpenBao Raft 成员。禁止 UI 公网入口、NodePort 与 LoadBalancer。
- Kubernetes Auth 精确绑定环境、Namespace、ServiceAccount 和 audience=openbao 的
  短期 projected Token。
- 每个 Workload 使用独立 Auth Role 与最小权限 Policy。
- Secret 只由 Agent Injector 写入 Pod tmpfs 文件，不进入普通环境变量、Deployment、
  Helm Values、ConfigMap、Git、镜像、日志、Trace、Metric 或 Audit 正文。
- OpenBao Audit 写独立 Audit PVC 与 stdout，采用 JSON、log_raw=false 与 HMAC；
  两个 Audit Device 都不可用时请求 Fail Closed。

### 5. GitOps 同步边界

GitOps 主仓已是 Public。后续只读 GitRepository 可以使用 HTTPS 公共读取，不需要为
读取仓库创建 deploy key 或 Git Credential。

这项变化不授权自动进入 Phase B/C。创建 GitRepository、Flux Kustomization、Prune
边界、ServiceAccount impersonation 和下游依赖图仍须单独设计、测试、CI 和 Runtime
批准。Flux Phase A 只安装四个 Controller，不激活 OpenBao 或其他基础设施。

## OpenBao Backup 后置

本批次不实现 OpenBao Snapshot、Cluster 外保存或 Restore Drill。后置不等于已经具备
恢复能力：

- Node、Raft PVC 或 Cluster 丢失可能导致 DEV Secret 无法恢复；
- DEV 密码、TOTP 与数据库凭据可能需要重置；
- PVC 存活、空 Snapshot 清单或未执行的 Runbook 不能替代真实 Restore 证据；
- OpenBao 已部署不等于 V0.1 已验收。

Canonical 架构把 OpenBao Backup/Restore 定义为 Security Floor。因此在没有恢复能力
的情况下激活 OpenBao 前，必须先在 engineering-platform-docs 的
architecture/deviations.md 登记明确、限时、仅 DEV 的治理偏差；GitOps 仓不得自行
铸造 DEV 编号。

该偏差至少必须固定：

- 仅限单用户、无生产数据和真实生产凭据的 DEV，PROD 永不适用；
- Shamir 分片与初始 Root Token 的离线 OpenPGP 保管不后置；
- NON_HA、PVC/Seal/Audit/容量告警、Root Token 回收、TLS、NetworkPolicy 与最小权限
  仍必须在激活时完成；
- Release/Acceptance 保持 BLOCKED；
- 关闭条件是应用一致性 Raft Snapshot、Cluster 外保存、Manifest、真实 Restore，
  以及恢复后的登录、TOTP 和数据库访问验证。

## Secret 与应用接入边界

OpenBao Runtime 与应用接入分开验收：

1. 先证明 OpenBao unsealed、TLS、Audit、Kubernetes Auth、Policy 和 Injector 正常；
2. Backend 继续通过 SecretManagerPort 和文件边界消费 Secret；
3. 数据库 owner/迁移身份与运行身份使用不同 ServiceAccount、Auth Role、Policy 和
   Secret path；
4. 文件不存在、权限不安全、内容为空、DSN 不合法或 TLS 连接失败时启动/就绪
   Fail Closed；
5. 不保留含 Secret 的环境变量回退或生产默认密码；
6. pepper、TOTP key 与 idempotency key 迁移时保持原值；
7. Injector、登录/TOTP 与权限验证通过后，才能回收旧 Kubernetes Secret 并关闭
   DEV-003。

数据库 Runtime 与 Backup 扩展也必须解耦。OpenBao 激活不得暗中激活 MinIO、Barman、
ObjectStore、ScheduledBackup 或恢复任务。应用迁移、Backend/Frontend 工作负载、
HTTPRoute、Smoke 与 Telemetry 属于 OpenBao Runtime 之后的纵向闭环。

## 交付顺序

每一步失败都停止，不得跳过：

1. 完成 Flux Phase A 服务器 Runtime 验证并保存证据；
2. 在 docs 登记 Backup 后置偏差，完成 OpenBao PCS、Desired State、Runbook 与测试；
3. GitOps 公共 CI 全绿并由 origin/validated 发布精确提交；
4. 单独完成 Flux Phase B/C 的只读同步、Prune 和权限边界；
5. 激活 foundation、cert-manager 与 OpenBao Runtime；
6. 初始化、解封并验证 TLS、Audit、Kubernetes Auth、Policy 与 Injector；
7. 迁移 Secret，执行数据库迁移与应用工作负载闭环；
8. 保持 Backup Gate BLOCKED，后续独立完成 Snapshot 与 Restore Drill。

## 错误处理与回退

- Chart/Image/PCS、容量、TLS、Seal、Audit、Auth、Policy、Secret 注入、迁移、
  readiness、Smoke 或 Telemetry 任一状态未知即停止。
- OpenBao 未初始化或 sealed 时，不启用 Kubernetes Secret fallback。
- OpenBao Desired State 回退不得删除 Raft/Audit PVC。
- 初始化后的单节点 OpenBao 若丢失状态，在 Backup 偏差关闭前必须按 DEV Secret 丢失
  与凭据重置事件处理，不能伪称恢复。
- 不得使用手工 Patch、浮动 tag、未登记镜像、force-conflicts 或删除 PVC 作为修复。

## 验证

仓库门至少覆盖：

- Helm template/Kustomize build、固定版本/digest、单节点 Launch Profile、
  NON_HA 标签、RBAC、NetworkPolicy、TLS、SecurityContext 与容量汇总；
- openbao 与 platform Namespace 的 PVC/Quota 边界互不混淆；
- 环境 overlay 只改变获准的环境绑定值；
- GitRepository 公共只读且无 Git Credential，Phase A 不包含 sync CR；
- Backend Secret 值只能来自文件，迁移与运行身份不能交叉读取；
- Backup/Restore 缺失时强制 Release Gate 保持 BLOCKED。

Runtime 验收至少覆盖：

- OpenBao 版本、Chart/Image digest、单 Raft peer、unseal、TLS 与双 Audit；
- Kubernetes Auth、Policy、Injector、tmpfs 文件与权限；
- Root Token 日常路径已回收，日志和工作负载环境中没有 Secret；
- PostgreSQL Ready 与迁移 heads；
- Backend healthz/readyz、同源 HTTPS 页面/API、登录、当前用户、受保护写入与
  Telemetry 关联；
- Backup/Restore 明确未执行且没有被伪报为通过。

## 不在范围内

- MinIO、OSS、Barman、etcd、OpenBao 或其他组件的 Backup/Restore 实现；
- 多节点 DEV 伪 HA、动态数据库凭据、自动轮换与连接热重建；
- V0.1 ACCEPTED 或 V0.2 Release Gate 收口；
- V0.3 Requirement、V0.4 Agent Runtime 或模型/Agent Framework 选型；
- 任何绕过 Git Review、CI、origin/validated、堡垒机或当前运维授权的服务器修改。
