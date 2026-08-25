# DEV Cluster Bootstrap 记录

> 仅记录 bootstrap 阶段获准的带外命令。后续 Desired State 只能通过本仓 PR 变更。

> **STOP GATE**：旧 Docker/Caddy 清退、全新 Kubernetes CRI runtime、稳定 DNS 与维护路径均完成并取得证据前，本页不得把任何运行时判定标为通过。

执行人：`root`
执行时间（含时区）：`2026-08-10 10:36:55 CST`（审计采集时间）；bootstrap 全流程完成 `2026-08-19 10:12 CST`
服务器标识：`retail-test-workflow`
GitOps commit / PR：bootstrap 完成于 `a3eb3945c733b77f2594c9ff10e99dcd8587cd4d`

## 当前状态：2026-08-24 Flux Phase A 已验收

在服务器 GitOps `main` 的 `685198db15299fdb6b8cdffd72162a4864c8666b` 上，外部
Chrome 堡垒机 root 会话于 `2026-08-24 12:16:47Z` 完成 Flux Phase A 四 Controller
验收。该记录不证明 2026-08-25 实时状态，也不证明 Git sync、平台基础设施、OpenBao、
备份或应用已部署。

## 当前 DEV Runtime 观测

| 字段 | 值 |
| --- | --- |
| 采样时间 | `2026-08-24 12:16:47Z` |
| GIT_COMMIT | `685198db15299fdb6b8cdffd72162a4864c8666b` |
| RESULT | `PASS_FLUX_PHASE_A` |
| REASON | `four-controller-runtime-accepted` |
| FLUX_CHECK | `all checks passed` |
| CONTROLLERS | `source v1.9.3/kustomize v1.9.4/helm v1.6.3/notification v1.9.2` |
| FLUX_CRD_COUNT | `11` |
| SECRET_COUNT | `0` |
| SYNC_INVENTORY | `empty` |
| DOWNSTREAM_NAMESPACE_INVENTORY | `empty` |
| NETWORK_PROBE_V2 | `PASS` |
| EVIDENCE | `/root/dev-infra-evidence/15-flux-phase-a-20260824T105630Z.txt` |
| EVIDENCE SHA256 | `2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7` |
| OPENBAO | `NOT_EXECUTED` |
| BACKUPS | `NOT_EXECUTED` |
| NEXT_STAGE | `PHASE_B_REQUIRES_SEPARATE_APPROVAL` |
| EXIT_CODE | `0` |

### 2026-08-19 历史 bootstrap apply

`2026-08-19` 在 `a3eb394` 上执行 `--apply`，编排器全部 8 个 stage 通过：

| Stage | 结果 |
| --- | --- |
| 00 preflight | `PASS_PREFLIGHT`（证据 `/root/dev-infra-evidence/07-preflight-20260819T021035Z.txt`，SHA-256 `74a80a473e0f571abe6a087d92f30e1f83db6b564f8ab0b2f501a6f21534bf51`） |
| 10–60 | `ALREADY_COMPLIANT` |
| 90 verify | `PASS_BOOTSTRAP_VERIFIED`（证据 `/root/dev-infra-evidence/14-verify-20260819T021224Z.txt`，SHA-256 `dde4cfdc04d199a44b2c0855468c01e5358a82a62fec1f52d540b6427215f75f`） |

编排器汇总：`RESULT=PASS_BOOTSTRAP_ALL`、`REASON=bootstrap-complete`、`NEXT_STAGE=NONE`、`EXIT_CODE=0`。

集群构成：kubeadm 单节点控制面（`clusterName=engineering-platform-dev`）、containerd 2.3.1 + runc、
Kubernetes 1.36.3 四包 hold、Cilium 1.20.0（kube-proxy replacement、Gateway API v1.6.1 standard、Envoy DaemonSet）。

### 2026-08-21 历史 bootstrap 观测

| 证据 | 结果 |
| --- | --- |
| `/root/dev-infra-evidence/07-preflight-20260821T071118Z.txt` | `PASS_PREFLIGHT`；SHA-256 `9d8a287936c14362899d26846cd92a3a0927fa392af1c74efda599c2f774fe20` |
| `/root/dev-infra-evidence/14-verify-20260821T073936Z.txt` | `PASS_BOOTSTRAP_VERIFIED`；SHA-256 `0c0b06a4b19c8cfe5169357be572dad77acdf227aeccdd6aa7ae82003a9d1daa` |

该日期的运行时观测只存在 Kubernetes/Cilium 基础组件和 GitLab Runner；Flux CRD、`flux-system`、`platform`、MinIO、CNPG、cert-manager、monitoring 及 frontend/backend 工作负载均不存在。因此这是历史 bootstrap 证据，只证明当时 bootstrap，不证明最新运行时、GitOps 或应用已部署。

## 可恢复的一次性执行合同

每轮只执行一条【运维】命令，并回填完整
命令、stdout/stderr、退出码、`RESULT`、`REASON`、`NEXT`、证据路径与 SHA-256；
agent 审核回执前不得执行下一条。不得把 Secret、Token、私钥或 kubeconfig 回填到仓库。

### 正常路径

服务器执行统一使用一行式入口（内建全部门禁，并以 `env -i` 干净环境启动编排器）：

```bash
scripts/bootstrap/run-approved.sh --check
```

不带 SHA 时，入口取 CI 发布的 `origin/validated`——`validate.yml` 的
`publish-validated` 只在 `push` 到 `main` 且 `validation-gate` 全绿后，把该引用指向
被验证的那个提交。运维因此无需转述 40 位字符；引用缺失或不在 `origin/main`
历史上（例如被回滚）时 fail-closed，绝不部署未过门禁的提交。

它按序校验：SHA 形态（显式传参时）、`--apply` 必须 root、仓库非软链、origin 为
`unif-code/engineering-platform-gitops.git`、当前分支 `main`、工作树干净、
`origin/main` 等于已批准 SHA（显式传参）或 `origin/validated` 可解析且在
`origin/main` 历史上（默认）、`merge --ff-only` 后本地 HEAD 等于该 SHA、
`/root/.helm-kubeconfig.*` 无残留；任一不满足即以固定退出码停止
（90/91/92/93/94/95/96/97/98/99/100）。输出的
`APPROVED_SHA=<sha> (source=origin/validated|argument)` 记录本轮部署的提交来源。

审核完整回执并明确批准 mutation 后，另行执行：

```bash
scripts/bootstrap/run-approved.sh --apply
```

需要部署某个更早的已批准提交（而非最新绿提交）时，仍可显式传参：
`scripts/bootstrap/run-approved.sh <approved-sha> --check`，此时该 SHA 必须等于
`origin/main`。

**`origin/validated` 落后或不可用时，显式传 SHA 是正规路径而非例外。**
`publish-validated` 只在 `validation-gate` 全绿后才推进该引用；门禁跑不起来时它会
停在旧提交上，此时**不带 SHA 会静默部署旧版本**（入口只校验它在 `origin/main` 历史上，
不校验它是不是最新）。

截至事实采样，私有仓 `origin/main` 为
`72f360f0aa64b77747b3689a2f5372a10dd651f3`，私有仓 `origin/validated` 仍为
`696e9849e4f22501394324a4001e3c0b7091fe66`。对应的脱敏公有镜像
`engineering-platform-gitops-temp` 的 `main` 与 `validated` 均为
`668035b25232216b094670e7dda956c14743b0b2`，CI run `32691520126` 的全部分片、
`validation-gate` 与 `publish-validated` 已成功。该公有提交只替换主机身份等敏感事实，
其 Release/PCS/验证逻辑已逐文件映射到私有提交 `72f360f`；它只承载验证，不是服务器
Desired State 来源。

私有 `validated` 落后期间，部署新私有提交的门禁固定为：从该私有提交单向生成脱敏
公有镜像、审计仅含允许的消毒差异、公有 `validation-gate` 全绿且公有 `validated`
精确指向镜像提交、记录私有 SHA ↔ 公有 SHA ↔ CI run 映射，最后由运维明确批准
`run-approved.sh <private-sha> --check|--apply` 的显式 SHA 路径。公有仓不得反向成为
服务器 remote，也不得以提交信息相似代替逐文件映射。显式 SHA 只解决私有引用落后或
回滚时的精确选版，不能绕过上述验证与人工授权。

历史上手工粘贴的等价门禁脚本已由该入口取代：粘贴长脚本曾多次因终端丢字符导致
`APPROVED_SHA` 截断或行断裂，也曾遗漏 `merge --ff-only`（`exit 97`）。

保留的底层入口（仅在明确需要绕过门禁诊断时使用）：

```bash
./scripts/bootstrap/bootstrap-all.sh --check
```

底层 `bootstrap-all.sh --check` 全程只读；即 `--check` 全程只读，在第一个需要 APPLY 的 stage 停止，不执行任何 APPLY。上层 `run-approved.sh --check` 对集群和主机配置只读，但会 `fetch` 并以 `ff-only` 更新服务器 Git checkout。审核完整回执并明确批准 mutation 后，另行执行：

```bash
./scripts/bootstrap/bootstrap-all.sh --apply
```

`--apply` 会先检查每个 stage，跳过返回 `ALREADY_COMPLIANT` 的 stage，仅对需要变更的
stage 执行 apply，并要求 apply 后的 post-check 回到 compliant；否则立即停止。当前编排顺序
为 stage `00`、`10`、`20`、`30`、`40`、`50`、`60`、`90`、`100`。Stage `100` 是 Flux Phase A 的正式一键入口，
仍严格限制为 source、kustomize、helm、notification 四个 Controller；它不会创建 Secret、
sync CR、第五个 Controller、下游 Namespace，也不会执行 OpenBao、备份或业务应用。
运行失败后，
重跑同一条命令即可恢复：orchestrator 根据真实主机状态重建进度，不读取或维护 progress file。

当前服务器已完成全部 stage `00`～`90`。GitHub `validation-gate` 成功后重跑
orchestrator，它必须依据各 stage 的检查结果跳过这些已完成 stage，并直接抵达 stage `90`。
Flux Phase A 四 Controller 另有历史验收；包含 stage `100` 的新候选继续运行时，由 stage
`100` 对 Flux Phase A 做 fail-closed 的只读判定；完整
compliant 时直接返回 `ALREADY_COMPLIANT`，不会重复部署或创建探针。

### 单阶段诊断和人工应急入口

下表保留为诊断和人工应急入口，不是正常 bootstrap 路径。使用任一单独 stage 时仍须每次
先提供一条完整命令并等待服务器回执；agent 审核前不得执行下一次 mutation。

| 阶段 | 入口 | 首次模式 | 通过结果 | 运行证据 |
| --- | --- | --- | --- | --- |
| 07 | `stages/00-preflight/run.sh` | 仅 `--check` | `PASS_PREFLIGHT` | `/root/dev-infra-evidence/07-preflight-*.txt` |
| 08 | `stages/10-stage-artifacts/run.sh` | `--check` 后批准 `--apply` | `PASS_ARTIFACTS_STAGED` 或 `ALREADY_COMPLIANT` | 终端回执及 `/root/dev-infra-artifacts/pcs-2026-08-10.1` 摘要清单 |
| 09 | `stages/20-prepare-kernel/run.sh` | `--check` 后批准 `--apply` | `PASS_KERNEL_PREPARED` 或 `ALREADY_COMPLIANT` | `/root/dev-infra-evidence/09-prepare-kernel-*.txt` |
| 10 | `stages/30-install-containerd/run.sh` | `--check` 后批准 `--apply` | `PASS_CONTAINERD_INSTALLED` 或 `ALREADY_COMPLIANT` | `/root/dev-infra-evidence/10-containerd-*.txt` |
| 11 | `stages/40-install-kubernetes/run.sh` | `--check` 后批准 `--apply` | `PASS_KUBERNETES_INSTALLED` 或 `ALREADY_COMPLIANT` | `/root/dev-infra-evidence/11-kubernetes-*.txt` |
| 12 | `stages/50-kubeadm-init/run.sh` | `--check` 后批准 `--apply` | `PASS_KUBEADM_INITIALIZED` 或 `ALREADY_COMPLIANT` | `/root/dev-infra-evidence/12-kubeadm-*.txt` |
| 13 | `stages/60-install-cilium/run.sh` | `--check` 后批准 `--apply` | `PASS_CILIUM_INSTALLED` 或 `ALREADY_COMPLIANT` | `/root/dev-infra-evidence/13-cilium-*.txt` |
| 14 | `stages/90-verify/run.sh` | 仅 `--check` | `PASS_BOOTSTRAP_VERIFIED` | `/root/dev-infra-evidence/14-verify-*.txt` |
| 15 | `stages/100-flux-phase-a/run.sh` | `--check` 后批准 `--apply` | `PASS_FLUX_PHASE_A_INSTALLED` 或 `ALREADY_COMPLIANT` | `/root/dev-infra-evidence/15-flux-phase-a-*.txt` 及同名 `.sha256` |

固定退出码：`0` 表示当前阶段按输出判定完成或需要获批 APPLY；`10` 为前置条件失败，
`20` 为供应链不匹配，`30` 为未知/漂移状态，`40` 为 APPLY 失败，`50` 为部署后
验证失败。任何非零退出码都必须停止。

### 编排器层的输出（2026-08-21 起）

某个 stage 停止时，编排器自己也会给出一层结论，与 stage 的退出码**并存**：

```
RESULT=STOP_STAGE
REASON=stage-60-check-stopped
EXIT_CODE=30
```

`REASON` 形如 `stage-<NN>-{check,apply,postcheck}-stopped`，指出是哪个 stage 的哪一次
调用停的。`EXIT_CODE` 原样沿用该 stage 自己的退出码，语义见上表。

**停止时同样会输出已完成 stage 的完整摘要与尾块**：每个已通过 stage 的
`STAGE_<NN>_RESULT`、`STAGE_<NN>_EVIDENCE`、`STAGE_<NN>_SHA256`，以及
`PHASE=bootstrap-all` 起的尾块。回填要求与成功时一致——失败回执同样有完整证据可填，
不再需要为了拿证据路径重跑一遍。

> 2026-08-21 之前不是这样：编排器的失败分支因 `errexit` 在函数边界上泄漏而**从未执行**，
> stage 一停就直接退出，00 到停止点之间的全部摘要与证据路径都被丢弃。

进度行与心跳走 **stderr**，形如：

```
[5/9] stage 40 check ...
[5/9] stage 40 check ... 5s elapsed
[5/9] stage 40 check -> ALREADY_COMPLIANT (37s)
```

它们是给人看的存活信号，**不属于 stdout 的证据契约，不需要回填**。慢 stage 首拍
5 秒内出现、之后每 15 秒一行；看到心跳就说明进程还活着，不是卡死。

## 排错：已知 STOP 与处置

`--check`/`--apply` 的 STOP 一律 fail-closed，先看 `REASON=` 再对照下表。以下条目均为
`2026-08-19` 打通全流程期间实际遇到并已修复的情形；除标注「运维动作」外，代码侧已容忍。

| REASON | 含义 | 处置 |
| --- | --- | --- |
| `untrusted-environment-override` | 调用方环境里存在被禁止的变量。输出的 `VARS=` 列出违规变量名 | 用 `run-approved.sh` 执行即可（`env -i` 干净环境）。若手工执行，先 `unset` `VARS=` 列出的变量 |
| `host-not-registered` / `host-config-*` | `bootstrap/hosts/<hostname>/` 缺失或不合规 | 确认主机名与目录名一致；目录 `0755`、四个文件 `0644` 且 root 拥有（合并时用 `umask 022`） |
| `host-pins-invalid` | `pins.sha256` 形态错误 | 改过 host 目录的 yaml 后运行 `scripts/bootstrap/pin-host.sh bootstrap/hosts/<hostname>` |
| `helm-kubeconfig-residue` | 上次运行被信号中断，`/root/.helm-kubeconfig.*` 有残留（内含已校验的 admin.conf 字节） | 人工检查后删除该目录，再重跑；脚本只检测不自动删除 |
| `kubelet-swap-config-drift` | kubelet configz 不可达，通常因 `serverTLSBootstrap` 的 serving CSR 未批准 | 见下节「kubelet serving CSR 人工批准」 |
| `cidr-overlap-or-invalid` | Pod/Service CIDR 与本机地址或路由重叠 | 若重叠项在 CNI 网卡（`cilium_host`/`lxc*`）且完全落在 Pod CIDR 内，属正常，已被豁免；其余为真实冲突，需调整网络规划 |
| `partial-kubernetes-contract` | `/opt/cni/bin` 条目集或包 payload 不符 | 允许的集合只有「kubernetes-cni 包清单」或「包清单 + 锁定的 `cilium-cni`」；其他多余文件需人工核实来源 |
| `control-plane-runtime-set-drift` | 4 个控制面容器未各恰好一个 Running 于 kube-system | 检查 `crictl ps`；装完 CNI 后额外的 cilium/coredns 容器属正常，已被容忍 |
| `cilium-post-install-state-invalid` | helm 装完后 Cilium 工作负载在超时窗口内未就绪 | 脚本在装后有界轮询（默认 10 分钟）；仍超时说明 Pod 真的没起来，查 `kubectl -n kube-system get pods` |
| `gateway-cilium-cluster-state-unknown` | Stage 60 的复合判定处于混合态：八个分量既非全部 COMPLIANT、也非全部 MISSING | **先读分量报告**，停止时会逐条打印（见下） |

`gateway-cilium-cluster-state-unknown` 停止时输出的分量：

```
CLUSTER_STATE=UNKNOWN
KUBE_PROXY_STATE=COMPLIANT
HELM_BINARY_STATE=COMPLIANT
GATEWAY_STATE=COMPLIANT
HELM_SECRET_STATE=UNKNOWN      ← 阻塞点
CILIUM_WORKLOAD_STATE=COMPLIANT
ENVOY_DAEMONSET_STATE=COMPLIANT
ENVOY_PODS_STATE=COMPLIANT
CILIUM_CONFIG_STATE=COMPLIANT
HELM_RELEASE_STATE=COMPLIANT
```

取值只有 `COMPLIANT`/`MISSING`/`UNKNOWN` 三种。注意 `KUBE_PROXY_STATE` 非 COMPLIANT 时
其余分量**根本没被查询**，会统一显示 `UNKNOWN`——那是「没查」不是「查了不对」，
先解决 kube-proxy 残留再重跑。

> 2026-08-21 之前这八个分量在停止时一个都不打印，定位只能靠额外跑一轮只读普查。

**外来 Helm release 不再判死。** Stage 60/90 的 helm 判定作用域已收窄为「我们的 cilium
release 对不对」，集群里其他运维装的 release（例如 gitlab-runner）会被服务端
`--selector owner=helm,name=cilium` 直接滤掉，不影响判定。仍然会被抓的是这三种：
cilium 被 `helm upgrade` 过（留下 revision 2）、cilium 装在非 `kube-system`、
存在同名的影子 release。

各 stage 能发出的**完整** STOP 原因清单见 `scripts/bootstrap/stages/<NN-name>/README.md`
——那些文件由源码生成并有 `StageReadmeTest` 防漂移。本表只收录实际遇到过、且处置方式
不显然的条目。

### kubelet serving CSR 人工批准（运维动作）

`bootstrap/hosts/<hostname>/kubeadm-init.yaml` 设 `serverTLSBootstrap: true`，kubelet 因此通过 CSR
申请服务端证书，而核心 Kubernetes 不自动批准 `kubernetes.io/kubelet-serving`。未批准时 kubelet
无服务端证书，apiserver 代理到 kubelet 报 `tls: internal error`，Stage 90 停在 `kubelet-swap-config-drift`。

批准前必须逐条核对（与 Stage 90 `csr_summaries_are_safe` 的判据一致）：

- requester 为 `system:node:<hostname>`
- usages 恰好 `digital signature` + `server auth`（ECDSA serving 证书不请求 `key encipherment`）
- SAN 恰好 `DNS:<hostname>` + `IP Address:<node-ip>`

只读核对：

```bash
KC=/etc/kubernetes/admin.conf
for c in $(kubectl --kubeconfig $KC get csr -o name); do
  u=$(kubectl --kubeconfig $KC get "$c" -o jsonpath='{.spec.username}')
  g=$(kubectl --kubeconfig $KC get "$c" -o jsonpath='{.spec.usages}')
  s=$(kubectl --kubeconfig $KC get "$c" -o jsonpath='{.spec.request}' \
      | base64 -d | openssl req -noout -text \
      | grep -A1 'Subject Alternative Name' | tail -1 | sed 's/^ *//')
  echo "$c | $u | $g | $s"
done
```

核对无误后批准（kubelet 每次重试可能换密钥，全批可确保命中当前私钥）：

```bash
kubectl --kubeconfig /etc/kubernetes/admin.conf get csr -o name \
  | xargs -r kubectl --kubeconfig /etc/kubernetes/admin.conf certificate approve
```

`2026-08-19` 本机批准 20 条，`conditions` 全为 `Approved`，configz 恢复可达
（`failSwapOn=False`、`memorySwap={'swapBehavior': 'NoSwap'}`）。禁止为绕过该步骤给
metrics-server 添加 `--kubelet-insecure-tls`。

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

### 宿主机 Workflow/Node 清退执行记录

| 字段 | 回执 |
| --- | --- |
| 证据文件 | `/root/dev-infra-evidence/06-host-workflow-cleanup-20260810T033358Z.txt` |
| SHA-256 | `a68a3d2ff340bcdcb4265853107a3a2c22a9f7328728473d81d9be2d1486e635` |
| Exit code | 脚本 `0`；外层命令 `0`；结果 `SUCCESS` |
| Fail-closed 复核 | 前序 `04`、`05` 证据 SHA-256 均通过；目标进程 UID、cwd、executable 与旧 `session-397.scope` 全部匹配；执行命令位于当前 `session-875.scope` |
| 进程 | 已结束 PID `1034710`、`1034712`、`1034740`、`1034741`、`1034757` 的完整旧 Workflow 进程链；`*:3001` 已关闭 |
| 永久删除 | `/data/workflow`、`/usr/local/lib/node-v24.18.0`、对应的 6 个 `/usr/local/bin` 链接、`uniflow` 账号/home/私有组，以及已无成员的旧 `docker` 组 |
| 非致命提示 | `userdel` 报告 `/var/mail/uniflow` 不存在；不影响账号删除与最终验证 |
| 主机健康 | SSH、DNS、NTP 与基础网络监听保留；未发现其他旧应用监听；证据目录未删除 |
| 清退后容量 | 根文件系统使用 `9.9G/489G`，可用 `459G`，使用率 `3%`；内存可用 `61Gi` |
| Swap | `/swap.img` `3.8Gi` 保留且当前未使用 |

清退完成回执：

```text
Docker/Caddy/旧 containerd 与宿主机 Workflow/Node 清退完成；服务器旧应用清退 CLOSED。
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

## Flux Phase A bootstrap

状态：`PHASE_A_CONTROLLERS_DEPLOYED_SYNC_INACTIVE`。本节只安装四个 Controller 基础层，不创建 Git deploy key、
Git Credential、`GitRepository`、Flux `Kustomization`、`HelmRelease`，也不激活任何
下游 Desired State。Git deploy key 与仓库 sync 属于后续 Phase B/C。

从 stage `100` 合入起，正常部署只使用上文的一键入口
`scripts/bootstrap/run-approved.sh --check|--apply`。本节保留的长命令块是历史执行合同、
审计细节和单阶段故障诊断依据，不再是正常部署时需要人工逐条粘贴的流程；不得用这些命令
绕过 stage `100` 的状态机、固定摘要、依赖顺序、UID 清理或证据门禁。

### 2026-08-24 执行与验收记录

| 字段 | 值 |
| --- | --- |
| 批准 SHA | `685198db15299fdb6b8cdffd72162a4864c8666b` |
| GitHub Actions | run `32724003530`；`validation-gate`、`publish-validated` 均 `success` |
| 验收完成时间 | `2026-08-24 12:16:47Z` |
| Controller | source `v1.9.3`、kustomize `v1.9.4`、helm `v1.6.3`、notification `v1.9.2`；全部 Ready |
| Flux CRD | `11` |
| `flux check` | `all checks passed`；`FINAL_ACCEPTANCE_V2_RESULT=PASS` |
| 禁止资源 | Secret `0`；sync CR、第五个 Controller、下游 Namespace 均为空 |
| 网络边界 | `NETWORK_PROBE_V2_RESULT=PASS`；两个瞬态 Pod 按本轮 UID 精确删除 |
| 证据 | `/root/dev-infra-evidence/15-flux-phase-a-20260824T105630Z.txt` |
| 证据 SHA-256 | `2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7`；侧车校验 `OK` |
| 未执行 | Git sync、OpenBao、全部备份、infrastructure、apps、MinIO 与应用部署 |

以上为带时间戳的历史运行证据，不冒充后续实时 readback。`2026-08-25` 恢复时外部 Chrome
没有“Web终端 - 统一企业堡垒机”标签页，因此本批次未重新查询服务器或集群，也未执行任何
`kubectl apply/diff` 或其他服务端写操作。

### 首次部署进入条件（历史执行合同）

1. 私有候选提交已生成脱敏公有镜像，允许差异已逐文件审计。
2. 公有仓 `engineering-platform-gitops-temp` 的 `validation-gate` 全绿，且公有
   `validated` 精确指向候选镜像提交。
3. 已记录私有候选 SHA、公有镜像 SHA、CI run URL 三者映射并获得本次 mutation 的
   明确批准。
4. 服务器执行 `run-approved.sh <private-sha> --check` 全绿；私有 `validated` 落后时
   禁止使用无 SHA 入口。
5. 运行前再次证明 DEV 不存在 `flux-system`、Flux CRD、sync CR 或下游 Namespace。

### 固定供应链与预检

在服务器私有仓 checkout 的已批准提交执行。`<private-sha>` 必须替换为记录映射中的
完整 40 位 SHA，不能使用短 SHA 或公有镜像 SHA。

```bash
cd /opt/uni-code/engineering-platform-gitops
APPROVED_FLUX_PHASE_A_SHA='REPLACE_WITH_40_HEX_PRIVATE_SHA'
./scripts/bootstrap/run-approved.sh "$APPROVED_FLUX_PHASE_A_SHA" --check

install -d -m 0700 /root/flux-phase-a-v2.9.3
curl --fail --location --proto '=https' --tlsv1.2 \
  --output /root/flux-phase-a-v2.9.3/flux_2.9.3_linux_amd64.tar.gz \
  https://github.com/fluxcd/flux2/releases/download/v2.9.3/flux_2.9.3_linux_amd64.tar.gz
cd /root/flux-phase-a-v2.9.3
printf '%s  %s\n' \
  eae4e8608c0ade2bf4e8dec1669dbb6b0c28b5822b252d97feccfb4fb1181fd2 \
  flux_2.9.3_linux_amd64.tar.gz | sha256sum --check --strict
tar -xzf flux_2.9.3_linux_amd64.tar.gz flux
./flux version --client
./flux check --pre --kubeconfig=/etc/kubernetes/admin.conf
```

期望：archive SHA-256 为 `OK`，CLI 为 `v2.9.3`，pre-install check 通过。任何下载、
TLS、摘要或兼容性失败都必须停止，不允许改用浮动 URL、tag 或未登记镜像。

### 渲染与 client dry-run

```bash
set -o errexit -o nounset -o pipefail
cd /opt/uni-code/engineering-platform-gitops
KC='/etc/kubernetes/admin.conf'
RENDERED='/root/flux-phase-a-v2.9.3/rendered.yaml'
FIELD_MANAGER='engineering-platform-flux-phase-a'

kubectl --kubeconfig="$KC" kustomize \
  clusters/dev/flux-system > "$RENDERED"
kubectl --kubeconfig="$KC" create --dry-run=client \
  -k clusters/dev/flux-system
```

这里必须使用 `create --dry-run=client`：该步骤只在客户端构建并校验完整 Desired State，
不针对集群中已有对象计算本地三方合并补丁，也不发出资源创建写请求。Phase A 资源由
server-side apply 管理，已有 CRD 还包含 API server 默认字段；使用
`apply --dry-run=client` 会混入 client-side apply 的补丁语义，并可能在 CRD 默认字段上以
`applying patch locally: expected a struct, but received a nil` 失败。权威的现状差异校验仍由
后续 server-side dry-run 与 `kubectl diff --server-side` 完成。

首次部署时 `flux-system` 尚不存在。API server 的 dry-run 不持久化前一个请求模拟创建的
Namespace，因此不能把完整 bundle 的 server-side dry-run 当成单个事务：后续 namespaced
对象会以 `namespaces "flux-system" not found` 失败。禁止以 `kubectl create namespace`、改写
对象 namespace 或跳过 server-side 校验来绕过。

### Namespace 分阶段持久化与完整 server dry-run

以下命令先从已审阅的 `rendered.yaml` 精确提取唯一 `flux-system` Namespace 并做
server-side dry-run。只有在单独获得写操作批准后，才允许持久化该 Namespace；这一步禁止
创建 CRD、RBAC、Service、Deployment、Secret 或 sync CR。Namespace 进入 `Active` 后，才
运行完整 bundle 的 server-side dry-run 和 diff：

```bash
set -o errexit -o nounset -o pipefail
cd /opt/uni-code/engineering-platform-gitops
KC='/etc/kubernetes/admin.conf'
RENDERED='/root/flux-phase-a-v2.9.3/rendered.yaml'
FIELD_MANAGER='engineering-platform-flux-phase-a'

test -s "$RENDERED"
cmp -s "$RENDERED" \
  <(kubectl --kubeconfig="$KC" kustomize clusters/dev/flux-system)
test -z "$(
  kubectl --kubeconfig="$KC" get namespace flux-system \
    --ignore-not-found -o name
)"

render_flux_namespace() {
  python3 - "$RENDERED" <<'PY'
import pathlib
import sys
import yaml

documents = [
    document
    for document in yaml.safe_load_all(
        pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    )
    if document
]
matches = [
    document
    for document in documents
    if document.get("apiVersion") == "v1"
    and document.get("kind") == "Namespace"
    and document.get("metadata", {}).get("name") == "flux-system"
]
if len(matches) != 1:
    raise SystemExit(
        f"STOP: expected exactly one flux-system Namespace, found {len(matches)}"
    )
if matches[0].get("metadata", {}).get("namespace"):
    raise SystemExit("STOP: Namespace unexpectedly has metadata.namespace")
sys.stdout.write(yaml.safe_dump(matches[0], sort_keys=False))
PY
}

render_flux_namespace |
  kubectl --kubeconfig="$KC" apply --server-side \
    --dry-run=server \
    --field-manager="$FIELD_MANAGER" \
    -f -

render_flux_namespace |
  kubectl --kubeconfig="$KC" apply --server-side \
    --field-manager="$FIELD_MANAGER" \
    -f -

kubectl --kubeconfig="$KC" wait \
  --for=jsonpath='{.status.phase}'=Active \
  namespace/flux-system \
  --timeout=60s

kubectl --kubeconfig="$KC" apply --server-side \
  --dry-run=server \
  --field-manager="$FIELD_MANAGER" \
  -k clusters/dev/flux-system

DIFF_RC=0
kubectl --kubeconfig="$KC" diff --server-side \
  --field-manager="$FIELD_MANAGER" \
  -k clusters/dev/flux-system || DIFF_RC=$?

case "$DIFF_RC" in
  0|1)
    printf 'KUBECTL_DIFF_EXIT_CODE=%s\n' "$DIFF_RC"
    ;;
  *)
    printf 'STOP: kubectl diff failed with exit code %s\n' "$DIFF_RC" >&2
    exit "$DIFF_RC"
    ;;
esac
```

如果 Namespace 已持久化但后续校验中断，不得重跑上述 Namespace 创建入口，也不得自动删除；
先只读核对 Namespace UID、labels 与内容，再从完整 server-side dry-run 继续。任何回滚删除都要
单独审阅精确目标。

`kubectl diff` 在存在预期新增对象时返回 `1`，这本身不是错误；必须人工审阅差异只含
`flux-system`、四个 Controller、对应 CRD/Service/RBAC 与 Phase A 网络策略。若出现
Git sync CR、`cluster-admin` binding、第五个 Controller、Secret 或下游 Namespace，
立即停止。

### Apply 与 rollout

仅在 dry-run 回执审核后执行一次：

```bash
cd /opt/uni-code/engineering-platform-gitops
kubectl --kubeconfig=/etc/kubernetes/admin.conf apply --server-side \
  --field-manager=engineering-platform-flux-phase-a \
  -k clusters/dev/flux-system
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  rollout status deployment/source-controller --timeout=5m
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  rollout status deployment/kustomize-controller --timeout=5m
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  rollout status deployment/helm-controller --timeout=5m
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  rollout status deployment/notification-controller --timeout=5m
/root/flux-phase-a-v2.9.3/flux check \
  --kubeconfig=/etc/kubernetes/admin.conf \
  --components=source-controller,kustomize-controller,helm-controller,notification-controller
```

禁止使用 `--force-conflicts`、`--prune`，禁止在 Phase A 创建 deploy key 或 sync CR。

### 验收与证据

完整命令、输出和退出码保存到
`/root/dev-infra-evidence/15-flux-phase-a-<UTC>.txt`，最后记录该文件 SHA-256。先把
本轮实际 UTC 文件名写入 `FLUX_PHASE_A_EVIDENCE_PATH`，至少包含：

```bash
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  get deployment,pod,service,serviceaccount,role,rolebinding,networkpolicy -o wide
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  get pod -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{range .status.containerStatuses[*]}{.imageID}{"\n"}{end}{end}'
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  get ciliumnetworkpolicy -n flux-system -o yaml
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  auth can-i create deployments -A \
  --as=system:serviceaccount:flux-system:kustomize-controller
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  auth can-i create clusterroles \
  --as=system:serviceaccount:flux-system:helm-controller
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  auth can-i list namespaces \
  --as=system:serviceaccount:flux-system:source-controller
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  auth can-i create helmreleases.helm.toolkit.fluxcd.io \
  --namespace=flux-system \
  --as=system:serviceaccount:flux-system:source-controller
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  get gitrepositories.source.toolkit.fluxcd.io,kustomizations.kustomize.toolkit.fluxcd.io,helmreleases.helm.toolkit.fluxcd.io \
  -A --ignore-not-found
kubectl --kubeconfig=/etc/kubernetes/admin.conf get namespace
```

四个 `auth can-i` 必须均为 `no`；sync inventory 必须为空；Namespace inventory 不得
新增 `platform`、`openbao`、`cert-manager`、`monitoring`、`cnpg-system` 或 MinIO 业务
Namespace。

网络证据使用 `runbook/examples/flux-phase-a-network-probe.yaml` 和
`runbook/examples/flux-phase-a-external-network-probe.yaml` 各创建一个瞬态 Pod。它们复用
PCS 已固定的 Kubernetes BusyBox linux/amd64 manifest
`sha256:caec39cad3b12c26600baf6e67ba811ac15d28a9288d0ccdfffb4b318992c3bb`，无 Token、
non-root、只读 RootFS；不属于 Desired State。下面整个 block 必须在同一个 Bash
中执行：`generateName` 避免固定名称冲突，trap 只在当前 Pod UID 与本轮创建回执
一致时删除精确 Pod；UID 不一致必须停止并人工处理，不得按标签批量删除：

```bash
set -o errexit -o nounset -o pipefail
cd /opt/uni-code/engineering-platform-gitops

FLUX_PHASE_A_PROBE_POD=''
FLUX_PHASE_A_PROBE_UID=''
FLUX_PHASE_A_EXTERNAL_PROBE_POD=''
FLUX_PHASE_A_EXTERNAL_PROBE_UID=''

delete_flux_phase_a_probe_if_owned() {
  local pod_namespace="$1"
  local pod_name="$2"
  local expected_uid="$3"
  local current_uid

  if [ -z "$pod_name" ]; then
    return 0
  fi
  if ! current_uid=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf \
    -n "$pod_namespace" get pod "$pod_name" --ignore-not-found \
    -o jsonpath='{.metadata.uid}'); then
    echo "STOP: unable to verify ownership of $pod_namespace/$pod_name" >&2
    return 1
  fi
  if [ -z "$current_uid" ]; then
    return 0
  fi
  if [ "$current_uid" != "$expected_uid" ]; then
    echo "STOP: refuse to delete $pod_namespace/$pod_name; UID changed" >&2
    return 1
  fi
  kubectl --kubeconfig=/etc/kubernetes/admin.conf \
    -n "$pod_namespace" delete pod "$pod_name" --wait=true
}

cleanup_flux_phase_a_probes() {
  local cleanup_status=0
  delete_flux_phase_a_probe_if_owned \
    flux-system "$FLUX_PHASE_A_PROBE_POD" "$FLUX_PHASE_A_PROBE_UID" || cleanup_status=$?
  delete_flux_phase_a_probe_if_owned \
    default "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" "$FLUX_PHASE_A_EXTERNAL_PROBE_UID" || cleanup_status=$?
  return "$cleanup_status"
}
trap cleanup_flux_phase_a_probes EXIT

FLUX_PHASE_A_PROBE_ID=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  create -f runbook/examples/flux-phase-a-network-probe.yaml \
  -o jsonpath='{.metadata.name}:{.metadata.uid}')
FLUX_PHASE_A_PROBE_POD=${FLUX_PHASE_A_PROBE_ID%%:*}
FLUX_PHASE_A_PROBE_UID=${FLUX_PHASE_A_PROBE_ID#*:}

FLUX_PHASE_A_EXTERNAL_PROBE_ID=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  create -f runbook/examples/flux-phase-a-external-network-probe.yaml \
  -o jsonpath='{.metadata.name}:{.metadata.uid}')
FLUX_PHASE_A_EXTERNAL_PROBE_POD=${FLUX_PHASE_A_EXTERNAL_PROBE_ID%%:*}
FLUX_PHASE_A_EXTERNAL_PROBE_UID=${FLUX_PHASE_A_EXTERNAL_PROBE_ID#*:}

kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  wait --for=condition=Ready "pod/$FLUX_PHASE_A_PROBE_POD" --timeout=2m
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  wait --for=condition=Ready "pod/$FLUX_PHASE_A_EXTERNAL_PROBE_POD" --timeout=2m

kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nslookup kubernetes.default.svc.cluster.local
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nc -z -w 5 kubernetes.default.svc.cluster.local 443
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nc -z -w 5 \
  source-controller.flux-system.svc.cluster.local 80
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nc -z -w 5 \
  notification-controller.flux-system.svc.cluster.local 80

if kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nc -z -w 5 github.com 443; then
  echo 'FAIL: Flux probe reached public github.com:443'
  exit 1
else
  echo 'PASS: Flux public egress denied'
fi

kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- nslookup \
  kubernetes.default.svc.cluster.local
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- nc -z -w 5 \
  kubernetes.default.svc.cluster.local 443
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- nc -z -w 5 github.com 443

if kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- nc -z -w 5 \
  source-controller.flux-system.svc.cluster.local 80; then
  echo 'FAIL: non-Flux probe reached source-controller:9090'
  exit 1
else
  echo 'PASS: non-Flux ingress to source-controller:9090 denied'
fi

if kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- nc -z -w 5 \
  notification-controller.flux-system.svc.cluster.local 80; then
  echo 'FAIL: non-Flux probe reached notification-controller:9090'
  exit 1
else
  echo 'PASS: non-Flux ingress to notification-controller:9090 denied'
fi

if kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- nc -z -w 5 \
  webhook-receiver.flux-system.svc.cluster.local 80; then
  echo 'FAIL: non-Flux probe reached webhook receiver:9292'
  exit 1
else
  echo 'PASS: non-Flux ingress to webhook receiver:9292 denied'
fi

FLUX_PHASE_A_SOURCE_POD_IP=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  -n flux-system get pod -l app=source-controller \
  -o jsonpath='{.items[0].status.podIP}')
FLUX_PHASE_A_NOTIFICATION_POD_IP=$(kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  -n flux-system get pod -l app=notification-controller \
  -o jsonpath='{.items[0].status.podIP}')

if kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nc -z -w 5 \
  "$FLUX_PHASE_A_SOURCE_POD_IP" 8080; then
  echo 'FAIL: Flux probe reached source-controller metrics:8080'
  exit 1
else
  echo 'PASS: Flux traffic to source-controller metrics:8080 denied'
fi

if kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  exec "$FLUX_PHASE_A_PROBE_POD" -- nc -z -w 5 \
  "$FLUX_PHASE_A_NOTIFICATION_POD_IP" 9292; then
  echo 'FAIL: Flux probe reached notification-controller receiver:9292'
  exit 1
else
  echo 'PASS: Flux traffic to notification-controller receiver:9292 denied'
fi

kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  get pod "$FLUX_PHASE_A_PROBE_POD" -o wide
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  get pod "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -o wide
cleanup_flux_phase_a_probes
trap - EXIT
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n flux-system \
  get pod "$FLUX_PHASE_A_PROBE_POD" --ignore-not-found
kubectl --kubeconfig=/etc/kubernetes/admin.conf -n default \
  get pod "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" --ignore-not-found

FLUX_PHASE_A_EVIDENCE_PATH='/root/dev-infra-evidence/15-flux-phase-a-REPLACE_WITH_UTC.txt'
sha256sum "$FLUX_PHASE_A_EVIDENCE_PATH"
```

正向七条命令必须成功，其中 non-Flux 探针访问同一 `github.com:443` 是企业出口实际
可达的公网路由正对照；固定公网 IP `1.1.1.1:443` 在该环境被上游阻断，禁止用作正对照。
六条负向连接必须进入 `PASS` 分支；最后两个 Pod 查询必须
为空。只检查 YAML 或 Cilium policy 对象存在不能代替这些运行证据。

判定：

- [ ] Flux CLI `v2.9.3`；Controller 精确为 source `v1.9.3`、kustomize `v1.9.4`、
  helm `v1.6.3`、notification `v1.9.2`，运行 Image ID 与 PCS linux/amd64 digest 一致。
- [ ] 仅 source/kustomize/helm/notification 四个 Controller，全部 Ready。
- [ ] 无 `cluster-admin` binding；Controller 直接创建 Deployment/ClusterRole 或写入
  其他 Controller 的 Flux API group 均被拒绝。
- [ ] 全部 Controller 只 watch `flux-system`；kustomize/helm 的 Reconcile impersonation
  后备、跨 Namespace 引用限制与 remote-base 限制均出现在实际 Pod args；Phase A
  未出现需要 `ObjectLevelWorkloadIdentity` 的 default identity 参数。
- [ ] default deny、DNS、Kubernetes API、source artifact 与 notification event
  `9090` 内部网络边界通过正反向运行验证。
- [ ] `flux check` 通过，sync CR 与下游 Namespace inventory 为空。
- [ ] Evidence 文件与 SHA-256 已回填到 PCS；在此之前 Flux 状态保持 `BLOCKED`。

### Phase A 回滚边界

只有在 Phase B 尚未创建任何 Git Secret/deploy key/sync CR，且 inventory 再次证明为空
时，才允许经单独批准回滚这个精确 bundle：

```bash
cd /opt/uni-code/engineering-platform-gitops
kubectl --kubeconfig=/etc/kubernetes/admin.conf \
  delete --wait=true -k clusters/dev/flux-system
```

出现任何 sync CR、用户 Secret 或下游资源后，此回滚路径立即失效，必须另写并评审
恢复方案；不得强删 CRD、Namespace 或 finalizer。
