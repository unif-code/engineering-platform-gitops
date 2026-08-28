# DEV OpenBao Runtime-Only Activation Implementation Plan

> **Status:** READY. engineering-platform-docs PR #3 was merged as
> `0039d697237eb3f3a4a6238f47d4b971974a031e` after the user explicitly selected the local
> `baseline:check` and `git diff --check` gate because the private repository's GitHub Actions runner
> could not start due to Billing. GitOps remains subject to its public PR and post-merge CI gates.

**Goal:** Deploy and accept a single-node DEV OpenBao 2.6.1 runtime with TLS, Raft, dual audit,
Kubernetes Auth and Agent Injector while keeping MinIO, every backup/restore path, and application
Secret migration explicitly inactive.

**Architecture:** A dormant repository-owned Flux Kustomization is installed only by approved Stage
170, so publishing `validated` cannot silently deploy OpenBao. Stage 170 installs runtime and stops at
uninitialized/sealed. A separate interactive Stage 180 plus a Windows recovery wizard performs
PGP-encrypted Shamir 5/3 initialization, unseal, Auth/Policy/Audit setup and final evidence without
placing plaintext recovery material in Git, command arguments, logs, or evidence.

**Tech stack:** Flux v2.9.3, Kustomize, Helm 3.21.0, OpenBao Helm Chart 0.28.6, OpenBao 2.6.1,
cert-manager, Bash, Python 3 `unittest`/PyYAML, GnuPG/Gpg4win.

**Design:** `docs/superpowers/specs/2026-08-28-openbao-runtime-only-activation-design.md`

---

## Task 1: Close the canonical governance gate

**Files:**

- Verify: `engineering-platform-docs/architecture/deviations.md`
- Verify: `engineering-platform-docs/architecture/baseline-manifest.json`

1. Confirm docs PR #3 head is `a2de7c12b7f119baf4e9af75d8ea87aefb60e368`.
2. Run `npm run baseline:check` and `git diff --check` locally; record that the private-repo Actions
   job did not start because of Billing rather than a test assertion.
3. Rebase-merge PR #3 into docs `main` as explicitly authorized by the user.
4. Record merged SHA `0039d697237eb3f3a4a6238f47d4b971974a031e` and baseline
   `2026-08-28.2`.
5. Sync local docs `main`, delete `codex/openbao-backup-deviation` locally/remotely, and remove its
   worktree only after the merged tree is verified equivalent and clean.

Commands:

```bash
npm run baseline:check
git diff --check
gh pr merge 3 --repo unif-code/engineering-platform-docs --rebase --delete-branch
```

Expected: DEV-005 exists on docs `main`, baseline `2026-08-28.2` is locally consistent, and the
GitHub Billing exception is recorded without being misreported as a passing CI run.

## Task 2: Lock the OpenBao supply chain

**Files:**

- Create: `pcs/candidate-3.md`
- Modify: `vendor/charts/README.md`
- Create: `vendor/charts/openbao/**`
- Create: `infrastructure/openbao/values.yaml`

1. Add failing contract tests to `scripts/test_validate.py` for Chart 0.28.6, app 2.6.1, official
   source, package SHA-256, registry digest, exact vendored tree and immutable Server/Agent/Injector
   images.
2. Run the new test class and confirm RED because candidate-3 and vendored chart are absent.
3. Download Helm 3.21.0 and verify the already-approved archive SHA-256.
4. Pull `oci://ghcr.io/openbao/charts/openbao:0.28.6`, record the registry digest, hash the package,
   reject unsafe archive entries, and vendor the exact chart contents.
5. Resolve linux/amd64 image manifest digests from official registries for:
   `quay.io/openbao/openbao:2.6.1`, the Chart-selected injector controller image, and every Agent
   image the rendered templates can launch.
6. Record provenance and the final immutable values in candidate-3 and `vendor/charts/README.md`.
7. Run the focused tests and confirm GREEN.

Commands:

```bash
python3 -B -m unittest test_validate.OpenBaoGitOpsContractTest.test_supply_chain_is_immutable -v
helm pull oci://ghcr.io/openbao/charts/openbao --version 0.28.6
sha256sum openbao-0.28.6.tgz
helm show chart openbao-0.28.6.tgz
```

Do not guess or copy a multi-arch index where the runtime contract requires a linux/amd64 manifest.

## Task 3: Specify the dormant GitOps graph with failing tests

**Files:**

- Modify: `scripts/test_validate.py`
- Modify: `scripts/validation_catalog.py`
- Modify: `scripts/validate.py`

Add `OpenBaoGitOpsContractTest` cases that require:

- `openbao` Namespace with restricted PSS and prune disabled;
- exactly one Server and one Injector, `NON_HA`, Raft `10Gi`, Audit `5Gi`;
- ClusterIP-only TLS and no Ingress/Gateway/HTTPRoute/NodePort/LoadBalancer;
- Namespace ResourceQuota, pod resources, secure contexts and retained PVC contracts;
- default-deny plus only DNS, Kubernetes API, Injector `8200`, Raft `8201`, and controlled probe
  network paths;
- least-privilege Kustomize and Helm impersonation ServiceAccounts;
- OpenBao Kubernetes TokenReview permission and a dedicated probe ServiceAccount with projected
  `audience=openbao` token;
- no Secret values, auto-unseal, dev mode, MinIO, Snapshot, Backup, Restore or application Secret
  migration;
- dormant activation manifests are absent from `clusters/dev/kustomization.yaml`;
- Helm chart values and render are byte/canonical digest locked.

Run the class and confirm RED for missing desired state before implementation.

## Task 4: Implement the OpenBao desired state

**Files:**

- Create: `infrastructure/openbao/kustomization.yaml`
- Create: `infrastructure/openbao/resourcequota.yaml`
- Create: `infrastructure/openbao/certificate.yaml`
- Create: `infrastructure/openbao/rbac.yaml`
- Create: `infrastructure/openbao/network-policy.yaml`
- Create: `infrastructure/openbao/helmrelease.yaml`
- Create: `infrastructure/openbao/values.yaml`
- Create: `infrastructure/openbao/probe.yaml`
- Create: `clusters/dev/openbao-bootstrap.yaml`
- Create: `clusters/dev/openbao-runtime.yaml`
- Modify: `vendor/charts/README.md`

Implementation constraints:

- the OpenBao Flux Kustomization and bootstrap RBAC are committed but not referenced by the active
  root;
- HelmRelease and its values ConfigMap live in `flux-system` so the existing
  `--no-cross-namespace-refs=true` controller policy is preserved; the release targets `openbao`,
  reads the vendored Chart from the already approved GitRepository artifact and uses only
  digest-pinned images; no runtime chart network dependency;
- TLS config uses the cert-manager Secret only as transport material; it contains no OpenBao
  recovery material;
- Raft and audit data use separate PVCs, and no rollback object can delete them;
- file-PVC and stdout audit devices are declared in server HCL with `log_raw=false` and accessor
  HMAC, become active after initialization without root-token API creation, and preserve OpenBao's
  documented audit availability semantics;
- rendered resources remain compatible with Kubernetes 1.36 restricted PSS.

Generate and commit a deterministic render/digest contract. Then run:

```bash
helm lint vendor/charts/openbao -f infrastructure/openbao/values.yaml
helm template openbao vendor/charts/openbao --namespace openbao \
  -f infrastructure/openbao/values.yaml > /tmp/openbao-rendered.yaml
kubectl kustomize infrastructure/openbao >/tmp/openbao-kustomized.yaml
python3 -B -m unittest test_validate.OpenBaoGitOpsContractTest -v
```

## Task 5: Specify Stage 170 orchestration with failing tests

**Files:**

- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/validation_catalog.py`
- Modify: `scripts/bootstrap/bootstrap-all.sh`

Add `OpenBaoRuntimeStageTest` RED cases for:

- Stage 170 is the final mutating orchestrator stage and Stage 180 is not auto-run;
- `--check` never applies, creates namespaces, writes evidence or changes files;
- exact approved render SHA and resource inventory are verified before Kubernetes queries;
- preflight captures business workload health and existing platform Secret UID/resourceVersion/hash;
- empty, compliant and partial/unknown OpenBao inventories are distinguished;
- capacity, external exposure, backup resources, image digest, ownership and Flux source revision
  drift fail closed;
- server dry-run/diff is limited to the bootstrap objects that live in existing `flux-system`; the
  downstream namespace dependency is not disguised as a complete server-side validation;
- `--apply` uses exact repository manifests, waits for Kustomization/HelmRelease/TLS/PVC/Server and
  Injector, and accepts uninitialized/sealed as its only fresh-install terminal state;
- rerun is idempotent and never deletes PVCs or initializes OpenBao.

Run the focused class and confirm RED.

## Task 6: Implement Stage 170

**Files:**

- Create: `scripts/bootstrap/lib/openbao-runtime.sh`
- Create: `scripts/bootstrap/stages/170-openbao-runtime/run.sh`
- Create: `scripts/bootstrap/stages/170-openbao-runtime/README.md`
- Modify: `scripts/bootstrap/bootstrap-all.sh`
- Modify: `scripts/test_bootstrap.py`

Use existing `admin-conf.sh`, `kubectl.sh`, `exec-safety.sh` and evidence helpers. Stage 170 must:

1. verify root/provenance/clean approved checkout;
2. verify docs baseline, PCS, chart/render/image digests and dormant-root invariant;
3. take only metadata/digests for existing application Secret state;
4. calculate node/PVC capacity and enforce DEV-002;
5. run client validation and server dry-run/diff on bootstrap resources;
6. in apply mode, install exact bootstrap RBAC and the standalone Flux Kustomization;
7. wait for runtime resources and read back actual image IDs;
8. stop successfully at `initialized=false`, `sealed=true`;
9. return `PASS_OPENBAO_RUNTIME_CHECK`, `PASS_OPENBAO_RUNTIME_INSTALLED` or
   `ALREADY_COMPLIANT` through the normal structured-output contract.

Run Stage 170 tests plus orchestrator focused tests until GREEN.

## Task 7: Specify and implement the human recovery wizard

**Files:**

- Create: `scripts/openbao/recovery-ceremony-wizard.sh`
- Create: `scripts/openbao/README.md`
- Modify: `scripts/test_bootstrap.py`

Copy the wizard skill `template.sh` library unchanged, then author exactly five stages:

1. verify or install Gpg4win/GnuPG on Windows;
2. create a dedicated OpenBao recovery key through GPG pinentry;
3. export only the public key for server initialization and show its fingerprint;
4. download/verify the encrypted recovery bundle and decrypt one selected item directly to the
   Windows clipboard without printing or persisting plaintext;
5. guide the user to paste three shares and then the root token only into Stage 180 hidden prompts,
   verify cloud upload of ciphertext/checksum, and clear the clipboard.

The wizard must never write a secret to `.env`, GitHub, the repository, stdout or a shell argument.
It must be restartable and must not overwrite an existing key or recovery bundle.

Verify statically:

```bash
bash -n scripts/openbao/recovery-ceremony-wizard.sh
shellcheck scripts/openbao/recovery-ceremony-wizard.sh
```

Do not run the wizard end-to-end in CI or as the agent.

## Task 8: Specify Stage 180 secret-safety and idempotency

**Files:**

- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/validation_catalog.py`

Add `OpenBaoInitializationStageTest` RED cases covering:

- allowed operations are `--check`, `--initialize`, `--configure` and `--accept`; no generic
  unattended apply;
- public key file ownership/mode/fingerprint and output directory are fail-closed;
- init uses five identical approved public-key file references for `-pgp-keys`, threshold 3, and
  `-root-token-pgp-key`; output is JSON ciphertext only;
- recovery bundle is created with noclobber, mode `0600`, checksum sidecar and sensitive-shape scan;
- initialized state can never initialize again or overwrite a bundle;
- unseal shares and root token come from `read -rs`, never arguments/environment/log/evidence;
- audit file/stdout, Kubernetes Auth, Role and Policy are idempotent and exact;
- positive/negative auth probes revoke temporary tokens and delete owned probe objects;
- acceptance compares pre/post application Secret metadata/content digests and business health;
- evidence contains no secret-like value and explicitly records all deferred capabilities.

Run the focused class and confirm RED.

## Task 9: Implement Stage 180 and final evidence

**Files:**

- Create: `scripts/bootstrap/lib/openbao-initialize.sh`
- Create: `scripts/bootstrap/stages/180-openbao-initialize/run.sh`
- Create: `scripts/bootstrap/stages/180-openbao-initialize/README.md`
- Modify: `scripts/test_bootstrap.py`

Stage 180 remains outside `bootstrap-all.sh`. Implement four explicit operations:

- `--check`: read-only readiness/state/public-key/evidence preflight;
- `--initialize`: initialize once and save only PGP ciphertext plus metadata/checksum;
- `--configure`: hidden-input unseal/root ceremony, dual audit, Kubernetes Auth, probe Policy/Role;
- `--accept`: secret-free runtime probes and final evidence generation.

All OpenBao API calls carrying tokens must feed headers/body through protected stdin or mode-0600
temporary descriptors; process arguments and environment must never contain secrets. Cleanup traps
must revoke temporary tokens, terminate port-forward processes and delete only owned ephemeral probes.

Final evidence path:

```text
/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt
/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt.sha256
```

Run Stage 180 focused tests until GREEN.

## Task 10: Update validators, runbooks and acceptance language

**Files:**

- Modify: `scripts/validate.py`
- Modify: `scripts/test_validate.py`
- Modify: `scripts/validation_catalog.py`
- Modify: `runbook/01-bootstrap.md`
- Modify: `runbook/02-secrets.md`
- Modify: `runbook/09-acceptance.md`
- Modify: `runbook/README.md`
- Create: `runbook/11-openbao-runtime.md`
- Modify: `pcs/candidate-3.md`

Document the exact check/apply/readback commands, manual ceremony, evidence contract, STOP reasons,
PVC-preserving rollback, cloud upload boundary, and the distinction between runtime acceptance and
backup/release acceptance. Never include example secret values that resemble real tokens or shares.

Run:

```bash
python3 -B scripts/run_validation.py --validate-catalog
python3 -B -m unittest test_validate.OpenBaoGitOpsContractTest -v
python3 -B -m unittest test_bootstrap.OpenBaoRuntimeStageTest -v
python3 -B -m unittest test_bootstrap.OpenBaoInitializationStageTest -v
git diff --check
```

## Task 11: Full verification and review

1. Run the affected focused tests in a Linux LF/ext4 checkout.
2. Run `./scripts/validate-fast.sh` and `./scripts/validate-static.sh` with shellcheck 0.9.0.
3. Run the full validation profile and deterministic render checks.
4. Search the complete diff for secrets, floating tags, public exposure, backup activation, PVC
   deletion, broad RBAC, automatic Stage 180 execution and root-sync OpenBao references.
5. Review the implementation against both the design and repository standards; fix findings before
   PR.
6. Commit in small Conventional Commit units and keep history linear.

## Task 12: GitOps PR, main gate and deployment checkpoint

1. Push the GitOps branch and create a Conventional Commit PR.
2. Wait for every PR job, including `validation-gate`.
3. Rebase-merge only after explicit merge authorization already in scope for this approved plan.
4. Wait for the separate `main` push run and `publish-validated`.
5. Verify `origin/main == origin/validated == merged SHA`.
6. Clean merged branches/worktrees only after equivalence and cleanliness checks.
7. Reconnect only to the latest external Chrome tab titled “Web终端 - 统一企业堡垒机”.
8. Show the complete read-only command before running:

```bash
cd /opt/uni-code/engineering-platform-gitops && \
./scripts/bootstrap/run-approved.sh <MERGED_SHA> --check; \
rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

9. After read-only output is reviewed, show the exact Stage 170 mutation command, affected resource
   inventory and expected readback, then wait for explicit approval. Do the same separately for each
   Stage 180 operation.
