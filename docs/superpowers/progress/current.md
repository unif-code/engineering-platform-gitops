# 当前开发进度

- Repository: engineering-platform-gitops
- Updated At: 2026-08-21T04:47:34Z
- Based On Commit: 6a5f85210e477e8ff97df57fbc60adfe05962497
- Branch: main
- State: active
- Active Plan: docs/superpowers/plans/2026-08-19-bootstrap-stage-decoupling.md
- Remote Recoverable: yes

## 已完成

- `2026-08-19-bootstrap-stage-decoupling` 的 Tasks 1–12 全部落地，共 22 个提交
  （`3f080d4..6a5f852`）。8 个 stage 迁入 `stages/<NN-name>/{run.sh,gates.sh,README.md}`，
  23 个跨 stage 同名函数收敛到 `lib/`，被 source 与被 root 执行的文件全部纳入门禁。
- 新增共享库：`path-facts.sh`、`exec-safety.sh`、`archive.sh`、`kubectl.sh`、`helm.sh`；
  `common.sh` 承载 `host_path` 与 `complete`。`scripts/bootstrap/` 顶层只余
  `bootstrap-all.sh`、`check_cidrs.py`、`lib/`、`pin-host.sh`、`run-approved.sh`、`stages/`。
- 用例 393 → 430。每个 stage 的 README 由源码生成，并有 `StageReadmeTest` 防漂移。
- 计划外修复的真实缺陷：CI 上 main 自 `3f080d4` 起因环境变量泄漏而红（四个调用方均已修）；
  硬链接防护在 GNU tar 上是死代码（改为以 tar 自身的净化警告为逃逸信号）；
  `check_cidrs.py` 以 root 执行却无门禁；`validate-static.sh` 迁移后静默漏检 4 个脚本。

## 进行中

- 无。计划内工作已全部完成并通过公开镜像仓的 8 分片 CI。

## 剩余工作

- 服务器执行 `scripts/bootstrap/run-approved.sh --check`，输出须与迁移前基线逐字段一致
  （PHASE/RESULT/REASON/EXIT_CODE），不得出现新的 STOP。属【运维】动作，需人工回执。
- helm 归档的「成员必须是正规文件」检查：合并 `validate_archive` 时未给 helm 族加，
  因无实测证据。待服务器上跑 `tar -tvzf helm-v3.21.0-linux-amd64.tar.gz linux-amd64/helm`
  确认条目类型后再定。
- `scripts/test_bootstrap.py` 两处 `invalid escape sequence '\$'`（Python 3.12 仅告警）。
- Tasks 4–12 尚未经独立评审（Task 3 那批已评审并修完 1 HIGH + 2 MEDIUM + 3 LOW）。

## 阻塞项

- **GitHub Actions 计费**：`unif-code` 组织 8 月的 2000 分钟免费额度已用尽（本仓库占
  1687 分钟 / 84%），spending limit 未开，私有仓所有 job 在 2 秒内失败，
  `validation-gate` 与 `publish-validated` 至今未绿。9 月 1 日重置或开小额上限即可恢复。
- 因上一条，`origin/validated` 仍指向迁移前的提交；服务器不带 SHA 执行
  `run-approved.sh` 时部署的是旧版本，服务器验收必须等计费恢复后进行。

## 最近验证

- 公开镜像仓 `engineering-platform-gitops-temp` 的 8 分片 CI 全绿（430 用例）：
  contracts 164 / artifacts 28 / kernel 12 / containerd 30 / kubernetes 62 /
  kubeadm 53 / cilium 46 / final-verify 35，另加 static、plan、validation-gate、
  publish-validated。该镜像是从本仓单向生成的消毒产物（主机身份换成 RFC 5737 文档段），
  仅用于借免费额度跑验证，不得在其上修改代码。
- `shellcheck -x $(git ls-files '*.sh')` 在 0.9.0（CI pin）与 0.11.0 下均干净。
- `./scripts/validate-static.sh` 通过；它已改为递归收集，迁移后仍覆盖全部 bootstrap 脚本。

## 工作树

- clean，`HEAD` 与 `origin/main` 一致。
- `.superpowers/sdd/` 按仓库规则被 gitignore，仅存于本机；但其中 R1–R15 各条裁决的
  依据与实测证据均已同步写入对应提交信息，从 git 历史可完整恢复，故
  `Remote Recoverable: yes`。
