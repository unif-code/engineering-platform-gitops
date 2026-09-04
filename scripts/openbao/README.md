# OpenBao 恢复仪式

仅在 Windows Git Bash 运行 `recovery-ceremony-wizard.sh`。它只协助需要操作者的
Windows GPG、pinentry、剪贴板和受控云存储步骤；不在 CI 中运行，也不连接服务器。

向导要求操作者选择已下载恢复包的 schema，并在解密前同时核对 `.sha256` sidecar 和
仓库内的 `openbao_recovery.py emit-item` 校验：

- `engineering-platform/openbao-recovery/v1`：只用于本次事故恢复；可选择
  `share1..share5` 或初始 `root`，但绝不可再次使用已暴露的旧 share。
- `engineering-platform/openbao-recovery-rotation-candidate/v1`：只允许
  `share1..share5`；候选恢复包尚未完成验证，不是最终恢复包。
- `engineering-platform/openbao-recovery/v2`：只允许 `share1..share5`；初始 root
  token 已撤销，确认最终密文包和 sidecar 已上传到受控云存储后清空剪贴板。

明文只经 GPG pinentry 解密到 Windows 剪贴板，绝不写入仓库、`.env`、GitHub、stdout、
命令参数、环境变量或文件。私钥和口令不得上传，也不得与密文包放在同一云端位置。

服务器步骤只可在外部 Chrome 的最新“Web终端 - 统一企业堡垒机”标签页中，按
`runbook/11-openbao-runtime.md` 所列的 `run-approved.sh` 命令执行并逐条等待回执；不得
使用 SSH、应用内浏览器或本地终端。source 与 candidate 恢复包的清理是另一项需明确批准的
工作；向导不会删除任何恢复材料，也不会执行 Backup、Restore 或应用迁移。
