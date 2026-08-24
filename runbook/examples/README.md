# 瞬态验证资源

本目录中的 YAML 只供已批准的人工验证/恢复窗口使用：

- 不属于 Flux Desired State，不得加入 `apps/`、`infrastructure/` 或任何 Kustomization。
- 执行前核对当前 Git commit、目标 context、Namespace 和 Image digest。
- `postgres-restore.yaml` 含一个显式时间占位，必须在副本中替换并复核，禁止原文件直接 apply。
- `flux-phase-a-network-probe.yaml` 与 `flux-phase-a-external-network-probe.yaml` 各自以
  `generateName` 创建一个无 Token、digest 固定的临时 BusyBox Pod，用于 Phase A
  网络正反向探测；无论成功失败都必须由 01 runbook 按本轮 Pod UID 校验后删除。
- 证据留存后按对应 runbook 删除瞬态 Job/Cluster/Namespace。
- 所有凭据只由已存在的 Kubernetes Secret 引用，不得写入 YAML 或日志。
