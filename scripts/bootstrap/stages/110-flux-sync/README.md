# 110-flux-sync

Creates the four approved downstream Namespaces and least-privilege reconciliation RBAC,
then activates only the public `validated` Git source/root Kustomization and the exact
source-controller `github.com:443` egress rule. Bootstrap owns the controller/sync/RBAC
objects; the root Kustomization owns only the downstream infrastructure/application DAG,
does not wait for that entire DAG, and must itself become Ready before Stage 110 succeeds.
No Git credential Secret is created.

Before any write, Stage 110 accepts a missing/empty root inventory or a subset containing
only the seven approved downstream Kustomizations. Any bootstrap-owned or unknown entry
stops the stage before `prune: true` can transfer ownership unsafely. Root readiness is
accepted only after `status.observedGeneration` reaches the current generation.

## 停止原因

- `admin-conf-content-or-structure-drift`
- `base64-provenance-drift`
- `curl-provenance-drift`
- `git-source-not-ready`
- `kubectl-provenance-drift`
- `namespace-apply-failed`
- `namespace-inventory-query-failed`
- `namespace-render-failed`
- `namespace-render-mode-failed`
- `namespace-server-dry-run-failed`
- `not-root`
- `openssl-provenance-drift`
- `root-sync-not-ready`
- `root-sync-inventory-query-failed`
- `root-sync-inventory-unsafe`
- `sync-apply-failed`
- `sync-diff-failed`
- `sync-server-dry-run-failed`
- `sync-work-cleanup-failed`
- `sync-work-directory-create-failed`
- `untrusted-environment-override`
