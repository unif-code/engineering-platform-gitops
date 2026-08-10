# 服务器基线核验（运维执行并回填）

执行人：`root`（人工回执；实名待补）
执行时间（含时区）：`2026-08-10T00:42:03Z`（`2026-08-10 08:42:03 Asia/Shanghai`）
服务器标识：`retail-test-workflow`（`10.93.1.27/24`，VMware VM）
对应 GitOps 提交：`d8ad31a`

| 检查 | 命令 | 判定 | 实测 |
| --- | --- | --- | --- |
| CPU | `nproc` | ≥16 | 16，通过 |
| 内存 | `free -g` | total ≥62 | 62 GiB，通过 |
| 磁盘 | `lsblk`、`df -hT` | 系统盘 ≥200G；独立数据盘/目录 ≥500G | 单块 500G `/dev/sda`；根 LV 497G、可用 438G；无独立数据盘/目录，不通过 |
| 架构 | `uname -m` | x86_64 | x86_64，通过 |
| Swap | `swapon --show` | 输出为空（`swapoff -a` 并注释 fstab） | `/swap.img` 3.8 GiB 已启用，不通过 |
| 发行版 | `cat /etc/os-release` | systemd 主流发行版 | Ubuntu 24.04.4 LTS；systemd 255 running，通过 |
| 时间同步 | `timedatectl` | NTP 同步 active | Chrony active，时钟已同步，通过 |
| cgroup | `stat -fc %T /sys/fs/cgroup` | cgroup v2 | `cgroup2fs`，通过 |
| 网络转发 | `sysctl net.ipv4.ip_forward` | 值为 1 | 1，通过 |
| bridge netfilter | `sysctl net.bridge.bridge-nf-call-*` | 参数存在且值为 1 | `br_netfilter` 未加载，参数文件不存在，待获批修复 |
| 稳定控制面端点 | `getent hosts dev-cp.unif.internal` | 解析到规划地址 | 无解析结果，不通过 |
| 容器运行时 | `containerd --version` | 规划版本 2.3.1 | 现有 Docker 共用 containerd.io 2.2.5；`/var/lib/containerd` 已占 20G，待共存/停机决策 |

## 原始输出摘录

```text
Operating System: Ubuntu 24.04.4 LTS
Kernel: Linux 6.8.0-134-generic
Architecture: x86-64

CPU(s): 16
MemTotal: 65942160 kB

/dev/sda                                  disk 500G
/dev/mapper/ubuntu--vg-ubuntu--lv         lvm  497G ext4 /
/dev/mapper/ubuntu--vg-ubuntu--lv         ext4 489G 32G 438G 7% /

/swap.img file 3.8G 0B -2

System clock synchronized: yes
NTP service: active
cgroup2fs
net.ipv4.ip_forward = 1
sysctl: cannot stat /proc/sys/net/bridge/bridge-nf-call-iptables

ens160 UP 10.93.1.27/24
containerd containerd.io v2.2.5
kubeadm: not installed
kubelet: not installed
kubectl: not installed
flux: not installed
cilium: not installed
```

服务器侧完整证据：

- 文件：`/root/dev-infra-evidence/00-server-baseline-20260810T004203Z.txt`
- SHA-256：`c100b23fbcc48253704c32bf7954b4dfc7e42ba9b831c2efb3fce488f56ea067`
- 证据文件仅保存在目标服务器，本仓记录路径、摘要与校验和。

## 结论

- [ ] 全部通过，可以继续 bootstrap。
- [x] 存在不达标项，已停止并请求决策。

不达标项 / 待决策：

1. 当前只有一块承载系统和现有 Docker 数据的 500G 磁盘，根文件系统可用 438G；不满足“独立数据盘/目录 ≥500G”。需增加独立磁盘并确认挂载点，或批准带风险说明的架构偏差。
2. `/swap.img` 仍启用。需确认允许永久禁用，并在执行后核验 `/etc/fstab`。
3. `dev-cp.unif.internal` 尚未解析。需确认是否将其固定映射到 `10.93.1.27`，以及由 DNS 还是 `/etc/hosts` 提供。
4. 服务器存在活跃 Docker 工作负载和共用的 containerd.io 2.2.5。升级到规划版本 2.3.1、生成配置和重启 containerd 可能中断现有服务；需明确采用专用新主机，或批准维护窗口及共存方案。
5. `br_netfilter` 未加载，bridge netfilter sysctl 尚不存在；获得继续授权后可在 bootstrap 阶段修复并复核。

根据实施计划 Task 2 Step 1 的 Stop Gate，上述决策关闭前不得执行 containerd/Kubernetes 安装。
