# 90-verify

只读整机验收：包、运行时、控制面、CNI、网关与证书的逐项核对。Cilium Helm
合同只接受使用当前 host-network + operator checksum rollout values 的精确 rev1/rev2/rev3；
其中 rev2 可由旧 rev1 一次升级得到，rev3 仅可由已知 pre-rollout rev2 再升级得到。
脚本逐版读取 Helm values 证明该血统，并用钉死的本地 Chart/values 离线渲染 Operator
checksum 后精确比对。其他 revision、Secret 历史、values 或 Operator 代际组合全部
fail-closed。

| 项 | 值 |
| --- | --- |
| PHASE | `verify` |
| 成功结果 | `PASS_BOOTSTRAP_VERIFIED` |
| 证据 | `/root/dev-infra-evidence/14-verify-*.txt` |
| 文件 | `run.sh` 流程与终止；`gates.sh` 判定族（只返回 0/1，不打印、不退出） |

## 停止原因

一律 fail-closed，退出码固定：10 前置条件 / 20 供应链 / 30 未知或漂移 /
40 apply 失败 / 50 verify 失败，不降级为告警。

下列 30 个字面量 REASON 由 `StageReadmeTest` 与 `run.sh` 逐项比对，
文档漂移会判红。模板化的 REASON（如 `missing-command-${cmd}`）不在此列。

- `admin-conf-content-or-structure-drift`
- `api-endpoint-or-health-drift`
- `cilium-operator-render-drift`
- `cilium-workload-unhealthy`
- `client-provenance-or-package-drift`
- `cni-payload-drift`
- `cri-runtime-unhealthy`
- `evidence-open-failed`
- `executable-version-drift`
- `gateway-bundle-drift`
- `helm-binary-provenance-drift`
- `helm-binary-raced`
- `helm-kubeconfig-residue`
- `helm-release-allowlist-drift`
- `host-pins-invalid`
- `kube-proxy-object-present-or-unreadable`
- `kubelet-serving-csr-drift`
- `kubelet-swap-config-drift`
- `missing-command-python3`
- `missing-command-sha256`
- `missing-command-tar`
- `node-readiness-or-address-drift`
- `not-root`
- `openssl-binary-metadata-drift`
- `package-version-selection-or-hold-drift`
- `read-only-stage-does-not-accept-apply`
- `runtime-provenance-or-state-drift`
- `staged-input-drift`
- `staged-input-raced`
- `swap-contract-drift`
