# DEV Business-Ready GitOps Activation Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan. Use superpowers:test-driven-development for every behavior change and superpowers:verification-before-completion before any completion claim.

**Goal:** Extend the approved DEV bootstrap from Flux Phase A to a resumable, one-command business-ready deployment of public gated Git sync, no-backup core infrastructure, PostgreSQL, migrations, frontend/backend and HTTPS routing, while keeping OpenBao, MinIO, backups, restore and observability inactive.

**Architecture:** Keep the four Flux controllers scoped to `flux-system`. Store every Flux CR in `flux-system`, reconcile downstream objects through dedicated least-privilege service accounts, and use a public `validated` branch without a Git credential Secret. Git owns all non-secret desired state. Bootstrap stages 110–160 own only ordered activation, out-of-band Secret generation, readiness gates and non-sensitive evidence. PostgreSQL is a single CNPG instance with managed roles and no Barman/ObjectStore/ScheduledBackup. Backend secrets are mounted as files, never injected through `env`/`envFrom`.

**Tech Stack:** Flux v2.9.3, Kustomize, Helm v3.21.0 offline rendering, cert-manager v1.21.1, CloudNativePG 1.30.0/chart 0.29.0, PostgreSQL 18.4, Kubernetes v1.36.3, Cilium Gateway API, Bash, Python 3, unittest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-08-25-business-ready-gitops-activation-design.md`

**Architecture Sources:** `engineering-platform-docs` commit `541b186878d1e28e1aa9308111a2962cdfefb91b`, especially `architecture/09-infrastructure-operations.md`, `architecture/appendix-parameters.md`, `architecture/deviations.md` and `architecture/baseline-manifest.json` baseline `2026-08-24.1`.

**Global Constraints:** Do not update `docs/superpowers/progress/current.md` without the exact user command `【同步进度】`. Do not commit a Secret or sensitive value. Do not deploy OpenBao, MinIO, Barman, etcd/PG backups, restore resources or observability. Do not perform a server/Kubernetes mutation until its full command has been shown and separately approved. Do not broaden the Flux controller set or watch scope.

## Task 1: Lock the business-ready repository contract with failing tests

**Files:**

- Modify: `scripts/test_validate.py`
- Modify: `scripts/validation_catalog.py`

1. Add `BusinessReadyGitOpsContractTest` with helpers that render `clusters/dev` and locate objects by `apiVersion/kind/namespace/name`.
2. Assert the active root contains exactly the approved Namespaces, least-privilege RBAC and Flux CR entrypoints; assert it does not render OpenBao, MinIO, monitoring, Barman, ObjectStore, ScheduledBackup or etcd backup resources.
3. Assert `GitRepository/flux-system` uses the public HTTPS repository, `ref.branch=validated`, has no `secretRef`, and is accompanied only by source-controller FQDN egress to `github.com:443`.
4. Assert cert-manager and CNPG use vendored charts, committed offline render output and dedicated Kustomization service accounts; assert no active `HelmRelease`, `HelmRepository` or Helm storage Secret.
5. Assert CNPG has one instance, fixed PostgreSQL digest, six managed non-superuser login roles, 20Gi storage and no plugins/ObjectStore/ScheduledBackup/archive configuration.
6. Assert migration, frontend and backend images are immutable; workloads have exact resources/security contexts, the backend uses Secret file volumes without Secret `env`/`envFrom`, and the app Kustomization depends on migration.
7. Assert Gateway routing is HTTPS-only with `/api`, `/healthz` and `/readyz` to backend and `/` to frontend; prohibit Ingress, NodePort and LoadBalancer.
8. Add mutation tests for a fifth Flux controller, `cluster-admin`, Git credentials, mutable chart/image, backup resource, Secret env injection, migration bypass, insecure workload, permissive egress and alternate northbound exposure.

Run and preserve the expected RED result:

```bash
cd scripts
python3 -B -m unittest test_validate.BusinessReadyGitOpsContractTest -v
```

## Task 2: Activate public gated sync and least-privilege reconciliation

**Files:**

- Modify: `clusters/dev/kustomization.yaml`
- Replace: `clusters/dev/flux-system/gotk-sync.yaml`
- Modify: `clusters/dev/flux-system/kustomization.yaml`
- Create: `clusters/dev/flux-system/phase-b-network-policy.yaml`
- Replace: `clusters/dev/reconcile-rbac.yaml`
- Replace: `clusters/dev/infrastructure.yaml`
- Replace: `clusters/dev/apps.yaml`

1. Create `GitRepository/flux-system` for `https://github.com/unif-code/engineering-platform-gitops.git`, branch `validated`, without `secretRef`; create root `Kustomization/flux-system` targeting a dedicated root reconciler.
2. Add a Cilium FQDN egress policy selecting only source-controller and allowing only `github.com:443`; retain Phase A deny/DNS/API/internal policies.
3. Replace staged cluster-admin bindings with explicit root/foundation/Helm/database/migration/app service accounts and narrowly enumerated Role/ClusterRole bindings. Prohibit Secret read, service-account token creation, CSR approval, impersonation and non-resource URL writes.
4. Activate only the dependency DAG `foundation -> cert-manager -> cnpg -> database -> migration -> apps`. Keep every Flux CR in `flux-system`, set `serviceAccountName`, and use `dependsOn`, health checks, timeouts and pruning.
5. Render `clusters/dev` and make the focused test progress past sync/RBAC failures.

Run:

```bash
python3 -B -m unittest scripts.test_validate.BusinessReadyGitOpsContractTest -v
kubectl kustomize clusters/dev
```

Commit:

```bash
git add clusters/dev scripts/test_validate.py scripts/validation_catalog.py
git commit -m "feat(gitops): activate gated public Flux sync"
```

## Task 3: Vendor and pin the two approved controller charts

**Files:**

- Create: `vendor/charts/cert-manager/`
- Create: `vendor/charts/cloudnative-pg/`
- Create: `vendor/charts/README.md`
- Delete: `infrastructure/cert-manager/controller/release.yaml`
- Modify: `infrastructure/cert-manager/controller/kustomization.yaml`
- Delete: `infrastructure/cert-manager/controller/repository.yaml`
- Delete: `infrastructure/cnpg/controller/cnpg-release.yaml`
- Modify: `infrastructure/cnpg/controller/kustomization.yaml`
- Keep inactive: `infrastructure/cnpg/controller/barman-release.yaml`
- Delete: `infrastructure/cnpg/controller/repository.yaml`
- Modify: `pcs/candidate-2.md`

1. Download cert-manager chart `v1.21.1` and CloudNativePG chart `0.29.0` only from their official repositories into a private temporary directory.
2. Compute SHA-256 before extraction. Verify CloudNativePG equals the existing PCS digest `668e065ff53508d58238788fd35b355a925060843629a951df0e6a9362e6d32f`; record the observed cert-manager chart digest as a new candidate fact.
3. Extract with path traversal/link checks and copy chart contents into `vendor/charts/`; retain upstream license files and provenance in `vendor/charts/README.md`.
4. Commit deterministic `helm template` output, change both active controller Kustomizations to that output, pin every operand image by digest, and remove HelmRepository/HelmRelease/Barman from active rendering.
5. Pin operand images/digests through chart values where supported and render both charts locally with the exact values to prove no floating workload image remains.

Run:

```bash
helm template cert-manager vendor/charts/cert-manager --namespace cert-manager --include-crds --values /tmp/cert-manager-values.yaml
helm template cloudnative-pg vendor/charts/cloudnative-pg --namespace cnpg-system --values /tmp/cnpg-values.yaml
python3 -B -m unittest scripts.test_validate.BusinessReadyGitOpsContractTest -v
```

Commit:

```bash
git add vendor infrastructure/cert-manager infrastructure/cnpg/controller pcs/candidate-2.md
git commit -m "feat(gitops): vendor approved platform charts"
```

## Task 4: Narrow the existing core and database entrypoints to no-backup desired state

**Files:**

- Modify: `infrastructure/foundation/kustomization.yaml`
- Modify: `infrastructure/foundation/resource-quotas.yaml`
- Create: `infrastructure/foundation/network-policies.yaml`
- Modify: `infrastructure/cnpg/database/kustomization.yaml`
- Modify: `infrastructure/cnpg/database/cluster.yaml`
- Create: `infrastructure/cnpg/database/network-policy.yaml`
- Modify: `infrastructure/foundation/environment.yaml`

1. Create only `local-path-storage`, `cert-manager`, `cnpg-system` and `platform` Namespaces with restricted Pod Security labels where compatible.
2. Reuse the fixed local-path provisioner/storage class and platform quota while excluding MinIO/monitoring quotas.
3. Create a no-backup CNPG Cluster with one non-superuser owner and six managed runtime roles/password Secret references, one instance, fixed PG 18.4 linux/amd64 digest, 20Gi PVC and DEV-002 resources.
4. Do not include the existing backup database kustomization, Barman plugin, ObjectStore, ScheduledBackup or archive parameters.
5. Update environment metadata so inactive DEV-001 storage does not appear as an active binding.

Run:

```bash
kubectl kustomize infrastructure/foundation
kubectl kustomize infrastructure/cnpg/database
python3 -B -m unittest scripts.test_validate.BusinessReadyGitOpsContractTest -v
```

Commit:

```bash
git add infrastructure/foundation infrastructure/cnpg/database
git commit -m "feat(gitops): add no-backup DEV database core"
```

## Task 5: Add migration and application workloads

**Files:**

- Create: `apps/migration/kustomization.yaml`
- Create: `apps/migration/job.yaml`
- Create: `apps/migration/network-policy.yaml`
- Create: `apps/platform/kustomization.yaml`
- Create: `apps/platform/service-accounts.yaml`
- Create: `apps/platform/frontend.yaml`
- Create: `apps/platform/backend.yaml`
- Create: `apps/platform/services.yaml`
- Create: `apps/platform/http-route.yaml`
- Create: `apps/platform/network-policy.yaml`
- Modify: `apps/kustomization.yaml`
- Modify: `apps/gateway/kustomization.yaml`

1. Add immutable migration Job generation for backend source `4aaf721...` and image `ghcr.io/unif-code/engineering-platform-backend@sha256:f32c5f...`; make role preflight and `alembic upgrade heads` one fail-closed command.
2. Mount the non-superuser `platform_owner` migration configuration and runtime configuration only as Secret files; do not print or transform their values in Pod arguments.
3. Add frontend using linux/amd64 digest `sha256:21248f...` and backend using the approved immutable digest, exact resources/probes, non-root read-only security and writable `emptyDir` mounts.
4. Mount backend runtime config at `/app/.env` and the three DEV-003 materials at dedicated read-only file paths; use no Secret env reference.
5. Add ClusterIP services, PDBs/network policies and one HTTPRoute attached to `platform-gateway`; preserve the existing Certificate/Gateway.
6. Keep migration and runtime as separate Flux paths so apps cannot reconcile before migration succeeds.

Run:

```bash
kubectl kustomize apps/migration
kubectl kustomize apps/platform
kubectl kustomize apps
python3 -B -m unittest scripts.test_validate.BusinessReadyGitOpsContractTest -v
```

Commit:

```bash
git add apps
git commit -m "feat(gitops): add migrated platform workloads"
```

## Task 6: Implement the fail-closed business-ready validator

**Files:**

- Modify: `scripts/validate.py`
- Modify: `scripts/test_validate.py`
- Modify: `scripts/validation_catalog.py`

1. Implement a validator matching every Task 1 invariant and emitting distinct actionable failures.
2. Remove only the newly active files from inactive-entrypoint checks; keep OpenBao, MinIO, backup, restore, Barman and observability entrypoints inactive.
3. Validate chart package provenance, no-backup dependency DAG, RBAC denylist, Secret file-only contract, immutable images, exact resource/security settings and northbound route shape.
4. Run mutation tests and the full validation test class until GREEN.

Run:

```bash
python3 -B -m unittest scripts.test_validate.BusinessReadyGitOpsContractTest -v
python3 -B scripts/run_validation.py --validate-catalog
python3 -B scripts/validate.py
```

Commit:

```bash
git add scripts/validate.py scripts/test_validate.py scripts/validation_catalog.py
git commit -m "feat(validation): enforce business-ready GitOps contract"
```

## Task 7: Add resumable bootstrap stages 110–160 test-first

**Files:**

- Modify: `scripts/test_bootstrap.py`
- Modify: `scripts/bootstrap/bootstrap-all.sh`
- Create: `scripts/bootstrap/stages/110-flux-sync/run.sh`
- Create: `scripts/bootstrap/stages/110-flux-sync/README.md`
- Create: `scripts/bootstrap/stages/120-platform-core/run.sh`
- Create: `scripts/bootstrap/stages/120-platform-core/README.md`
- Create: `scripts/bootstrap/stages/130-platform-database/run.sh`
- Create: `scripts/bootstrap/stages/130-platform-database/README.md`
- Create: `scripts/bootstrap/stages/140-platform-migration/run.sh`
- Create: `scripts/bootstrap/stages/140-platform-migration/README.md`
- Create: `scripts/bootstrap/stages/150-platform-apps/run.sh`
- Create: `scripts/bootstrap/stages/150-platform-apps/README.md`
- Create: `scripts/bootstrap/stages/160-business-ready-evidence/run.sh`
- Create: `scripts/bootstrap/stages/160-business-ready-evidence/README.md`

1. Extend orchestrator tests first for 15-stage order, check/apply/postcheck semantics, summaries, progress counters, exact accepted results and stage-directory security gates. Preserve RED output.
2. Add focused stage fixtures that prove `--check` is read-only, partial/unknown state stops, Secret values never reach stdout/stderr/evidence, existing Secret drift is never overwritten, migration cannot run before role checks, and apps cannot run before migration.
3. Stage 110 activates only sync and exact FQDN egress; Stage 120 waits for approved core/Helm resources; Stage 130 uses CSPRNG under `umask 077`, creates prerequisite Secrets without value output, waits for CNPG and creates `/app/.env`; Stage 140 runs one immutable migration generation; Stage 150 waits for workloads/TLS/routes and executes non-sensitive smoke probes; Stage 160 writes evidence plus mode-600 SHA-256 sidecar.
4. Make every stage idempotent with `ALREADY_COMPLIANT`, use no `--force-conflicts`, fail closed on mixed state and keep account bootstrap outside the orchestrator.

Run RED then GREEN:

```bash
python3 -B -m unittest scripts.test_bootstrap.BusinessReadyStageTest scripts.test_bootstrap.BootstrapOrchestratorTest -v
python3 -B -m unittest scripts.test_bootstrap -v
```

Commit:

```bash
git add scripts/bootstrap scripts/test_bootstrap.py
git commit -m "feat(bootstrap): add business-ready stages 110 through 160"
```

## Task 8: Document the one-command run and acceptance boundary

**Files:**

- Modify: `runbook/01-bootstrap.md`
- Modify: `runbook/06-apps.md`
- Modify: `runbook/09-acceptance.md`
- Modify: `pcs/candidate-2.md`

1. Document that `run-approved.sh <sha> --check|--apply` now resumes through Stage 160 but still requires command-first mutation approval.
2. Record the exact active DAG, exclusions, supply-chain inputs, Secret metadata-only evidence, migration generation, smoke expectations and `/root/dev-infra-evidence/16-business-ready-<UTC>.txt` contract.
3. Keep business deployment, migration and account initialization as `NOT_EXECUTED` until runtime evidence exists; keep V0.1 backup/restore/observability acceptance `BLOCKED`.
4. Add the separate interactive admin bootstrap command template without a password, employee number or display name; state that one-time output must not enter evidence/chat/files.

Run:

```bash
python3 -B -m unittest scripts.test_validate.RepositoryProfileContractTest scripts.test_validate.BootstrapContractTest -v
git diff --check
```

Commit:

```bash
git add runbook pcs/candidate-2.md
git commit -m "docs(runbook): define business-ready activation and evidence"
```

## Task 9: Run all local gates and review the candidate

1. Execute focused tests and WSL/ext4 LF repository gates because the Windows checkout CRLF changes fixed supply-chain bytes.
2. Run fast, static and full profiles with shellcheck 0.9.0, render every active Kustomization and template both vendored charts.
3. Run `git diff --check`, placeholder/secret scans, and review the diff against the spec and architecture baseline.
4. Do not claim runtime deployment from repository tests.

Commands:

```bash
python3 -B -m unittest scripts.test_validate.BusinessReadyGitOpsContractTest scripts.test_bootstrap.BusinessReadyStageTest -v
python3 -B scripts/run_validation.py --profile fast
python3 -B scripts/run_validation.py --profile static
python3 -B scripts/run_validation.py --profile full
kubectl kustomize clusters/dev
kubectl kustomize infrastructure/foundation
kubectl kustomize infrastructure/cnpg/database
kubectl kustomize apps/migration
kubectl kustomize apps/platform
git diff --check
```

## Task 10: Deliver through protected main and clean merged work

1. Push `codex/business-ready-gitops`, open a PR, and wait for the exact candidate SHA `validation-gate` and all required jobs to pass.
2. Merge only the verified SHA linearly into `main`; verify `origin/main` and `origin/validated` both point to the merged SHA after `publish-validated` succeeds.
3. Delete the merged remote/local branch and remove the isolated worktree only after main equivalence and clean-state checks.
4. Refresh the external Chrome `Web终端 - 统一企业堡垒机` tab read-only. If absent, stop rather than using another terminal.
5. Present the exact server command below with the merged SHA substituted, its impact, expected readback and rollback boundary; wait for a new explicit approval before running it:

```bash
cd /opt/uni-code/engineering-platform-gitops && ./scripts/bootstrap/run-approved.sh <MERGED_SHA> --check; rc=$?; printf '\nCOMMAND_EXIT_CODE=%s\n' "$rc"; (exit "$rc")
```

6. After a successful check and separate approval, present the exact `--apply` command. Execute Stage 110–160 only through the external Chrome tab, capture evidence, then run readback and the separate interactive account bootstrap approval flow.
