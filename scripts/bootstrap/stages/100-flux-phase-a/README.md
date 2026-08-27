# 100-flux-phase-a

Flux Phase A 的一键部署与验收，只允许安装 source、kustomize、helm、notification
四个 Controller。禁止 Secret、sync CR、第五个 Controller、下游 Namespace、OpenBao、
备份与业务应用。

| 项 | 值 |
| --- | --- |
| PHASE | `flux-phase-a` |
| check 结果 | `PASS_FLUX_PHASE_A_CHECK` 或 `ALREADY_COMPLIANT` |
| apply 结果 | `PASS_FLUX_PHASE_A_INSTALLED` |
| 证据 | `/root/dev-infra-evidence/15-flux-phase-a-*.txt` 及同名 `.sha256` |
| 网络探针 | 两个瞬态 Pod；只按本轮创建回执的名称和 UID 精确删除 |

`--check` 只读识别 `ABSENT`、精确 `NAMESPACE_ONLY`、完整 `COMPLIANT`，或 inventory
边界仍精确但批准清单存在 SSA diff 的 `UPGRADE_REQUIRED` 状态。Phase A 基线完整后，允许
Stage `110`～`160` 已批准 sync CR 与下游 Namespace 清单的任意无重复子集作为合法续跑
检查点；sync CR 按 `resource/namespace/name` 身份核对，错误 Namespace、未批准名称或
`kubectl diff` 执行错误都 fail-closed，并由后续所属 stage 负责精确收敛。`--apply` 固定
Flux CLI 版本与摘要；CLI 归档成员只流式写入 root 新建的私有文件，再显式规范化为
`root:root 0755`，不继承归档 owner。首次安装先单独处理 Namespace 依赖，升级不重建
Namespace；两条路径都只对同一份已验摘要的私有 `rendered.yaml` 依次执行完整 bundle 的
server-side dry-run、diff 和 apply，最后完成 rollout、`flux check`、网络边界验证、只读
postcheck，并重新读取最终 sync CR/Namespace inventory 后落盘证据。

## 停止原因

一律 fail-closed，退出码固定：10 前置条件 / 20 供应链 / 30 未知或漂移 /
40 apply 失败 / 50 verify 失败，不降级为告警。

下列 65 个字面量 REASON 由 `StageReadmeTest` 与 `run.sh` 逐项比对，
文档漂移会判红。模板化的 REASON（如 `missing-command-${cmd}`）不在此列。

- `admin-conf-content-or-structure-drift`
- `admin-conf-raced-after-flux-precheck`
- `admin-conf-raced-before-flux-precheck`
- `bundle-diff-state-unexpected`
- `bundle-server-apply-failed`
- `bundle-server-dry-run-failed`
- `client-dry-run-failed`
- `curl-provenance-drift`
- `downstream-namespace-query-failed`
- `evidence-open-failed`
- `flux-check-failed`
- `flux-cluster-resource-query-failed`
- `flux-cli-archive-digest-drift`
- `flux-cli-binary-mode-failed`
- `flux-cli-binary-unsafe`
- `flux-cli-download-failed`
- `flux-cli-extraction-failed`
- `flux-cli-version-drift`
- `flux-controller-not-ready`
- `flux-controller-rollout-failed`
- `flux-crd-query-failed`
- `flux-deployment-query-failed`
- `flux-desired-state-query-failed`
- `flux-external-probe-create-failed`
- `flux-external-probe-identity-unsafe`
- `flux-external-probe-not-ready`
- `flux-internal-probe-create-failed`
- `flux-internal-probe-identity-unsafe`
- `flux-internal-probe-not-ready`
- `flux-kubeconfig-create-failed`
- `flux-kubeconfig-mode-failed`
- `flux-kubeconfig-unsafe`
- `flux-namespace-drift`
- `flux-namespace-query-failed`
- `flux-network-boundary-failed`
- `flux-network-pod-ip-query-failed`
- `flux-network-pod-ip-unsafe`
- `flux-network-positive-probe-failed`
- `flux-network-probe-cleanup-failed`
- `flux-phase-a-state-unknown`
- `flux-postcheck-failed`
- `flux-postcheck-output-drift`
- `flux-precheck-failed`
- `flux-resource-query-failed`
- `flux-secret-query-failed`
- `flux-sync-query-failed`
- `flux-work-directory-cleanup-failed`
- `flux-work-directory-create-failed`
- `flux-work-directory-unsafe`
- `flux-work-root-unsafe`
- `kubectl-provenance-drift`
- `missing-command-python3`
- `missing-command-sha256`
- `namespace-active-wait-failed`
- `namespace-apply-failed`
- `namespace-extraction-failed`
- `namespace-server-dry-run-failed`
- `not-root`
- `render-failed`
- `render-raced`
- `rendered-bundle-digest-drift`
- `rendered-bundle-raced`
- `tar-provenance-drift`
- `test-flux-archive-sha256-unsafe`
- `test-rendered-sha256-unsafe`
