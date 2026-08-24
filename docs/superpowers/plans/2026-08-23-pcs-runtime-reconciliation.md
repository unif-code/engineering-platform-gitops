# PCS Candidate 2 And Runtime Evidence Reconciliation Implementation Plan（已执行）

> **执行状态：`EXECUTED`。** 本计划已完成；以下步骤均为已执行记录，而非待办。当前发布、Runtime 与 Gate 事实以本节的最终 reconciliation 结果、PCS Candidate 2 和 runbook 为准。

**Goal:** 建立自洽的 PCS Candidate 2，并让 GitOps validator、bootstrap/app runbook 与 V0.1 acceptance 共同表达“bootstrap 已验证，Flux/基础设施/应用未激活，V0.1 仍为 BLOCKED”。

**Architecture:** Candidate 1 保持历史不变，Candidate 2 复制其完整组件锁定表后叠加当前 Source Commit、制品和 DEV Runtime 证据。validator 通过单一 `CURRENT_PCS` 常量切到 Candidate 2；runbook 只回填已验证事实，不修改任何 Deployment、Kustomization、Secret、Flux 引用或集群对象。

**Tech Stack:** Markdown、Python 3、unittest、PyYAML、GitOps validator、Git

**Spec:** `../engineering-platform-docs/docs/superpowers/specs/2026-08-22-release-fact-reconciliation-design.md`

## Final reconciliation result（2026-08-24）

- docs 架构事实提交为远端可追溯的 `d6d846a612c974991f4d0ffc0685d06adf2ddfe7`。
- frontend 当前 Source Commit 为 `da72238abc87a19c07a5cac96e41d88d5f6bf2d3`；CI run `32683635240`、publish-image job `97305929974`、tag `sha-da72238`、OCI index `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` 与可部署 `linux/amd64` manifest `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` 均已绑定；Runtime Image ID 仍为 `NOT_VERIFIED`。
- 当前 DEV Runtime 采样为 `2026-08-24 03:42Z`：`run-approved --check` 的 `RESULT=PASS_BOOTSTRAP_ALL_CHECK`，GitOps commit `1c5034b9a9c29ab72fde63644c57fa88604c45b6`，但 `flux-system`、`platform`、`openbao` 仍不存在，GitRepository 查询为空；应用、恢复和容量 Gate 因此仍为 `BLOCKED`。
- 2026-08-22 frontend 和 Runtime 值仅保留于明确的历史证据区段，不构成当前候选或验收结论。

## Global Constraints

- docs 架构基线固定为 `2026-08-23.1`，事实提交为 `d6d846a612c974991f4d0ffc0685d06adf2ddfe7`。
- 当前采样时 GitOps main 为 `1c5034b9a9c29ab72fde63644c57fa88604c45b6`，frontend 为 `da72238abc87a19c07a5cac96e41d88d5f6bf2d3`，backend 为 `647d509bca1bbf9ff0f6ab719d5905d8f836e92f`。
- DEV Runtime 只能陈述最后一次成功观测：`2026-08-24 03:42Z` 的 `PASS_BOOTSTRAP_ALL_CHECK`；它只证明 bootstrap check，不证明 GitOps 或应用已部署。
- frontend CI 事实为 run `32683635240`、publish-image job `97305929974`、tag `sha-da72238`、OCI index `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` 与已核验的 `linux/amd64` manifest `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`；运行 Image ID 仍未核验。
- backend 当前 Source Commit 没有可用 image digest；旧 commit `1d627b9` 的 `sha256:c77fb2d88a61659fa8c2b5074a4ea3103002698085e578652d999d2e2b45e8d7` 只可列为历史证据。
- MinIO Server digest 继续为 `BLOCKED`；清单已引用不表示可信、获准或已部署。
- 不记录外部账户运维事项；平台文档只记录制品和验证结果是否存在。
- 不修改 `pcs/candidate-1.md`、`clusters/`、`infrastructure/`、`apps/`、`origin/validated` 或服务器状态。
- 未收到 `【同步进度】`，不得修改 `docs/superpowers/progress/current.md`。

---

### Task 1: 让 validator 使用 Candidate 2

**Files:**
- Create: `pcs/candidate-2.md`
- Modify: `scripts/validate.py:12-25,1231`
- Modify: `scripts/test_validate.py:1-12,180-205`

**Interfaces:**
- Consumes: Candidate 1 的完整组件锁定表、docs 基线 `2026-08-23.1` 和四仓 Source Commit。
- Produces: `validator.CURRENT_PCS: Path`，供 `validate_metrics_server()` 读取当前 PCS。

- [x] **Step 1: 写入会失败的当前 PCS 路径测试**

在 import 区新增 `from unittest import mock`，并在 `RepositoryProfileContractTest` 的 `test_metrics_server_contract` 前新增：

```python
def test_metrics_server_reads_current_pcs_candidate(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
        current_pcs = Path(directory) / 'candidate-2.md'
        current_pcs.write_text('current candidate without metrics facts\n')
        stderr = io.StringIO()
        with (
            mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            validate_metrics_server()

    self.assertEqual(raised.exception.code, 1)
    self.assertIn(
        'PCS 缺少 Metrics Server 供应链事实：Metrics Server',
        stderr.getvalue(),
    )
```

该测试运行真实 `validate_metrics_server()`；若生产代码仍硬编码 Candidate 1，临时 Candidate 2 不会触发失败，测试就无法通过。

- [x] **Step 2: 运行测试并确认失败原因**

Run:

```bash
(cd scripts && python3 -B -m unittest test_validate.RepositoryProfileContractTest.test_metrics_server_reads_current_pcs_candidate -v)
```

Expected: FAIL，唯一原因是 `validate` 尚无 `CURRENT_PCS`，`mock.patch.object` 无法建立替换。

- [x] **Step 3: 创建完整 Candidate 2**

使用 `pcs/candidate-1.md` 的完整组件表作为只读来源，通过 `apply_patch` 创建 `pcs/candidate-2.md`，保留所有未发生版本变化的组件行，并应用以下精确差异：

```markdown
# Platform Compatibility Set Candidate 2

状态：`BLOCKED CANDIDATE`
环境：`DEV` / `NON_HA`
基线：`2026-08-23.1`
```

在组件表前增加：

```markdown
## 事实采样

| 事实 | 值 |
| --- | --- |
| docs 架构事实提交 | `d6d846a612c974991f4d0ffc0685d06adf2ddfe7` |
| GitOps main 采样提交 | `1c5034b9a9c29ab72fde63644c57fa88604c45b6` |
| frontend Source Commit | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` |
| backend Source Commit | `647d509bca1bbf9ff0f6ab719d5905d8f836e92f` |
| DEV Runtime 观测时间 | `2026-08-24 03:42Z` |
| DEV Runtime 结论 | `PASS_BOOTSTRAP_ALL_CHECK`；Flux、平台基础设施与应用未激活 |
```

组件表应用以下状态差异：

- Kubernetes、containerd、etcd、CoreDNS、Cilium 与 Gateway API 标为“运行版本已观察，实际 Image ID/digest 仍待回填”；Cilium 同时记录 Helm revision 1、chart/app `1.20.0`，GatewayClass `cilium` Accepted。
- Flux 行标为 `BLOCKED：CRD、flux-system Namespace 与 Controller 均不存在`。
- local-path、cert-manager、MinIO/CNPG/observability 行标明平台工作负载未部署；保留原锁定版本和 digest。
- MinIO Server 继续保留原 index/amd64 digest，并以“精确摘要供应链证据或获批风险决定未满足”的稳定理由保持 `BLOCKED`。
- frontend 行写入 Source Commit `da72238abc87a19c07a5cac96e41d88d5f6bf2d3`、tag `sha-da72238`、CI run `32683635240`、publish-image job `97305929974`、OCI index `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` 与已核验 `linux/amd64` manifest `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`；只有运行 Image ID 与工作负载仍未核验。
- backend 行写入当前 Source Commit，digest 状态为 `BLOCKED`；备注中只把 commit `1d627b9` 和 digest `sha256:c77fb2d88a61659fa8c2b5074a4ea3103002698085e578652d999d2e2b45e8d7` 标成历史证据，不得作为当前候选。

部署后核验清单中，bootstrap 与 frontend platform manifest 可标为完成；MinIO、backend 当前 digest、Flux Inventory、实际 Image ID 和全栈一致性保持未完成。

- [x] **Step 4: 实现 `CURRENT_PCS`**

在 `scripts/validate.py` 的 `ROOT` 后新增：

```python
CURRENT_PCS = ROOT / 'pcs/candidate-2.md'
```

把：

```python
pcs = (ROOT / 'pcs/candidate-1.md').read_text(encoding='utf-8')
```

替换为：

```python
pcs = CURRENT_PCS.read_text(encoding='utf-8')
```

- [x] **Step 5: 运行定向测试**

Run:

```bash
(cd scripts && python3 -B -m unittest \
  test_validate.RepositoryProfileContractTest.test_metrics_server_reads_current_pcs_candidate \
  test_validate.RepositoryProfileContractTest.test_metrics_server_contract -v)
```

Expected: 2 tests PASS；Candidate 2 包含 Metrics Server 的全部版本与 digest 契约。

- [x] **Step 6: 提交 Candidate 2 与 validator**

```bash
git add pcs/candidate-2.md scripts/validate.py scripts/test_validate.py
git commit -m "docs(pcs): 建立 Candidate 2 事实快照" -m "保留 Candidate 1 历史并让 validator 读取当前候选，明确 bootstrap-only Runtime、应用制品缺口与 MinIO 阻塞。"
```

### Task 2: 收敛 bootstrap 与应用 runbook

**Files:**
- Modify: `runbook/01-bootstrap.md:7-25,41-101`
- Modify: `runbook/06-apps.md:1-28`
- Modify: `runbook/10-image-owner-handoff.md:1-35`

**Interfaces:**
- Consumes: Task 1 的 Candidate 2、最后一次 DEV Runtime 观测和前后端 Docker 启动合同。
- Produces: V0.1 acceptance 可直接引用的 bootstrap、制品与 Smoke 状态。

- [x] **Step 1: 回填最新 bootstrap 证据和 Runtime 边界**

在 `runbook/01-bootstrap.md` 的 2026-08-19 stage 表后增加：

```markdown
### 2026-08-21 历史复核

| 证据 | 结果 |
| --- | --- |
| `/root/dev-infra-evidence/07-preflight-20260821T071118Z.txt` | `PASS_PREFLIGHT`；SHA-256 `9d8a287936c14362899d26846cd92a3a0927fa392af1c74efda599c2f774fe20` |
| `/root/dev-infra-evidence/14-verify-20260821T073936Z.txt` | `PASS_BOOTSTRAP_VERIFIED`；SHA-256 `0c0b06a4b19c8cfe5169357be572dad77acdf227aeccdd6aa7ae82003a9d1daa` |

最后一次运行时只存在 Kubernetes/Cilium 基础组件和 GitLab Runner；Flux CRD、`flux-system`、`platform`、MinIO、CNPG、cert-manager、monitoring 及 frontend/backend 工作负载均不存在。因此本页只证明 bootstrap，不证明 GitOps 或应用已部署。
```

- [x] **Step 2: 删除非平台账户事项并收紧部署前置**

删除当前关于外部账户状态的段落，用以下内容替换：

```markdown
截至事实采样，`origin/main` 为 `1c5034b9a9c29ab72fde63644c57fa88604c45b6`，`origin/validated` 为 `696e9849e4f22501394324a4001e3c0b7091fe66`。当前 main 尚无可推动 `validated` 的成功验证结果，因此不得执行服务器部署。显式 SHA 入口只解决引用落后或回滚时的精确选版，不能绕过“目标 SHA 已通过 validation-gate”的人工授权前置。
```

保留 `run-approved.sh --check|--apply` 的既有 fail-closed 合同，不改变任何命令。

- [x] **Step 3: 更新应用 Smoke 事实**

把 `runbook/06-apps.md` 的顶部状态改为：

```markdown
> 当前状态：`BLOCKED`。frontend OCI digest 已产生；backend 当前 Source Commit 无 image digest；集群没有平台 Namespace、migration Job、frontend/backend Deployment 或 Gateway Route。

GitOps commit / PR：未执行应用 Desired State
frontend Source Commit：`da72238abc87a19c07a5cac96e41d88d5f6bf2d3`
frontend OCI index digest：`sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1`
backend Source Commit：`647d509bca1bbf9ff0f6ab719d5905d8f836e92f`
backend digest：`BLOCKED`
执行状态：`NOT_EXECUTED`
Gateway address：`NOT_AVAILABLE`
Hostname：`platform.dev.local`
```

Smoke 表改成真实接口合同：`GET /` 预期 200；`GET /healthz` 预期 200；`GET /readyz` 在 DB ready 时预期 200；未认证 `GET /api/v1/me` 预期 401 Problem Details，受控登录后预期 200 Principal projection。所有“HTTP 状态/证据”栏写 `NOT_EXECUTED`，不得写成通过。

- [x] **Step 4: 更新 image owner handoff**

把 `runbook/10-image-owner-handoff.md` 的 Runtime 审计采样时间改为 `2026-08-24 03:42Z`，状态保持 `BLOCKED`，并用以下事实替换旧代码骨架判断：

- frontend 当前 commit 有 Dockerfile、nginx 80 启动合同和 main image workflow；CI run `32683635240`、publish-image job `97305929974` 产生 tag `sha-da72238` 与 OCI index `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1`。
- frontend `linux/amd64` platform manifest `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` 已独立核验；运行 Image ID 尚不存在。
- backend 当前 commit 有 Dockerfile，启动命令为 `uvicorn control_plane.app.bootstrap.app:create_app --factory --host 0.0.0.0 --port 8000`，并包含 Alembic；当前 Source Commit 无成功 image digest。
- backend 旧 commit `1d627b9` 的 digest 只作历史记录，不进入当前 handoff。

Handoff 表填入上述确定值；唯一未核验的镜像事实是运行 Image ID，运行 Smoke 保持 `NOT_EXECUTED`，不留空、不猜测。

- [x] **Step 5: 运行定向文档与 validator 检查**

Run:

```bash
rg -n 'bootstrap|BLOCKED|NOT_EXECUTED|NOT_VERIFIED|77c2b012|647d509b' runbook/01-bootstrap.md runbook/06-apps.md runbook/10-image-owner-handoff.md pcs/candidate-2.md
python3 -B scripts/validate.py
git diff --check
```

Expected: 外部账户事项已移除，所有状态和 digest 可追溯；validator 与 diff-check 通过。

- [x] **Step 6: 提交 runbook 收敛**

```bash
git add runbook/01-bootstrap.md runbook/06-apps.md runbook/10-image-owner-handoff.md
git commit -m "docs(runbook): 对齐制品与 DEV Runtime 事实" -m "以最后一次只读观测区分 bootstrap、GitOps 和应用状态，移除过期应用骨架判断并保留未执行 Smoke 的明确边界。"
```

### Task 3: 收敛 V0.1 acceptance 并运行门禁

**Files:**
- Modify: `runbook/09-acceptance.md:1-38`
- Verify: `pcs/candidate-2.md`
- Verify: `runbook/01-bootstrap.md`
- Verify: `runbook/06-apps.md`
- Verify: `runbook/10-image-owner-handoff.md`

**Interfaces:**
- Consumes: Tasks 1–2 的 PCS、bootstrap、image handoff 与 Smoke 状态。
- Produces: V0.1 总结论 `BLOCKED` 和进入部署闭环所需的精确剩余 Gate。

- [x] **Step 1: 切换 acceptance 到 Candidate 2**

把 PCS 引用从 `pcs/candidate-1.md` 改为 `pcs/candidate-2.md`，并把六项状态写为：

1. `BLOCKED`：Flux 未安装，单向 Reconcile 未验证。
2. `BLOCKED`：backend digest、应用工作负载、migration 与 Smoke 未完成。
3. `BLOCKED`：PG PITR 与 etcd restore 依赖未激活 Flux 和被阻塞的 MinIO。
4. `BLOCKED`：MinIO 供应链决定未关闭，Object Lock 未验证。
5. `BLOCKED`：Candidate 2 尚未与实际 Image ID/Chart revision 全量对齐。
6. `BLOCKED`：Metrics API、容量包络、Stop Gate 与整机重启自愈依赖未激活 Flux 和被阻塞的 MinIO。

- [x] **Step 2: 更新 Stop Gates 和最终结论**

将 Docker/containerd 清退标为已完成；将 frontend OCI index 与 `linux/amd64` platform manifest 标为已核验，但 backend digest、实际 Image ID、稳定 DNS、MinIO、Metrics API 与应用 Runtime 保持未完成。

把最终段改为：

```markdown
最终结论：`BLOCKED`（bootstrap 已验证；Flux、平台基础设施、应用与 V0.1 Release Gate 证据未闭环）
DEV-001 状态：`ACTIVE`
DEV-002 状态：`ACTIVE`
关闭负责人：尚未登记（事实缺口）
截止 Gate：`V0.5 Production Candidate` 前
```

- [x] **Step 3: 运行 focused tests**

Run:

```bash
(cd scripts && python3 -B -m unittest test_validate.ProfileValidationTest test_validate.RepositoryProfileContractTest -v)
./scripts/validate-static.sh
git diff --check
```

Expected: focused tests、manifest/static validation 和 diff-check 全部通过；ShellCheck 实际版本会打印，本机 `0.11.0` 与 CI `0.9.0` 的差异只作提示。

- [x] **Step 4: 提交 acceptance 收敛**

```bash
git add runbook/09-acceptance.md
git commit -m "docs(acceptance): 固定 V0.1 为 BLOCKED" -m "按 Candidate 2 拆分已通过的 bootstrap 证据与未完成的 Flux、应用、恢复和容量 Gate，避免部分证据被误读为整体验收。"
```

- [x] **Step 5: 运行仓库提交前门禁**

Run:

```bash
./scripts/validate-fast.sh
git diff --check
git status --short --branch
```

Result: 已完成 focused contracts、`validate.py`、`validate-static.sh` 与 diff-check；已知 `validate-fast` 会在既有 bootstrap subprocess wait 挂起，未将其重跑或宣称为绿。若本机 ShellCheck 不是 CI 固定的 0.9.0，最终报告必须明确本地版本，不能宣称完全复刻 CI。

- [x] **Step 6: 提交后事实复核**

Run:

```bash
rg -n 'candidate-1|IN_PROGRESS|等待应用 owner digest|没有 Dockerfile' pcs/candidate-2.md runbook/01-bootstrap.md runbook/06-apps.md runbook/09-acceptance.md runbook/10-image-owner-handoff.md scripts/validate.py
git log -4 --format='%H %s'
```

Result: `candidate-1` 仅保留为历史说明；当前事实已由 Candidate 2、runbook、acceptance 和 validator 共同约束。最终 reconciliation 证据记录于指定的 final-fix-report。
