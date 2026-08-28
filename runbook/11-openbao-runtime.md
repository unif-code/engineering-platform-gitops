# DEV OpenBao Runtime-Only 部署与验收

状态：`CANDIDATE / RUNTIME NOT_EXECUTED`

本 runbook 只部署并验收 OpenBao Runtime。固定范围是 OpenBao `2.6.1`、官方 Chart
`0.28.6`、Server `1`、Agent Injector `1`、`NON_HA` 单节点 Raft、Data PVC
`10Gi`、Audit PVC `5Gi`、TLS `ClusterIP` only、Shamir 5/3、Audit file + stdout、
Kubernetes Auth 和专用 probe Policy。

以下始终不在本批次：MinIO、Snapshot、Backup、Restore、应用 Secret 迁移、Ingress、
Gateway、NodePort、LoadBalancer。OpenBao Runtime 验收不等于 Backup/Restore 或 Release
Gate 通过。

## 门禁与执行原则

- 只使用合并后且 `origin/main == origin/validated` 的完整 SHA。
- 所有服务器入口统一经过 `scripts/bootstrap/run-approved.sh`；它校验 SHA、origin、
  `main`、干净工作树、ff-only 与残留，并用 `env -i` 启动。
- Stage 170 在 `bootstrap-all` 中；Stage 180 永不自动串联，必须显式选择单个操作。
- 每条服务器或 Kubernetes 写命令仍须在执行前完整展示，说明影响与预期 readback，并等待
  当前回执审核。不得把 blanket approval 当成跳过现场回执。
- 不得把 share、root token、私钥、口令、JWT、kubeconfig 或解密后的任何值写入聊天、
  命令参数、环境变量、文件、日志或 evidence。

## 1. Stage 170 只读检查

【运维】完整命令：

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --check; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

预期：Stage 00–160 返回 `ALREADY_COMPLIANT`，Stage 170 返回
`PASS_OPENBAO_RUNTIME_CHECK`，且 `REASON=openbao-runtime-apply-required`。检查必须确认
当前 OpenBao inventory 为空、业务仍 Ready、平台 Secret fingerprint 可读取、容量足够、
固定 Chart/Image/render digest 一致。任何 `STOP_*`、未知 inventory、外部暴露、备份资源、
source revision 漂移或非零退出码都停止。

## 2. Stage 170 安装 Runtime

【运维】【写入】完整命令：

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --apply; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

影响范围只允许：

- 创建 `openbao` Namespace、固定 ResourceQuota、最小 RBAC、TLS Certificate 与网络策略；
- 在 `flux-system` 创建 OpenBao bootstrap RBAC 和独立 `openbao-runtime` Kustomization；
- 由 Flux 创建固定 HelmRelease、Server、Injector、ClusterIP Service、Data/Audit PVC；
- 保持根 `clusters/dev/kustomization.yaml` 不引用 OpenBao，避免发布 `validated` 时静默激活。

预期结果为 `PASS_OPENBAO_RUNTIME_INSTALLED`。readback 必须证明 OpenBao `2.6.1`、
Server/Injector 各 1、运行 `imageID` 精确匹配 linux/amd64 digest、PVC 为
`10Gi/5Gi`、无外部 Service/Route/Ingress、无 MinIO/Backup/Snapshot/Restore，且
`initialized=false`、`sealed=true`。Stage 170 不初始化、不 unseal、不创建 OpenBao
root token。

安装后重跑第 1 节命令；预期 Stage 170 为 `ALREADY_COMPLIANT`。

## 3. Windows OpenPGP 恢复准备

在 Windows Git Bash 运行：

```bash
./scripts/openbao/recovery-ceremony-wizard.sh
```

向导只处理必须由人完成的五步：安装/确认 Gpg4win、创建带 passphrase 的专用恢复 key、
导出 base64 公钥及 fingerprint、校验并解密 ciphertext bundle 到 Windows clipboard、
确认 cloud 上传并清空 clipboard。私钥和 passphrase 不上传服务器，也不与 ciphertext
bundle 存在同一 cloud 位置。

服务器只接收以下两个公开文件，均须 root-owned、mode `0600`：

- `/root/.config/engineering-platform/openbao-recovery-public-key.b64`
- `/root/.config/engineering-platform/openbao-recovery-public-key.fingerprint`

恢复目录必须预先创建为 root-owned、mode `0700`：
`/root/openbao-recovery`。上传落点确定后，agent 必须用实际绝对路径替换
`<UPLOADED_PUBLIC_KEY>` 与 `<UPLOADED_FINGERPRINT>`，再完整展示受控
`install -d/install -m 0600` 命令；不得猜测上传路径或覆盖不同的既有文件。

## 4. Stage 180 只读检查

【运维】完整命令：

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --check --stage=180; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

首次预期：
`RESULT=PASS_OPENBAO_INITIALIZATION_CHECK`、
`REASON=initialization-required`。该操作不初始化、不 unseal、不配置 API、不写 evidence。

## 5. 初始化并生成 ciphertext recovery bundle

【运维】【写入，初始化不可重复】完整命令：

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --apply --stage=180 --operation=initialize; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

该操作只执行一次 Shamir 5/3 初始化，同一已核验 OpenPGP 公钥分别加密 5 个 share 和初始
root token。服务器只保存 ciphertext JSON、公开 metadata、公钥副本、ciphertext
`.tar.gz` 和 SHA-256 sidecar，权限为 `0600`。任何不完整目录、既有不匹配 archive、
明文 token 形态或校验失败都 fail closed，绝不重新初始化。

预期：
`RESULT=PASS_OPENBAO_INITIALIZED`、
`REASON=encrypted-recovery-bundle-ready`，OpenBao 状态变为
`initialized=true,sealed=true`。bundle 位于：

```text
/root/openbao-recovery/openbao-recovery-<MERGED_SHA>.tar.gz
/root/openbao-recovery/openbao-recovery-<MERGED_SHA>.tar.gz.sha256
```

将这两个 ciphertext 文件下载到 Windows，用 recovery wizard 校验 sidecar。上传到受控
cloud 后仍保留本地 ciphertext 副本，直到最终验收完成；cloud 上传不属于 Stage 180 自动操作。

## 6. Unseal、配置与初始 root token 吊销

先在 Windows 向导中逐次选择 `share1`、`share2`、`share3`，每次只把解密结果放入
clipboard。然后执行：

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --apply --stage=180 --operation=configure; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

命令会出现三个 hidden unseal prompt。完成 unseal 后，再由 Windows 向导选择 `root`，
仅粘贴到 hidden root-token prompt。root token 通过 stdin 登录 mode-`0600` 的临时 token
helper，配置并精确 readback：

- declarative `to-file/` 与 `to-stdout/` Audit，HMAC 开启、`log_raw=false`；
- Kubernetes Auth，使用 in-cluster reviewer token/CA；
- `openbao-probe/` KV v2、最小 probe Policy 与 `audience=openbao` 的 10 分钟角色。

成功 readback 后初始 root token立即 `revoke -self`，临时 token helper 删除。预期结果：
`PASS_OPENBAO_CONFIGURED`，`REASON=openbao-kubernetes-auth-ready`。若中途失败，保持 PVC
和 ciphertext bundle，不创建第二次初始化；清空 clipboard 后先审核 `STOP_*` 再重跑同一
显式操作。

## 7. 验收与 evidence

【运维】【写入 probe 与 evidence】完整命令：

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --apply --stage=180 --operation=accept; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

该操作创建 10 分钟、`audience=openbao` 的 ServiceAccount JWT，经 stdin 换取临时 OpenBao
token，完成 KV put/get/delete 正向 probe、`sys/auth` 拒绝负向 probe、单 Raft leader
readback，并吊销临时 token。随后验证 file/stdout audit 都包含 HMAC path 且不含 probe 明文，
重放业务 HTTPS smoke，并确认现有应用 Kubernetes Secret fingerprint 未变。

预期：
`RESULT=PASS_OPENBAO_RUNTIME_ACCEPTED`，并生成：

```text
/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt
/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt.sha256
```

evidence 必须包含 `MINIO=NOT_EXECUTED`、`BACKUP=NOT_EXECUTED`、
`APP_SECRET_MIGRATION=NOT_EXECUTED`、`INITIAL_ROOT_TOKEN=REVOKED` 和
`SECRET_VALUES=NOT_RECORDED`，不得包含 share、root token、JWT、OpenBao client token
或 recovery ciphertext。用 `sha256sum -c` 核验 sidecar 后再回填验收记录。

## STOP 分类

- `STOP_SUPPLY_CHAIN_MISMATCH`：Chart、Image、render、bootstrap/runtime bundle 任一摘要漂移。
- `STOP_PRECONDITION`：容量、业务、public key、recovery root、运行状态或命令入口不合规。
- `STOP_UNKNOWN_STATE`：inventory、OpenBao 状态、recovery bundle、Git SHA 或 fingerprint
  无法精确判定。
- `STOP_APPLY_FAILED`：Namespace/bootstrap/runtime、初始化、unseal、配置或 evidence 写入失败。
- `STOP_VERIFY_FAILED`：server validation、readback、Auth/Audit probe、业务 smoke、Secret
  fingerprint 或 evidence secret scan 失败。

出现 STOP 时禁止手工 `kubectl apply`、临时扩权、重建 Namespace、重跑
`bao operator init` 或删除 PVC 来绕过。

## PVC-preserving 恢复与回滚边界

- Stage 170 失败且 inventory 非空时停止，不做自动清理；先保留 Namespace、Data PVC 与 Audit
  PVC，按 UID/generation/readback 确认归属。
- Stage 180 初始化后只能恢复或继续，不能“重新初始化”。恢复依赖 ciphertext bundle、其
  SHA-256、专用私钥/passphrase 和任意 3 个 share。
- 若必须停用 Runtime，先提交并通过 `validation-gate` 的专门 suspend/scale 方案，逐条展示
  mutation 与 readback；不得删除 Raft/Audit PVC、Namespace、finalizer 或 recovery bundle。
- 本批次没有自动卸载路径。任何删除请求必须另写经评审的销毁 runbook，并在已验证 cloud
  ciphertext bundle 和本地恢复材料后单独批准。
