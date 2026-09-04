# 180-openbao-initialize

Stage 180 是手工、交互式仪式，故意不在 `bootstrap-all.sh` 中。它接受 `--check`、
`--initialize`、`--configure`、`--recover-start`、`--recover-verify` 与 `--accept`；没有
通用 `--apply` 操作。

- `--check` 是只读操作，报告下一条显式操作；事故恢复必须带
  `--source-recovery-sha=<40 位小写 SHA>`。
  正常全新环境仍使用 `run-approved.sh [<SHA>] --check --stage=180`，无需 source SHA。
  普通 check/configure 遇到 candidate、marker、checkpoint 或私有 staging 时必须停止，
  不得把有效 v1 与事故材料混合状态当作普通配置。
- `--initialize` 仅执行一次 Shamir 5/3 初始化，仅写入 PGP 密文、公开 metadata、受保护的
  archive 及其 checksum。
- `--configure` 是正常 v1 路径：通过隐藏终端提示读取三份 unseal share 和初始 root token，
  在精确配置和 readback 后撤销 root token。
- `--recover-start` 仅用于已初始化事故现场：验证 source v1 包，使用三份未暴露旧 share，
  配置 Runtime 并生成候选恢复包；它不会撤销 root token。
- `--recover-verify` 验证候选包后通过三份新 share 完成 rotation verification，证明撤销初始
  root token，写入最终 v2 包和 verified marker。
- `--accept` 使用短期 Kubernetes-auth token，运行正反 Policy probe、核对两条 audit 流并写入
  `17-openbao-runtime` evidence；事故路径还验证最终 v2、marker、rotation 和 root 撤销状态。

恢复包由操作者上传到受控云存储。私有 OpenPGP key 与口令始终留在 Windows，绝不进入此仓库、
服务器、Kubernetes、日志或 evidence。MinIO、Snapshot、Backup、Restore 与应用 Secret
migration 均继续延后；本阶段不删除 Raft/Audit PVC，也不经 API 创建 audit device。source 或
candidate 包的清理不是本操作的一部分，必须另列精确路径并获得单独明确批准。

## 停止原因

- `untrusted-environment-override`
- `invalid-openbao-operation`
- `openbao-asset-drift`
- `openbao-runtime-not-ready`
- `public-key-missing-or-unsafe`
- `recovery-root-missing-or-unsafe`
- `recovery-bundle-state-unsafe`
- `unexpected-openbao-state`
- `git-commit-unreadable`
- `missing-command-install`
- `missing-command-mkdir`
- `missing-command-tar`
- `platform-secret-fingerprint-failed`
- `platform-secret-drift`
- `openbao-initialization-failed`
- `recovery-bundle-validation-failed`
- `recovery-bundle-finalization-failed`
- `openbao-unseal-failed`
- `openbao-configuration-failed`
- `openbao-auth-probe-failed`
- `openbao-audit-readback-failed`
- `applications-not-ready`
- `https-smoke-failed`
- `evidence-open-failed`
- `evidence-scan-failed`
- `source-recovery-sha-required`
- `source-recovery-sha-invalid`
- `source-recovery-bundle-unsafe`
- `interactive-tty-required`
- `openbao-root-login-failed`
- `remote-session-cleanup-failed`
- `openbao-cluster-identity-invalid`
- `openbao-rotation-state-unsafe`
- `openbao-rotation-init-failed`
- `openbao-rotation-share-submit-failed`
- `rotation-candidate-state-unsafe`
- `rotation-candidate-write-failed`
- `rotation-verification-failed`
- `rotation-backup-delete-failed`
- `recovery-final-bundle-state-unsafe`
- `recovery-final-bundle-write-failed`
- `initial-root-token-revoke-failed`
- `initial-root-token-still-valid`
- `recovery-verification-marker-unsafe`
