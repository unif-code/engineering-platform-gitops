# 当前开发进度

- Repository: engineering-platform-gitops
- Updated At: 2026-08-25T02:48:30Z
- Based On Commit: 685198db15299fdb6b8cdffd72162a4864c8666b
- Branch: codex/fix-flux-phase-a-dry-run-order-v2
- State: active
- Active Plan: docs/superpowers/plans/2026-08-24-flux-phase-a.md
- Remote Recoverable: yes

## 已完成

- Flux Phase A Desired State、RBAC、NetworkPolicy 与 fail-closed validator 已落地；只包含
  source、kustomize、helm、notification 四个 Controller，sync CR 与下游 Desired State
  继续 inactive。
- `kubectl apply --server-side --dry-run=server -k` 的 Namespace 依赖问题已在
  `14c1d3904b92b228618a169ef44b7ff5554afd42` 修复为两阶段 Runbook：Namespace 先做
  server dry-run，只有获得单独 mutation 批准后才从已审阅 render 精确持久化，随后运行
  完整 bundle server dry-run/diff。Kubernetes dry-run 不持久化对象，因此不存在可替代该
  审批门的纯 dry-run 事务。
- 最终批准 SHA `685198db15299fdb6b8cdffd72162a4864c8666b` 的 `main` 与
  `validated` 一致；GitHub Actions run `32724003530` 全绿。
- `2026-08-24 12:16:47Z` 的历史验收记录显示四个 Controller Ready、11 个 Flux CRD、
  `flux check` 为 `all checks passed`、Secret/sync CR/第五个 Controller/下游 Namespace
  均为空，网络探针与 UID 精确清理通过。
- 证据为 `/root/dev-infra-evidence/15-flux-phase-a-20260824T105630Z.txt`，SHA-256
  `2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7`。

## 进行中

- 将 Phase A 部署后的精确 Runtime 事实同步到 PCS、Runbook、活动计划与验证器，保持
  “Controller 基础层已部署”与“Git sync/下游 Desired State 仍 BLOCKED”两个状态分离。

## 剩余工作

- 外部 Chrome 当前没有“Web终端 - 统一企业堡垒机”标签页；重新打开后，只读刷新服务器
  HEAD、四 Controller Ready、空 Secret/sync/downstream inventory 与证据校验状态。
- Phase B/C 的 Git Credential、deploy key、`GitRepository`、Flux `Kustomization` 与
  `HelmRelease` 需要独立计划、CI 与 mutation 批准；本批次不执行。
- OpenBao、所有备份任务、infrastructure、apps、MinIO 与应用部署均不在本批次执行范围。

## 阻塞项

- **服务器现场刷新**：批准的外部 Chrome 堡垒机标签页缺失，禁止切换到应用内浏览器或
  其他终端。历史证据不得冒充 2026-08-25 的实时 readback。

## 最近验证

- 本地 `main`、`origin/main` 与 `origin/validated` 已只读刷新并一致指向
  `685198db15299fdb6b8cdffd72162a4864c8666b`。
- GitHub Actions run `32724003530`：workflow `validate`、head SHA
  `685198db15299fdb6b8cdffd72162a4864c8666b`、conclusion `success`。
- WSL/ext4 LF 临时副本的 Flux Phase A 全类测试 `44/44 OK`；仓库 fast profile
  `202/202 OK`。
- `python3 -B scripts/run_validation.py --validate-catalog`、
  `python3 -B scripts/validate.py`、`kubectl kustomize clusters/dev/flux-system`、
  `kubectl kustomize clusters/dev` 与 `git diff --check` 均通过。
- Windows 工作树本身的 `git diff --check` 通过；Windows 全类测试会因 checkout CRLF
  改变固定 bundle SHA 而先被供应链门禁截获，因此 Linux 门禁以 WSL/ext4 LF 副本为准。

## 工作树

- 改动位于隔离 worktree
  `D:/tongyi/code/.worktrees/engineering-platform-gitops-flux-phase-a-dry-run-order-v2`，
  分支 `codex/fix-flux-phase-a-dry-run-order-v2`。
- 本节的 `Remote Recoverable: yes` 以本进度同步提交已推送远端为成立条件；若 push/CI
  尚未完成，交接时必须明确报告实际远端状态。
