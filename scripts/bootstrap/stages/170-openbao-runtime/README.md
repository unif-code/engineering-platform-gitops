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
