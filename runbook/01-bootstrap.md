# DEV Cluster Bootstrap 记录

> 仅记录 bootstrap 阶段获准的带外命令。后续 Desired State 只能通过本仓 PR 变更。

> **STOP GATE**：旧 Docker/Caddy 清退、全新 Kubernetes CRI runtime、稳定 DNS 与维护路径均完成并取得证据前，本页不得把任何运行时判定标为通过。

执行人：`root`
执行时间（含时区）：`2026-08-10 10:36:55 CST`（审计采集时间）
服务器标识：`retail-test-workflow`
GitOps commit / PR：  

## 旧 Docker/containerd 审计与清退决定

| 证据 | 回执 |
| --- | --- |
| 前置基线 | `/root/dev-infra-evidence/00-server-baseline-20260810T004203Z.txt`；SHA-256 `c100b23fbcc48253704c32bf7954b4dfc7e42ba9b831c2efb3fce488f56ea067` |
| 审计文件 | `/root/dev-infra-evidence/01-platform-server-pre-cleanup-20260810T023655Z.txt` |
| SHA-256 | `4634d71119324f451d0a055d10c373e08a208551f1b71c8ce5ee329d5cb1fc3c` |
| Docker / containerd.io / runc | Docker `29.6.1`；containerd.io `2.2.5`；runc `1.3.6` |
| Docker 与 containerd service/socket | 两个 service 均 enabled/running；Docker 通过 `/run/containerd/containerd.sock` 使用同一个 containerd |
| containerd config / CRI | config version `3`；`io.containerd.grpc.v1.cri` 被禁用；runc `SystemdCgroup = false`，不满足 Kubernetes 目标配置 |
| 运行容器 | 15 个：10 running、5 stopped；Coze Loop 全套与独立 `uni-mysql`；ClickHouse 处于持续重启状态 |
| 数据路径 | Docker volume 位于 `/var/lib/docker/volumes`；Coze Loop bind mount 位于 `/data/coze-loop` |
| 实际占用 | `/var/lib/docker` `6.1G`；`/var/lib/containerd` `20G` |
| 监听端口 | Docker 暴露 `3306`、`8082`、`8888`；Caddy 使用 `80`/`2019`；宿主机 `3001` 进程身份仍待核验 |
| 批准路径 | 用户确认旧业务与数据均可删除；服务器定位为“研发平台专有服务器”，不是 Kubernetes-only 节点 |

批准维护路径为：清退 Docker Engine、Caddy、Coze Loop、独立 `uni-mysql` 及旧共享 containerd 数据；随后从干净状态安装 PCS 锁定的 Kubernetes CRI runtime。不得把现有 Docker runtime 原地改造成 Kubernetes runtime。

当前 Docker APT 源只回报 containerd.io candidate `2.3.3`，未提供 PCS 锁定的 `2.3.1`。清退完成后，必须先验证 `2.3.1` 的可信供应路径与 digest；不得静默改装 `2.3.3`。

### 清退边界

允许永久删除：

- Docker 的全部 container、image、network、volume 与 `/var/lib/docker`。
- 旧共享 runtime 数据 `/var/lib/containerd` 及 Docker 提供的 `/etc/containerd/config.toml`。
- `/data/coze-loop`、Caddy package/config/data/log，以及 Docker APT source/key。

必须保留：

- Ubuntu 基础系统、SSH、systemd-networkd、systemd-resolved、chrony、APT、LVM、Swap、VMware Tools。
- `/root/dev-infra-evidence` 中的全部证据。
- 身份未核验的宿主机 `3001` 进程；在取得 executable、cwd 与启动来源证据前不得结束或删除。

清退完成回执：

```text
待运维回填清退证据文件与 SHA-256。
```

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
