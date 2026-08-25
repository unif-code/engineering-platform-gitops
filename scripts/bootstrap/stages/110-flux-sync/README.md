# 110-flux-sync

Creates the four approved downstream Namespaces and least-privilege reconciliation RBAC,
then activates only the public `validated` Git source/root Kustomization and the exact
source-controller `github.com:443` egress rule. No Git credential Secret is created.

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
- `sync-apply-failed`
- `sync-diff-failed`
- `sync-server-dry-run-failed`
- `sync-work-cleanup-failed`
- `sync-work-directory-create-failed`
- `untrusted-environment-override`
