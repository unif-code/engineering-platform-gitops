# OpenBao 恢复仪式

仅在 Windows Git Bash 运行 `recovery-ceremony-wizard.sh`。它只协助需要操作者的
Windows GPG、pinentry、剪贴板和受控云存储步骤；不在 CI 中运行，也不连接服务器。

向导从已完整校验的恢复包读取 schema；操作者不声明 schema。它在解密前同时核对
`.sha256` sidecar，并将读取到的 schema 作为 `openbao_recovery.py emit-item` 的预期值，
使检查与取出之间的 schema 变化失败关闭：

- `engineering-platform/openbao-recovery/v1`：只用于本次事故恢复；可选择
  `share1..share5` 或初始 `root`。unseal 和旧份额轮换授权分别需要三份不同的有效旧 share，
  两轮可以复用同三份；无需识别泄露编号，不从聊天或日志取回明文。
- `engineering-platform/openbao-recovery-rotation-candidate/v1`：只允许
  `share1..share5`；候选恢复包尚未完成验证，不是最终恢复包。
- `engineering-platform/openbao-recovery/v2`：只允许 `share1..share5`；初始 root
  token 已撤销，确认最终密文包和 sidecar 已上传到受控云存储后清空剪贴板。

这里的 v1 是事故恢复路径：先带 source SHA 的只读 check，再 `recover-start`。它不是
Stage 180 正常首次配置的 `--configure` 路径；事故恢复不得跳步或改用 `configure`。

整组旧 share 均按待替换材料处理；只有新份额 verification 成功后，才能声明当前实例的
旧份额失效。恢复完成前保留旧包和 GPG 私钥，不重新生成 GPG key，也不重新初始化 OpenBao。
新份额验证、初始 root token 撤销、最终包验证与验收门禁全部保留。

明文只经 GPG pinentry 解密到 Windows 剪贴板，绝不写入仓库、`.env`、GitHub、stdout、
命令参数、环境变量或文件。私钥和口令不得上传，也不得与密文包放在同一云端位置。

服务器步骤只可在外部 Chrome 的最新“Web终端 - 统一企业堡垒机”标签页中，按
`runbook/11-openbao-runtime.md` 所列的 `run-approved.sh` 命令执行并逐条等待回执；不得
使用 SSH、应用内浏览器或本地终端。source 与 candidate 恢复包的清理是另一项需明确批准的
工作；向导不会删除任何恢复材料，也不会执行 Backup、Restore 或应用迁移。
