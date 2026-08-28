# DEV OpenBao Runtime-Only 激活设计

## 1. 目的与事实基线

本文固定 DEV OpenBao 的当前交付边界：只部署并验收 OpenBao Runtime，不部署 MinIO，
不执行 Snapshot、Backup 或 Restore，不迁移现有应用 Kubernetes Secret。
本文取代 `2026-08-23-openbao-runtime-activation-delta-design.md` 作为后续实现依据；旧文档仅
保留为历史设计记录，不得用其中已过时的现场 SHA、同步阶段或交付顺序驱动部署。

本设计基于以下已验证现场事实：

- GitOps `main`、`origin/main` 与 `origin/validated` 均为
  `bc35eed4a739e81d0473903ac996b5066d377247`；
- Flux 四个 Controller、基础设施、PostgreSQL、migration、backend、frontend、TLS 与
  Gateway 已完成运行验收；
- OpenBao、MinIO、OpenBao Snapshot、备份任务与恢复任务均未部署；
- 现有应用继续从 Kubernetes Secret 读取材料，OpenBao Runtime 故障不得影响现有应用；
- engineering-platform-docs 的治理候选提交
  `a2de7c12b7f119baf4e9af75d8ea87aefb60e368` 已登记 DEV-005、修正多审计设备的
  Fail Closed 语义，并把架构基线刷新为 `2026-08-28.2`。DEV-005 必须先进入 docs
  `main`，GitOps 实现才可引用并交付。

Canonical Contract 仍由 engineering-platform-docs 的
`architecture/08-security-audit-governance.md`、
`architecture/09-infrastructure-operations.md`、
`architecture/appendix-parameters.md` 与 `architecture/deviations.md` 拥有。

## 2. 锁定范围

### 2.1 本批次必须完成

- 独立 `openbao` Namespace；
- OpenBao Server `2.6.1`，一个副本，`NON_HA`；
- 官方 OpenBao Helm Chart `0.28.6`；
- Agent Injector，一个副本；
- Integrated Storage Raft 单节点，Data PVC `10 GiB`；
- 独立 Audit PVC `5 GiB`；
- TLS ClusterIP-only、最小 RBAC、ResourceQuota、Pod Security 与 NetworkPolicy；
- Shamir `5/3` 初始化，五份 share 与初始 root token 只输出 OpenPGP 密文；
- Kubernetes Auth、最小 Policy、受控 ServiceAccount 登录探针；
- OpenBao Audit 同时写独立 PVC 与 stdout；
- Stage 170 Runtime 安装与 Stage 180 受控初始化；
- 最终证据 `/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt` 及 SHA-256 sidecar。

Chart、Server 与 Injector 镜像都必须固定为经供应链核验的不可变 digest。版本号不能替代
digest，`latest`、浮动 tag 或部署时临时查询到的未审阅 digest 均禁止进入运行路径。

### 2.2 明确不在范围内

- MinIO、Barman、etcd Backup、OpenBao Snapshot、ScheduledBackup、Restore Drill；
- 任何应用 Secret 写入 OpenBao、Agent 注入应用 Pod 或旧 Kubernetes Secret 回收；
- 应用 Deployment、数据库账号、pepper、TOTP key 或 idempotency key 的变更；
- OpenBao UI 的 Gateway、Ingress、NodePort、LoadBalancer 或公网入口；
- 多 Server、自动 unseal、动态数据库凭据、自动轮换或生产可用性声明；
- V0.1/V0.2 Release Gate 状态变更。

验收必须把上述项目明确记录为 `NOT_EXECUTED`，不能以 OpenBao Ready 推断这些能力存在。

## 3. 运行时拓扑与资源边界

OpenBao 运行在独立 `openbao` Namespace：

```text
受控运维 / 探针
        │ TLS :8200
        ▼
  openbao ClusterIP ── OpenBao Server x1 ── Raft Data PVC 10 GiB
        ▲                       │
        │                       └────────── Audit PVC 5 GiB
 Agent Injector x1
        │ Kubernetes Auth
        ▼
 Kubernetes API
```

- Server 与 Injector 使用各自 ServiceAccount 和最小权限；
- HPA 禁用，Raft peer 必须精确为一个并明确标记 `NON_HA`；
- `openbao` 使用独立 ResourceQuota，不修改 `platform` Namespace 配额；
- 部署前重新计算根盘余量、PVC 总量与恢复峰值，继续满足 DEV-002；
- 回滚、失败和重试都不得删除或重建 Raft/Audit PVC；
- StorageClass、Retain、容量或节点压力未知时 Fail Closed。

## 4. 网络与 TLS

- API 仅通过 TLS ClusterIP 暴露，证书必须覆盖集群内实际服务 DNS 名；
- 禁止 HTTP 明文、UI 外部入口、Ingress、Gateway、NodePort 与 LoadBalancer；
- Namespace 默认拒绝入站和出站；
- 只放行 DNS、OpenBao 到 Kubernetes API 的 Auth 访问、Injector 到 OpenBao `8200`、
  OpenBao Raft `8201` 与受控运维探针；
- 每条放行规则都必须绑定 Namespace、ServiceAccount、Pod label 或明确 CIDR，不能使用
  无边界的 `0.0.0.0/0`；
- 证书、Service DNS、容器监听地址和探针 SNI/CA 必须一致。

## 5. 初始化与恢复材料

初始化是一次受控 operator ceremony，不属于 GitOps 自动同步：

1. 用户在 Windows 生成专用 OpenPGP key，passphrase 只在本机隐藏输入；
2. 私钥、passphrase 不进入服务器、Git、聊天、日志或证据；
3. Stage 180 只接收公钥，并要求 OpenBao 初始化返回五份加密 share 与加密 root token；
4. 脚本只保存密文、元数据与 SHA-256，不输出或解密任何明文；
5. 用户把加密恢复包上传到其受控网络云盘，并独立保管私钥与 passphrase；
6. 用户本人通过隐藏输入提供三份已解密 share 完成 unseal；
7. 用户本人通过隐藏输入使用初始 root token 完成一次性配置；
8. 日常验证改用 Kubernetes Auth 的短期身份，root token 不进入日常路径。

加密 share 与 root token 只能恢复访问，不能替代 Raft Snapshot。DEV-005 关闭前，Data PVC
丢失仍意味着 OpenBao 状态不可恢复。

## 6. Audit、Auth 与最小权限

- Audit file device 写独立 Audit PVC，格式为 JSON、`log_raw=false`，敏感字段使用 HMAC；
- 同时启用 stdout Audit；任一配置失败或所有 Audit device 不可用时请求 Fail Closed；
- Kubernetes Auth 必须绑定 `openbao` Namespace、专用验证 ServiceAccount 与
  `audience=openbao`；
- 验证 Policy 只允许对专用探针路径执行最小读写，不访问现有应用 Secret；
- 运行验收必须证明允许操作成功、越权操作失败、Audit 中存在对应请求且不含明文 Secret；
- 不把 token、share、私钥、passphrase、kubeconfig 或 Secret 值写入环境变量、命令行、
  shell history、ConfigMap、Evidence 或 Git。

## 7. GitOps 激活门

当前 Flux 根 Kustomization 会自动跟踪 `origin/validated`。如果把 OpenBao 直接加入
`clusters/dev/kustomization.yaml`，`publish-validated` 后可能在服务器写入审批前自动部署，
因此本设计禁止这种激活方式。

交付采用“仓库内 dormant desired state + 获批后显式安装独立 Flux Kustomization”：

- OpenBao HelmRepository/HelmRelease、配置、RBAC、TLS、NetworkPolicy、Quota 与 PVC 契约
  全部进入仓库并通过 CI；
- 一个独立的 OpenBao Flux Kustomization 清单也进入仓库，但不被当前
  `clusters/dev/kustomization.yaml` 引用；
- `origin/validated` 发布候选 SHA 不会自动创建 OpenBao Namespace 或资源；
- Stage 170 `--check` 对精确批准 SHA 做供应链、render、client dry-run、分阶段
  server dry-run、diff、容量与现场空状态检查；
- 只有用户看到完整 Stage 170 `--apply` 命令并明确批准后，脚本才按依赖顺序安装仓库内
  已审阅的 Namespace、最小 bootstrap RBAC 与独立 Flux Kustomization；
- 独立 Flux Kustomization 随后从同一批准 SHA 的仓库路径 reconcile OpenBao Runtime；
- 禁止手工拼接 Manifest、`kubectl patch`、`force-conflicts` 或临时绕过自动同步边界。

这个边界保证 Git 仍是 Desired State，同时确保 CI/validated 更新本身不是未经批准的集群
写操作。集群重建时也必须重新经过 Stage 170，而不是由根同步静默激活 OpenBao。

## 8. Stage 170：Runtime 安装契约

Stage 170 加入 `bootstrap-all.sh`，但必须具有独立的停机语义：

- `--check` 只读，不创建 Namespace、CR、PVC、Secret 或其他资源；
- 空集群状态通过后返回可审阅的 render digest、资源清单、diff、容量与下一条完整命令；
- 已完全合规时返回 `ALREADY_COMPLIANT`；
- 部分安装、未知所有者、digest 漂移、容量不足、已有 Secret、外部暴露或备份资源出现时
  返回明确 `STOP_*`，不得吸收未知状态；
- `--apply` 只激活 OpenBao Runtime，不初始化、不 unseal、不配置 Auth/Policy/Audit，
  不部署 MinIO/Backup，不修改应用；
- apply 后必须等待 HelmRelease、Server、Injector、PVC、Service、TLS 与 NetworkPolicy
  readback；OpenBao 处于未初始化/sealed 状态是 Stage 170 的预期终态；
- 所有持久化写入必须来自批准 SHA 的固定 render，并记录对象 UID、generation、digest 与
  ownership；失败时停止且保留 PVC。

## 9. Stage 180：受控初始化契约

Stage 180 不加入无人值守的 `bootstrap-all --apply` 自动连续执行；它需要用户在场完成
OpenPGP 与隐藏输入步骤：

- `--check` 验证 Stage 170 已合规、OpenBao 未初始化或已知幂等状态、公钥可用、输出目录
  权限安全、现有应用健康且 OpenBao 未承载应用 Secret；
- 首次 `--apply` 生成只含密文的恢复包，随后停在用户解密和隐藏输入门；
- unseal 后配置 TLS 验证、Audit、Kubernetes Auth、验证 Role 与最小 Policy；
- 重跑不得再次初始化、覆盖恢复包、轮换 share、生成第二个 root token 或扩大 Policy；
- 最终 readback 验证 initialized、unsealed、单 Raft peer、Server/Injector Ready、Auth、
  Policy、Audit、TLS、无外部入口、现有应用仍健康且旧 Kubernetes Secret 未变化；
- 最终证据文件 mode 为 `0600`，sidecar 只保存 SHA-256；证据先经过敏感值扫描再落盘。

## 10. 失败、回退与幂等

- Chart/Image/digest、容量、TLS、RBAC、NetworkPolicy、PVC、Seal、Audit、Auth、Policy、
  Injector 或现有应用状态任一未知即停止；
- Stage 170 失败不进入初始化；Stage 180 失败不迁移应用 Secret；
- 已初始化 OpenBao 不允许自动重新初始化；已存在恢复包不允许覆盖；
- rollback 只回退无状态配置和控制器对象，永不删除 Raft/Audit PVC；
- sealed 或不可用的 OpenBao 不触发应用 fallback，因为应用本批次从未切换到 OpenBao；
- 不使用临时 Secret、浮动 tag、手工 patch、删除 PVC 或修改现有应用作为修复手段。

## 11. 验证与验收

### 11.1 仓库与 CI

- Chart、Server、Injector 均固定版本和 digest；
- Kustomize/Helm render 稳定且资源清单精确；
- 只允许一个 Server、一个 Injector、Raft `10 GiB`、Audit `5 GiB`、`NON_HA`；
- RBAC、ResourceQuota、Pod Security、TLS、NetworkPolicy 与 PVC 保留策略满足设计；
- OpenBao 未加入自动同步根，候选 SHA 发布不会自动写集群；
- 任何 MinIO、Snapshot、Backup、Restore、应用 Secret 迁移或外部暴露都会使验证失败；
- Stage 170/180 的 check/apply、部分状态、幂等、失败与证据脱敏路径都有测试；
- focused tests 与 `./scripts/validate-fast.sh` 通过，GitHub `validation-gate` 和
  `publish-validated` 在同一 SHA 全绿。

### 11.2 Runtime acceptance

最终证据至少包含：

- GitOps SHA、docs baseline/DEV-005、Chart 与镜像 digest；
- Namespace、Quota、PVC、Pod、Service、HelmRelease、Flux Kustomization 的 UID 与状态；
- OpenBao `2.6.1`、initialized、unsealed、单 Raft peer、`NON_HA`；
- TLS 证书与服务 DNS 验证、无 Gateway/Ingress/NodePort/LoadBalancer；
- Kubernetes Auth 成功、最小 Policy 正向与越权拒绝探针；
- file/stdout Audit 可用、HMAC 生效且没有敏感值；
- Server/Injector Ready，现有 PostgreSQL/backend/frontend/TLS/Gateway 继续健康；
- 现有 Kubernetes Secret 名称、UID、resourceVersion 与内容摘要未发生变化；
- `MINIO=NOT_EXECUTED`、`SNAPSHOT=NOT_EXECUTED`、`BACKUP=NOT_EXECUTED`、
  `RESTORE=NOT_EXECUTED`、`APP_SECRET_MIGRATION=NOT_EXECUTED`；
- `/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt`、mode `0600` 与 SHA-256 sidecar。

## 12. 交付顺序

1. DEV-005 与架构 baseline 先进入 docs `main` 并通过 docs CI；
2. 基于已合并的 docs SHA 编写 OpenBao Desired State、Stage 170/180、runbook、validators
   与测试；
3. GitOps focused tests、fast validation、PR、`validation-gate` 与
   `publish-validated` 全绿；
4. 服务器仅执行 `run-approved.sh <SHA> --check`，收集只读 inventory、render、dry-run、
   diff 与容量结果；
5. 展示 Stage 170 `--apply` 完整命令、影响范围和预期 readback，等待用户明确批准；
6. Stage 170 激活 Runtime，并停在未初始化/sealed；
7. 用户生成专用 OpenPGP key 并确认离线保管；
8. 展示 Stage 180 完整命令、秘密输入边界和预期 readback，等待用户明确批准；
9. 完成初始化、unseal、Auth/Policy/Audit 与 Runtime acceptance；
10. 用户把密文恢复包上传到受控网络云盘，保存最终证据与 checksum；
11. 合并完成后清理已经进入 `main` 的临时分支与旧 worktree。
