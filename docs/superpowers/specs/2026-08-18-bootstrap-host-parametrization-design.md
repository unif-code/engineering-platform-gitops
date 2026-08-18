# Bootstrap 主机参数化设计

## Context

`scripts/bootstrap/` 当前把目标服务器的身份写死在代码里：`10.93.1.27` 在 9 个文件中出现 40 次，`retail-test-workflow` 在 6 个文件中出现 19 次，`engineering-platform-dev`、`/swap.img` 与 4.0–4.4 GB 区间、Pod/Service CIDR 也分别写死在 Stage 00/50/60/90 与 `lib/admin-conf.sh` 中。

两份 Desired State 输入同时混有锁死内容与主机内容：

- `bootstrap/kubeadm/init.yaml`：锁死 `kubernetesVersion`、`cgroupDriver`、`skipPhases`、`proxy.disabled`；主机字段 `advertiseAddress`、`nodeRegistration.name`、`certSANs`、`controlPlaneEndpoint`、`clusterName`、`podSubnet`、`serviceSubnet`。Stage 50 以 `CONFIG_SHA256` 常量锁其 digest。
- `bootstrap/cilium/values.yaml`：锁死镜像 digest、`kubeProxyReplacement` 等；主机字段 `k8sServiceHost`。Stage 60 以 `VALUES_SHA256` 常量锁其 digest，并在 `values_semantics_are_exact` 中用内嵌整份字面量逐字比对。

后果：换一台机器需要改 5 个脚本、重算 2 个 digest、改 2 份 yaml、改测试 fixture、重跑完整套件。这不是运维能独立完成的操作。`retail-test-workflow` 是测试机，后续要在正式服务器或其他机器上部署，因此必须参数化。

## Decision

采用**按主机目录**：`bootstrap/hosts/<hostname>/` 保存该机的全部主机身份与两份具体 yaml。脚本按实际 `hostname` 选择目录，目录不存在即停。所有输入仍是 git 中的具体文件、仍被 digest pin、仍在运行时做形状校验；只是主机值从脚本字面量迁到 `host.env`，digest 从脚本常量迁到 `pins.sha256`。

否决的替代方案：

- 模板 + 运行时渲染：实际交给 kubeadm/helm 的文件不在 git 中，审计弱一档；bash 模板脆弱；与"每个输入都是 git 里一份具体文件"的既有哲学相悖。
- 命令行 / 环境变量传参：编排器与各 stage 明确拒绝一切外部环境覆盖（`STOP_TEST_OVERRIDE`、`untrusted-git-environment`）；信任根只有 clean main 工作树 + 指定 SHA。从外部塞配置等于开洞。

## 主机目录合同

```
bootstrap/hosts/<hostname>/
  host.env             主机身份参数（唯一需要人填写的文件）
  kubeadm-init.yaml    该主机完整 kubeadm InitConfiguration/ClusterConfiguration/KubeletConfiguration
  cilium-values.yaml   该主机完整 Cilium Helm values
  pins.sha256          上两个文件的 SHA-256（sha256sum -c 兼容格式）
```

- 目录名必须等于该机 `hostname`（短主机名，不带 `-f`）输出，且等于 `host.env` 中的 `HOST_NAME`。
- 文件集精确为上述 4 个，不多不少。
- 运行时要求：目录为真实目录、非软链、root:root、`0755`；四个文件为常规非软链文件、root:root、`0644`。
- `bootstrap/kubeadm/` 与 `bootstrap/cilium/` 目录删除，内容迁入 `bootstrap/hosts/retail-test-workflow/`。`bootstrap/artifacts.lock.tsv` 与 `bootstrap/containerd/` 不变——跨主机锁死。

### host.env 语法

每行为 `KEY=VALUE`，或以 `#` 开头的注释行，或空行；不允许其他形态。不允许引号、空格、`$`、反引号、续行。键集必须**精确**等于以下 8 个，重复键拒绝：

| 键 | 值语法 | 说明 |
| --- | --- | --- |
| `HOST_NAME` | RFC 1123 label：`^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$` | 必须等于 `hostname` 与目录名 |
| `HOST_NODE_IP` | IPv4 点分四段，每段 0–255 | 节点 IP，亦为 API server 地址 |
| `HOST_CLUSTER_NAME` | RFC 1123 label | kubeadm `clusterName` |
| `HOST_POD_CIDR` | `A.B.C.D/N`，IPv4 网络 | kubeadm `podSubnet` |
| `HOST_SERVICE_CIDR` | `A.B.C.D/N`，IPv4 网络 | kubeadm `serviceSubnet` |
| `HOST_SWAP_FILE` | 绝对路径 `^/[A-Za-z0-9._/-]+$` | 主机 swap 文件 |
| `HOST_SWAP_MIN_BYTES` | `^[0-9]+$` | swap 允许下限（含） |
| `HOST_SWAP_MAX_BYTES` | `^[0-9]+$`，且 > MIN | swap 允许上限（含） |

**不用 `source` 加载**——`source` 等于执行任意代码。`lib/host-config.sh` 逐行解析、按上表校验、键集比对后 `readonly` 赋值。

派生值（不单独配置，一律由上表推出）：

- API server：`https://${HOST_NODE_IP}:6443`
- admin.conf cluster 名 = `HOST_CLUSTER_NAME`；context 名 = `kubernetes-admin@${HOST_CLUSTER_NAME}`；用户名固定 `kubernetes-admin`
- kubelet-serving CSR requester = `system:node:${HOST_NAME}`；SAN 精确为 `DNS:${HOST_NAME}` + `IP Address:${HOST_NODE_IP}`
- kubelet configz 路径 = `/api/v1/nodes/${HOST_NAME}/proxy/configz`
- 节点 InternalIP 精确为 `HOST_NODE_IP`

端口 `6443`、evidence 目录、PCS staging 路径、`kubernetes-admin` 用户名不参数化：当前无变化需求。

### pins.sha256

两行、固定顺序、`sha256sum -c` 兼容：

```
<sha256>  kubeadm-init.yaml
<sha256>  cilium-values.yaml
```

Stage 50 读第一行代替 `CONFIG_SHA256`；Stage 60 读第二行代替 `VALUES_SHA256`。格式不符（行数、顺序、文件名、digest 形状）→ `STOP_SUPPLY_CHAIN_MISMATCH host-pins-invalid`。

## 主机选择门（`load_host_config`）

新增 `scripts/bootstrap/lib/host-config.sh`。Stage 00/50/60/90 在 `source lib/common.sh` 之后、任何其他 gate 之前调用 `load_host_config`；Stage 10/20/30/40 不含主机参数，不加载。hosts 根目录由 lib 自身按 `${script_dir}/../../bootstrap/hosts` 经 `pwd -P` 解析，不接受外部传入。

`load_host_config` 是纯谓词：失败时把 reason 写入 `HOST_CONFIG_ERROR` 并返回 1，由调用 stage 执行 `complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE`——与既有 lib 只判定、stage 决定结果的分工一致。调用 stage 须把 `hostname` 列入 `required_command`。顺序：

1. `hostname` 读取实际主机名；不可读 → `hostname-unreadable`。
2. `${repo_root}/bootstrap/hosts/<hostname>` 必须存在且满足目录合同 → 否则 `STOP_PRECONDITION host-not-registered`（目录不存在）或 `STOP_PRECONDITION host-config-unsafe`（存在但类型/软链/属主/权限不符）。
3. `host.env` 满足文件合同 → 否则 `host-config-unsafe`；解析与键集校验失败 → `STOP_PRECONDITION host-config-invalid`。
4. `HOST_NAME` 必须等于实际 `hostname` → 否则 `STOP_PRECONDITION host-config-name-mismatch`。
5. 通过后 8 个变量 `readonly`，派生值由各 stage 按需计算。

以上一律退出码 `10`：与 `not-root`、`missing-command-*` 同类，语义是"还没开始就不该跑"，一个字节都不写。

测试 seam：`BOOTSTRAP_TEST_HOSTS_DIR` 仅在 `BOOTSTRAP_TEST_MODE=1` 下允许，把 hosts 根目录指向 fixture；production 下出现该变量沿用现有 `STOP_TEST_OVERRIDE` 拒绝路径。

## 各 stage 合同变化

| Stage | 现状 | 变化 |
| --- | --- | --- |
| 00-preflight | `EXPECTED_HOSTNAME`、`EXPECTED_NODE_IP`、`/swap.img` 与 4.0–4.4 GB 字面量、`SERVICE_CIDR`/`POD_CIDR` 常量；`STOP_HOST_IDENTITY hostname-mismatch` 门 | 全部改为 `HOST_*`；`check_cidrs.py` 入参随之；hostname 门由 `load_host_config` 的 `host-not-registered` / `host-config-name-mismatch` 取代（未登记的机器在 00 第一步即停） |
| 10 / 20 / 30 / 40 | 无主机参数 | 不变，不加载 host config |
| 50-kubeadm-init | `CONFIG_SHA256` 常量、`bootstrap/kubeadm/init.yaml` 路径、hostname/IP/CIDR 常量 | digest ← `pins.sha256` 第一行；路径 ← `hosts/<h>/kubeadm-init.yaml`；其余 ← `HOST_*` |
| 60-install-cilium | `VALUES_FILE`/`VALUES_SHA256`、`values_semantics_are_exact` 内嵌整份字面量、`api_endpoint_is_exact` URL、`lib/admin-conf.sh` 四个常量 | 路径/digest ← host 目录；semantics 字面量改为锁死骨架 + `k8sServiceHost` 取 `HOST_NODE_IP`；endpoint 与 admin-conf 常量改为派生值 |
| 90-verify | `EXPECTED_NODE`/`EXPECTED_NODE_IP`、CSR requester/SAN、configz 路径、swap、api endpoint、admin-conf | 全部改为 `HOST_*` 派生 |
| lib/admin-conf.sh | 4 个 readonly 常量 | 由 `load_host_config` 之后派生赋值；谓词本身不变 |

数据流：`hostname` → 选目录 → 解析 `host.env` → `readonly` 变量 → 各 gate 用变量代替字面量。没有任何值从命令行、环境或编排器传入。

## 供应链锁的保留

- 两份 yaml 仍是 git 中的具体文件，仍被 digest pin；pin 只是从脚本常量迁到 `pins.sha256`。
- Stage 60 `values_semantics_are_exact` **保留整份形状比对**：内嵌字面量里只有 `k8sServiceHost:` 一行取 `HOST_NODE_IP`，其余每一行照旧写死。digest 防"文件被换"，semantics 防"形状漂移"，两层都在。
- Stage 50 对 `kubeadm-init.yaml` 维持 digest 单层运行时校验；其主机字段与 `host.env` 的一致性、锁死字段的取值，由 `validate.py` 静态保证。

## validate.py 静态合同

对每个 `bootstrap/hosts/*/`：

1. 文件集精确为 4 个；目录名 = `host.env` 的 `HOST_NAME`。
2. `host.env` 按上表语法完整校验（含 CIDR 为合法 IPv4 网络、`MIN < MAX`）。
3. `kubeadm-init.yaml`：`localAPIEndpoint.advertiseAddress` = `HOST_NODE_IP`；`nodeRegistration.name` = `HOST_NAME`；`nodeRegistration.kubeletExtraArgs` 含 `node-ip=HOST_NODE_IP`；`apiServer.certSANs` = `[HOST_NODE_IP]`；`clusterName` = `HOST_CLUSTER_NAME`；`controlPlaneEndpoint` = `HOST_NODE_IP:6443`；`networking.podSubnet`/`serviceSubnet` = 对应 CIDR；锁死字段 `kubernetesVersion`、`cgroupDriver`、`skipPhases`、`proxy.disabled`、`failSwapOn`、`memorySwap`、`serverTLSBootstrap` 等于预期值。
4. `cilium-values.yaml`：`k8sServiceHost` = `HOST_NODE_IP`；其余内容与锁死骨架逐字一致。
5. `pins.sha256` 两行格式正确且与两个文件实际 digest 一致；不一致时错误信息提示运行 `scripts/bootstrap/pin-host.sh <host-dir>`。

## 工具

`scripts/bootstrap/pin-host.sh <host-dir>`：重算并原子写入 `<host-dir>/pins.sha256`。只写这一个文件，不修改 yaml。例：`scripts/bootstrap/pin-host.sh bootstrap/hosts/retail-test-workflow`。

## 执行与错误行为

| 情况 | RESULT / REASON | 退出码 |
| --- | --- | --- |
| host 目录不存在 | `STOP_PRECONDITION host-not-registered` | 10 |
| 目录或文件类型/软链/属主/权限不符 | `STOP_PRECONDITION host-config-unsafe` | 10 |
| host.env 语法、键集、值语法不符 | `STOP_PRECONDITION host-config-invalid` | 10 |
| `HOST_NAME` ≠ 实际 hostname | `STOP_PRECONDITION host-config-name-mismatch` | 10 |
| pins.sha256 格式错 | `STOP_SUPPLY_CHAIN_MISMATCH host-pins-invalid` | 20 |
| yaml 与 pin 不符 | 沿用现有 reason（如 `staged-input-contract-drift`） | 20 |

pins.sha256 **缺失**不会走到 `host-pins-invalid`：目录合同要求文件集精确为 4 个，缺文件在 `load_host_config` 阶段即以 `STOP_PRECONDITION host-config-unsafe` / 10 失败。

`--check` 保持零写入，唯一的文档化例外是 Stage 60/90 的 helm kubeconfig：helm 3.21 无法从管道读取 kubeconfig，CHECK 期间会在 `/root/.helm-kubeconfig.XXXXXX/config`（0700 目录、0600 文件，内容仅为已校验的 admin.conf 字节）建立私有临时文件，helm 返回后立即删除，并由 EXIT trap 保证被信号中断时同样删除。上次运行被中断留下的残留 fail-closed：Stage 60 报 `STOP_UNKNOWN_STATE helm-kubeconfig-residue` / 30，Stage 90 报 `STOP_VERIFY_FAILED helm-kubeconfig-residue` / 50；只检测不自动删除，由运维检查后手工清理。

加载了 host config 的 stage 在 evidence 中记录 `HOST_NAME=`、`HOST_NODE_IP=`；Stage 00 另行保留其既有的 `HOSTNAME=`、`NODE_IP=` evidence 键（Stage 50/60/90 新增 `HOST_NAME=`、`HOST_NODE_IP=`）。evidence 保持纯 ASCII。

## Test strategy

1. **`HostConfigTest`（lib 级）**：正向解析出 8 个 readonly 变量；fail-closed 矩阵覆盖目录缺失、目录软链、目录 `0777`、`host.env` 软链、`0666`、属主漂移、少键、多键、重复键、值含空格/引号/`$`/反引号、非法 IP、非法 CIDR、`MIN ≥ MAX`、`HOST_NAME` 与 hostname 不符、空文件、末行无换行；每个子用例断言精确 reason 与退出码 10。
2. **参数流通**：fixture 内第二台假机器 `fixture-host-b`（不同 IP、clusterName、CIDR、swap 区间），通过 `BOOTSTRAP_TEST_HOSTS_DIR` 注入，fake `hostname` 返回 `fixture-host-b`。对 00/50/60/90 各一条：断言 stage 使用的是 B 的值（00 期望 B 的 IP 与 swap 区间；50 期望 B 的 CIDR；60 的 admin.conf 谓词要求 `kubernetes-admin@<B cluster>`、endpoint 为 B 的 IP；90 的 CSR SAN 要求 `DNS:fixture-host-b`、configz 路径含 B）。
3. **结构约束**：`scripts/bootstrap/*.sh` 与 `lib/*.sh` 中禁止出现 `10.93.1.27`、`retail-test-workflow`、`engineering-platform-dev`、`CONFIG_SHA256=`、`VALUES_SHA256=`；唯一允许位置为 `bootstrap/hosts/` 与测试文件。
4. **`validate.py` / `test_validate.py`**：上节 5 条静态合同各有正向与负向用例。
5. **现有 fixture 不改**：默认 host 目录即 `retail-test-workflow`，现有用例行为完全一致，是"迁移未改坏"的直接证据。
6. **服务器基线对比**：迁移完成后在服务器仅跑 `bootstrap-all.sh --check`，输出与迁移前的基线逐字一致。

## 迁移顺序

每步一个 commit、每步全绿、服务器行为不变：

1. `lib/host-config.sh` + `bootstrap/hosts/retail-test-workflow/host.env` + `HostConfigTest`；尚无消费者。
2. 两份 yaml 迁入 host 目录 + `pins.sha256` + `pin-host.sh` + `validate.py` 校验；Stage 50/60 改从 host 目录读文件与 pin（digest 值不变）。
3. Stage 00 参数化。
4. Stage 50 参数化。
5. Stage 60 参数化（semantics 骨架、admin-conf 派生、endpoint）。
6. Stage 90 参数化。
7. 删除全部死掉的字面量常量；加入结构约束测试与 `fixture-host-b` 流通测试。
8. 服务器 `--check` 与基线逐字对比。

## Scope

本设计只覆盖主机身份参数化。不在范围内、留给后续子项目：

- 每 gate 一行进度与终端 UX（子项目 A，建立在 E 之上）
- 按 stage 目录拆分与脚本解耦（子项目 E）
- 新手册与 runbook 梳理（子项目 B/C）
- kubelet-serving CSR 自动批准 stage（安全策略变更，需单独决策）
- 正式环境 profile 差异（swap、容量、DEV-00x 偏差）——需对照 `engineering-platform-docs`
- 端口、evidence 目录、PCS staging 路径参数化
