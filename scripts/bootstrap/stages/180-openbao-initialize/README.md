# 180-openbao-initialize

Stage 180 is a manual, interactive ceremony and is deliberately absent from
`bootstrap-all.sh`. It accepts only `--check`, `--initialize`, `--configure`, and
`--accept`; there is no generic `--apply` operation.

- `--check` is read-only and reports the next explicit operation.
- `--initialize` performs Shamir 5/3 initialization once and writes only PGP ciphertext,
  public metadata, a protected archive, and its checksum.
- `--configure` reads three unseal shares and the initial root token through hidden
  terminal prompts. The root token is revoked after exact configuration and readback.
- `--accept` uses a short-lived Kubernetes-auth token, runs positive and negative policy
  probes, verifies both audit streams, and writes evidence `17-openbao-runtime`.

The recovery bundle must be uploaded by the operator to controlled cloud storage. The
private OpenPGP key and passphrase remain on Windows and never reach this repository,
the server, Kubernetes, logs, or evidence.

MinIO, Snapshot, Backup, Restore, and application Secret migration remain deferred.
The stage never deletes Raft or Audit PVCs and never creates an audit device through the
API.

## 停止原因

- `untrusted-environment-override`
- `invalid-openbao-operation`
- `openbao-asset-drift`
- `openbao-runtime-not-ready`
- `public-key-missing-or-unsafe`
- `recovery-root-missing-or-unsafe`
- `recovery-bundle-state-unsafe`
- `unexpected-openbao-state`
- `git-commit-unreadable`
- `missing-command-tar`
- `platform-secret-fingerprint-failed`
- `platform-secret-drift`
- `openbao-initialization-failed`
- `recovery-bundle-validation-failed`
- `recovery-bundle-finalization-failed`
- `openbao-unseal-failed`
- `openbao-configuration-failed`
- `openbao-auth-probe-failed`
- `openbao-audit-readback-failed`
- `applications-not-ready`
- `https-smoke-failed`
- `evidence-open-failed`
- `evidence-scan-failed`
