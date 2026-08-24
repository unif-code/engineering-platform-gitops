# Platform Compatibility Set Candidate 2

状态：`BLOCKED CANDIDATE`

环境：`DEV` / `NON_HA`

基线：`2026-08-23.1`

基础设施与运维架构：`engineering-platform-docs/architecture/09-infrastructure-operations.md`

架构参数：`engineering-platform-docs/architecture/appendix-parameters.md`

治理例外（DEV-001 / DEV-002 / DEV-004）：`engineering-platform-docs/architecture/deviations.md`

容量 Profile：`DEV-002` / `SINGLE_USER_MINIMAL`

目标平台：`linux/amd64`（已由服务器基线确认 `uname -m=x86_64`）

任何版本、Chart、Manifest 或 Image 变化都必须建立新的 PCS Candidate。候选 digest 只允许来自官方 Registry/Chart index 或 CI provenance，实际 digest 只允许来自部署 Image ID；不得填写猜测值。候选值仍需在部署后与实际 Image ID 比对。

## 事实采样

| 事实 | 值 |
| --- | --- |
| docs 架构事实提交 | `d6d846a612c974991f4d0ffc0685d06adf2ddfe7` |
| GitOps main 采样提交 | `1c5034b9a9c29ab72fde63644c57fa88604c45b6` |
| frontend Source Commit | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` |
| backend Source Commit | `647d509bca1bbf9ff0f6ab719d5905d8f836e92f` |
| DEV Runtime 当前观测时间 | `2026-08-24 03:42Z` |
| DEV Runtime 历史观测时间 | `2026-08-22 16:58 +08:00`（历史） |
| DEV Runtime 当前结论 | `run-approved --check` 的 8 个 stage 均通过或 `ALREADY_COMPLIANT`；仅 bootstrap 基础组件和 GitLab Runner 存在，Flux、平台基础设施与应用仍未激活 |

## 当前 DEV Runtime 观测

本节是外部 Chrome 堡垒机 root 会话在服务器 GitOps `main` 上只读执行 `run-approved --check` 的最新采样；不构成部署或应用验收。

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

## 组件锁定与运行状态

| 领域 | 组件 | 锁定版本 / Artifact | Image / Chart | 候选 / 实际 digest | 状态与备注 |
| --- | --- | --- | --- | --- | --- |
| Runtime | Kubernetes | `v1.36.3` | `registry.k8s.io/kube-{apiserver,controller-manager,scheduler}:v1.36.3` | 运行版本 `v1.36.3`；实际 Image ID 待回填 | Node `Ready`；kube-proxy 不部署 |
| Runtime | containerd | `2.3.1` | OS package / 官方二进制 | 运行版本 `2.3.1`；安装制品摘要见 bootstrap 证据 | CRI v1、config v4、cgroup v2 已验证 |
| Runtime | etcd | `3.6.8-0` | `registry.k8s.io/etcd:3.6.8-0` | index `sha256:397189418d1a00e500c0605ad18d1baf3b541a1004d768448c367e48071622e5`；amd64 `sha256:aa2b41e3f99c9a337b82f687875a63c5119e6d39bc43fc76b6c40a96f55cf391`；实际 Image ID 待回填 | kubeadm control plane Running；CronJob 尚未激活 |
| Runtime | CoreDNS | `v1.14.2` | `registry.k8s.io/coredns/coredns:v1.14.2` | 运行版本 `v1.14.2`；实际 Image ID 待回填 | 两副本 Ready |
| Network | Cilium | `1.20.0` | Helm `cilium/cilium` | Helm revision `1`、chart/app `1.20.0`；实际 Image ID 待回填 | kube-proxy replacement、Gateway API enabled；agent/operator/Envoy Ready |
| Network | Gateway API CRD | `v1.6.1` Standard | upstream release manifest | CRD 已安装；Manifest digest 待回填 | GatewayClass `cilium` Accepted；平台 Gateway/HTTPRoute 不存在 |
| GitOps | Flux | `v2.9.3` | bootstrap manifests | `BLOCKED` | Flux CRD、`flux-system` Namespace 与 Controller 均不存在；无 image automation |
| Storage | local-path-provisioner | `v0.0.31` | `docker.io/rancher/local-path-provisioner` | amd64 `sha256:5fb0394abf87407a27cc56db94334eb0c92d0b5de2636683a7ec51f38143dfc9` | **DEV-002 GAP**；平台 Desired State 未激活，运行补偿控制未验证 |
| Storage | local-path helper | `1.36.1-1` | `registry.k8s.io/e2e-test-images/busybox` | amd64 `sha256:caec39cad3b12c26600baf6e67ba811ac15d28a9288d0ccdfffb4b318992c3bb` | platform provisioner helper Pod 未部署 |
| PKI | cert-manager | `v1.21.1` | Helm chart `v1.21.1` | Chart/运行 digest 待部署回填 | `dev-selfsigned` 仅限 DEV；CRD/Controller 未部署 |
| Object Storage | MinIO Server | `RELEASE.2025-09-07T16-13-09Z` | `quay.io/minio/minio` | index `sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`；amd64 `sha256:a1a8bd4ac40ad7881a245bab97323e18f971e4d4cba2c2007ec1bedd21cbaba2` | **BLOCKED：精确摘要供应链证据或获批风险决定未满足；清单引用不代表获准或已部署** |
| Object Storage | MinIO Client (`mc`) | `RELEASE.2025-08-13T08-35-41Z` | `quay.io/minio/mc` | index `sha256:a7fe349ef4bd8521fb8497f55c6042871b2ae640607cf99d9bede5e9bdf11727`；amd64 `sha256:eb4ea9884b77704230e2423e9004d2fa738dc272876b9cc41a297d29443b8780` | 初始化、验证与 etcd 上传工具；未部署 |
| Database | CloudNativePG Operator | `1.30.0` | Helm chart `cloudnative-pg` `0.29.0` | chart `sha256:668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f`；运行镜像待部署回填 | CRD/Operator 未部署 |
| Database | PostgreSQL | `18.4` | `ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie` | index `sha256:f0cc49632b5cc1e51f65ba03658c89bd31d64ea2672b14843a808a8d281417e1`；amd64 `sha256:ae0ec6943c3c24b0de87f93b73ac531a8e546a4cc895655f793547eed2fdbef1` | Cluster 未部署 |
| Database | Barman Cloud Plugin | `0.13.0` | Helm chart `plugin-barman-cloud` `0.7.0` | chart `sha256:683494c04cc94f7d33c4ac5f3d8d64c209634b48bd0e84da31d7d1fad22cdcdb`；运行镜像待部署回填 | Plugin/备份对象未部署 |
| Observability | kube-prometheus-stack | `88.1.5` | Helm chart `kube-prometheus-stack` | Chart/运行 digest 待部署回填 | 未部署；Grafana Managed Alerting off |
| Observability | Metrics Server | app `0.8.1` / chart `3.13.1` | Helm chart `metrics-server` | chart `sha256:084e6edb680cf4e2acc30bd496568c53fdf663cbacf6e17876b25785c35b7a13`；index `sha256:b2d2efaf5ac3b366ed0f839d2412a2c4279d4fc2a2a733f12c52133faed36c41`；amd64 `sha256:6231fb0a1ffab76c92ab880f51a0d11b290f688373647bcedff85af025dfd8a9` | 未部署；禁止任何 insecure TLS 参数 |
| Application | engineering-platform-backend | Source `647d509bca1bbf9ff0f6ab719d5905d8f836e92f` | 当前 Source Commit 无候选 image | `BLOCKED` | 历史 commit `1d627b9` 的 digest `sha256:c77fb2d88a61659fa8c2b5074a4ea3103002698085e578652d999d2e2b45e8d7` 不得作为当前候选；无工作负载 |
| Application | engineering-platform frontend | Source `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` / CI run `32683635240`、publish-image job `97305929974`（均 `success`） | `ghcr.io/unif-code/engineering-platform:sha-da72238`；OCI index `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` | linux/amd64 manifest `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`；运行 Image ID `NOT_VERIFIED` | 当前 provenance 与 linux/amd64 manifest 已确认；工作负载未部署 |

## 当前 frontend 候选

| 字段 | 值 |
| --- | --- |
| Source Commit | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` |
| CI run | `32683635240` |
| publish-image job | `97305929974` |
| Image tag | `sha-da72238` |
| CI provenance | `VERIFIED` |
| Artifact / OCI index digest | `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` |
| linux/amd64 manifest digest | `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` |
| Runtime Image ID | `NOT_VERIFIED` |

CI run `32683635240` 与 publish-image job `97305929974` 均已 `success`，发布 tag 为 `ghcr.io/unif-code/engineering-platform:sha-da72238`。workflow 的 `build --platform linux/amd64`、导出 manifest 日志与独立 attestation manifest 均确认该 digest 为可部署的 `linux/amd64` manifest。当前候选不得复用带日期的历史制品观察；运行 Image ID 在工作负载部署前仍 fail-closed。

## 2026-08-22 frontend 历史证据

此段只保留 `2026-08-22` 的历史观察，不代表当前 frontend 候选、当前制品或运行状态。

| 字段 | 值 |
| --- | --- |
| Source Commit | `c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c` |
| OCI index digest | `sha256:ee548974e159916ba7ca0fafe8bb30d72722a34625ffbce31d6e495324d06c0c` |

## 当前阻塞依赖

| 依赖 | 状态 |
| --- | --- |
| Flux | `BLOCKED` |
| MinIO | `BLOCKED` |

## 已拒绝的 MinIO 替代候选

采样日期：`2026-08-23`

候选结论：`REJECTED`（不进入 Deployment，不构成 DEV 风险批准）。

| 组件 | 精确候选 | 可复现的精确摘要证据 |
| --- | --- | --- |
| MinIO Server | `cgr.dev/chainguard/minio`；index `sha256:cc18cac5456a3718bde96c368beaed53b9b876233f28c5f68b8fb667b9a528a7`；linux/amd64 `sha256:c9680a1ad80b56c67b2b9e44cc480a8fd0fb4362dab01f68b8bfbccae9d77596` | `NOT_VERIFIED` |
| MinIO Client | `cgr.dev/chainguard/minio-client`；index `sha256:b456af84dd3aa6883e67a74e2cc9aca9b1e060197dcd040d73bdec9e8c6b99fb`；linux/amd64 `sha256:043d0ad5c2b297c0f0382dcac9b9436483d9f4a1d16cecdcc9471affb5e643e4` | `NOT_VERIFIED` |

拒绝原因：

- MinIO 与 MinIO Client 的精确 digest provenance、可保存的 SBOM、签名验证回执及 digest-specific scan 均未取得可复现证据。供应商公开产品页可随时变化，不能代替精确摘要的扫描结论。
- 供应链证据：`NOT_VERIFIED`。
- 激活结论：`BLOCKED`。当前 GitOps 清单继续保留原始阻塞引用；未做风险批准，不得切换、部署或激活上述摘要。

## 2026-08-21 历史 Bootstrap 证据

| 证据 | 结果 |
| --- | --- |
| `/root/dev-infra-evidence/07-preflight-20260821T071118Z.txt` | `PASS_PREFLIGHT`；SHA-256 `9d8a287936c14362899d26846cd92a3a0927fa392af1c74efda599c2f774fe20` |
| `/root/dev-infra-evidence/14-verify-20260821T073936Z.txt` | `PASS_BOOTSTRAP_VERIFIED`；SHA-256 `0c0b06a4b19c8cfe5169357be572dad77acdf227aeccdd6aa7ae82003a9d1daa` |

## 部署后核验

```bash
kubectl --kubeconfig=/etc/kubernetes/admin.conf get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
```

- [x] Node Ready，Kubernetes/containerd/Cilium/Gateway API 运行版本已观察。
- [x] bootstrap preflight 与 final verify 证据及 SHA-256 已回填。
- [ ] Flux 安装并形成 Inventory/Condition 证据。
- [ ] MinIO 供应链阻塞关闭并记录可信构件或明确风险决定。
- [x] frontend linux/amd64 manifest digest 已由 workflow、CI log 与 attestation 独立确认。
- [ ] backend 当前 digest 与 frontend/backend 实际 Image ID 回填。
- [ ] 所有计划组件逐项与实际版本、Chart Revision、Image digest 对齐。
- [ ] 无 `latest`、无浮动 tag、无未解释的 digest 漂移。
- [ ] DEV-002 运行补偿控制完成验收。
