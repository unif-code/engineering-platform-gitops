# 170-openbao-runtime

Stage 170 is the final automatic bootstrap stage. It activates the repository-owned dormant Flux
Kustomization and installs exactly one OpenBao Server and one Agent Injector. A fresh install must
finish `uninitialized=true` and `sealed=true`; Stage 170 never initializes or unseals OpenBao.

`--check` is read-only. When the `openbao` Namespace is absent, Kubernetes cannot server-validate
objects in that Namespace, so the stage validates the Namespace and existing-scope bootstrap objects
separately and reports the namespace-dependent part as deferred. An interrupted install may resume
only from one of two exact inventory fingerprints: the reviewed bootstrap checkpoint, or that same
checkpoint plus the chart-retained `10Gi` data and `5Gi` audit PVCs. The retained-PVC checkpoint must
also prove both claims are `Bound`, use `stateful-rwo-lowlatency`, and have the exact requested sizes.
Both resume checkpoints require a safe Secret inventory, no Service or external exposure, no
Snapshot/Backup resources, and full server validation. Any one-object deviation remains an unknown
partial inventory. After waiting for the approved Flux source and immediately before its first write,
`--apply` must observe the same checkpoint and repeat its safety gate. It then replays only the exact
reviewed Namespace, bootstrap bundle, and standalone Flux Kustomization.

A third recovery checkpoint is limited to a fully present runtime that is still uninitialized and
sealed, has exact workloads, image digests, PVCs, private Services, certificates, and Secret inventory,
and whose HelmRelease reports only the reviewed `openbao-discovery-role` anti-escalation failure while
the Helm service account either has none of the standard pods resource verbs or already has exactly
`get/list/watch/update/patch` while `create/delete/deletecollection` remain forbidden. The second form
recovers only the failed revision that raced with the authorization cache; it does not admit any other
Helm failure or permission set. This checkpoint is rechecked after the Flux source wait and may only
replay the same three reviewed manifests. After the bootstrap RBAC replay, Stage 170 waits up to 60
seconds for that exact allowed-and-denied permission set before activating the runtime Kustomization.
Every other present-but-drifted runtime remains fail-closed.

Stage 180 is intentionally not part of `bootstrap-all.sh`; initialization needs the operator to be
present for hidden input and the encrypted recovery ceremony.

The following remain deferred and absent after Stage 170:

- MinIO
- Snapshot
- Backup
- Restore
- application Secret migration

The stage never deletes PVCs. Partial or unknown OpenBao inventory, external exposure, source
revision drift, image drift, insufficient capacity, business health regression, or application
Secret fingerprint drift stops fail-closed.

## 停止原因

- `applications-not-ready`
- `apply-requires-empty-or-approved-checkpoint`
- `bootstrap-apply-failed`
- `client-dry-run-failed`
- `flux-source-revision-drift`
- `full-server-validation-failed`
- `insufficient-openbao-capacity`
- `invalid-openbao-inventory-state`
- `invalid-openbao-mode`
- `inventory-query-failed`
- `namespace-apply-failed`
- `openbao-asset-drift`
- `openbao-apply-checkpoint-raced`
- `openbao-rbac-delegation-not-effective`
- `openbao-runtime-drift`
- `openbao-runtime-not-ready`
- `openbao-runtime-readback-failed`
- `partial-or-unknown-openbao-inventory`
- `platform-secret-drift`
- `platform-secret-fingerprint-failed`
- `runtime-activation-failed`
- `safe-server-validation-failed`
- `unexpected-initialization-state`
- `unsafe-openbao-resume-checkpoint`
- `untrusted-environment-override`
