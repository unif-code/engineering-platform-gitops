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

### 清退执行记录

第一次执行：

| 字段 | 回执 |
| --- | --- |
| 证据文件 | `/root/dev-infra-evidence/03-legacy-runtime-cleanup-20260810T025142Z.txt` |
| SHA-256 | `e758df7f2af5ce2ea43e10ef3aa75f18e7d936808ffa363ecda9bee6556c83af` |
| Exit code | `100`（未完成） |
| 已执行 | 15 个容器已关闭并删除；Caddy、Docker 与旧 containerd service 已 disable/stop |
| 未执行 | APT package purge、数据目录删除、bridge 删除及最终验证均未开始 |
| 根因 | Docker 相关 package 被 APT hold；`apt-get purge -y` 拒绝变更 held package |
| 续跑约束 | 仅解除 7 个明确清退目标的 hold；允许 purge held package；禁止执行 `apt autoremove` |

APT 报告的可自动移除项包含 `iptables`、`nftables`、`libnetfilter-conntrack3` 等后续 Kubernetes/Cilium 仍可能使用的宿主机网络组件，因此本阶段必须保留。

第二次执行：

| 字段 | 回执 |
| --- | --- |
| 证据文件 | `/root/dev-infra-evidence/04-legacy-runtime-cleanup-resume-20260810T025913Z.txt` |
| SHA-256 | `166d8a71b5c459356f6c668770d9e8565ced5ef3a3ebe21372333f50a42b4aed` |
| Exit code | `0`（成功） |
| Package | Caddy、Docker Engine/CLI/plugins/rootless extras 与 containerd.io 均已 purge；目标 package hold 已清空 |
| 数据 | `/var/lib/docker`、`/var/lib/containerd`、`/etc/{docker,containerd,caddy}`、`/opt/containerd`、`/data/coze-loop` 均已删除 |
| 网络 | `docker0`、`br-28cd7b020fce` 与旧端口 `80`、`2019`、`3306`、`8082`、`8888` 均已清退 |
| 主机健康 | SSH、chrony、systemd-networkd、systemd-resolved active；`ens160` up；Swap `3.8Gi` 保留 |
| 清退后容量 | 根文件系统使用 `11G/489G`，可用 `458G`，使用率 `3%`；内存可用 `61Gi` |

旧 Docker/Caddy/runtime 清退已关闭；没有执行 `apt autoremove`。宿主机仍有以下旧应用待单独审计和清退：

- `uniflow` 用户的 Node 进程监听 `*:3001`。
- executable：`/usr/local/lib/node-v24.18.0/bin/node`。
- cwd：`/data/workflow/apps/server`。
- cgroup：`/user.slice/user-0.slice/session-397.scope`，未发现 system service 归属证据。

### 宿主机 Workflow/Node 审计

| 字段 | 回执 |
| --- | --- |
| 证据文件 | `/root/dev-infra-evidence/05-host-workflow-audit-20260810T030918Z.txt` |
| SHA-256 | `3f3432d0e3a5fdef9da4f292e0329d598e7554f8af0e7ded2f2728b9dbdb4933` |
| 监听进程 | `*:3001`；PID `1034757`；用户 `uniflow`；executable `/usr/local/lib/node-v24.18.0/bin/node`；cwd `/data/workflow/apps/server` |
| 父进程链 | 两层 Node `MainThread` → `sh` → `npm exec tsx` → `bash`；整条链均属于 `uniflow`，cwd 均为 `/data/workflow/apps/server` |
| 会话归属 | 全部进程位于 `/user.slice/user-0.slice/session-397.scope`；对应旧 root SSH session `397`，RemoteHost `10.96.125.33`，状态 `closing` |
| 持久化检查 | root/uniflow crontab 均不存在；未发现用户 systemd unit、已安装 Workflow systemd unit、PM2、forever 或 Supervisor |
| 账号 | `uniflow` 为 UID/GID `1000`，仅属于 `uniflow` 与旧 `docker` 组；未登录且未启用 lingering；home 占用 `76K` |
| 应用数据 | `/data/workflow` 位于根文件系统，归 `uniflow` 所有；旧 Git 项目及依赖合计约 `2.2G`，包含应用 `.env`、`.git`、构建产物与 `node_modules` |
| Node runtime | `/usr/local/lib/node-v24.18.0` 为非 dpkg 管理的手工安装，约 `203M`；`node`、`npm`、`npx`、`corepack`、`pnpm`、`pnpx` 的 `/usr/local/bin` 链接均指向该目录 |
| 其余监听 | 除 DNS、NTP、SSH 与 `3001` 外，无其他旧应用监听端口 |

审计已确认 `3001` 为旧 Workflow 应用的孤立进程链，不属于当前 SSH 会话，也没有发现宿主机持久化启动入口。用户已批准清除旧安装及数据；下一维护动作可永久删除该进程链、`/data/workflow`、手工 Node runtime、`uniflow` 账号/home，以及清空后的旧 `docker` 组。

执行清退前仍须以进程 UID、cwd、executable、cgroup 与证据 SHA-256 做 fail-closed 复核；任一身份漂移必须停止，不得扩大删除范围。不得执行 `apt autoremove`，且必须保留 `/root/dev-infra-evidence` 与基础系统服务。

清退完成回执：

```text
Docker/Caddy/旧 containerd 清退完成；宿主机 workflow/Node 已核验，清退仍 PENDING。
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
