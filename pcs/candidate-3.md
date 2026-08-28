# Platform Compatibility Set Candidate 3 — OpenBao Runtime-Only Delta

状态：`CANDIDATE / RUNTIME NOT_EXECUTED`

环境：`DEV` / `NON_HA` / `SINGLE_USER_MINIMAL`

架构基线：`2026-08-28.2`

docs 事实提交：`0039d697237eb3f3a4a6238f47d4b971974a031e`

治理偏差：`DEV-002`、`DEV-003`、`DEV-005`

父集：`pcs/candidate-2.md`。本文件只增加 OpenBao Runtime-Only 兼容集，不改变已运行的
Kubernetes、Cilium、Flux、cert-manager、CNPG、PostgreSQL、backend 或 frontend 输入。
MinIO、Snapshot、Backup、Restore 与应用 Secret 迁移继续为 `NOT_EXECUTED`。

## 固定供应链

| 组件 | 固定输入 | OCI index / package | linux/amd64 manifest | 状态 |
| --- | --- | --- | --- | --- |
| Helm | `v3.21.0` Windows amd64 | archive SHA-256 `sha256:3ea6b8383e6c0b7ce45d06a5746313b8e9225edd88d42f4f64582ff3792d7b55` | N/A | 本地供应链工具，官方 checksum 已匹配 |
| OpenBao Chart | `oci://ghcr.io/openbao/charts/openbao:0.28.6` | registry `sha256:b3a8d99a56ffa36174b3848917ca849311f890d3bc2214245c88c270a54d0795`；package `sha256:175c5cea2d36b68d348eca872044656bd8740c4dbe26b7dc8eb7c7438474a8b3` | N/A | 官方 Chart；已 vendor，尚未部署 |
| OpenBao Server / Agent | `quay.io/openbao/openbao:2.6.1` | index `sha256:5b2486ab0fb90bbc788cc345b0a08616dfb375873ee8be5df3a2fd4d378a67e0` | `sha256:15e90b578c970ae57b596ed51295380cd54f93860fe36758f05b455d71aae0e0` | 固定 linux/amd64，尚未部署 |
| Injector Controller | Chart 默认 `docker.io/hashicorp/vault-k8s:1.7.2` | index `sha256:ae3d307658b72a1cf35dab9bdf92c995d45cdc7183af0516857714b5bd0ba84d` | `sha256:3dd30a9ac5909d17555480f51be734dfb719a323409f06cffe8b48cdaf6237d2` | OpenBao 官方 Chart 选择的兼容控制器；固定 linux/amd64，尚未部署 |

## Runtime 锁定

- OpenBao Server `1`、Agent Injector `1`，明确 `NON_HA`；
- Integrated Storage Raft 单节点，Data PVC `10 GiB`；
- Audit PVC `5 GiB`；
- TLS ClusterIP-only，无 Ingress/Gateway/HTTPRoute/NodePort/LoadBalancer；
- Shamir `5/3`，只允许 OpenPGP 加密 share 与初始 root token；
- Audit file + stdout，默认 HMAC、`log_raw=false`；非 blocking device 至少一个可写时请求
  可继续，所有可用 device 都无法写入时 Fail Closed，任一 blocking device 失败还可能令
  请求挂起；
- Kubernetes Auth 与验证 Policy 只用于专用 probe，不读取现有应用 Secret；
- Runtime 激活不改变现有应用 Kubernetes Secret。

## 激活状态

| 能力 | 状态 |
| --- | --- |
| Desired State / validators / Stage 170 / Stage 180 | `IN_PROGRESS` |
| Runtime deployment | `NOT_EXECUTED` |
| Initialization / unseal / Auth / Policy / Audit | `NOT_EXECUTED` |
| MinIO / Snapshot / Backup / Restore | `NOT_EXECUTED` |
| Application Secret migration | `NOT_EXECUTED` |
| Final evidence | `NOT_EXECUTED` |

候选值必须在部署后与 Pod `imageID`、Chart/HelmRelease、Raft peer、PVC、TLS、Auth、Policy、
Audit 与业务健康 readback 对齐，才可把 Runtime 标记为已验收。DEV-005 不允许把运行时
验收解释为 Backup/Restore 或 Release Gate 通过。
