# DEV 单节点 Bootstrap Fail-Closed Design

状态：已完成对话式设计确认，等待书面审阅

工作分支：`feat/bootstrap-fail-closed-v01`

目标主机：`retail-test-workflow` / Ubuntu 24.04.4 LTS / `linux/amd64`

控制面地址：`10.93.1.27:6443`
服务器仓库：`/opt/uni-code/engineering-platform-gitops`（脚本从自身路径解析仓库根，不依赖当前工作目录）

## 1. 目标

在不触碰 `engineering-platform` 前端仓和 backend 仓的前提下，为单节点 DEV 主机建立一组可审计、可分阶段执行、默认拒绝危险状态的 bootstrap 工具。第一阶段从已完成的旧运行时清退证据开始，完成以下闭环：

1. 验证主机身份、网络、内核与旧运行时清退证据。
2. 从官方来源获取并固定 containerd 及全部配套制品。
3. 配置 Kubernetes 所需内核模块与 sysctl。
4. 安装并验证 containerd、runc、CNI plugins 和 crictl。
5. 安装并锁定 Kubernetes `v1.36.3` 的 kubelet、kubeadm 和 kubectl。
6. 使用固定 IP 初始化无 kube-proxy 的单节点 control plane。
7. 安装 Gateway API Standard CRD `v1.6.1` 与 Cilium `1.20.0`。
8. 验证节点 `Ready`、Cilium 健康且集群不存在 kube-proxy。

每个服务器阶段单独执行并停止。任何后续阶段只能在用户返回当前阶段的完整回执后再给出命令。

## 2. 非目标

本阶段不执行以下工作：

- Flux bootstrap。
- local-path-provisioner、cert-manager、Observability 的部署。
- MinIO、CloudNativePG、etcd backup 的部署。
- frontend/backend 应用部署。
- Secret 创建或读取 Secret 值。
- 自动重置已有 Kubernetes 集群。
- 自动回滚、自动清理未知状态或 `apt autoremove`。
- 对 `main` 的直接提交或 push。

## 3. 已确认决策

| 主题 | 决策 |
| --- | --- |
| Git 工作方式 | 所有设计、脚本、测试与文档仅进入 `feat/bootstrap-fail-closed-v01`；`main` 保持不变 |
| 现有仓库内容 | 全部保留，不删除、不重命名；未来组件标记为 `STAGED` 或 `BLOCKED` |
| 激活方式 | 注释仅用于说明；真正的停止机制是从活动 Kustomize/Flux 引用链断开 |
| containerd 来源 | 官方 GitHub release 的 `containerd-2.3.1-linux-amd64.tar.gz` |
| containerd artifact SHA-256 | `628448bd973610c656c1cbea8e88b32fafd85b23cc1aa4a3372eb7198478c054` |
| containerd 配置 | config version 4、CRI v1、overlayfs、runc v2、`SystemdCgroup = true` |
| runc | `v1.3.6` 官方 `linux/amd64` artifact |
| CNI plugins | `v1.9.1` 官方 `linux/amd64` artifact |
| crictl | `v1.36.0` 官方 `linux/amd64` artifact；固定显式 containerd endpoint |
| Kubernetes | `v1.36.3`，只接受官方 `pkgs.k8s.io` v1.36 APT repository 的精确 package 版本 |
| Helm CLI | `v3.21.0` 官方 `linux/amd64` artifact；只用于固定 Cilium chart 的安装与核验 |
| Cilium | Helm chart `1.20.0`，启用 kube-proxy replacement 与 Gateway API |
| Gateway API | Standard CRD `v1.6.1` 官方 release manifest |
| API Server | advertise address 与 certificate IP SAN 均为 `10.93.1.27`；control plane endpoint 为 `10.93.1.27:6443` |
| Service CIDR | `172.20.0.0/16`，仅在服务器地址和全部本地路由无重叠时允许使用 |
| Pod CIDR | `172.21.0.0/16`，仅在服务器地址和全部本地路由无重叠时允许使用 |
| Swap | 保留主机 `/swap.img`；kubelet `failSwapOn=false` 且 Pod 使用 `NoSwap` |
| kube-proxy | kubeadm 跳过 `addon/kube-proxy`；Cilium 完整替代 |
| 完成边界 | Cilium 健康且单节点 `Ready`；Flux 与平台组件属于后续阶段 |

版本选择依据：

- [containerd 2.3.1 release](https://github.com/containerd/containerd/releases/tag/v2.3.1)
- [containerd 官方安装说明](https://github.com/containerd/containerd/blob/main/docs/getting-started.md)
- [containerd 配置版本与 Kubernetes 兼容矩阵](https://github.com/containerd/containerd/blob/main/RELEASES.md)
- [runc 1.3.6 release](https://github.com/opencontainers/runc/releases/tag/v1.3.6)
- [CNI plugins 1.9.1 release](https://github.com/containernetworking/plugins/releases/tag/v1.9.1)
- [Kubernetes v1.36 kubeadm 安装文档](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/)
- [kubeadm v1beta4 配置 API](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/)
- [Cilium 无 kube-proxy 安装说明](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/)

## 4. 现有 Desired State 的保留与隔离

### 4.1 保留规则

现有 `clusters/`、`infrastructure/`、`apps/`、`pcs/`、`runbook/` 与 `scripts/` 文件全部保留。未来组件文件顶部增加统一说明，至少包含：

```text
STATUS: STAGED 或 BLOCKED
ACTIVE: false
REASON: 当前停止原因
ACTIVATION_GATES: 必须关闭的前置 Gate
```

这些字段是审计信息，不承担技术隔离功能。

### 4.2 技术隔离

`clusters/dev/kustomization.yaml` 在本阶段只允许引用 `flux-system`。以下现有入口继续保留，但不得从活动入口可达：

- `reconcile-rbac.yaml`
- `infrastructure.yaml`
- `apps.yaml`

这同时避免当前 5 个 `cluster-admin` binding、MinIO、CNPG、Observability、etcd backup 与 Gateway 在 Flux 启用后被意外创建。

`clusters/dev/flux-system/gotk-components.yaml` 与 `gotk-sync.yaml` 保留路径并标记为未生成；本阶段不伪造 Flux Controller 或 GitRepository 内容。后续 Flux bootstrap 必须用锁定版本生成真实内容，再单独审阅。

### 4.3 自动 Gate

仓库测试必须证明：

- 活动根只能到达 `clusters/dev/flux-system`。
- 所有 `STAGED/BLOCKED` 路径无法从活动根渲染。
- MinIO 的文档 `BLOCKED` 状态不会仅靠注释维持。
- 任何把 `reconcile-rbac.yaml`、`infrastructure.yaml` 或 `apps.yaml` 接回活动根的改动都会使测试失败，除非同步更新明确的激活 allowlist。

## 5. 新增文件边界

```text
bootstrap/
  artifacts.lock.tsv
  containerd/config.toml
  containerd/containerd.service
  kubeadm/init.yaml
  cilium/values.yaml

scripts/bootstrap/
  lib/common.sh
  check_cidrs.py
  00-preflight.sh
  10-stage-artifacts.sh
  20-prepare-kernel.sh
  30-install-containerd.sh
  40-install-kubernetes.sh
  50-kubeadm-init.sh
  60-install-cilium.sh
  90-verify.sh

scripts/test_bootstrap.py
```

每个文件只有一个职责：

- `artifacts.lock.tsv`：版本、官方 URL、SHA-256、预期文件名与安装目标的唯一机器可读来源。
- `containerd/config.toml`：containerd 2.3.1 的完整 config v4 目标配置。
- `containerd/containerd.service`：随 Git 审阅和版本化的 systemd unit，安装阶段不从网络即时获取 unit。
- `kubeadm/init.yaml`：固定 control plane、CIDR、Swap 与无 kube-proxy 配置。
- `cilium/values.yaml`：固定 Cilium kube-proxy replacement、API endpoint、IPAM 与 Gateway API 配置。
- `common.sh`：日志、root/host 身份检查、文件摘要、原子写入、证据封装和统一退出码。
- `check_cidrs.py`：仅使用 Python 标准库解析本机 IPv4 地址与路由并检查 CIDR 重叠。
- 数字前缀脚本：一个文件对应一个可独立授权、执行和验收的服务器阶段。
- `test_bootstrap.py`：静态合同、fake PATH 行为与幂等测试。

## 6. Artifact Lock 与供应链

`artifacts.lock.tsv` 使用固定五列：

```text
name<TAB>version<TAB>url<TAB>sha256<TAB>target
```

约束如下：

1. `version` 必须是精确版本，禁止 `latest`、`stable`、`main`、`master` 或版本范围。
2. `url` 必须包含版本，且 host 必须在代码内的官方来源 allowlist 中。
3. `sha256` 必须是 64 位小写十六进制；下载完成后先校验再解包。
4. tar archive 在解包前检查绝对路径、`..` 穿越、异常 symlink 和预期文件清单。
5. 所有文件先放入 `/root/dev-infra-artifacts/pcs-2026-08-10.1`，目录权限为 `0700`。
6. 安装阶段禁止联网，只消费已验证的本地 staged artifacts。
7. Kubernetes APT repository 必须使用独立 `signed-by` keyring；package candidate 和实际 `.deb` metadata 必须精确匹配 `v1.36.3`，安装后立即 `apt-mark hold`。
8. 下载或 APT metadata 中出现同版本不同 digest 时，结果是 `STOP_SUPPLY_CHAIN_MISMATCH`，不得自动接受新值。

锁清单精确覆盖七项：containerd archive、runc、CNI plugins、crictl、Helm CLI、Gateway API Standard manifest 和 Cilium chart。containerd systemd unit 作为仓库内审阅文件交付，安装时记录 Git blob 与文件 SHA-256，不属于网络下载制品。Kubernetes package 的签名 repository metadata、package version 与下载后的 `.deb` SHA-256 同样进入 evidence。

## 7. 阶段数据流

### 7.1 `00-preflight.sh`

只读检查：

- 当前用户为 root。
- hostname 精确为 `retail-test-workflow`。
- `/etc/os-release` 为 Ubuntu 24.04 系列。
- `uname -m` 为 `x86_64`。
- `10.93.1.27` 绑定在本机 UP 状态网卡。
- cgroup filesystem 为 `cgroup2fs`。
- `/swap.img` 保留，且 Swap 总量符合既有证据。
- chrony/NTP、systemd-networkd、systemd-resolved 与 SSH 保持健康。
- `/root/dev-infra-evidence/06-host-workflow-cleanup-20260810T033358Z.txt` 的 SHA-256 精确为 `a68a3d2ff340bcdcb4265853107a3a2c22a9f7328728473d81d9be2d1486e635`。
- Docker、Caddy、旧 containerd、Node/Workflow 与端口 3001 仍不存在。
- Service CIDR 和 Pod CIDR 不与本机地址、全部 IPv4 route table 或彼此重叠。

通过结果为 `PASS_PREFLIGHT`。检查无法证明组织网络全局未使用 CIDR，因此 evidence 必须保留 `SERVER_LOCAL_SCOPE_ONLY` 限制说明。

### 7.2 `10-stage-artifacts.sh`

`--check` 只验证网络、allowlist、staging 目录和磁盘空间；`--apply` 下载并验证全部制品。该阶段不写 `/usr/local`、`/etc`、`/opt/cni`、APT source 或 systemd。

通过结果为 `PASS_ARTIFACTS_STAGED`。精确 artifact 已存在时返回 `ALREADY_COMPLIANT`；同名文件摘要不同则停止，不覆盖。

### 7.3 `20-prepare-kernel.sh`

管理两个明确文件：

- `/etc/modules-load.d/99-kubernetes.conf`
- `/etc/sysctl.d/99-kubernetes-cri.conf`

目标模块为 `overlay` 与 `br_netfilter`；目标 sysctl 为：

```text
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
net.ipv4.ip_forward=1
```

写入使用同目录临时文件、`fsync` 与原子 rename。目标文件已存在但内容不受本脚本管理时停止，不自动接管。写入后重新加载并逐项读取 `/proc/sys` 验证。

### 7.4 `30-install-containerd.sh`

安装位置固定为：

- containerd binaries：`/usr/local/bin`
- runc：`/usr/local/sbin/runc`
- CNI plugins：`/opt/cni/bin`
- crictl：`/usr/local/bin/crictl`
- systemd unit：`/usr/local/lib/systemd/system/containerd.service`
- config：`/etc/containerd/config.toml`
- root：`/var/lib/containerd`
- state/socket：`/run/containerd` 与 `/run/containerd/containerd.sock`

任何未知 containerd/runc/crictl binary、非空旧 data root、未知 service unit 或未知 config 都是停止条件。安装后验证 binary version、config version 4、CRI plugin、overlayfs、runc v2、`SystemdCgroup=true`、service active/enabled 与 socket 权限；`crictl info` 必须显式使用 `unix:///run/containerd/containerd.sock`，要求 `RuntimeReady=true`，Cilium 安装前允许 `NetworkReady=false`。

### 7.5 `40-install-kubernetes.sh`

只配置官方 v1.36 APT repository，安装精确版本的 kubelet、kubeadm、kubectl 及其明确依赖，然后 hold。检测到其他 Kubernetes minor repository、浮动 candidate、未知 package hold 或已安装不同版本时停止。

kubelet 在 kubeadm init 前可能处于等待配置的 restart 状态；脚本只接受官方预期状态，不把它误判为完整失败。

### 7.6 `50-kubeadm-init.sh`

执行前重新运行所有关键只读检查，并使用 `kubeadm config validate` 和 `kubeadm init phase preflight`。以下任一对象存在即停止，不运行 reset：

- `/etc/kubernetes/admin.conf`
- `/etc/kubernetes/manifests/kube-apiserver.yaml`
- `/var/lib/etcd/member`
- API port 6443 的未知 listener

配置必须包含：

- `kubeadm.k8s.io/v1beta4`
- `kubernetesVersion: v1.36.3`
- `controlPlaneEndpoint: 10.93.1.27:6443`
- API advertise address 与 certificate SAN `10.93.1.27`
- `serviceSubnet: 172.20.0.0/16`
- `podSubnet: 172.21.0.0/16`
- `skipPhases: [addon/kube-proxy]`
- kubelet `cgroupDriver: systemd`
- `failSwapOn: false`
- `memorySwap.swapBehavior: NoSwap`
- `serverTLSBootstrap: true`

脚本不得输出 bootstrap token、certificate key 或 kubeconfig 内容。成功后只报告文件存在性、权限、证书 subject/SAN/期限摘要与 control plane component 状态。

### 7.7 `60-install-cilium.sh`

先校验并安装 Gateway API Standard CRD `v1.6.1`，再用 staged Helm CLI 与 staged Cilium chart 安装。固定值至少包括：

- `kubeProxyReplacement=true`
- `k8sServiceHost=10.93.1.27`
- `k8sServicePort=6443`
- `ipam.mode=kubernetes`
- `gatewayAPI.enabled=true`
- cgroup host root `/sys/fs/cgroup`

Helm install 使用 `--atomic`、固定 namespace 与超时；禁止在线 repo update、浮动 chart 或临时 `--set` 覆盖 lock 文件。底层内核能力不足时 Cilium 必须失败，脚本不得降级关闭 kube-proxy replacement。

### 7.8 `90-verify.sh`

最终只读验证：

- containerd、runc、CNI、kubelet、kubeadm、kubectl 精确版本。
- containerd CRI v1 健康且 systemd cgroup 生效。
- API endpoint 为 `10.93.1.27:6443`。
- control plane static Pods 健康。
- 不存在 kube-proxy DaemonSet、Pod 或 config。
- Cilium DaemonSet、operator、CNI 与 kube-proxy replacement 健康。
- Gateway API Standard CRD 版本符合 `v1.6.1`。
- Node 为 `Ready`，InternalIP 为 `10.93.1.27`。
- Swap 仍启用，kubelet 为 `NoSwap`。
- kubelet serving CSR 存在时仅报告 metadata、requester、usages 和 SAN；本阶段不自动批准。

## 8. Fail-Closed 行为

所有修改型脚本默认执行 `--check`，只有显式 `--apply` 才允许写系统。不存在串联全部阶段的 `all.sh` 或自动继续开关。

统一结果：

```text
PHASE=<阶段>
MODE=CHECK|APPLY
RESULT=PASS_*|ALREADY_COMPLIANT|STOP_*
REASON=<无敏感信息的原因>
EVIDENCE=<文件路径>
SHA256=<证据摘要>
EXIT_CODE=<数字>
NEXT=<允许的下一阶段或 NONE>
```

统一退出码：

| Exit code | 含义 |
| --- | --- |
| `0` | 检查通过或已精确符合目标状态 |
| `10` | 主机身份、前置证据或授权前置不满足 |
| `20` | 供应链、版本、URL 或 digest 不匹配 |
| `30` | 检测到未知、漂移或部分安装状态 |
| `40` | 获准 apply 未能原子完成 |
| `50` | apply 后验证失败 |

`ALREADY_COMPLIANT` 只能在所有目标字段逐项精确匹配时返回。部分匹配不能被当作幂等成功。

脚本不自动执行破坏性补救。出现 apply 中断时保留临时文件、实际状态与 evidence，后续动作必须经过新的设计判断和用户授权。

## 9. Evidence 与敏感信息

- evidence 目录固定为 `/root/dev-infra-evidence`，必须预先存在，脚本不创建或清空它。
- 新 evidence 使用连续阶段编号、UTC timestamp、权限 `0600` 和唯一文件名。本阶段编号固定为 `07-preflight`、`08-artifacts`、`09-kernel`、`10-containerd`、`11-kubernetes`、`12-kubeadm`、`13-cilium` 和 `14-verify`；重试保留同一阶段编号并使用新 timestamp，永不覆盖旧 evidence。
- 证据写完并关闭后计算 SHA-256；摘要不写回被摘要文件。
- 命令输出经过显式 allowlist，不使用 `set -x`。
- 禁止记录 Secret、Token、bootstrap token、certificate key、私钥、完整 kubeconfig 或环境变量转储。
- `/etc/kubernetes/admin.conf` 只允许报告 metadata 和权限，不输出内容。

## 10. 测试设计

### 10.1 静态合同测试

- artifact lock 每行字段数量正确。
- 所有版本精确、URL 固定、SHA-256 合法、来源在 allowlist。
- 禁止 `latest`、`stable`、`main`、`master`、空摘要和 HTTP URL。
- kubeadm、containerd、Cilium 配置包含全部锁定字段。
- 活动 Kustomize 根无法到达任何 `STAGED/BLOCKED` 内容。
- bootstrap 脚本不包含 `apt autoremove`、`kubeadm reset`、`rm -rf`、`curl | sh`、force 或禁用 TLS 校验参数。

### 10.2 行为测试

使用 Python `unittest`、临时目录和 fake PATH 执行真实 Bash 入口，至少覆盖：

- 非 root、错误 hostname、错误 OS、错误架构、目标 IP 不在本机时停止。
- cleanup evidence digest 不匹配时停止。
- CIDR 与地址、route 或彼此重叠时停止。
- artifact URL 非官方、摘要错误、archive 路径穿越时停止。
- 已存在未知 binary/config/data root 时停止。
- 精确目标状态返回 `ALREADY_COMPLIANT` 且没有写操作。
- `--check` 永远不调用修改命令。
- 缺失 `--apply` 时修改型阶段不写文件。
- kubeadm 已初始化或部分初始化时拒绝继续。
- Cilium 安装参数不允许关闭 kube-proxy replacement。
- 证据输出不包含预置的 canary Secret 字符串。

### 10.3 本地与服务器边界

本地测试验证脚本决策与生成文件，不模拟 Linux kernel、systemd、containerd 或真实 kubeadm 成功。服务器运行态只能通过逐阶段获批命令和 evidence 验证，不能用本地测试替代。

## 11. 完成标准

仓库实现完成必须同时满足：

- 所有新测试先以预期原因失败，再由最小实现变绿。
- `./scripts/validate.sh` 继续通过。
- ShellCheck 无 error。
- bootstrap 全部单元与合同测试通过。
- `main` SHA 未变化；所有提交仅存在于 `feat/bootstrap-fail-closed-v01`。
- 没有任何服务器命令在未先展示完整命令并取得用户回执的情况下执行。
- 仓库实现完成不等于服务器 bootstrap 完成；后者必须以各阶段 evidence 和最终 `90-verify.sh` 回执为准。
