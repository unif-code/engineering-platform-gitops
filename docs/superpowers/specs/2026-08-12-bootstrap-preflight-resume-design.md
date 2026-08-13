# Bootstrap Preflight 可恢复运行时验真设计

状态：已完成方案选择，待书面设计确认

目标仓库：`engineering-platform-gitops`

目标主机：`retail-test-workflow` / Ubuntu 24.04 / `linux/amd64`

## 1. 背景

目标主机已经完成 stage 00～30，containerd、runc、crictl、配置、systemd unit 与 data root 均由 `30-install-containerd.sh` 安装并验证。主机同步到 commit `12141c77cbbdf43cee3719e114d5d36980d6ac8b` 后执行：

```text
./scripts/bootstrap/bootstrap-all.sh --check
```

编排器在 stage 00 安全停止：

```text
RESULT=STOP_OLD_RUNTIME
REASON=unexpected-path-/etc/containerd
EXIT_CODE=30
```

根因不是服务器漂移，而是恢复合同自相矛盾：

- stage 00 把任何 containerd binary、目录或 unit 都视为旧运行时；
- stage 30 又把这些路径作为期望的受管状态；
- 编排器每次都从 stage 00 读取真实状态，因此 stage 30 一旦成功，后续恢复必然被 stage 00 永久拦截。

## 2. 目标

1. stage 00 继续验证主机身份、OS、架构、cgroup、IP、swap、基础服务、清理 evidence、CIDR 与遗留工作流状态。
2. 对 containerd 目标状态不按“存在即拒绝”，而由唯一事实源 stage 30 做完整只读验真。
3. 只接受 stage 30 的精确 `ALREADY_COMPLIANT` 结果；部分状态、漂移、未知状态、异常输出或执行失败仍 fail closed。
4. 编排器保持无进度文件恢复：00～30 合规时逐项跳过，并在 40 首个需要 apply 的阶段停止。
5. 保持 `--check` 零变更，不删除服务器上的 `/etc/containerd` 或任何已完成的受管状态。

## 3. 非目标

- 不放宽 Docker、Caddy、Node、旧 workflow 或端口 3001 的拒绝规则。
- 不在 stage 00 复制 stage 30 的 digest、systemd、socket、CRI health 或 data-root 校验逻辑。
- 不根据文件存在、版本字符串、evidence 文件或编排进度文件推断 containerd 合规。
- 不改变 stage 10～90 的安装顺序、RESULT 合同或 apply 行为。
- 不在本次修复中清理主机、重装 containerd、继续 Kubernetes 部署或引入额外 hardening。

## 4. 设计

### 4.1 将遗留状态分成两类

stage 00 保留“无条件拒绝”的遗留状态：

- `caddy`、`docker`、`dockerd`、`node`、`npm`、`npx`、`pnpm` binary；
- Caddy、Docker 相关 package、目录与 systemd unit/socket；
- `/data/workflow`、旧 Node 目录和监听端口 3001；
- 与本仓目标安装方式冲突的 `containerd.io` package。

以下内容改为“目标 containerd footprint”，不能仅凭存在判定好坏：

- containerd、runc 及配套受管 binary；
- `/etc/containerd`、`/opt/containerd`、`/var/lib/containerd`；
- `containerd.service` 及其运行状态。

### 4.2 目标 containerd 的三态处理

stage 00 先完成与运行时无关的主机检查，再判断目标 containerd footprint：

1. **完全不存在**：记录 `TARGET_RUNTIME=absent`，继续 preflight。
2. **存在且 stage 30 精确合规**：只读执行固定仓内 `30-install-containerd.sh --check`；仅当子阶段 exit 0 且结构化输出唯一、完整、`RESULT=ALREADY_COMPLIANT`、`EXIT_CODE=0` 时，记录 `TARGET_RUNTIME=managed-compliant` 并继续。
3. **其他所有情况**：返回 `STOP_OLD_RUNTIME` / exit 30。包括部分文件、错误版本、digest/owner/mode 漂移、unit/service/socket/CRI 不健康、stage 30 非零、`PASS_CONTAINERD_CHECK`、输出缺字段/重复字段或未知 RESULT。

这保证“已安装的目标状态可恢复”，但“看起来像 containerd 的任意状态”仍不会被信任。

### 4.3 子阶段调用边界

stage 00 使用固定 `/bin/bash -p` 与固定仓内 stage 30 路径，以 `--check` 调用；清除会影响子 shell 的 `BASH_ENV`、`ENV`，生产 PATH 保持批准的系统路径。调用不得使用 `--apply`。

stage 30 的原始 stdout/stderr 仅用于严格解析，不透传到 stage 00 的成功摘要或 evidence。解析合同与编排器一致：RESULT、EXIT_CODE、EVIDENCE、SHA256 各恰好一项，且成功 exit 必须与 `EXIT_CODE=0` 一致。任何 canary、重复字段或非零退出都作为未知/不合规状态处理，不泄漏为成功证据。

test mode 只允许显式的隔离 fixture 注入同目录 stage 30；production 不接受 override。

### 4.4 编排恢复语义

`bootstrap-all.sh` 无需改变阶段顺序：

```text
00 PASS_PREFLIGHT
10 ALREADY_COMPLIANT
20 ALREADY_COMPLIANT
30 ALREADY_COMPLIANT
40 PASS_KUBERNETES_CHECK
```

因此 `bootstrap-all.sh --check` 应返回 `PASS_BOOTSTRAP_CHECK`、`NEXT_STAGE=40`。`--apply` 仍会在获取互斥锁、验证 clean main 后从真实状态重新检查，并只从 40 开始发生后续变更。

## 5. 安全与错误处理

- stage 00 不自行声明 containerd 健康；所有目标运行时判定都委托给 stage 30。
- 委托只读、固定路径、固定参数、严格输出，拒绝环境 override 与模糊成功。
- target footprint 的竞态最终由 stage 30 的多层路径、owner、mode、digest、systemd 与 health Gate fail closed。
- stage 00 的其他主机 Gate 不因已安装 containerd 而跳过；每次恢复仍重新验证 swap、IP、服务、CIDR 和遗留状态。
- 失败时不删除、不覆盖、不修复目标状态；只给出结构化 STOP，等待诊断。

## 6. 测试策略

先写会在旧实现上失败的回归测试，再修改生产代码：

1. target containerd footprint 存在且 stage 30 返回精确 `ALREADY_COMPLIANT` 时，stage 00 必须 PASS。
2. stage 30 返回 `PASS_CONTAINERD_CHECK`、非零、malformed、duplicate 或其他 RESULT 时，stage 00 必须 STOP 30。
3. Docker、Caddy、Node 和端口 3001 的既有负向回归继续 STOP。
4. 编排集成测试必须使用真实 stage 00 恢复边界，证明 00～30 合规后 `--check` 停在 40，而不是用永远 PASS 的 stage 00 fake 掩盖矛盾。
5. focused tests 后运行 Preflight、Containerd、Orchestrator 相关 suite、ShellCheck、`git diff --check` 与 `validate-fast.sh`；全量重型 shard 继续由 GitHub Actions 门禁承担。

## 7. 部署验收

修复提交 push 且 GitHub `validation-gate` 通过后，服务器同步到精确新 commit，再执行：

```text
./scripts/bootstrap/bootstrap-all.sh --check
```

预期结果是 stage 00～30 合规、编排器返回 `PASS_BOOTSTRAP_CHECK` 且 `NEXT_STAGE=40`。只有该只读验收通过后，才继续执行 `bootstrap-all.sh --apply`。
