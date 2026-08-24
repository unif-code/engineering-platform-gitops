# Flux Phase A bundle

本目录的 Phase A 只安装 Flux Controller 基础层。它不创建 Git 凭据、
`GitRepository`、Flux `Kustomization`、`HelmRelease`，也不激活
`infrastructure/`、`apps/` 或任何业务工作负载。

## 生成来源

- Flux CLI：`v2.9.3`
- darwin/amd64 archive SHA-256：
  `cfe276124801f2057b7960b5ac2fe5dc019cdf245d1e791ed947b9f4e97e06c2`
- linux/amd64 archive SHA-256：
  `eae4e8608c0ade2bf4e8dec1669dbb6b0c28b5822b252d97feccfb4fb1181fd2`
- `gotk-components.yaml` SHA-256：
  `c6e84495c3b611978d053adc40aca1e2a12af38f6e239c44a6b6c1224e01cab7`

固定生成命令：

```bash
flux install \
  --namespace=flux-system \
  --components=source-controller,kustomize-controller,helm-controller,notification-controller \
  --network-policy=true \
  --watch-all-namespaces=true \
  --export
```

`gotk-components.yaml` 保留上游生成结果；本项目的收敛通过
`kustomization.yaml`、`phase-a-rbac.yaml` 和 `phase-a-network-policy.yaml`
完成。重新生成时必须先校验 CLI archive SHA-256，再证明生成文件 SHA-256 与上面的
固定值一致。

## Controller 镜像

Kustomize 将上游 tag 替换为精确的 linux/amd64 manifest digest。OCI index digest
同时记录在这里用于供应链复核，但不得直接作为单架构运行时 pin。

| Controller | Version | OCI index | linux/amd64 manifest |
| --- | --- | --- | --- |
| source-controller | `v1.9.3` | `sha256:ff8f3c92f1bcb433e858c948040c3a3393fe73f5dd72048a4502bfaf0a4c26cd` | `sha256:c6c82b3182f48b833252c71aefa0741957ca18296612bc6d2b9b5fb276f926e4` |
| kustomize-controller | `v1.9.4` | `sha256:2b8bec54ffb6caf421bd2a6c005d27f567d5dd4db7feb55794fb51fcabd69b8f` | `sha256:3e57aecb74419be93d09ba062cfc882bea405193c474009e0da1826de71a4ebd` |
| helm-controller | `v1.6.3` | `sha256:16ada99456385100698a5d7adf90aba8a2089d987ab541c9566b6d7b0e897038` | `sha256:22c0a585d0d9b1f792b9d5638144b7810e273d28e310da37740f01226bd044a2` |
| notification-controller | `v1.9.2` | `sha256:9ce503e7bcb8493fafe2aaef0c2ac4396df4f6890256acf9cd444a2dcd2a69ed` | `sha256:cb17eefffbc442412ba6f63336defd04c0fc387d5082d951998d1ff163a9180d` |

## Phase A 安全收敛

- 只保留四个 Controller，并限制为 `flux-system` 单 Namespace watch。
- kustomize/helm 使用无权限 `default` ServiceAccount 作为 Reconcile impersonation 后备；
  Phase A 不启用 `ObjectLevelWorkloadIdentity`，也不配置需要该 feature gate 与 Token
  创建权的 source/notification/decryption/kubeconfig 默认身份。
- 删除上游 `cluster-admin` binding、未安装 Controller 的潜伏 subject、用户聚合角色
  和未启用能力所需的 ServiceAccount token 创建权。
- 四个 Controller 各自使用一对一 namespaced Role/RoleBinding，只能写自己的 Flux
  API group；依赖的 source/core 资源只读，Leader Election 只允许 Lease
  `create/get/update`。规则以表中各精确版本的官方 `config/rbac/role.yaml` 为基线，
  去掉 Phase A 未启用的 Workload Identity token 与跨 Controller 写权。集群级权限只剩
  Kubernetes API `/livez/ping` 的 `HEAD` 健康探测。
- 使用 Pod Security `restricted`、non-root、只读根文件系统、drop `ALL`、
  `RuntimeDefault` seccomp 和固定资源边界。
- 删除上游宽松 NetworkPolicy，改为双向 default deny，仅放行 DNS、Kubernetes API
  以及四个 Controller 在 `flux-system` 内访问 source artifact 与 notification
  event 的 `9090` 内部端点。
- `gotk-sync.yaml` 保持 `ACTIVE: false` 且不进入 Kustomize resources；Phase A 不允许
  Git、OCI、Helm 或任意公网出站。

Phase C 启用 sync 前必须完成独立的 ServiceAccount impersonation RBAC POC；需要
Workload Identity 时还必须单独评审 feature gate、Token 子资源权限与身份边界。不得把
Controller 身份恢复为 `cluster-admin`。

## 本地验证

```bash
python3 -B scripts/run_validation.py --validate-catalog
python3 -B scripts/validate.py
./scripts/validate-static.sh
kubectl kustomize clusters/dev/flux-system
kubectl kustomize clusters/dev
git diff --check
```

渲染结果必须仍然只有四个 Flux Deployment，且不含 `GitRepository`、Flux
`Kustomization`、`HelmRelease` 或下游 Namespace。
