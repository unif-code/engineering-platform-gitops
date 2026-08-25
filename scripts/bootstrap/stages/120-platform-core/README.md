# 120-platform-core

Waits read-only for Flux foundation, cert-manager controller/config and CloudNativePG
operator Kustomizations. It does not activate OpenBao, MinIO, backups or observability.

## 停止原因

- `admin-conf-content-or-structure-drift`
- `base64-provenance-drift`
- `cert-manager-config-not-ready`
- `cert-manager-controller-not-ready`
- `cnpg-controller-not-ready`
- `curl-provenance-drift`
- `infrastructure-foundation-not-ready`
- `kubectl-provenance-drift`
- `not-root`
- `openssl-provenance-drift`
- `untrusted-environment-override`
