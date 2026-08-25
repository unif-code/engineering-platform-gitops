# DEV Business-Ready GitOps Activation Design

## 目的

在已经验收的 Flux Phase A 四 Controller 基础上，把当前单用户 DEV 推进到可通过
`https://platform.dev.local` 使用 frontend/backend 的状态。交付包括公共 Git 仓的 gated
sync、最小必要平台基础设施、无备份 PostgreSQL、DEV-003 Secret 文件供给、Alembic
migration、应用工作负载、Gateway 路由和运行验收。

本设计不把“业务可用”冒充完整 V0.1 验收。OpenBao、MinIO、Barman、etcd/PG 备份、
restore drill、observability 和整机重启验收继续保持 `BLOCKED`/`NOT_EXECUTED`。

## 批准范围

- 保留 Flux v2.9.3 的 source、kustomize、helm、notification 四个 Controller，不新增第五个
  Controller。
- GitOps 仓是 Public；Flux 只读拉取 `origin/validated`，不创建 deploy key、Git Token 或
  Git credential Secret。
- Secret 值只由获准服务器操作生成并写入 Kubernetes Secret，绝不进入 Git、命令回显、
  CI、证据、ConfigMap、普通环境变量或持久卷。
- backend 继续使用已核验镜像输入；数据库 DSN 通过只读 Secret volume 挂载到 `/app/.env`，
  pepper、TOTP sealing key、idempotency key 通过独立文件挂载到内存 Secret volume。
- CNPG 只部署 Operator 和单实例 PostgreSQL。ObjectStore、Barman plugin、
  ScheduledBackup 与任何备份 Job 不进入活动 Desired State。
- 账号初始化是数据库写入且会一次性显示临时密码，不能放入捕获 stdout 的一键 orchestrator；
  它在应用 Ready 后使用独立受控交互命令执行。

## 当前事实与新发现

- 当前 GitOps HEAD 为 `c12036bfdf8bb8c0c0c6add12cd91ddf4d34e530`；
  `main == validated`，Phase A `run-approved --check` 已返回 `PASS_BOOTSTRAP_ALL_CHECK`。
- `clusters/dev` 目前只引用 `flux-system`；`gotk-sync.yaml` 没有 YAML document；
  `reconcile-rbac.yaml`、`infrastructure.yaml`、`apps.yaml` 均为 inactive staged entrypoint。
- 暂存 RBAC 含多个 `cluster-admin` binding，不能直接激活。
- 当前 apps 只有 Gateway 与 Certificate，没有 Deployment、Service、HTTPRoute 或 migration。
- backend `DbSettings` 和 `SecuritySettings` 已使用 `env_file=".env"`；容器工作目录固定
  `/app`，因此 Kubernetes Secret volume 可把完整配置作为 `/app/.env` 文件挂载，无需
  修改业务镜像，也不需要 Secret 环境变量回退。
- 历史 migration 只有在角色不存在时才会走 `localdev` fallback。部署必须先由 CNPG
  managed roles 预建全部登录角色，并在 Alembic 前显式验证；任一角色缺失即停止。

## 方案比较与选择

### 方案 A：GitOps 原生分阶段激活（采用）

一个受保护候选提交包含全部最终 Desired State，一键 orchestrator 先激活 sync，再按阶段等待
Controller/基础设施、创建带外 Secret、等待数据库/migration/应用。Flux 负责持续 Reconcile，
stage 只处理 Git 无法保存的 Secret、顺序门禁和证据。

优点是最终状态只有一个 Git 事实源，重复运行可判定 `ALREADY_COMPLIANT`，且不会把临时
手工 apply 留成永久事实。代价是 stage 与 validator 必须理解 Phase A 到业务可用的状态迁移。

### 方案 B：直接 kubectl 部署后再交给 Flux（不采用）

实现更快，但会同时存在脚本 apply 与 Flux Desired State 两套 owner，field manager、prune、
回退和漂移判定不清晰，不满足单向 Reconcile 验收。

### 方案 C：把全部动作塞进单个 stage（不采用）

命令数量少，但无法精确定位 Secret、CNPG、migration 或应用失败，恢复时也无法安全跳过已完成
部分。阶段输出与证据会失去可恢复性。

## 目标目录与职责

### Flux bootstrap

- `clusters/dev/flux-system/gotk-sync.yaml`：公共 `GitRepository/flux-system`，固定 URL 和
  `ref.branch=validated`；根 `Kustomization/flux-system` 指向 `./clusters/dev`。
- `clusters/dev/flux-system/phase-b-network-policy.yaml`：只给 source-controller 增加
  `github.com:443` FQDN egress；其余 Phase A default deny 保持不变。
- `clusters/dev/kustomization.yaml`：最终只引用受审阅的 Namespace/RBAC/Flux CR entrypoint，
  不直接展开 workload manifests。

### Reconcile 权限

- `clusters/dev/reconcile-rbac.yaml`：删除全部 `cluster-admin` binding，改为按职责拆分的
  root、foundation、cert-manager Helm、CNPG Helm、platform database、migration 和 app
  ServiceAccount/Role/ClusterRole/Binding。
- root reconciler 只能管理固定 Namespace、上述 RBAC 和 `flux-system` 中受支持的 Flux CR。
- controller manifest reconciler 只拥有固定渲染对象所需的 API group/resource verbs；不得取得
  Secret 内容读取、Node 写、CSR 批准、Token 创建或任意非资源 URL 权限。
- platform database、migration、app reconciler 使用不同身份；migration 身份不能成为 backend
  runtime 身份。

### 固定 Chart

- cert-manager `v1.21.1` 与 CloudNativePG chart `0.29.0` 必须从官方来源下载并先验证 SHA-256。
- Chart 解包内容 vendored 到 `vendor/charts/`，用固定 Helm 二进制离线渲染后提交 YAML；
  active Kustomization 对不支持 digest value 的 operator 镜像做精确 digest transform。
- 不创建 HelmRelease、HelmRepository 或 Helm release-storage Secret。根因是 HelmRelease 的
  impersonation ServiceAccount 必须读写 Helm storage Secret，与本设计的 Secret 零读取权限冲突。
  四个 Flux Controller 仍全部保留并只 watch `flux-system`。

### Core infrastructure

- 活动基础设施只包含 Namespace、ResourceQuota、local-path StorageClass/provisioner、
  cert-manager、DEV self-signed issuer、CloudNativePG Operator 和单实例 PostgreSQL。
- 复用 `infrastructure/foundation` 与 `infrastructure/cnpg/database` 的精确活动入口；原 MinIO、
  Barman、ScheduledBackup、etcd-backup、observability 清单继续保留为 inactive，不进入 root render。
- PostgreSQL Cluster 删除 `plugins`、`ObjectStore`、`ScheduledBackup` 和 WAL archiver 参数，
  继续固定 PG `18.4` linux/amd64 digest、20Gi PVC 和 DEV-002 resources。
- `flux-system`、`local-path-storage`、`cert-manager`、`cnpg-system`、`platform` 五个活动 Namespace
  均保留双向 default deny 与 DNS egress；按职责精确增加 kube-apiserver/webhook 流量，并仅以
  Cilium `ingress` entity 放行 Gateway 到 frontend/backend 的入口。

## Secret 与数据库顺序

### 预创建 Secret

stage 在 `umask 077` 的 `/root` 私有临时目录中用 CSPRNG 生成：

- 一个数据库 owner `platform_owner` 的独立密码；
- 六个 runtime 数据库角色的独立密码：`audit_rw`、`identity_rw`、`organization_rw`、
  `workspace_rw`、`authorization_rw`、`configuration_rw`；
- 三份互不相同的 32-byte 二进制材料：`pepper`、`totp_key`、`idempotency_key`。

每个角色使用独立 `kubernetes.io/basic-auth` Secret。CNPG `managed.roles` 在 initdb/Alembic 前
创建所有角色为 LOGIN、非 superuser，并从对应 Secret 读取密码。stage 对任何已存在但类型、
key contract 或 owner 不符的 Secret fail closed，绝不覆盖或轮换。

### PostgreSQL 与运行配置

1. stage 110 持久化精确 Namespace、公共 GitRepository、根 Kustomization 与 Git egress。
2. stage 120 等待 foundation、cert-manager 与 CNPG Operator 达到 Ready；数据库 Kustomization
   在 Secret prerequisite 到齐前允许由 Flux 重试，但后续 stage 不会越过。
3. stage 130 创建 `platform-owner`、六个 runtime role 与三份材料 Secret；owner 与 runtime role
   均必须 LOGIN、非 superuser，任何 Secret 语义漂移都停止。
4. 等待 `platform/platform` Ready，并在不输出值的情况下组合 `/app/.env` 内容，写入
   `platform/backend-runtime-config`
   Secret；该 Secret 只以文件挂载，Pod spec 不出现 `env`/`envFrom` Secret 引用。
5. migration Job 先连接数据库验证七个期望角色均存在；六个 runtime role 必须 LOGIN、
   非 superuser 且密码不等于历史默认值。验证通过才执行 `alembic upgrade heads`。
6. migration 成功后，backend Deployment 才允许 Ready。

Secret 检查只输出名称、type、key 名集合、ownerReference 和计数，不输出 data、长度、hash、
base64 或 DSN。

## 应用 Desired State

### Migration

- `apps/migration/`：一次性 Alembic Job，backend 镜像按不可变 digest固定，
  `restartPolicy: Never`、`backoffLimit: 0`、有限 deadline，resources 固定为
  `100m/256Mi` requests、`1 CPU/1Gi` limits。
- Job 通过固定 annotation 绑定 backend Source SHA、image digest 和 migration contract
  generation；新 migration 只能用新 Job name/generation，不能修改已完成 Job。
- NetworkPolicy 只允许 migration Pod 访问 PostgreSQL DNS/5432 和 kube-dns。

### Runtime workloads

- `apps/platform/`：frontend/backend Deployment、ClusterIP Service、HTTPRoute、PDB/Policy
  和 ServiceAccount。
- frontend image 固定 linux/amd64 digest，资源为 `10m/64Mi` requests、`250m/256Mi` limits，
  Service port 80。
- backend image 固定到经 CI 核验的不可变 digest，资源为 `100m/256Mi` requests、
  `1 CPU/1Gi` limits，Service port 8000；readiness `/readyz`，liveness `/healthz`。
- 两个 Deployment 均 non-root、drop ALL、禁止 privilege escalation、只读根文件系统、
  RuntimeDefault seccomp；需要写入的临时目录使用 `emptyDir`。
- HTTPRoute 同源分流：`/api`、`/healthz`、`/readyz` 到 backend，其余路径到 frontend。
  只存在 Gateway HTTPS 北向入口，不创建 NodePort、LoadBalancer 或额外 Ingress。
- app Kustomization `dependsOn` migration，migration 未成功时 frontend/backend 不激活。

## Stage 编排

`bootstrap-all.sh` 增加以下阶段，并保留机器输出合同：

| Stage | 责任 | 成功状态 |
| --- | --- | --- |
| 110 | Phase B 公共 gated GitRepository、sync CR 与 Git egress | check `PASS_FLUX_SYNC_CHECK`；apply `PASS_FLUX_SYNC_ENABLED`；已合规 `ALREADY_COMPLIANT` |
| 120 | Namespace、最小 RBAC、core infrastructure prerequisites | check `PASS_PLATFORM_CORE_CHECK`；apply `PASS_PLATFORM_CORE_READY`；已合规 `ALREADY_COMPLIANT` |
| 130 | 角色/材料 Secret、CNPG Ready、runtime `.env` Secret | check `PASS_PLATFORM_DATABASE_CHECK`；apply `PASS_PLATFORM_DATABASE_READY`；已合规 `ALREADY_COMPLIANT` |
| 140 | Alembic migration，验证所有 heads | check `PASS_PLATFORM_MIGRATION_CHECK`；apply `PASS_PLATFORM_MIGRATION_COMPLETE`；已合规 `ALREADY_COMPLIANT` |
| 150 | frontend/backend/Gateway rollout 与只读 Smoke | check `PASS_PLATFORM_APPS_CHECK`；apply `PASS_PLATFORM_APPS_READY`；已合规 `ALREADY_COMPLIANT` |
| 160 | 汇总非敏感运行证据与 SHA-256 sidecar | check `PASS_BUSINESS_READY_EVIDENCE_CHECK`；apply `PASS_BUSINESS_READY`；已合规 `ALREADY_COMPLIANT` |

各 stage 的 `--check` 对主机与集群只读，在第一个需要 mutation 的 stage 停止；顶层
`run-approved.sh` 仍会 fetch 并以 ff-only 更新服务器 checkout。stage 150/160 check 会执行非变更性
HTTPS probe。`--apply` 对每个 stage 先 check，只执行缺失部分。Phase A stage 100 改为验证
“四 Controller 基础子集仍合规”，sync 的精确合法性交给 stage 110；未知或非预期 sync 仍 fail closed。

## 账号初始化

一键部署完成后，先证明数据库尚无 Super Admin，再在 backend Pod 的受控交互终端执行
`control_plane.tools.bootstrap_admin --interactive`。员工号与显示名是运行参数，不进入 Git；
临时密码只在当前 TTY 一次显示，不进入 Kubernetes Job log、证据、聊天或文件。

该操作必须单独展示完整命令并取得数据库写入批准。随后用户通过 HTTPS 页面设置正式密码并
完成 TOTP；未完成前账号初始化状态保持 `PENDING_USER_INITIALIZATION`，不能宣称登录验收通过。

## 验证与证据

### Repository gates

- 新增针对 sync URL/ref、无 Git credential、精确 Stage 顺序、inactive exclusions、Chart digest、
  RBAC、NetworkPolicy、Secret volume、CNPG no-backup、migration/app dependency、image digest、
  securityContext、resources 和 Gateway Route 的 fail-closed 测试。
- 每项 mutation test 必须证明第五 Controller、`cluster-admin`、MinIO/OpenBao/backup、Secret
  env 注入、浮动 image/chart、migration bypass、NodePort/Ingress 或宽松网络会被拒绝。
- 运行 focused tests、`validate-fast.sh`、static gate、完整 Linux full profile、Kustomize/Helm
  render 和 `git diff --check`；CI `validation-gate` 全绿后才发布 `validated`。

### Runtime readback

- Flux GitRepository/Kustomization Ready、observed revision 等于批准的 `validated` SHA。
- 仍恰好四个 Flux Controller；无第五 Controller、无 Git Secret。
- 活动 Namespace 精确为批准集合；OpenBao、MinIO、monitoring、Barman、backup inventory 为空。
- CNPG Operator/Cluster Ready，PG Image ID、角色 metadata、migration heads 合规。
- frontend/backend Image ID 与 GitOps digest 对齐，Gateway/Certificate/HTTPRoute Ready。
- `/`、`/healthz`、`/readyz` 和未认证 `/api/v1/me` 返回预期状态；响应证据不含 Cookie、Token、
  TOTP、密码、Secret 或完整业务数据。

最终保存 `/root/dev-infra-evidence/16-business-ready-<UTC>.txt` 和同名 `.sha256`，权限 `600`。
证据明确记录 `OPENBAO=NOT_EXECUTED`、`MINIO=NOT_EXECUTED`、`BACKUPS=NOT_EXECUTED`、
`RESTORE=NOT_EXECUTED`，并保持对应 V0.1 条目 `BLOCKED`。

## 失败与回退

- 任一供应链、Secret metadata、RBAC、CNPG、migration、readiness、Image ID、TLS 或 Smoke 状态
  未知即停止，不继续后续 stage。
- 禁止 `--force-conflicts`、手工 patch Desired State、浮动 tag、删除 PVC 或覆盖既存 Secret。
- migration 已提交后不自动 downgrade；使用 forward-fix migration。
- 应用回退只允许切换到上一个已通过 CI 的 Git digest，数据库 schema 兼容性必须先验证。
- PostgreSQL PVC 默认保留；任何删除 Cluster/PVC 的回退需要独立破坏性审批。
- Phase B 后不能再使用 Phase A 的“删除整个 flux-system”回滚路径。

## 明确不在本批次

- OpenBao Runtime、Agent Injector、Secret 迁移或 OpenBao Backup/Restore；
- MinIO、Object Lock、Barman、ScheduledBackup、etcd backup、任何 restore drill；
- Prometheus/Grafana/Metrics Server 与容量/整机重启验收；
- V0.1 `ACCEPTED` 或 V0.2 Release Gate 通过声明；
- 修改 frontend/backend 业务源码或重新解释已核验的业务 API 契约。
