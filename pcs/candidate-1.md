# Platform Compatibility Set Candidate 1

状态：`CANDIDATE`  
环境：`DEV` / `NON_HA`  
基线：`2026-08-09.2`

任何版本、Chart、Manifest 或 Image 变化都必须建立新的 PCS Candidate。`实际 digest` 只允许由部署或官方 Registry 查询结果回填；不得填写猜测值。

| 领域 | 组件 | 锁定版本 / Artifact | Image / Chart | 实际 digest | 状态与备注 |
| --- | --- | --- | --- | --- | --- |
| Runtime | Kubernetes | `v1.36.3` | `registry.k8s.io/kube-{apiserver,controller-manager,scheduler}:v1.36.3` | 待部署回填 | kube-proxy 不部署 |
| Runtime | containerd | `2.3.1` | OS package / 官方二进制 | 待安装回填 | CRI v1、config v4、cgroup v2 |
| Runtime | etcd | `3.6.8-0` | `registry.k8s.io/etcd:3.6.8-0` | `sha256:397189418d1a00e500c0605ad18d1baf3b541a1004d768448c367e48071622e5` | kubeadm v1.36.3 锁定；CronJob 同版本 |
| Runtime | CoreDNS | `v1.14.2` | `registry.k8s.io/coredns/coredns:v1.14.2` | 待部署回填 | kubeadm v1.36.3 锁定 |
| Network | Cilium | `1.20.0` | Helm `cilium/cilium` | 待部署回填 | kube-proxy replacement、Gateway API enabled |
| Network | Gateway API CRD | `v1.6.1` Standard | upstream release manifest | 待部署回填 | bootstrap 带外安装，命令留证 |
| GitOps | Flux | `v2.9.3` | bootstrap manifests | 待部署回填 | 仅四个 Controller；无 image automation |
| Storage | local-path-provisioner | `v0.0.31` | upstream release manifest | 待部署回填 | 与实施计划命令保持一致；运行前需确认是否升级到当前 stable |
| PKI | cert-manager | `v1.21.1` | Helm chart `v1.21.1` | 待部署回填 | `dev-selfsigned` 仅限 DEV |
| Object Storage | MinIO Server | `RELEASE.2025-09-07T16-13-09Z` | `quay.io/minio/minio` | `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e` | **BLOCKED：上游已归档且该预构建版本早于最后 CVE 修复版本；合并前需风险决策或提供内部构建 digest** |
| Object Storage | MinIO Client (`mc`) | `RELEASE.2025-08-13T08-35-41Z` | `quay.io/minio/mc` | 待回填 index digest | 初始化与 etcd 上传工具 |
| Database | CloudNativePG Operator | `1.30.0` | Helm chart `cloudnative-pg` `0.29.0` | 待部署回填 | Chart `appVersion=1.30.0` |
| Database | PostgreSQL | `18.4` | `ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie` | `sha256:f0cc49632b5cc1e51f65ba03658c89bd31d64ea2672b14843a808a8d281417e1` | Cluster 清单按 digest 引用 |
| Database | Barman Cloud Plugin | `0.13.0` | Helm chart `plugin-barman-cloud` `0.7.0` | 待部署回填 | Chart `appVersion=v0.13.0` |
| Observability | kube-prometheus-stack | `88.1.5` | Helm chart `kube-prometheus-stack` | 待部署回填 | 单副本；Grafana Managed Alerting off |
| Application | engineering-platform-backend | 待 Task 7 构建 | `ghcr.io/unif-code/engineering-platform-backend@sha256:…` | **BLOCKED** | 由 backend owner 提供首个 digest |
| Application | engineering-platform frontend | 待 Task 7 构建 | `ghcr.io/unif-code/engineering-platform@sha256:…` | **BLOCKED** | 由 frontend owner 提供首个 digest |

## 部署后核验

```bash
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
```

- [ ] 所有计划组件逐项与实际版本、Chart Revision、Image digest 对齐。
- [ ] 无 `latest`、无浮动 tag、无未解释的 digest 漂移。
- [ ] MinIO 供应链阻塞已关闭并记录决策证据。
- [ ] frontend/backend 首个发布 digest 已回填。
