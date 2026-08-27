# 140-platform-migration

Waits for the immutable backend migration generation and requires its one-shot Job to
complete. The Job validates the owner and six runtime roles before Alembic runs.

Failed generations are retained as audit evidence. A reviewed Git change must advance
both `platform.unif.internal/migration-generation` and the Job name before a retry; the
bootstrap never deletes or reruns a failed immutable generation in place.

## 停止原因

- `admin-conf-content-or-structure-drift`
- `base64-provenance-drift`
- `curl-provenance-drift`
- `kubectl-provenance-drift`
- `migration-job-failed`
- `migration-kustomization-not-ready`
- `not-root`
- `openssl-provenance-drift`
- `untrusted-environment-override`
