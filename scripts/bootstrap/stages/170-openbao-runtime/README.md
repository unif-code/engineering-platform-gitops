# 170-openbao-runtime

Stage 170 is the final automatic bootstrap stage. It activates the repository-owned dormant Flux
Kustomization and installs exactly one OpenBao Server and one Agent Injector. A fresh install must
finish `uninitialized=true` and `sealed=true`; Stage 170 never initializes or unseals OpenBao.

`--check` is read-only. When the `openbao` Namespace is absent, Kubernetes cannot server-validate
objects in that Namespace, so the stage validates the Namespace and existing-scope bootstrap objects
separately and reports the namespace-dependent part as deferred. `--apply` first persists the exact
reviewed Namespace, then server-validates and applies the complete bootstrap bundle before activating
the standalone Flux Kustomization.

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
- `apply-requires-empty-inventory`
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
- `openbao-runtime-drift`
- `openbao-runtime-not-ready`
- `openbao-runtime-readback-failed`
- `partial-or-unknown-openbao-inventory`
- `platform-secret-drift`
- `platform-secret-fingerprint-failed`
- `runtime-activation-failed`
- `safe-server-validation-failed`
- `unexpected-initialization-state`
- `untrusted-environment-override`
