# DEV Bootstrap Fail-Closed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `retail-test-workflow` 提供按阶段授权、默认只检查、遇到未知状态即停止的 containerd 2.3.1、Kubernetes 1.36.3 与 Cilium 1.20.0 单节点 bootstrap 工具。

**Architecture:** 仓库保存机器可读 artifact lock、完整目标配置和一组独立 Bash 阶段入口；公共库统一模式解析、证据输出、摘要校验、未知状态判定与原子文件安装。Python `unittest` 通过临时目录和 fake `PATH` 执行真实入口或可独立调用的阶段函数，先证明危险状态会失败，再补最小实现；服务器运行态仍必须逐阶段获得人工授权与回执。

**Tech Stack:** Bash 5、Python 3 标准库、PyYAML（沿用现有 validator）、Kustomize、ShellCheck、systemd、containerd 2.3.1、kubeadm 1.36.3、Helm 3.21.0。

## Global Constraints

- 只修改 `engineering-platform-gitops`；不得修改 frontend 或 backend 仓。
- 所有实现仅进入 `feat/bootstrap-fail-closed-v01`；`main` 只包含已独立发布的治理提交。
- 所有修改型入口默认 `--check`，只有显式 `--apply` 才写系统；不存在自动串联全部阶段的入口。
- 任一未知、漂移、部分安装或供应链不一致状态必须返回 `STOP_*`，不得自动 reset、清理、覆盖或降级。
- 禁止 `apt autoremove`、`kubeadm reset`、`rm -rf`、`curl | sh`、force、`--insecure` 与 TLS 校验关闭参数。
- evidence 只允许写 `/root/dev-infra-evidence`，编号固定为 07～14，权限 `0600`，文件名唯一且永不覆盖；不得记录 Secret、Token、私钥、完整 kubeconfig 或环境变量转储。
- Artifact staging 目录固定为 `/root/dev-infra-artifacts/pcs-2026-08-10.1`，权限 `0700`；安装阶段不得联网。
- 主机固定为 Ubuntu 24.04、`linux/amd64`、hostname `retail-test-workflow`、Node IP `10.93.1.27`。
- Service CIDR 为 `172.20.0.0/16`，Pod CIDR 为 `172.21.0.0/16`；必须与本机所有地址、所有 IPv4 路由和彼此不重叠。
- 保留 `/swap.img`；kubelet 使用 `failSwapOn=false` 与 `memorySwap.swapBehavior=NoSwap`。
- 每个生产行为都必须先有会因该行为缺失而失败的测试，并实际观察 RED 后再实现 GREEN。

---

### Task 1: 隔离活动 Kustomize 根并建立回归 Gate

**Files:**
- Modify: `clusters/dev/kustomization.yaml`
- Modify: `clusters/dev/reconcile-rbac.yaml`
- Modify: `clusters/dev/infrastructure.yaml`
- Modify: `clusters/dev/apps.yaml`
- Modify: `clusters/dev/flux-system/gotk-components.yaml`
- Modify: `clusters/dev/flux-system/gotk-sync.yaml`
- Modify: `scripts/validate.py`
- Modify: `scripts/test_validate.py`

**Interfaces:**
- Produces: `validate_active_root(root: Path = ROOT) -> None`，从 `clusters/dev/kustomization.yaml` 遍历活动资源引用，只允许根资源 `flux-system`。
- Produces: inactive 入口统一审计头 `STATUS`、`ACTIVE`、`REASON`、`ACTIVATION_GATES`。

- [ ] **Step 1: 写活动根失败测试**

在 `scripts/test_validate.py` 用临时仓库构造 `clusters/dev/kustomization.yaml`，让其引用 `flux-system` 与 `apps.yaml`，断言 `validate_active_root(temp_root)` 以 `SystemExit(1)` 失败；另一个 fixture 只引用 `flux-system` 并通过。该测试捕获“未来组件被重新接回活动根且未更新 allowlist”的错误。

```python
def test_active_root_rejects_staged_entrypoint(self) -> None:
    root = self.make_root(['flux-system', 'apps.yaml'])
    with self.assertRaises(SystemExit):
        validate_active_root(root)

def test_active_root_accepts_flux_only(self) -> None:
    root = self.make_root(['flux-system'])
    validate_active_root(root)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest scripts.test_validate.ActiveRootIsolationTest -v`

Expected: FAIL，原因是 `validate_active_root` 尚不存在。

- [ ] **Step 3: 实现最小活动根校验并断开 staged 入口**

`clusters/dev/kustomization.yaml` 的 `resources` 只保留 `flux-system`。三个 inactive 入口和两个未生成 Flux 文件顶部写入 YAML 注释形式的四个审计字段；`validate_active_root` 明确拒绝 `reconcile-rbac.yaml`、`infrastructure.yaml`、`apps.yaml` 以及任何未在 `{'flux-system'}` allowlist 内的根资源。

- [ ] **Step 4: 运行局部与全量测试**

Run: `python3 -m unittest scripts.test_validate.ActiveRootIsolationTest -v`

Run: `./scripts/validate.sh`

Expected: 全部 PASS，且 `kubectl kustomize clusters/dev` 不包含 staged workload。

- [ ] **Step 5: 提交**

```bash
git add clusters/dev scripts/validate.py scripts/test_validate.py
git commit -m "fix(gitops): isolate staged resources from active root"
```

### Task 2: 固定供应链 Lock 与目标配置合同

**Files:**
- Create: `bootstrap/artifacts.lock.tsv`
- Create: `bootstrap/containerd/config.toml`
- Create: `bootstrap/containerd/containerd.service`
- Create: `bootstrap/kubeadm/init.yaml`
- Create: `bootstrap/cilium/values.yaml`
- Modify: `scripts/validate.py`
- Modify: `scripts/test_validate.py`

**Interfaces:**
- Produces: `validate_bootstrap_contracts(root: Path = ROOT) -> None`。
- Produces: 五列 lock：`name<TAB>version<TAB>url<TAB>sha256<TAB>target`。
- Consumes: Task 1 的现有 validator 入口。

- [ ] **Step 1: 写缺失合同的失败测试**

测试必须捕获非五列、浮动版本、非 HTTPS、非官方 host、64 位小写摘要缺失、URL 不含版本、重复 name、未知 target，以及 kubeadm/containerd/Cilium 任一锁定字段漂移。测试 fixture 使用手工字面量，不复用生产 parser 生成 expected。

```python
def test_artifact_lock_rejects_floating_version(self) -> None:
    root = self.make_bootstrap_root(
        'containerd\tlatest\thttps://github.com/containerd/containerd/x\t'
        + 'a' * 64 + '\t/usr/local/bin\n'
    )
    with self.assertRaises(SystemExit):
        validate_bootstrap_contracts(root)
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python3 -m unittest scripts.test_validate.BootstrapContractTest -v`

Expected: FAIL，原因是 bootstrap 合同校验尚不存在。

- [ ] **Step 3: 写入已由官方 release metadata 核对的 lock**

lock 精确包含以下六项，不允许占位符：

```text
containerd	2.3.1	https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz	628448bd973610c656c1cbea8e88b32fafd85b23cc1aa4a3372eb7198478c054	/usr/local/bin
runc	1.3.6	https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64	3f3921dbbee7723e9868f97e88e51ffc910206e3ba55646e74d93d24ea76023c	/usr/local/sbin/runc
cni-plugins	1.9.1	https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz	b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303	/opt/cni/bin
helm	3.21.0	https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz	0093eb572e3d2380f094df162ddb525e219249de88957afe24cfbb19632acd36	/usr/local/bin/helm
gateway-api	1.6.1	https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml	24d931f22abd8e40c973264319ead7cfa09d0fb7716b7ab1ee2ff174cb063a73	kubernetes://gateway-api/standard
cilium-chart	1.20.0	https://helm.cilium.io/cilium-1.20.0.tgz	c5f013912360d1a334f44ef25f36da59ba3414cdb48f466ee12d0c4fdff27883	kubernetes://kube-system/cilium
```

- [ ] **Step 4: 写入完整目标配置并实现合同校验**

containerd 必须是 config `version = 4`、root `/var/lib/containerd`、state `/run/containerd`、CRI v1、overlayfs、runc v2、`SystemdCgroup = true`；systemd unit 固定 `/usr/local/bin/containerd`。kubeadm 必须固定 `v1.36.3`、`10.93.1.27:6443`、两个 CIDR、`addon/kube-proxy` skip phase、systemd cgroup、NoSwap 与 serving TLS bootstrap。Cilium values 必须固定 kube-proxy replacement、API endpoint、Kubernetes IPAM、Gateway API、单副本 operator 和 `/sys/fs/cgroup`。

- [ ] **Step 5: 验证并提交**

Run: `python3 -m unittest scripts.test_validate.BootstrapContractTest -v`

Run: `./scripts/validate.sh`

Expected: PASS。

```bash
git add bootstrap scripts/validate.py scripts/test_validate.py
git commit -m "feat(bootstrap): lock runtime and cluster contracts"
```

### Task 3: 公共 Fail-Closed 库、CIDR 检查与 Preflight

**Files:**
- Create: `scripts/bootstrap/lib/common.sh`
- Create: `scripts/bootstrap/check_cidrs.py`
- Create: `scripts/bootstrap/00-preflight.sh`
- Create: `scripts/test_bootstrap.py`

**Interfaces:**
- Produces Bash: `parse_mode`, `require_root`, `require_command`, `sha256_file`, `managed_file_state`, `install_managed_file`, `open_evidence`, `log_evidence`, `finish_phase`。
- Produces Python CLI: `check_cidrs.py --service-cidr CIDR --pod-cidr CIDR --address CIDR... --route CIDR...`。
- Produces phase result fields：`PHASE`、`MODE`、`RESULT`、`REASON`、`EVIDENCE`、`SHA256`、`EXIT_CODE`、`NEXT`。

- [ ] **Step 1: 写公共库和 CIDR RED 测试**

测试真实调用 shell 函数和 Python CLI，覆盖默认 CHECK、未知参数退出 10、受管文件 `MISSING/COMPLIANT/UNKNOWN`、已有 evidence 不覆盖、CIDR 地址重叠、路由重叠、两个目标 CIDR 互相重叠与合法输入。

```python
def test_cidrs_stop_on_route_overlap(self) -> None:
    result = self.run_cidr('--service-cidr', '172.20.0.0/16',
                           '--pod-cidr', '172.21.0.0/16',
                           '--route', '172.20.8.0/24')
    self.assertEqual(result.returncode, 10)
    self.assertIn('STOP_CIDR_OVERLAP', result.stdout)
```

- [ ] **Step 2: 确认 RED 后实现公共库与 CIDR CLI**

Run: `python3 -m unittest scripts.test_bootstrap.CommonLibraryTest scripts.test_bootstrap.CidrCheckTest -v`

Expected before implementation: FAIL；实现后 PASS。CIDR parser 只接受 IPv4 network，遇到 `default` 路由时忽略目的网段但保留其 `src` 地址供地址检查。

- [ ] **Step 3: 写 Preflight RED 行为测试**

fake `PATH` 分别让 `id`、`hostname`、`uname`、`ip`、`systemctl`、`ss` 与 `sha256sum` 返回受控字面量；逐项证明非 root、错误 hostname、错误 OS、错误架构、目标 IP 不在 UP 网卡、cleanup digest 漂移、旧 runtime 命令/包/service/路径存在、端口 3001 存在和 CIDR 重叠都会返回 10 或 30。canary `SECRET_CANARY_DO_NOT_LOG` 出现在 fake command stderr 时不得进入 evidence。

- [ ] **Step 4: 实现只读 Preflight**

`00-preflight.sh` 只执行 allowlisted 读取，验证 cleanup evidence `a68a3d2ff340bcdcb4265853107a3a2c22a9f7328728473d81d9be2d1486e635`，通过时输出 `PASS_PREFLIGHT` 与 `SERVER_LOCAL_SCOPE_ONLY`，`NEXT=10-stage-artifacts.sh --check`。脚本不得输出完整环境、进程命令行或任意文件内容。

- [ ] **Step 5: 验证并提交**

Run: `python3 -m unittest scripts.test_bootstrap.CommonLibraryTest scripts.test_bootstrap.CidrCheckTest scripts.test_bootstrap.PreflightTest -v`

Run: `shellcheck scripts/bootstrap/lib/common.sh scripts/bootstrap/00-preflight.sh`

```bash
git add scripts/bootstrap scripts/test_bootstrap.py
git commit -m "feat(bootstrap): add fail-closed host preflight"
```

### Task 4: Artifact Staging 与 Archive 安全检查

**Files:**
- Create: `scripts/bootstrap/10-stage-artifacts.sh`
- Modify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: `bootstrap/artifacts.lock.tsv` 与 Task 3 公共库。
- Produces: `/root/dev-infra-artifacts/pcs-2026-08-10.1/<URL basename>`，全部摘要精确匹配后才返回 `PASS_ARTIFACTS_STAGED`。

- [ ] **Step 1: 写 staging RED 测试**

覆盖非官方 host、HTTP URL、摘要错误、同名漂移文件、containerd/CNI/Helm archive 的绝对路径或 `..`、逃逸 symlink、预期成员缺失、CHECK 调用修改命令，以及全部文件精确存在时 `ALREADY_COMPLIANT`。fake downloader 只复制本地 fixture，不访问网络。

- [ ] **Step 2: 运行并确认 RED**

Run: `python3 -m unittest scripts.test_bootstrap.ArtifactStageTest -v`

Expected: FAIL，入口尚不存在。

- [ ] **Step 3: 实现 CHECK/APPLY**

CHECK 只验证命令、官方 host allowlist、目录状态和至少 `1 GiB` 可用空间。APPLY 用 `curl --fail --location --proto '=https' --tlsv1.2 --output <exclusive-temp>` 下载，摘要通过后才原子 rename；archive 通过 `tar -tzf` 与 `tar -tvzf` 检查成员和 symlink，禁止覆盖任何摘要不同的既有文件。日志只记录 URL、文件名、大小和 SHA-256。

- [ ] **Step 4: 验证并提交**

Run: `python3 -m unittest scripts.test_bootstrap.ArtifactStageTest -v`

Run: `shellcheck scripts/bootstrap/10-stage-artifacts.sh`

```bash
git add scripts/bootstrap/10-stage-artifacts.sh scripts/test_bootstrap.py
git commit -m "feat(bootstrap): stage verified release artifacts"
```

### Task 5: 内核前置与 containerd 原子安装

**Files:**
- Create: `scripts/bootstrap/20-prepare-kernel.sh`
- Create: `scripts/bootstrap/30-install-containerd.sh`
- Modify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: staged containerd、runc、CNI artifacts 与仓库内 config/unit。
- Produces: 两个受管 kernel 文件、containerd binaries、runc、CNI、systemd unit、config、active/enabled service 与 CRI socket。

- [ ] **Step 1: 写 kernel RED 测试**

测试未知既有 modules/sysctl 文件必须 STOP 30，精确内容为 `ALREADY_COMPLIANT`，CHECK 不调用 `modprobe/sysctl/install/mv`，APPLY 仅写两个目标文件并逐项验证 `/proc/sys` 期望值。

- [ ] **Step 2: 实现 kernel 阶段并转绿**

原子写入内容固定为 `overlay`、`br_netfilter` 与三条值为 `1` 的 sysctl；同目录临时文件经 `sync` 后 rename。Run: `python3 -m unittest scripts.test_bootstrap.KernelStageTest -v`。

- [ ] **Step 3: 写 containerd RED 测试**

分别覆盖未知 `/usr/local/bin/containerd`、未知 runc、非空 `/var/lib/containerd`、未知 unit/config、staged 摘要漂移、archive 成员缺失、CHECK 写操作，以及精确已安装状态不重启服务。测试捕获生产变更“把部分安装误判为幂等成功”。

- [ ] **Step 4: 实现 containerd 阶段并转绿**

APPLY 先将 archive 解到同 filesystem 临时目录，逐个校验预期可执行文件，再以 `install` 安装；CNI 同理。config 与 unit 只允许 MISSING 或精确 COMPLIANT，data root 只允许不存在或空目录。完成后 daemon-reload、enable/start，并用 `containerd --version`、`runc --version`、`ctr plugins ls`、`crictl info` 的 allowlisted 字段验证 config v4、CRI v1、overlayfs、runc v2 与 systemd cgroup。

- [ ] **Step 5: 验证并提交**

Run: `python3 -m unittest scripts.test_bootstrap.KernelStageTest scripts.test_bootstrap.ContainerdInstallTest -v`

Run: `shellcheck scripts/bootstrap/20-prepare-kernel.sh scripts/bootstrap/30-install-containerd.sh`

```bash
git add scripts/bootstrap scripts/test_bootstrap.py
git commit -m "feat(bootstrap): prepare kernel and install containerd"
```

### Task 6: Kubernetes 包安装与 kubeadm 初始化 Gate

**Files:**
- Create: `scripts/bootstrap/40-install-kubernetes.sh`
- Create: `scripts/bootstrap/50-kubeadm-init.sh`
- Modify: `scripts/test_bootstrap.py`

**Interfaces:**
- Produces: official v1.36 signed-by APT source、精确 `kubelet/kubeadm/kubectl=1.36.3-1.1`、hold 状态与无 kube-proxy control plane。
- Consumes: Task 5 healthy containerd 与 `bootstrap/kubeadm/init.yaml`。

- [ ] **Step 1: 写 Kubernetes package RED 测试**

覆盖其他 minor source、未知 keyring/source、candidate 不是 `1.36.3-1.1`、已安装不同版本、未知 hold、下载后 `dpkg-deb -f` metadata 不匹配和 CHECK 写操作。fixture 中 amd64 官方 SHA-256 固定验证为 kubeadm `7225b4…c2af`、kubectl `22c1bb…c330`、kubelet `99c77d…eaca`。

- [ ] **Step 2: 实现 package 阶段并转绿**

APPLY 独立安装 keyring/source，`apt-get update` 后先 `apt-get download` 三个精确版本，逐包核验 metadata 和 signed Packages 中 SHA-256，再 `apt-get install` 本地 `.deb`，最后 hold 并验证版本。不得接受浮动 candidate。

- [ ] **Step 3: 写 kubeadm RED 测试**

任何 `/etc/kubernetes/admin.conf`、API server static manifest、etcd member 或 6443 listener 都必须 STOP 30，且不得调用 `kubeadm reset`。配置 validate/preflight 失败必须停止；成功 fixture 证明实际 init 参数只引用仓库固定配置，输出不包含预置 token、certificate key 或 kubeconfig canary。

- [ ] **Step 4: 实现 kubeadm 阶段并转绿**

CHECK 重新调用 preflight、containerd 和 CIDR 关键检查；APPLY 依次运行 `kubeadm config validate --config`、`kubeadm init phase preflight --config` 与 `kubeadm init --config`，禁止打印原始 init 输出，只报告 component 状态、文件 metadata、证书 subject/SAN/期限摘要。成功结果 `PASS_KUBEADM_INITIALIZED`，`NEXT=60-install-cilium.sh --check`。

- [ ] **Step 5: 验证并提交**

Run: `python3 -m unittest scripts.test_bootstrap.KubernetesInstallTest scripts.test_bootstrap.KubeadmInitTest -v`

Run: `shellcheck scripts/bootstrap/40-install-kubernetes.sh scripts/bootstrap/50-kubeadm-init.sh`

```bash
git add scripts/bootstrap scripts/test_bootstrap.py
git commit -m "feat(bootstrap): install kubernetes and guard kubeadm init"
```

### Task 7: Cilium 安装与最终只读验收

**Files:**
- Create: `scripts/bootstrap/60-install-cilium.sh`
- Create: `scripts/bootstrap/90-verify.sh`
- Modify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: staged Helm、Gateway manifest、Cilium chart、固定 values 与 `/etc/kubernetes/admin.conf`。
- Produces: Gateway API Standard v1.6.1、Cilium 1.20.0 kube-proxy replacement 和最终 `PASS_BOOTSTRAP_VERIFIED`。

- [ ] **Step 1: 写 Cilium RED 测试**

测试任一 staged digest 漂移、values 禁用 kube-proxy replacement、出现临时 `--set`、在线 repo/update、缺少 `--atomic`、既有 kube-proxy、未知 Helm release 或 CRD 版本时停止；成功命令必须只引用 staged chart 与 values。

- [ ] **Step 2: 实现 Cilium 阶段并转绿**

先用 server-side apply 安装 staged Gateway manifest，再使用 staged Helm binary 执行固定 namespace、`--atomic`、固定 timeout 的 install；不得改变 values 或降级内核功能。Run: `python3 -m unittest scripts.test_bootstrap.CiliumInstallTest -v`。

- [ ] **Step 3: 写最终验证 RED 测试**

覆盖版本漂移、CRI 不健康、API endpoint 漂移、kube-proxy 任一对象存在、Cilium/operator 不健康、Gateway CRD 版本错误、Node 非 Ready/InternalIP 错误、Swap 关闭、kubelet 不是 NoSwap。CSR 只断言输出 metadata/requester/usages/SAN，不得出现证书私钥或 kubeconfig。

- [ ] **Step 4: 实现只读验证并转绿**

`90-verify.sh` 无 APPLY 分支，只读取 allowlisted 状态并输出 `NEXT=NONE`。Run: `python3 -m unittest scripts.test_bootstrap.FinalVerifyTest -v`。

- [ ] **Step 5: 验证并提交**

Run: `shellcheck scripts/bootstrap/60-install-cilium.sh scripts/bootstrap/90-verify.sh`

```bash
git add scripts/bootstrap scripts/test_bootstrap.py
git commit -m "feat(bootstrap): install and verify cilium cluster"
```

### Task 8: Runbook、统一验证与分支交付

**Files:**
- Modify: `runbook/01-bootstrap.md`
- Modify: `runbook/README.md`
- Modify: `README.md`
- Modify: `scripts/validate.sh`
- Modify: `scripts/test_bootstrap.py`

**Interfaces:**
- Consumes: Tasks 1～7 的全部入口与统一输出。
- Produces: 阶段命令模板、回执字段与本地一键验证入口；不包含任何真实 Secret 或服务器执行结果。

- [ ] **Step 1: 写验证入口 RED 测试**

让 `scripts/validate.sh` 在 bootstrap unittest 或 ShellCheck 失败时返回非零，并验证它不会执行任何 bootstrap `--apply`。Expected before wiring: FAIL。

- [ ] **Step 2: 更新文档与验证入口**

README 说明本地合同校验与服务器证据边界；runbook 列出 07～14 阶段、每阶段 `--check` 后等待回执再给 `--apply` 的规则、固定结果字段与失败退出码。`validate.sh` 顺序运行现有 unittest、bootstrap unittest、validator 与 ShellCheck。

- [ ] **Step 3: 全量验证**

Run: `python3 -m unittest discover -s scripts -p 'test_*.py' -v`

Run: `shellcheck scripts/bootstrap/lib/common.sh scripts/bootstrap/*.sh`

Run: `./scripts/validate.sh`

Run: `git diff --check`

Expected: 全部 PASS，输出无 warning，工作树只包含本计划列出的文件。

- [ ] **Step 4: 提交文档集成**

```bash
git add README.md runbook scripts/validate.sh scripts/test_bootstrap.py
git commit -m "docs(runbook): wire staged bootstrap workflow"
```

- [ ] **Step 5: 交付前检查**

确认 `git merge-base --is-ancestor origin/main HEAD` 与 `git merge-base --is-ancestor origin/feat/bootstrap-fail-closed-v01 HEAD` 都返回 0；普通 push feature 分支，不 force。仓库交付完成后只提供首个服务器阶段的完整 `00-preflight.sh --check` 命令并停止，等待回执。

## Self-Review

- Spec coverage：活动根隔离、六项固定制品、CIDR、host preflight、artifact staging、kernel、containerd、Kubernetes packages、kubeadm、Gateway/Cilium、最终验证、evidence 与服务器人工 Gate 均有对应任务。
- Placeholder scan：计划不含待补内容、猜测 digest 或浮动版本；运行态未知值明确由脚本读取并形成 evidence，而非静态占位。
- Interface consistency：所有阶段共用 Task 3 的模式、evidence 与退出码；`validate_active_root` 和 `validate_bootstrap_contracts` 都接受可替换 `root` 以便真实 fixture 测试。
- Mutation coverage：每个修改型阶段至少覆盖未知既有状态、CHECK 禁止写、精确幂等、摘要/版本漂移和敏感信息 canary；删除关键 Gate、放宽版本或接回 staged 入口都会使测试失败。
