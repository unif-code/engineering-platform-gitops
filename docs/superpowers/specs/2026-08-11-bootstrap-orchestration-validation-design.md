# Bootstrap 可恢复编排与分层验证设计

状态：已完成对话式设计确认

目标仓库：`engineering-platform-gitops`

工作方式：用户已批准本批次直接在 `main` 完成；保持线性历史，禁止 force push

目标主机：`retail-test-workflow` / Ubuntu 24.04 / `linux/amd64`

服务器仓库：`/opt/uni-code/engineering-platform-gitops`

## 1. 背景

现有 bootstrap 已按 `00`、`10`、`20`、`30`、`40`、`50`、`60`、`90` 拆成独立的 fail-closed 阶段。它们适合逐项审计，但当前有两个直接影响首次部署的问题：

1. 运维人员需要重复执行 `--check`、回传结果、再执行 `--apply`，已经完成的阶段也缺少统一的自动跳过与恢复入口。
2. `./scripts/validate.sh` 会顺序运行全部 mutation test，单机耗时过长，不适合作为每次本地小改动的提交前反馈。

服务器目前已完成 `00`、`10`、`20`、`30`，并在 `40-install-kubernetes.sh --apply` 安全停止。实际 APT 2.8.3 对 Kubernetes flat repository 的 `indextargets` 输出保留 `$(SUITE)`、`$(COMPONENT)`、`$(ARCHITECTURE)` 字面占位符，而现有实现错误地把这些不存在的字段当成 index provenance 必选项，导致 `packages-index-provenance-invalid`。Packages 文件中的 package architecture、版本、size、digest 与 dependency 仍有独立的精确校验，不依赖这些 index-target 占位符。

本设计在保留现有分阶段脚本和 fail-closed 边界的基础上，增加薄编排层、修复 flat repository 识别，并把验证拆成本地快速反馈与 GitHub 全量门禁。

## 2. 目标

1. 修复 Kubernetes v1.36 官方 flat APT repository 在 Ubuntu 24.04 / APT 2.8.3 上的合法 index 识别。
2. 提供一个可重复运行、从真实主机状态自动恢复的一次性 bootstrap 入口。
3. 本地提交前验证稳定控制在两分钟以内。
4. 将全部重型 mutation test 放到 GitHub Actions 并行执行，且保证测试 class 不会被遗漏。
5. 保留现有 `00`～`90` 脚本作为阶段事实源，不复制安装逻辑。
6. 在 GitHub 全量验证通过后，从服务器当前 stage 40 继续部署，而不是重做已完成的变更。

## 3. 非目标

- 不重新设计 Kubernetes、containerd、Cilium 或应用层 Desired State。
- 不引入 `wip/evidence-atomic-publish-v01` 中尚未收口的扩展 hardening。
- 不自动执行 `git pull`、`git reset`、历史改写、主机清理或 kubeadm reset。
- 不用进度文件替代真实主机状态，也不把进度文件当作恢复依据。
- 不在 orchestrator 中复制 artifact、APT、systemd、kubeadm 或 Cilium 实现。
- 不在本批次恢复 Flux、应用部署、恢复演练和容量验收工作。
- 不向 Git、GitHub Actions log 或运维摘要写入 Secret、Token、私钥或 kubeconfig 内容。

## 4. 总体架构

本次变更分为四个清晰边界：

```text
bootstrap stage scripts (00..90)
           ^
           | exact RESULT/exit contract
           |
bootstrap-all.sh

validation catalog/runner
      |                 |
      v                 v
validate-fast.sh   GitHub Actions shards
      |                 |
local feedback     validation-gate
```

### 4.1 阶段脚本

现有数字前缀脚本继续独立负责检查、变更、部署后验证和 evidence。每个脚本仍可单独执行；orchestrator 只是严格消费其公开结果，不读取或推断脚本内部状态。

唯一需要补齐的阶段合同是 `50-kubeadm-init.sh --check`：

- 全新、可初始化主机返回 `PASS_KUBEADM_CHECK`。
- 精确且健康的已初始化 control plane 返回 `ALREADY_COMPLIANT`。
- 部分初始化、身份漂移或未知状态继续返回 STOP，绝不自动 reset。

### 4.2 Bootstrap orchestrator

新增 `scripts/bootstrap/bootstrap-all.sh`。它负责串联阶段、解析结果、跳过已完成阶段、互斥执行和生成不含敏感值的终端摘要。它不拥有任何阶段的业务实现。

### 4.3 Validation catalog/runner

新增单一机器可读测试目录与 runner，统一描述：

- 本地 fast profile 包含哪些测试。
- GitHub full validation 有哪些 shard。
- 每个 concrete `unittest.TestCase` 属于哪个 shard。
- 每个 shard 的执行命令和依赖。

目录校验会动态发现实际含测试方法的 concrete class，并要求每个 class 在 full profile 中恰好出现一次。遗漏、重复、未知 class 或空 shard 都会失败。

### 4.4 GitHub Actions

GitHub Actions 从同一测试目录生成 matrix，不在 YAML 中维护第二份 class 清单。各重型 class 并行运行，最后由固定名称 `validation-gate` 汇总。

## 5. Flat APT Repository 修复

`40-install-kubernetes.sh` 对 `apt-get indextargets` 只绑定真实且稳定存在的三个字段：

```text
$(IDENTIFIER)|$(URI)|$(FILENAME)
```

合法目标必须同时满足：

- 恰好一个非空 target。
- `IDENTIFIER` 精确为 `Packages`。
- `URI` 精确为批准的 v1.36 repository `Packages` URL。
- `FILENAME` 位于本次 root-only private APT workspace 的 lists 目录。
- 文件是非 symlink regular file，owner/mode 符合既有合同。

不再在 index-target 层要求 flat repository 不提供的 Suite、Component 与 Architecture。以下校验保持不变：签名 InRelease、Packages 文件摘要、唯一 package stanza、package architecture `amd64`、精确版本、size、SHA-256、Depends、`.deb` metadata、四包 transaction、hold 与安装后 provenance。

因此该修复只删除错误的 metadata 假设，不降低 package 供应链 Gate。

## 6. 阶段公开合同

orchestrator 按下表解释 stage 输出：

| Stage | `--check` 表示可继续 | `--check` 表示需要 APPLY | APPLY 成功结果 |
| --- | --- | --- | --- |
| `00` | `PASS_PREFLIGHT` | 不适用 | 不适用 |
| `10` | `ALREADY_COMPLIANT` | `PASS_ARTIFACTS_CHECK` | `PASS_ARTIFACTS_STAGED` |
| `20` | `ALREADY_COMPLIANT` | `PASS_KERNEL_CHECK` | `PASS_KERNEL_PREPARED` |
| `30` | `ALREADY_COMPLIANT` | `PASS_CONTAINERD_CHECK` | `PASS_CONTAINERD_INSTALLED` |
| `40` | `ALREADY_COMPLIANT` | `PASS_KUBERNETES_CHECK` | `PASS_KUBERNETES_INSTALLED` |
| `50` | `ALREADY_COMPLIANT` | `PASS_KUBEADM_CHECK` | `PASS_KUBEADM_INITIALIZED` |
| `60` | `ALREADY_COMPLIANT` | `PASS_CILIUM_CHECK` | `PASS_CILIUM_INSTALLED` |
| `90` | `PASS_BOOTSTRAP_VERIFIED` | 不适用 | 不适用 |

固定非零退出码保持原义：

- `10`：前置条件或主机身份失败。
- `20`：供应链不匹配。
- `30`：未知或漂移状态。
- `40`：APPLY 失败。
- `50`：部署后验证失败。

每次调用必须满足：

1. stage 自己返回非零时，orchestrator 原样返回该退出码，不把真实 STOP 改写成其他类别。
2. process exit 0 时，输出中的唯一 `EXIT_CODE` 必须为 `0`。
3. process exit 0 时必须恰好存在一个 `RESULT`，且属于该 stage/mode 的 allowlist。
4. process exit 0 但结构缺失、重复、矛盾或未知时，orchestrator 按 `30` 停止。

`NEXT` 仅用于展示，不能覆盖 stage 表或驱动任意命令执行。

## 7. 一次性执行与恢复

### 7.1 `--check`

```bash
./scripts/bootstrap/bootstrap-all.sh --check
```

执行流程：

1. 从 `00` 开始执行只读检查。
2. `00` 通过后，按 `10`、`20`、`30`、`40`、`50`、`60` 顺序检查。
3. 返回 `ALREADY_COMPLIANT` 的阶段继续向后。
4. 遇到第一个 apply-required 结果时停止并打印该阶段及建议的 `--apply`，不执行任何 stage APPLY、不变更受管系统状态；阶段原有的 evidence 写入合同保持不变。
5. 所有 mutating stage 均 compliant 后执行 `90 --check`。
6. 只有 `90` 返回 `PASS_BOOTSTRAP_VERIFIED` 才报告整体验证通过。

### 7.2 `--apply`

```bash
./scripts/bootstrap/bootstrap-all.sh --apply
```

入口先验证：

- 当前用户为 root。
- 仓库路径和脚本路径安全。
- 当前分支为 `main`。
- worktree 无 tracked/untracked 改动。
- 获得固定 bootstrap exclusive lock；并发运行立即停止。

之后执行：

1. 从 `00` 重新检查，确保主机前置条件未漂移。
2. 每个 `ALREADY_COMPLIANT` 阶段跳过 APPLY。
3. 对第一个 apply-required 阶段执行该阶段 `--apply`。
4. APPLY 只接受该阶段成功结果或并发外部状态已精确完成时的 `ALREADY_COMPLIANT`。
5. APPLY 后立即重新执行同阶段 `--check`；它必须返回 `ALREADY_COMPLIANT`，否则停止。
6. 继续下一阶段，最终执行 `90 --check`。
7. `90` 通过后才报告 `PASS_BOOTSTRAP_ALL`。

脚本被中断或某阶段失败时不写“已完成”进度。再次运行同一命令会从 `00` 重查，并依据真实主机状态跳过已完成阶段。因此当前服务器在同步新 commit 后会自动跳过 `00`、`10`、`20`、`30`，从 `40` 继续。

### 7.3 证据与摘要

阶段 evidence 继续由原脚本生成。orchestrator 只输出：

- Git commit。
- 当前 mode。
- 每阶段最终 RESULT。
- 停止或完成位置。
- 原阶段返回的 evidence path 与 SHA-256（若有）。

orchestrator 不复制 kubeconfig、command raw payload、Secret 或凭据，也不另造可与阶段 evidence 冲突的事实源。

## 8. 本地快速验证

新增 `scripts/validate-fast.sh`，作为本地提交前入口，目标是在正常开发机两分钟内完成。它运行：

1. 依赖与版本存在性检查。
2. `scripts/test_validate.py` 的全部轻量合同测试。
3. `CommonLibraryTest`、`CidrCheckTest`、`PreflightTest` 与 `BootstrapEntrySecurityTest`。
4. `scripts/validate.py` 的 GitOps manifest/锁文件合同验证。
5. `scripts/bootstrap/lib/common.sh` 与所有 bootstrap shell entry 的 ShellCheck。
6. 测试目录自身的一致性检查。

fast profile 明确不运行以下重型 mutation class：

- `ArtifactStageTest`
- `KernelStageTest`
- `ContainerdInstallTest`
- `KubernetesInstallTest`
- `KubeadmInitTest`
- `CiliumInstallTest`
- `FinalVerifyTest`

`scripts/validate.sh` 保留为兼容的完整顺序验证入口，供 CI 诊断或人工需要时使用；本地日常不再要求运行它。

## 9. GitHub 全量验证

新增 `.github/workflows/validate.yml`：

- 触发：`push` 到 `main`、Pull Request、`workflow_dispatch`。
- Runner：Ubuntu 24.04。
- 权限：只授予 `contents: read`。
- concurrency：同一 ref 新运行取消旧运行。
- 第三方/官方 Action 固定到完整 commit SHA，不使用浮动 major tag。
- Python dependency 固定 `PyYAML==6.0.3`；kubectl、ShellCheck 等外部工具固定精确版本，并在运行测试前验证实际版本。

CI 由三个层次组成：

1. `plan`：验证测试目录，输出由目录生成的 JSON matrix。
2. `tests`：按 matrix 并行运行 contract/light、Artifact、Kernel、Containerd、Kubernetes、Kubeadm、Cilium、FinalVerify shard。
3. `static`：独立运行 manifest validation、ShellCheck 与 diff/工作流合同检查。

固定名称 `validation-gate` 依赖所有 test shard 和 static job。任一 shard skipped、cancelled 或失败，gate 都失败；只有全部成功才允许继续服务器部署。

由于本批次已获准直接提交 `main`，GitHub 全量验证是 push 后门禁，不能阻止 commit 先进入远端。失败时必须暂停部署并追加 fix-forward commit；禁止 force push 或改写已发布历史。一般变更仍应遵循仓库既有 PR 审核规则。

## 10. 测试策略

### 10.1 Flat repository

行为测试使用 APT 2.8.3 的真实 flat repository shape，证明：

- literal `$(SUITE)`、`$(COMPONENT)`、`$(ARCHITECTURE)` 不再造成误拒绝。
- target 数量、URI、文件路径或文件类型漂移仍被拒绝。
- package stanza 的 architecture/version/digest/dependency Gate 仍然生效。

### 10.2 Orchestrator

使用 fake stage entries 做 TDD，至少覆盖：

- clean host 从 `00` 开始。
- 已完成 `00`～`30` 时从 `40` 恢复。
- 全部完成时只做 check 并进入 `90`。
- `--check` 在第一个 apply-required stage 停止且零写。
- `--apply` 自动 apply、post-check、继续下一阶段。
- stage STOP 退出码原样透传。
- 缺失/重复/未知 `RESULT` 与 exit sentinel 不一致时 fail closed。
- APPLY 成功但 post-check 未变成 compliant 时停止。
- 非 main、dirty worktree、非 root 和并发运行被拒绝。
- 中断后不依赖 progress file，重跑按真实状态恢复。

### 10.3 Kubeadm 幂等

补充 `50-kubeadm-init.sh` 测试：

- fresh 主机行为保持为 apply-required。
- exact initialized/healthy control plane 返回 `ALREADY_COMPLIANT` 且零写。
- partial manifests、etcd、admin.conf、listener、runtime/API drift 均继续 STOP。
- 已初始化状态绝不触发 reset 或再次 init。

### 10.4 Validation framework

测试证明：

- fast profile 不包含重型 class。
- full CI matrix 覆盖每个 concrete test class 恰好一次。
- 新增 class 未登记、重复登记、未知 class、空 shard 或未知 profile 都失败。
- GitHub workflow 必须存在最终 `validation-gate`，且 gate 依赖全部动态测试与 static 结果。
- `validate.sh` 仍可执行完整顺序验证。

## 11. 文档与治理变更

实现时同步更新：

- `AGENTS.md`：提交前改为 `./scripts/validate-fast.sh`；push 后必须等待 GitHub `validation-gate`，通过后才能继续部署或验收。
- `README.md`：说明 fast/full/CI 三种验证入口与适用场景。
- `runbook/01-bootstrap.md`：保留单阶段应急入口，增加一次性 `--check`/`--apply`、恢复语义和完整回执要求。

所有服务器执行仍受“先给完整【运维】命令并等待回执”约束。实现、提交、push 和 GitHub gate 通过之前，不提供新的服务器 mutation 命令。

## 12. 交付与验收顺序

1. 提交本设计文档并完成用户复核。
2. 编写并提交详细实现计划。
3. 用 TDD 完成 flat APT 修复、validation catalog/runner、GitHub workflow、orchestrator 与 stage 50 幂等。
4. 本地运行 fast profile、所有受影响 class、ShellCheck 和 diff check；不再本地顺序运行全部重型 suite。
5. 直接向 `main` 普通 push。
6. 等待 GitHub `validation-gate` 全绿，并记录 workflow run/commit。
7. 生成一条完整、可复制的服务器同步与 `bootstrap-all.sh --check`【运维】命令，等待回执。
8. check 回执符合预期后，再提供 `bootstrap-all.sh --apply` 命令。
9. orchestrator 自动跳过已完成的 `00`～`30`，从修复后的 `40` 继续，直到 `90` 或首个 Stop Gate。

## 13. 验收标准

- APT flat repository 正常形态不再触发 `packages-index-provenance-invalid`。
- 本地 `validate-fast.sh` 在两分钟目标内通过。
- GitHub `validation-gate` 覆盖全部 concrete test class 并通过。
- `bootstrap-all.sh --check` 对服务器当前状态只读并定位到 stage 40。
- `bootstrap-all.sh --apply` 可从 stage 40 恢复，不重写已完成 stage 的目标文件。
- stage 50 初始化后可被严格识别为 `ALREADY_COMPLIANT`。
- 任一未知状态、供应链漂移、APPLY 失败或部署后验证失败仍在原阶段立即停止。
- Git 历史线性、无 force push、无 Secret/kubeconfig/Token 入库。
