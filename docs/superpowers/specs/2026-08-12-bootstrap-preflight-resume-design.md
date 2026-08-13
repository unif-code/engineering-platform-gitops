# Bootstrap 阶段所有权与可恢复兼容设计

状态：已按用户反馈扩展为全阶段恢复设计，待书面规格确认

目标仓库：`engineering-platform-gitops`

目标主机：`retail-test-workflow` / Ubuntu 24.04 / `linux/amd64`

## 1. 背景

目标主机已经手动完成 stage 00～30。主机同步到 commit `12141c77cbbdf43cee3719e114d5d36980d6ac8b` 后执行：

```text
./scripts/bootstrap/bootstrap-all.sh --check
```

编排器在 stage 00 安全停止：

```text
RESULT=STOP_OLD_RUNTIME
REASON=unexpected-path-/etc/containerd
EXIT_CODE=30
```

`/etc/containerd` 是 stage 30 创建的受管目标状态，不是旧环境残留。当前 stage 00 却把任何 containerd binary、目录或 unit 都视为旧运行时，导致 stage 30 一旦成功，后续恢复必然被 stage 00 永久拦截。

继续核对全链路后发现这不是单点问题：stage 40 还把 stage 50 初始化后正常生成的 `/var/lib/kubelet` 内容当成 pre-init 漂移。因此仅增加一个“stage 00 调 stage 30”的特例不能彻底解决问题，后续阶段仍会出现相同自锁，而且跨阶段相互调用可能形成递归依赖。

## 2. 目标

1. 建立适用于 stage 00～90 的统一所有权与恢复合同，而不是只修复当前 stage 30。
2. 每个 stage 只判定自己拥有的 Desired State，并允许后续 stage 创建的合法状态存在。
3. 任一 stage 的自有状态只有三种结果：缺失且可 apply、精确合规、部分/漂移/未知；第三种始终 fail closed。
4. 编排器只依据真实主机状态按顺序恢复，不使用进度文件，也不信任 evidence 作为完成标记。
5. 在任意已完成前缀以及最终完成状态上重复运行，早期 stage 都不能把后续合法状态误判成污染。
6. 保持 `--check` 不执行安装、删除或修复；服务器现有 `/etc/containerd` 等受管状态不做清理。

## 3. 非目标

- 不放宽 Docker、Caddy、Node、旧 workflow、端口 3001 或其他真正冲突状态的拒绝规则。
- 不允许一个 stage 仅凭文件存在、版本字符串、evidence 或进度文件宣称合规。
- 不在早期 stage 复制后续 stage 的完整验证逻辑。
- 不改变 Kubernetes、containerd、Cilium 的版本或 Desired State。
- 不在本次修复中继续服务器部署；代码 push 且 GitHub 门禁通过后才恢复服务器操作。
- 不引入 `wip/evidence-atomic-publish-v01` 中未收口的额外 hardening。

## 4. 统一阶段合同

### 4.1 所有权规则

| Stage | 唯一拥有并验真的状态 | 必须兼容的后续状态 |
| --- | --- | --- |
| 00 preflight | 主机身份、OS/架构、cgroup、IP、swap、基础服务、清理 evidence、CIDR、真正冲突的遗留软件 | artifacts、kernel、containerd、Kubernetes、control plane、Cilium 已完成状态 |
| 10 artifacts | 固定 artifact set、文件类型/owner/mode/digest 与目录集合 | artifact 已被后续阶段消费 |
| 20 kernel | 固定 modules/sysctl 文件及实时 kernel 值 | containerd 与 Kubernetes 正在运行 |
| 30 containerd | 固定 binary/config/unit digest、目录、service/socket、CRI health | Kubernetes workload 已写入 containerd data root |
| 40 Kubernetes packages | APT source/keyring、四个固定 package/hold、binary provenance、CNI package payload、kubelet unit provenance | stage 50 生成的 kubelet config、PKI、flags 与运行态 |
| 50 kubeadm | control-plane identity、static manifests、etcd、kubelet generated state、API、证书与 kube-proxy absence | stage 60 安装的 Gateway API 与 Cilium workload |
| 60 Cilium | Gateway API bundle、Helm release/storage/values、Cilium/Envoy workload 与 config | stage 90 evidence |
| 90 verify | 全链路只读聚合验收与最终 evidence | 无后续受管状态 |

一个 stage 不得以“后续 owner 的状态必须不存在”作为自身已合规分支的前置条件。跨阶段依赖由编排器的固定顺序保证；后续状态是否健康由对应 owner stage 验真。

### 4.2 每个可变更 stage 的状态机

stage 10～60 对其自有状态统一返回：

```text
ABSENT + prerequisites safe  -> PASS_<STAGE>_CHECK / apply-required
COMPLIANT                    -> ALREADY_COMPLIANT
PARTIAL | DRIFT | UNKNOWN    -> structured STOP / non-zero
```

其中 `COMPLIANT` 必须基于该 stage 的完整 provenance、metadata、content 与 runtime Gate，不能退化成存在性判断。

fresh-only Gate 只允许出现在从 `ABSENT` 进入 apply 的路径上。例如：

- stage 40 在首次安装 Kubernetes packages 前，仍必须拒绝预先存在的 kubelet generated/identity state；
- 一旦四包与其自有合同精确合规，stage 40 不再要求 `/var/lib/kubelet` 为空，因为该目录此时属于 stage 50；
- 编排器随后必定执行 stage 50 `--check`，任何部分初始化或 kubelet 漂移仍会在那里 STOP。

### 4.3 Stage 00 的职责边界

stage 00 保留无条件拒绝的真正遗留状态：

- `caddy`、`docker`、`dockerd`、`node`、`npm`、`npx`、`pnpm` binary；
- Caddy、Docker 相关 package、目录与 systemd unit/socket；
- `/data/workflow`、旧 Node 目录与监听端口 3001；
- 与本仓 tarball 安装方式冲突的 `containerd.io` package。

stage 30 拥有的 containerd/runc/crictl binary、`/etc/containerd`、`/opt/containerd`、`/var/lib/containerd` 与 `containerd.service` 不再由 stage 00 判定。stage 00 只报告 baseline preflight；编排器稍后固定调用 stage 30 `--check`，由 stage 30 对这些状态做完整且唯一的权威判定。

这种 owner-scoped 设计优于 stage 00 直接调用 stage 30：它避免验证逻辑重复、输出解析重复以及 stage 40/50 之间的递归委托，同时保持编排器端到端 fail closed。

### 4.4 编排器恢复规则

`bootstrap-all.sh` 继续固定按 `00,10,20,30,40,50,60,90` 执行，不跳过检查本身：

- 之前已完成的 stage 必须重新返回合规结果；
- 遇到第一个 `apply-required`，`--check` 返回 `PASS_BOOTSTRAP_CHECK` 与该 `NEXT_STAGE`；
- `--apply` 只对该 stage 执行 apply，随后必须 post-check 为 `ALREADY_COMPLIANT`，再继续后续 stage；
- 任一 stage STOP、输出 malformed 或结果不在 allowlist，编排器立即原样停止，不继续后续变更；
- 不读取任何 progress file，也不根据上次运行摘要跳过真实 Gate。

## 5. 恢复兼容矩阵

每个合法 checkpoint 都必须满足以下结果：

| 主机真实状态 | 已完成 stage 的结果 | 第一个未完成 stage | 编排结果 |
| --- | --- | --- | --- |
| 仅 preflight baseline | 00=`PASS_PREFLIGHT` | 10=`PASS_ARTIFACTS_CHECK` | `NEXT_STAGE=10` |
| artifacts staged | 00 PASS，10 ALREADY | 20=`PASS_KERNEL_CHECK` | `NEXT_STAGE=20` |
| kernel prepared | 00 PASS，10～20 ALREADY | 30=`PASS_CONTAINERD_CHECK` | `NEXT_STAGE=30` |
| containerd installed（服务器当前状态） | 00 PASS，10～30 ALREADY | 40=`PASS_KUBERNETES_CHECK` | `NEXT_STAGE=40` |
| Kubernetes packages installed | 00 PASS，10～40 ALREADY | 50=`PASS_KUBEADM_CHECK` | `NEXT_STAGE=50` |
| control plane initialized | 00 PASS，10～50 ALREADY | 60=`PASS_CILIUM_CHECK` | `NEXT_STAGE=60` |
| Cilium installed | 00 PASS，10～60 ALREADY | 90=`PASS_BOOTSTRAP_VERIFIED` | 全链路 check PASS |

最终完成主机再次运行 `--apply` 时，也必须只重验并返回全链路合规，不重复安装或初始化。

## 6. 安全与错误处理

- owner-scoped 不等于放宽：状态从早期 stage 移出后，必须在 owner stage 有更完整的 fail-closed Gate。
- 任一自有状态的部分安装、额外对象、symlink、owner/mode/digest 漂移、service/runtime 不健康仍返回 STOP。
- 对 fresh-only Gate 的移动必须保留 apply 前、关键竞态点和 apply 后的验证；只是不再污染已完成后的 `ALREADY_COMPLIANT` 分支。
- stage 脚本独立运行时只声明自身 scope 的状态；需要全链路结论时必须运行 `bootstrap-all.sh` 或 stage 90。
- 失败路径不删除、不覆盖、不自动修复未知状态，不输出 Secret 或原始 kubeconfig。

## 7. 实现范围

当前已确认的生产矛盾有两处：

1. stage 00 将 stage 30 的目标状态列入旧运行时 Gate；
2. stage 40 在其 package 合规分支仍强制 stage 50 的 kubelet generated state 为空。

实现时先用测试证明这两处 RED，再做最小 owner-boundary 修复。stage 10、20、30、50、60、90 不因推测而改代码；它们必须通过下述完整恢复矩阵测试，只有出现可复现的跨阶段自锁才追加同原则修复。

## 8. 测试策略

1. stage 00：存在精确或任意 containerd 目标 footprint 时不再提前 STOP；Docker、Caddy、Node、冲突 package 与端口 3001 仍 STOP。
2. stage 30：containerd 缺失返回 apply-required，精确安装返回 ALREADY，partial/drift/health failure 仍 STOP，证明安全责任没有丢失。
3. stage 40：fresh 主机的恶意 kubelet generated state 仍在 apply 前 STOP；精确 packages 加 stage 50 合法 generated state 时返回 ALREADY；partial generated state 随后由 stage 50 STOP。
4. prefix matrix：覆盖 00、10、20、30、40、50、60 每个合法 checkpoint，编排器必须停在正确的下一 stage。
5. final replay：全量完成 fixture 重跑 `--check` 和 `--apply`，所有早期 stage 都必须兼容后续状态且不得重复变更。
6. mutation：每个 owner 至少保留 partial、metadata/content drift、runtime failure 三类 load-bearing STOP。
7. focused tests 后运行相关完整 class、ShellCheck、`git diff --check` 与 `validate-fast.sh`；重型全量 shard由 GitHub Actions 并行门禁执行。

## 9. 部署验收

修复提交 push 且 GitHub `validation-gate` 通过后，服务器同步到精确新 commit，再执行：

```text
./scripts/bootstrap/bootstrap-all.sh --check
```

服务器当前应得到：

```text
STAGE_00_RESULT=PASS_PREFLIGHT
STAGE_10_RESULT=ALREADY_COMPLIANT
STAGE_20_RESULT=ALREADY_COMPLIANT
STAGE_30_RESULT=ALREADY_COMPLIANT
STAGE_40_RESULT=PASS_KUBERNETES_CHECK
RESULT=PASS_BOOTSTRAP_CHECK
NEXT_STAGE=40
EXIT_CODE=0
```

只有该只读编排验收通过后，才继续 `bootstrap-all.sh --apply`。之后每完成一个新阶段，都用同一恢复矩阵验证，不再依赖手工记录判断从哪里续跑。
