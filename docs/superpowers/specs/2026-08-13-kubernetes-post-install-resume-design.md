# Kubernetes 安装后恢复状态设计

## 背景与实证

Stage 40 已在 Ubuntu 24.04 主机上从 private APT cache 成功安装并 hold：

- `kubeadm/kubectl/kubelet=1.36.3-1.1`；
- `kubernetes-cni=1.9.1-1.1`；
- 四包 selection 均为 `hold ok installed`；
- package-owned CNI payload 已通过 Stage 40 的独立完整验证。

最终综合验证仍错误停止。服务器只读证据确认三个合法 Ubuntu/package shape：

1. kubelet 官方 `postinst` 只执行 `systemctl preset kubelet.service`，不会启动
   service。首次安装后的官方状态是 `enabled + inactive/dead`，`Result=success`、
   `NRestarts=0` 且 journal 为空。
2. Ubuntu usrmerge 的 `/lib` 是指向 `usr/lib` 的 root-owned symlink。systemd 将
   unit canonicalize 为 `/usr/lib/systemd/system/...`，但 dpkg database 按 package
   manifest 记录 `/lib/systemd/system/...`。
3. 宿主 `/etc/dpkg/dpkg.cfg.d/excludes` 明确排除 `/usr/share/doc/*`，只重新包含
   copyright/changelog。因此 `dpkg --verify` 对每个 Kubernetes package 返回 0，
   但输出该 package 的 `LICENSE` 与 `README.md` 两个 missing 记录。

这些结果不是 package/version/digest drift，也不是部分安装。

## 决策

### 1. kubelet runtime 三态

在 unit static provenance、package payload、hold、CNI 与所有 pre-init mutable input
均已通过时，Stage 40 将 kubelet runtime 分类为：

- `READY`：`activating/auto-restart` 或 `active/running`；
- `START_REQUIRED`：`enabled + inactive/dead`，且 systemd `Result=success`；
- `UNKNOWN`：其他任意状态，包括 `failed`、disabled、unknown substate、字段缺失、
  重复字段或 command failure。

`START_REQUIRED` 是官方 postinst 留下的可恢复中间态，不是最终合规态。

### 2. CHECK 与 APPLY

- `--check` 遇到 `START_REQUIRED` 必须保持零写并返回
  `PASS_KUBERNETES_CHECK / apply-required`。
- `--apply` 遇到 `START_REQUIRED` 执行固定绝对边界的
  `systemctl restart kubelet.service`，然后重新运行完整 package/unit/runtime Gate。
- fresh install 在 hold、CNI 与静态 provenance 验证后，同样显式 restart kubelet，
  不再假设 package postinst 会启动服务。
- restart 非零返回 `STOP_APPLY_FAILED`；restart 后未进入 `READY` 返回
  `STOP_VERIFY_FAILED`。
- 已为 `READY` 的幂等路径不得 restart。

### 3. usrmerge unit ownership

Stage 40 继续只接受两个固定 unit：

- kubelet fragment，由 `kubelet` package ownership；
- `10-kubeadm.conf` drop-in，由 `kubeadm` package ownership。

systemd 报 `/usr/lib/...` 而 dpkg 仅记录 `/lib/...` 时，fallback 只对这两个精确
路径生效，并必须证明：

- `/lib` 是 root-owned、非可写、指向 `usr/lib` 的 symlink；
- `/lib/...` 与 `/usr/lib/...` 解析到同一现存 regular file；
- dpkg-query 对 `/lib/...` 返回精确 package ownership。

不得对任意 prefix 或任意 symlink 做通用 canonicalization。

### 4. dpkg payload verification

`dpkg --verify` 的返回码仍必须为 0。每个 package 的 stdout 只允许两种 shape：

- 完全为空；或
- 恰好两条、无重复、顺序无关的：
  `missing /usr/share/doc/<package>/LICENSE` 与
  `missing /usr/share/doc/<package>/README.md`。

第二种 shape 只有在 root-owned、regular、non-symlink 的 dpkg excludes 配置中存在
精确 `path-exclude=/usr/share/doc/*` 时才允许。任何其他 missing、checksum、mode、
owner、binary、unit 或 CNI drift 都必须失败。runtime-critical payload 仍由现有
binary metadata、dpkg ownership、CNI manifest/digest 与 unit provenance Gate 独立绑定。

## 恢复行为

当前服务器不重装 package。同步修复 commit 后：

1. orchestrator CHECK 从 00–30 跳过，Stage 40 识别 `START_REQUIRED`；
2. APPLY 在 Stage 40 只启动并复验 kubelet，写入成功 evidence；
3. Stage 40 完成后继续 Stage 50 kubeadm init；
4. 任一已安装 payload、hold、unit 或 mutable input drift 仍 fail closed。

## 测试合同

必须先取得以下 load-bearing RED：

1. official postinst shape：exact installed/held/CNI + `inactive/dead`；CHECK 零写并
   apply-required，APPLY 唯一 restart 后 PASS，再次 APPLY ALREADY_COMPLIANT。
2. systemd `/usr/lib` + dpkg `/lib` official usrmerge ownership 应通过；错误 symlink、
   不同 inode 或错误 owner 应失败。
3. exact doc exclusion + exact两条 missing 应通过；未声明 exclusion、额外 missing、
   checksum/mode drift 或非零 verify 应失败。
4. fresh install 必须显式 restart；restart failure 与 restart 后仍 inactive/failed
   必须结构化 STOP，且不得写成功 evidence。
