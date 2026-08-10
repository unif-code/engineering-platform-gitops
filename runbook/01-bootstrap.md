# DEV Cluster Bootstrap 记录

> 仅记录 bootstrap 阶段获准的带外命令。后续 Desired State 只能通过本仓 PR 变更。

> **STOP GATE**：现有 Docker/containerd 共存审计、稳定 DNS 与维护路径未获用户确认前，本页不得回填安装命令或把任何运行时判定标为通过。

执行人：  
执行时间（含时区）：  
服务器标识：  
GitOps commit / PR：  

## 现有 Docker/containerd 共存审计

| 证据 | 回执 |
| --- | --- |
| 审计文件 | |
| SHA-256 | |
| Docker / containerd.io / runc package version | |
| Docker 与 containerd service/socket | |
| containerd config version / CRI plugin 状态 | |
| 运行容器与恢复方法 | |
| `/var/lib/docker` / `/var/lib/containerd` 实际占用 | |
| 批准路径与 Decision | `PENDING` |

批准路径只能是：共享 runtime 维护窗口升级到 2.3.1、独立 Kubernetes CRI containerd 2.3.1，或以新增 DEV-only Decision 保留经验证兼容的 2.2.5。不得在审计回执前预选。

## containerd 与内核前置

命令与输出：

```text
待运维回填。
```

判定：

- [ ] containerd 版本、service、socket 与 data-root 符合已批准路径；若不是 `2.3.1`，已关联独立 DEV-only Decision。
- [ ] `SystemdCgroup = true`，cgroup v2 生效。
- [ ] `overlay`、`br_netfilter` 已加载，`net.ipv4.ip_forward = 1`。

## kubeadm 单节点

kubeadm 配置必须包含以下 kubelet 配置；保留主机 Swap，但 Pod 不使用 Swap。为安全提供 Metrics API，同时请求由 Cluster CA 签发的 kubelet serving certificate：

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
failSwapOn: false
memorySwap:
  swapBehavior: NoSwap
serverTLSBootstrap: true
```

`serverTLSBootstrap` 产生的 `kubernetes.io/kubelet-serving` CSR 必须由运维核对请求者、用途及节点 DNS/IP SAN 后人工批准；核心 Kubernetes 不自动批准 serving CSR。禁止为通过 metrics-server 验收添加 `--kubelet-insecure-tls`。

命令与输出：

```text
待运维回填。
```

判定：

- [ ] Kubernetes 为 `v1.36.3`，节点为 `Ready`。
- [ ] kubelet 为 `failSwapOn=false`、`memorySwap.swapBehavior=NoSwap`；`/swap.img` 保留且 Pod 不使用 Swap。
- [ ] kubelet serving certificate 由 Cluster CA 签发、SAN 匹配节点；CSR 审批证据已留存。
- [ ] 使用稳定端点 `dev-cp.unif.internal:6443`。
- [ ] 未部署 kube-proxy，Cilium `1.20.0` Ready。
- [ ] Gateway API Standard CRD `v1.6.1` 已安装。
- [ ] local-path-provisioner 已安装且 `local-path` 不是默认 StorageClass。

`kubectl get nodes -o wide`：

```text
待运维回填。
```

## Flux bootstrap

命令与输出：

```text
待运维回填。
```

判定：

- [ ] Flux CLI / Controller 为 `v2.9.3`。
- [ ] Git deploy key 为只读。
- [ ] 仅 source/kustomize/helm/notification 四个 Controller。
- [ ] `kustomize-controller` 与 `helm-controller` 启用 `--no-cross-namespace-refs=true`。
- [ ] `flux check` 通过。
