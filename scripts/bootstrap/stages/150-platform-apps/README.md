# 150-platform-apps

Waits for the frontend/backend Deployments, TLS Certificate and application Flux
Kustomization, then performs non-sensitive HTTPS smoke requests.

## 停止原因

- `admin-conf-content-or-structure-drift`
- `apps-kustomization-not-ready`
- `backend-not-ready`
- `base64-provenance-drift`
- `certificate-not-ready`
- `curl-provenance-drift`
- `frontend-not-ready`
- `gateway-not-programmed`
- `https-smoke-failed`
- `kubectl-provenance-drift`
- `not-root`
- `openssl-provenance-drift`
- `untrusted-environment-override`
