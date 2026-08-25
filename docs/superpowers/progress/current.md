# 当前开发进度

- Repository: engineering-platform-gitops
- Updated At: 2026-08-25T03:29:15Z
- Based On Commit: 685198db15299fdb6b8cdffd72162a4864c8666b
- Branch: main
- State: blocked
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
- backend main `4aaf721fa91abd729b33765e4e329b02aa2ece02` 的 CI run
  `32802909349` 已核验成功；tag `sha-4aaf721` 的不可变 OCI index digest 为
  `sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857`。
  该事实仅作为后续应用阶段可用输入；业务应用尚未部署，migration 与账号初始化均未执行。
- Runtime 事实与 backend 可用输入已通过 PR #3 合入 `main`；实现/事实同步提交
  `2f5aa38bd94211e4e31b9400061070dc7b57a54c` 的 GitHub Actions run
  `32804691522` 全绿，`validation-gate` 与 `publish-validated` 均成功。
- 修复过程使用的两个旧 worktree，以及本地/远端三个旧修复分支均已在验证树对象等价且
  工作树干净后删除；当前只保留仓库 `main` 工作树。

## 进行中

- 没有进行中的仓库实现或集群写入；当前停在服务器现场只读刷新前的安全检查点。

## 剩余工作

- 外部 Chrome 当前没有“Web终端 - 统一企业堡垒机”标签页；重新打开后，只读刷新服务器
  HEAD、四 Controller Ready、空 Secret/sync/downstream inventory 与证据校验状态。
- Phase B/C 的 Git Credential、deploy key、`GitRepository`、Flux `Kustomization` 与
  `HelmRelease` 需要独立计划、CI 与 mutation 批准；本批次不执行。
- OpenBao、所有备份任务、infrastructure、apps、MinIO 与应用部署均不在本批次执行范围。
- 业务应用、backend migration、健康 readback 与账号初始化当前均为 `NOT_EXECUTED`；
  只有后续批准计划进入 backend 部署阶段才能使用已锁定 digest。

## 阻塞项

- **服务器现场刷新**：批准的外部 Chrome 堡垒机标签页缺失，禁止切换到应用内浏览器或
  其他终端。历史证据不得冒充 2026-08-25 的实时 readback。

## 最近验证

- Phase A 运行批准基线 `685198db15299fdb6b8cdffd72162a4864c8666b` 仍是本进度文件的
  Based On Commit；事实同步提交 `2f5aa38bd94211e4e31b9400061070dc7b57a54c` 已确认同时位于
  本地 `main`、`origin/main` 与 `origin/validated`。
- GitHub Actions run `32804691522`：workflow `validate`、head SHA
  `2f5aa38bd94211e4e31b9400061070dc7b57a54c`、conclusion `success`；static、plan、
  8 个测试分片、`validation-gate` 与 `publish-validated` 均成功。
- backend GitHub Actions run `32802909349`：head SHA
  `4aaf721fa91abd729b33765e4e329b02aa2ece02`，verify 与 publish-image 均 `success`；
  publish 日志确认 `--platform linux/amd64`、tag `sha-4aaf721` 与上述 OCI index digest。
- WSL/ext4 LF 临时副本的 Flux Phase A 全类测试 `44/44 OK`；仓库 fast profile
  `204/204 OK`。
- `python3 -B scripts/run_validation.py --validate-catalog`、
  `python3 -B scripts/validate.py`、`kubectl kustomize clusters/dev/flux-system`、
  `kubectl kustomize clusters/dev` 与 `git diff --check` 均通过。
- Windows 工作树本身的 `git diff --check` 通过；Windows 全类测试会因 checkout CRLF
  改变固定 bundle SHA 而先被供应链门禁截获，因此 Linux 门禁以 WSL/ext4 LF 副本为准。

## 工作树

- 当前只保留 `D:/tongyi/code/engineering-platform-gitops` 的 `main` 工作树。
- 已清理本地与远端分支 `codex/fix-flux-phase-a-dry-run-order-v2`、
  `codex/fix-flux-phase-a-egress-control`、`codex/fix-flux-phase-a-dry-run-order`，以及它们的
  两个旧隔离 worktree。
- `Remote Recoverable: yes` 表示 Phase A 代码、Runtime 事实、backend 可用输入与当前阻塞
  均已进入受保护远端流程；不存在本机独有业务改动。
