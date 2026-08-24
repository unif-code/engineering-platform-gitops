# Flux Phase A Four-Controller Activation Implementation Plan

> **执行状态：`IN_PROGRESS`。** 本计划只激活 Flux Controller 基础层，不创建 Git Credential、`GitRepository`、Flux `Kustomization`、`HelmRelease`，也不激活 infrastructure、apps、MinIO、OpenBao 或任何应用工作负载。

**Goal:** 在 DEV 安装并验证 Flux v2.9.3 的 `source-controller`、`kustomize-controller`、`helm-controller`、`notification-controller`，同时保持 Git sync 与所有下游 Desired State fail-closed。

**Architecture:** Phase A 只让 `clusters/dev/flux-system` 渲染四个 Controller 及其 CRD、RBAC、Service、NetworkPolicy。`clusters/dev/kustomization.yaml` 继续只引用 `flux-system`；`clusters/dev/flux-system/kustomization.yaml` 只引用 `gotk-components.yaml`；`gotk-sync.yaml` 保持纯注释和 `ACTIVE: false`。Controller 镜像使用 Kustomize `images.digest` 固定 linux/amd64 manifest，运行前后均验证不存在任何 sync CR 或下游 Namespace。

**Tech Stack:** Flux CLI v2.9.3、Kustomize、Kubernetes v1.36.3、Python 3、unittest、PyYAML、GitHub Actions。

**Architecture Sources:** `engineering-platform-docs` main `d6d846a612c974991f4d0ffc0685d06adf2ddfe7` 的 `architecture/09-infrastructure-operations.md` 与 `architecture/appendix-parameters.md`。

## Fixed supply-chain inputs

- Flux CLI v2.9.3 darwin/amd64 archive SHA-256：`cfe276124801f2057b7960b5ac2fe5dc019cdf245d1e791ed947b9f4e97e06c2`。
- Flux CLI v2.9.3 linux/amd64 archive SHA-256：`eae4e8608c0ade2bf4e8dec1669dbb6b0c28b5822b252d97feccfb4fb1181fd2`。
- 生成命令固定为：

```bash
flux install \
  --namespace=flux-system \
  --components=source-controller,kustomize-controller,helm-controller,notification-controller \
  --network-policy=true \
  --watch-all-namespaces=true \
  --export
```

- `source-controller:v1.9.3` linux/amd64 manifest：`sha256:c6c82b3182f48b833252c71aefa0741957ca18296612bc6d2b9b5fb276f926e4`。
- `kustomize-controller:v1.9.4` linux/amd64 manifest：`sha256:3e57aecb74419be93d09ba062cfc882bea405193c474009e0da1826de71a4ebd`。
- `helm-controller:v1.6.3` linux/amd64 manifest：`sha256:22c0a585d0d9b1f792b9d5638144b7810e273d28e310da37740f01226bd044a2`。
- `notification-controller:v1.9.2` linux/amd64 manifest：`sha256:cb17eefffbc442412ba6f63336defd04c0fc387d5082d951998d1ff163a9180d`。

## Phase A invariants

1. 渲染结果恰好包含四个 Controller Deployment，不含 image automation 或 source-watcher。
2. `gotk-sync.yaml` 没有 YAML document，Phase A 渲染不含 `GitRepository`、Flux `Kustomization` 或 `HelmRelease`。
3. `clusters/dev` 不得引用 infrastructure/apps；渲染中不得出现 `platform`、`minio`、`cert-manager`、`monitoring`、`cnpg-system` 或 `openbao` Namespace。
4. `flux-system` Namespace 固定 Pod Security `restricted`，版本 `v1.36`。
5. 四个 Controller 均固定 non-root、drop ALL、禁止 privilege escalation、只读根文件系统、RuntimeDefault seccomp。
6. 多租户参数固定：全部 Controller 使用默认 ServiceAccount；kustomize/helm/notification 禁止跨 Namespace 引用；kustomize 禁止 remote bases，并固定 decryption/kubeconfig 默认 ServiceAccount；helm 固定 kubeconfig 默认 ServiceAccount。
7. 资源请求与架构附录一致，Limit 不低于 4×CPU Request 与 2×Memory Request：

| Controller | Request | Limit |
| --- | --- | --- |
| source | `100m / 256Mi` | `400m / 512Mi` |
| kustomize | `250m / 512Mi` | `1000m / 1Gi` |
| helm | `100m / 256Mi` | `400m / 512Mi` |
| notification | `50m / 128Mi` | `200m / 256Mi` |

8. 生成来源、CLI archive SHA-256、Controller 版本、OCI index 与 linux/amd64 manifest 均有唯一固定值；清单不得退回 tag 或浮动引用。

## Task 1: Add fail-closed Phase A contract tests

**Files:**

- Modify: `scripts/test_validate.py`
- Modify: `scripts/validation_catalog.py`

Add `FluxPhaseAContractTest` covering the eight invariants above, exact four Deployment identities, exact image digests, exact security args, PSS labels, resources, inactive sync and root isolation. Add mutation tests for a fifth Controller, a tag-only image, reintroduced sync resource, missing security arg and an infrastructure Namespace.

Run the focused selector before implementation and preserve the RED output:

```bash
cd scripts
python3 -B -m unittest test_validate.FluxPhaseAContractTest -v
```

## Task 2: Generate and lock the four-controller bundle

**Files:**

- Replace: `clusters/dev/flux-system/gotk-components.yaml`
- Modify: `clusters/dev/flux-system/kustomization.yaml`
- Keep inactive: `clusters/dev/flux-system/gotk-sync.yaml`
- Create: `clusters/dev/flux-system/README.md`

Download only the fixed v2.9.3 CLI archive, verify its SHA-256 before extraction, and export the four-component bundle. Do not use the upstream seven-controller `install.yaml`. Remove `gotk-sync.yaml` from active Kustomize resources. Use Kustomize image transforms to replace the generated tags with the four fixed linux/amd64 digests. Add PSS labels, security args, rollout strategy and current resource patches. Record generation provenance and all index/manifest digests in the README.

## Task 3: Teach validation the Phase A state

**Files:**

- Modify: `scripts/validate.py`
- Modify: `scripts/test_validate.py`

Remove only `gotk-components.yaml` from the inactive entrypoints list; keep `gotk-sync.yaml` inactive. Add a dedicated Phase A validator that parses both source and rendered resources. Scope the placeholder exception narrowly to generated Flux CRD schema descriptions; do not weaken placeholder checks for other manifests. Update single-user resource contracts to the new architecture values.

## Task 4: Record the pre-deployment candidate and runbook contract

**Files:**

- Modify: `pcs/candidate-2.md`
- Modify: `runbook/01-bootstrap.md`

Record the fixed Flux CLI/controller supply-chain facts while keeping Flux activation and V0.1 status `BLOCKED` until runtime evidence exists. Add exact Phase A preflight, dry-run, apply, evidence and rollback commands. Do not claim execution and do not alter the current Runtime snapshot.

## Task 5: Verify and commit Desired State

Run:

```bash
python3 -B scripts/run_validation.py --validate-catalog
python3 -B scripts/validate.py
./scripts/validate-static.sh
kubectl kustomize clusters/dev/flux-system
kubectl kustomize clusters/dev
git diff --check
```

Request independent code review. Merge and push only after focused and repository validation pass. GitHub `validation-gate` must succeed and `origin/validated` must equal the Phase A commit before any server mutation.

## Task 6: Deploy Phase A and capture evidence

This task remains `BLOCKED` while GitHub does not allocate a Runner or `origin/validated` has not advanced. Once unblocked:

1. Run `run-approved.sh --check` to synchronize and re-verify the server checkout.
2. Verify the fixed linux/amd64 Flux CLI archive and run `flux check --pre`.
3. Render and inspect exact object identities; run client and server-side dry-run.
4. Apply only `clusters/dev/flux-system` with field manager `engineering-platform-flux-phase-a`; never use `--force-conflicts` or `--prune`.
5. Wait for all four rollouts and prove GitRepository/Kustomization/HelmRelease plus downstream Namespace inventories are empty.
6. Save `/root/dev-infra-evidence/15-flux-phase-a-<UTC>.txt` and its SHA-256.
7. Commit the new Runtime facts across PCS, runbooks and validator fixtures; V0.1 remains `BLOCKED` because sync, infrastructure and applications are still inactive.

Rollback before Phase B may delete only the exact Phase A Kustomize bundle after proving no sync CR or user Secret exists. After deploy key or sync creation, this rollback is invalid and requires a separate reviewed procedure.
