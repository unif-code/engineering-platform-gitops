# DEV OpenBao Stage 180 事故恢复设计

## 1. 目的与适用现场

本文定义 DEV OpenBao 在 Stage 180 已完成初始化、但首次配置因隐藏输入未连接到真实
TTY 而中断后的非破坏性恢复路径。它补充
`2026-08-28-openbao-runtime-only-activation-design.md`，只覆盖本次 Stage 180 事故恢复；
未被本文修改的 Runtime、GitOps、供应链、容量和安全边界继续以原设计为准。

恢复路径基于以下可验证状态，不在文档中记录任何 recovery share、root token、私钥或
passphrase：

- Stage 170 已完成，OpenBao Server、Agent Injector、Data PVC 与 Audit PVC 均保留；
- Stage 180 `initialize` 已成功生成五份 OpenPGP 加密 share 与加密初始 root token；
- OpenBao 已初始化且 sealed，尚未完成 Runtime 配置与最终验收；
- 首次 `configure` 在 `bao operator unseal` 读取非 TTY stdin 时 Fail Closed；
- 一份旧 share 随后被误粘贴到交互 shell，必须视为已经泄露；
- shell history 中同形态条目已清理并完成非敏感回读，但终端记录与聊天记录不能被视为
  已消除，因此最终验收前必须通过正式 key rotation 使旧 share 失效。

本文不授权重新初始化、删除 PVC、修改 Raft 数据、手工 patch 集群对象或绕过
`run-approved.sh`。

## 2. 根因与修复边界

当前实现先用 shell 的隐藏 `read` 捕获 share，再通过管道把值送给：

```text
bao operator unseal -format=json
```

`bao operator unseal` 在没有位置参数时会自行从终端隐藏读取 key。管道使文件描述符 0
不再是 TTY，因此 CLI 在提交 share 前失败。修复必须尊重不同 OpenBao 命令的输入契约：

- unseal 不捕获、不管道、不放入参数；通过 `kubectl exec --stdin --tty` 让 OpenBao CLI
  自己执行隐藏读取；
- `operator rotate-keys` 的 share 提交显式使用其 `KEY=-` stdin 契约；外层脚本仅做一次
  无回显读取，通过 stdin 提交后立即清空临时 shell 变量；
- root token 通过真实 TTY 交给 `bao login` 的隐藏提示，绝不进入参数、环境变量、日志或
  Evidence；认证完成后只允许使用容器内短期 token helper，并用 trap 保证清理。

实现不得以 `-key=<value>`、`BAO_TOKEN=<value>`、临时 Kubernetes Secret、命令替换、
调试回显或 shell tracing 规避输入问题。

READY checkpoint 重入使用固定 v2.6.1 的 `bao login -no-print lookup=false`（无 token
参数），仍由 CLI 自身隐藏读取。stdout 在容器内丢弃、早于 kubectl TTY 合流，stderr 保留
隐藏提示，避免 token-helper Store 失败时输出 token。Store 成功不代表认证或撤销成功；
必须先匹配 checkpoint commitment，再验证 lookup/revoke 与精确认证拒绝，且检查清理。

## 3. 锁定范围

### 3.1 本批次必须完成

- 修复 unseal 的真实 TTY 交互；
- 从已验证的旧 recovery bundle 恢复配置流程，且不覆盖旧包；
- 完成 TLS、Audit、Kubernetes Auth、最小 Policy 与验证 Role 配置；
- 使用同一专用 OpenPGP 公钥启动 OpenBao `5/3` root key rotation；
- 用三份不同的有效旧 share 授权 rotation，无需识别泄露编号；
- 生成仅含新 share 密文和非敏感元数据的候选恢复包；
- 用三份新 share 完成 OpenBao rotation verification；
- verification 成功后撤销初始 root token，并证明泄露的旧 share 已随整组旧 key 失效；
- 生成最终恢复包、Stage 180 验收结果和既定 Evidence/SHA-256 sidecar。

### 3.2 明确不在范围内

- 重新执行 `operator init`、删除或重建 Data/Audit PVC；
- 自动删除旧 recovery bundle、候选 bundle、用户本地下载或旧 GPG key；
- MinIO、Snapshot、Backup、Restore、Restore Drill；
- 应用 Secret migration、应用 Pod 注入、现有 Kubernetes Secret 回收；
- OpenBao 外部入口、多副本、auto-unseal 或生产可用性声明；
- 任何分支、worktree 或用户本地提交清理。

最终 Evidence 必须继续将上述未执行项记录为 `NOT_EXECUTED`。

### 3.3 2026-09-04 获批调整：有效旧份额 quorum

操作者已无法确认曾暴露的旧 share 编号，选择保留数据、轮换份额的非破坏性路径。此前
“只能使用未泄露旧 share”的人工限制在本次恢复中改为：从已校验 source v1 包选择任意
三份不同的有效旧 share，分别用于 unseal 与 rotation 授权；两轮可复用同三份。无需寻找、
比对或记录泄露明文，不从聊天/日志取回 share，也不根据提示中的提交次序猜测包内编号。

该调整不改变 OpenBao quorum 或输入契约，不把旧材料重新判为安全。整组旧份额均按待替换
材料处理；只有新份额 verification 的 live readback 成功后，才能声明当前实例的旧份额
失效，不据此声称历史备份或已泄露数据安全。新 5/3 份额仍由同一专用 PGP 公钥加密，保留
新份额验证、root token 撤销、恢复包与最终验收门禁；不得先删除旧包、GPG 私钥或 PVC。

## 4. 跨 SHA recovery bundle 采用

初始化包以当时获批 Git SHA 命名。修复进入新的获批 SHA 后，恢复路径必须显式接收：

```text
--source-recovery-sha=<40 位小写 Git SHA>
```

该参数只标识 `/root/openbao-recovery/openbao-recovery-<SHA>.tar.gz`，不能接收任意路径。
采用旧包前必须 Fail Closed 验证：

1. source SHA 存在于本地 Git 对象库，且是当前获批 `origin/main` 的祖先；
2. archive 与 `.sha256` 都存在、属主为 root、mode 为 `0600`，摘要匹配；
3. tar entry 全部为普通文件、没有绝对路径、`..`、symlink、hardlink 或设备文件；
4. v1 metadata 的 source SHA、docs baseline、平台 Secret 非敏感 fingerprint 与 OpenPGP
   fingerprint 一致；
5. 恰有五份合法 OpenPGP share 密文和一份加密初始 root token；
6. live OpenBao 必须为 initialized/sealed，cluster identity 格式合法；该 identity 的摘要从
   live readback 建立并写入本次恢复事务，不能伪称来自不含该字段的 v1 metadata；
7. 敏感形态扫描不得发现明文 share、token 或私钥。

旧包保持只读、不可覆盖。新 SHA 的恢复状态只引用其摘要，不复制旧密文为“新初始化”证据。
任何参数、metadata、checksum 或集群身份不一致都返回明确 `STOP_*`，不得猜测或吸收未知
现场状态。

## 5. 受控操作与状态机

Stage 180 保留现有 `check`、`initialize`、`configure`、`accept`，并为这个已知事故加入两个
显式操作。正常的全新环境不自动进入事故恢复路径。

```text
INITIALIZED_SEALED
        |
        | recover-start --source-recovery-sha=<old SHA>
        v
UNSEALED_CONFIGURED_ROTATION_PENDING
        |
        | 下载并验证候选包，在 Windows 隐藏解密三份新 share
        v
NEW_SHARES_AVAILABLE_TO_OPERATOR
        |
        | recover-verify --source-recovery-sha=<old SHA>
        v
ROTATION_VERIFIED_ROOT_REVOKED
        |
        | accept
        v
ACCEPTED
```

### 5.1 `recover-start`

`recover-start` 必须按顺序执行：

1. 重跑 Stage 170/180 非敏感前置 readback，并采用经过验证的 source bundle；
2. 连续三次启动真实 TTY unseal，每次由 OpenBao CLI 自己隐藏读取一份不同的有效旧 share；
3. 每次提交后用独立 `bao status -format=json` readback 判断 progress，禁止解析或保存输入；
4. OpenBao unsealed 后，通过真实 TTY 隐藏登录初始 root token；
5. 幂等配置并验证 TLS、两个 Audit device、Kubernetes Auth、最小 Policy 与 Role；
6. 用 source bundle 中同一 OpenPGP public key 初始化 `5/3` rotation，并要求 PGP 加密与
   verification；
7. 通过 `KEY=-` 分别提交三份不同的有效旧 share，保存 OpenBao 返回的新 share 密文、
   verification nonce 和非敏感状态；
8. 生成 mode `0600`、noclobber 的候选包及 SHA-256 sidecar；
9. 无论成功或失败都删除容器内 token helper，并关闭 shell tracing。

候选包只用于操作者在 Windows 解密新 share。它不能被 `accept` 当作最终恢复包，也不能
证明 rotation 已完成。

### 5.2 `recover-verify`

`recover-verify` 必须：

1. 验证 source bundle、候选包、checksum、fingerprint、cluster identity 与当前 rotation
   状态一致；
2. 通过真实 TTY 再次隐藏登录初始 root token；
3. 使用 OpenBao verification nonce 与 `KEY=-` 提交三份新 share；
4. 从 OpenBao readback 证明 verification 完成且没有 pending rotation；
5. 重新验证 Runtime 配置和 Kubernetes Auth 最小权限探针；
6. 撤销初始 root token，并用非敏感失败 readback 证明该 token 不再可认证；
7. 清理容器内 token helper；
8. 生成 noclobber 的最终恢复包，内容只包括五份新 share 的 OpenPGP 密文、公钥、
   fingerprint、checksum 与非敏感 verified metadata，不携带已撤销 token 密文；
9. 写入非敏感 verified marker；marker 必须与 OpenBao live readback 共同验证，不能单独
   作为事实源。

任何一步失败都不得撤销或覆盖 source/candidate bundle。只有 OpenBao 明确完成 verification
后，才能声明整组旧 key（包括已泄露 share）失效。

### 5.3 `accept`

`accept` 除原有 Runtime 验收外，必须新增硬门禁：

- rotation 不处于 pending 状态；
- verified marker 与 OpenBao live readback、最终 bundle digest 一致；
- 最终 bundle 为 `5/3`、五份新 share 密文、无 root token；
- 初始 root token 已撤销；
- 旧 share 集合已经失效；
- 当前 Git SHA 与 `origin/main`、`origin/validated` 一致，CI 门禁已通过。

任一条件不满足都返回 `STOP_*`，不得生成最终 Evidence。

## 6. 恢复包 schema 与生命周期

最终恢复包使用新 schema `engineering-platform/openbao-recovery/v2`。非敏感 metadata 至少
包含：

- current Git SHA 与 source recovery SHA；
- source bundle SHA-256 与 OpenPGP fingerprint；
- OpenBao cluster identity 的非敏感摘要；
- `key_shares=5`、`key_threshold=3`；
- `rotation_state=verified` 与 verification 完成 UTC；
- `initial_root_token=revoked`；
- 每份密文文件的 SHA-256。

候选包使用独立的
`openbao-recovery-rotation-candidate-<current SHA>.tar.gz` 文件名和
`engineering-platform/openbao-recovery-rotation-candidate/v1` schema。最终包继续使用既定
`openbao-recovery-<current SHA>.tar.gz` 名称，且必须通过 noclobber 创建。最终包生成后也不
自动删除 source 或 candidate；后续清理必须单独列出精确路径并取得明确批准。

Windows wizard 必须识别 v1 source 包和 v2 最终包：

- v1 允许选择旧 share 或初始 root token，只用于本次受控恢复；
- candidate 只允许选择新 share，并明确显示“尚未 verification，不可作为最终恢复包”；
- v2 只允许选择新 share，并明确初始 root token 已撤销；
- 所有解密仍通过 GPG pinentry 和 Windows clipboard，wizard 不打印、不落盘明文；
- wizard 不自动上传云盘，不把 passphrase、私钥或恢复材料发送给 Codex、Git 或服务器。

## 7. 失败处理与重入

- TTY 不可用时在读取任何 share 前停止，错误必须是 `interactive-tty-required`；
- unseal 未达 quorum 时允许重跑，但脚本不能记录已提交 share 的值或序号到 Evidence；
- 已 unsealed 时跳过 unseal，只做 live readback，不要求重复输入旧 share；
- 配置步骤必须幂等；未知 Audit/Auth/Policy 所有者或超出设计权限时停止；
- rotation 已初始化但未提交满旧 quorum 时，从 OpenBao status 恢复同一 nonce，禁止启动
  第二次 rotation；
- candidate 已存在时验证并复用，禁止覆盖或生成另一组新 share；
- candidate 在同文件系统 mode `0700` 的 `.openbao-candidate-staging-<SHA>` 中构建，
  固定 intent 绑定预期密文字节，文件 mode `0600` 并逐文件/父目录 fsync。完整 archive、
  sidecar 与目录验证一致后只用 noclobber hardlink 发布，sidecar 最后可见。中断重入从同一
  已认证加密 backup 重建预期字节，私有半写文件只补齐严格匹配前缀的缺失后缀；已发布
  部分必须与 staging 同 inode。未知成员、字节/属主/mode/nonce 不一致均停止。staging
  有界保留，不自动删除 source/candidate/staging；使用完整候选包前重新确认目录持久性；
- verification 部分完成时恢复同一 nonce，禁止重新初始化 rotation；
- root token 撤销只发生在 verification 和 Runtime readback 均成功之后；
- token helper 清理使用 trap，失败也执行；清理失败使操作失败并阻止 Evidence；
- 任何失败都保留 PVC、source bundle、candidate bundle 与 OpenBao live state，禁止自动
  rollback 到重新初始化。

## 8. 日志、Evidence 与敏感值门禁

脚本和测试必须证明：

- `set -x` 在所有隐藏输入和 token helper 生命周期内被禁止；
- share、token、passphrase、私钥不出现在 argv、environment、stdout、stderr、临时文件、
  journal、shell history、Git diff 或 Evidence；
- rotation API/CLI 的 JSON 只保存允许的密文和非敏感字段；敏感字段使用 allowlist 解析，
  不整包回显；
- 临时文件目录 mode 为 `0700`，文件 mode 为 `0600`，并使用 trap 做最小化清理；
- 最终 Evidence 先完成敏感形态扫描，再以 `0600` 原子落盘并生成 SHA-256 sidecar。

最终 Evidence 路径保持：

```text
/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt
/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt.sha256
```

除原有验收字段外，至少包含：

```text
UNSEAL_KEY_ROTATION=PASS
COMPROMISED_SHARE_INVALIDATED=true
INITIAL_ROOT_TOKEN=REVOKED
RECOVERY_BUNDLE_SCHEMA=engineering-platform/openbao-recovery/v2
MINIO=NOT_EXECUTED
SNAPSHOT=NOT_EXECUTED
BACKUP=NOT_EXECUTED
RESTORE=NOT_EXECUTED
APP_SECRET_MIGRATION=NOT_EXECUTED
```

Evidence 只能记录 bundle checksum，不能记录密文正文、fingerprint 以外的 key material、
nonce、share、token 或可用于认证的值。

## 9. 验证策略

实现采用 test-first，至少覆盖：

- unseal 必须使用 `kubectl exec --stdin --tty`，且没有 share pipe/argv/env；
- 无 TTY 在读取敏感值前 Fail Closed；
- rotation share 只通过隐藏读取和 `KEY=-` stdin 契约提交；
- source SHA、archive 路径、tar entry、schema、checksum、owner/mode 与 fingerprint 拒绝矩阵；
- source/candidate/final bundle 的 noclobber 与重入；
- 配置成功、rotation pending、部分提交、verification、root revoke 的状态机；
- verification 前 `accept` 必须失败，verified 后才生成 Evidence；
- source/candidate/final artifacts 和测试输出均通过敏感形态扫描；
- wizard 对 v1、candidate、v2 的选择与禁止行为；
- MinIO、Snapshot、Backup、Restore、应用 Secret migration 仍保持未执行。

focused tests、ShellCheck `0.9.0`、manifest/render 检查和 `./scripts/validate-fast.sh` 必须在
本地通过；PR `validation-gate` 全绿、合并后的独立 main push CI 全绿且
`publish-validated` 成功后，服务器才允许执行新 SHA。

## 10. 运维执行门禁

- 服务器只能使用外部 Chrome 中最新的“Web终端 - 统一企业堡垒机”标签页；禁止 SSH 或
  本地终端访问服务器；
- 每一条服务器命令必须先完整展示并等待回执，且只通过
  `scripts/bootstrap/run-approved.sh <approved SHA> ...`；
- 所有敏感输入都由操作者在实际黑色终端的 OpenBao/GPG 隐藏提示中手动输入；不得粘贴到
  浏览器辅助发送框、聊天、命令行或普通 shell prompt；
- 部署修复 SHA 前必须重新执行 `--check`，并核对 `origin/main=origin/validated=<SHA>`；
- 只有 `recover-start`、候选包下载/验证、`recover-verify`、最终包下载/验证和 `accept`
  的全部 readback 符合本文，才可声明 Stage 180 完成。

本文不改变进度同步、Secret migration、备份或分支清理的授权边界。

## 11. 官方行为依据

- OpenBao `operator unseal`：无 key 参数时从 TTY 隐藏读取，key 作为命令参数会暴露在
  shell history：<https://openbao.org/docs/commands/operator/unseal/>；
- OpenBao Kubernetes Helm 操作指南：unseal 示例使用交互 TTY：
  <https://openbao.org/docs/platform/k8s/helm/run/>；
- OpenBao `operator rotate-keys`：支持 PGP 加密、verification、`5/3` 参数与 `KEY=-`
  stdin 提交：<https://openbao.org/docs/commands/operator/rotate-keys/>；
- OpenBao `v2.6.1` 对应 CLI 实现与测试：
  <https://github.com/openbao/openbao/blob/v2.6.1/command/operator_rotate_keys.go>、
  <https://github.com/openbao/openbao/blob/v2.6.1/command/operator_rotate_keys_test.go>。
