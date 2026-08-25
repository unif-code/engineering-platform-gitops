# 130-platform-database

Creates missing Secrets without printing values, never overwrites an existing Secret,
and waits for the single-instance no-backup CNPG Cluster. Private GHCR inputs must exist
as root-owned mode-600 files under `/root/.config/engineering-platform/`.

## 停止原因

- `admin-conf-content-or-structure-drift`
- `base64-provenance-drift`
- `curl-provenance-drift`
- `database-kustomization-not-ready`
- `database-not-ready`
- `database-secret-content-invalid`
- `kubectl-provenance-drift`
- `material-generation-failed`
- `material-secret-create-failed`
- `not-root`
- `openssl-provenance-drift`
- `registry-credential-invalid`
- `registry-credential-missing-or-unsafe`
- `registry-secret-create-failed`
- `runtime-config-create-failed`
- `secret-contract-drift`
- `secret-create-failed`
- `secret-generation-failed`
- `secret-query-failed`
- `secret-work-cleanup-failed`
- `secret-work-directory-create-failed`
- `secret-work-directory-mode-failed`
- `untrusted-environment-override`
