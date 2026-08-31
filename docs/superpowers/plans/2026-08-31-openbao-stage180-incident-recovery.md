# DEV OpenBao Stage 180 Incident Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely recover the initialized DEV OpenBao instance from the Stage 180 non-TTY failure, complete Runtime configuration, rotate the exposed 5/3 unseal-key set under PGP protection, revoke the initial root token, and gate final acceptance on live verified state.

**Architecture:** Keep `run-approved.sh` as the only server entrypoint and add an exact incident-operation argv contract. Put archive/schema parsing in a focused Python module, keep OpenBao orchestration in `openbao-initialize.sh`, and test the Bash state machine with fake live-state functions plus a real pseudo-TTY harness. Preserve the normal fresh-environment v1 path; once any incident artifact is present, fail closed into the v2 rotation path and never fall back to normal acceptance.

**Tech Stack:** Bash 5, Python 3 standard library, `unittest`, Kubernetes `kubectl exec`, OpenBao CLI 2.6.1, OpenPGP/GnuPG, ShellCheck 0.9.0.

**Spec:** `docs/superpowers/specs/2026-08-31-openbao-stage180-incident-recovery-design.md`

## Global Constraints

- Server work uses only the newest external Chrome tab titled `Web终端 - 统一企业堡垒机`; never use SSH or a local terminal to access the server.
- Show every server command in full before execution and wait for its exact readback before sending the next command.
- Sensitive values are entered only by the human at the actual OpenBao/GPG hidden prompt; browser helper fields, chat, ordinary shell prompts, and command lines are forbidden.
- Never print, log, commit, persist in Evidence, or place in argv/environment any recovery share, root token, private key, passphrase, or decrypted recovery value.
- Do not re-run `operator init`, delete/recreate Raft or Audit PVCs, patch live objects by hand, or bypass `scripts/bootstrap/run-approved.sh`.
- Keep MinIO, Snapshot, Backup, Restore, and application Secret migration `NOT_EXECUTED`.
- Keep the source v1 bundle and candidate bundle; do not auto-delete server/local recovery artifacts, branches, worktrees, or user commits.
- A PGP-encrypted OpenBao rotation backup is allowed only as crash protection; plaintext backup is forbidden, and the encrypted backup must be deleted after the final v2 bundle validates and before root-token revocation.
- Incident acceptance requires `origin/main == origin/validated == approved SHA`; the existing ordinary bootstrap rule that permits main ahead of validated remains unchanged.
- A fresh environment with a valid current-SHA v1 bundle and no incident artifact keeps the normal `configure`/legacy acceptance path. Source/candidate/final/marker presence selects the incident path permanently; mixed or ambiguous state stops.
- Do not update `docs/superpowers/progress/current.md` without the exact user instruction `【同步进度】`.

## File Structure

- Create `scripts/bootstrap/lib/run-approved-args.sh`: pure, side-effect-free parsing of the approved SHA, mode, Stage 180 operation, and source recovery SHA into a fixed argv array.
- Create `scripts/bootstrap/lib/openbao_recovery.py`: exact v1/candidate/v2 archive validation, allowlisted rotation-response normalization, metadata generation, and wizard item extraction.
- Modify `scripts/bootstrap/run-approved.sh`: consume the parser, enforce Stage 180 main/validated equality, and pass only the parser-produced argv array through `env -i`.
- Modify `scripts/bootstrap/lib/openbao-initialize.sh`: TTY primitives, source/candidate/final paths, root-session lifecycle, rotation state machine, v2 acceptance, and Evidence gates.
- Modify `scripts/bootstrap/stages/180-openbao-initialize/README.md`: exact operations, results, next actions, and stop-reason set.
- Modify `scripts/openbao/recovery-ceremony-wizard.sh`: below the `STAGES` marker only, localize operator stages and support v1/candidate/v2 selection rules.
- Modify `scripts/openbao/README.md`: three-bundle lifecycle and secret boundaries.
- Modify `runbook/11-openbao-runtime.md`: exact incident check/start/download/verify/final-download/accept sequence.
- Modify `scripts/test_bootstrap.py`: executable parser, PTY, archive, state-machine, cleanup, and Evidence regressions.
- Modify `scripts/test_validate.py`: runbook/operation contract assertions.

---

### Task 1: Exact incident argv routing and validated gate

**Files:**
- Create: `scripts/bootstrap/lib/run-approved-args.sh`
- Modify: `scripts/bootstrap/run-approved.sh:4-63,105-157`
- Modify: `scripts/bootstrap/lib/openbao-initialize.sh:12-52,995-1036`
- Test: `scripts/test_bootstrap.py:3363-3565,7614-7622`

**Interfaces:**
- Consumes: command line `[approved SHA] --check|--apply`.
- Produces: `RUN_APPROVED_SHA`, `RUN_APPROVED_MODE`, `RUN_APPROVED_TARGET`, and indexed array `RUN_APPROVED_TARGET_ARGUMENTS`.
- Produces Stage 180 argv only in these new shapes: `--check --source-recovery-sha=$SOURCE_SHA`, `--recover-start --source-recovery-sha=$SOURCE_SHA`, or `--recover-verify --source-recovery-sha=$SOURCE_SHA`.
- Preserves existing `--check`, `--initialize`, `--configure`, and `--accept` shapes without a source SHA.

- [ ] **Step 1: Write failing parser and wrapper tests**

Add executable parser tests and extend `RunApprovedTest` so fake Stage 180 records every argv element:

```python
def test_incident_operations_require_exact_source_sha_argv(self) -> None:
    source = 'a' * 40
    accepted = (
        ('--check', '--stage=180', f'--source-recovery-sha={source}'),
        ('--apply', '--stage=180', '--operation=recover-start',
         f'--source-recovery-sha={source}'),
        ('--apply', '--stage=180', '--operation=recover-verify',
         f'--source-recovery-sha={source}'),
    )
    rejected = (
        ('--apply', '--stage=180', '--operation=recover-start'),
        ('--apply', '--stage=180', '--operation=accept',
         f'--source-recovery-sha={source}'),
        ('--apply', '--stage=180', '--operation=recover-start',
         '--source-recovery-sha=' + 'A' * 40),
        ('--apply', '--stage=180', '--operation=recover-start',
         f'--source-recovery-sha={source}', '--extra'),
    )
```

Add a Stage 180 check test where `origin/main` is ahead of `origin/validated`; expect the wrapper to stop before the fake stage. Keep `test_uses_validated_even_when_main_moved_ahead` green for ordinary bootstrap.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.RunApprovedTest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest -v
```

Expected: FAIL because the parser file, the two recovery operations, exact argv forwarding, and Stage 180 validated equality do not exist.

- [ ] **Step 3: Implement the pure parser and controlled argv forwarding**

The parser must build an array and never return unreviewed `"$@"`:

```bash
RUN_APPROVED_TARGET_ARGUMENTS=()
case "$mode:$#:${1:-}:${2:-}:${3:-}" in
  --check:2:--stage=180:--source-recovery-sha=*:)
    source_sha=${2#--source-recovery-sha=}
    [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
    RUN_APPROVED_TARGET=openbao-initialize
    RUN_APPROVED_TARGET_ARGUMENTS=(--check "--source-recovery-sha=${source_sha}")
    ;;
  --apply:3:--stage=180:--operation=recover-start:--source-recovery-sha=*)
    source_sha=${3#--source-recovery-sha=}
    [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || return 2
    RUN_APPROVED_TARGET=openbao-initialize
    RUN_APPROVED_TARGET_ARGUMENTS=(--recover-start "--source-recovery-sha=${source_sha}")
    ;;
esac
```

Implement the symmetric `recover-verify` branch and preserve all existing branches. For any Stage 180 target, fetch `validated` and require both remote refs to equal the approved SHA before merge. Execute:

```bash
/usr/bin/env -i HOME="${HOME:-/root}" PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C \
  /bin/bash -p "$target_script" "${RUN_APPROVED_TARGET_ARGUMENTS[@]}"
```

Inside `openbao_parse_operation`, validate the source SHA again and set `OPENBAO_OPERATION=RECOVER_START|RECOVER_VERIFY`; never trust wrapper-only validation.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the command from Step 2.

Expected: all `RunApprovedTest` and operation-parser tests PASS; ordinary bootstrap still accepts a validated ancestor while every Stage 180 route requires exact main/validated equality.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap/lib/run-approved-args.sh \
  scripts/bootstrap/run-approved.sh scripts/bootstrap/lib/openbao-initialize.sh \
  scripts/test_bootstrap.py
git commit -m "fix(openbao): gate incident recovery operations"
```

### Task 2: Safe cross-SHA v1 source-bundle adoption

**Files:**
- Create: `scripts/bootstrap/lib/openbao_recovery.py`
- Modify: `scripts/bootstrap/lib/openbao-initialize.sh:40-216,769-814`
- Test: `scripts/test_bootstrap.py:7607-7754`

**Interfaces:**
- Consumes: root-owned mode-0600 source archive/sidecar derived only from `OPENBAO_SOURCE_RECOVERY_SHA`.
- Produces: immutable `SourceBundleFacts(schema, archive_sha256, source_sha, public_key_sha256, public_key_fingerprint, platform_secret_fingerprint)`; no ciphertext or root token is returned or printed.
- Produces CLI `validate-source` with exit 0 and no stdout on success.

- [ ] **Step 1: Write the source archive rejection matrix**

Create tar fixtures with exact v1 files, then mutate one property per subtest:

```python
def test_source_v1_rejects_unsafe_members_and_metadata(self) -> None:
    cases = (
        'absolute-path', 'dot-dot', 'symlink', 'hardlink', 'fifo',
        'extra-member', 'missing-member', 'wrong-schema', 'wrong-source-sha',
        'wrong-docs-baseline', 'wrong-platform-fingerprint',
        'wrong-public-fingerprint', 'wrong-share-count', 'missing-root-token',
        'checksum-drift',
    )
    for case in cases:
        with self.subTest(case=case):
            archive, sidecar = self.make_source_bundle(case=case)
            result = self.run_recovery_helper('validate-source', archive, sidecar)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
```

Also test that a syntactically valid source SHA must resolve as a Git commit and be an ancestor of the current approved commit; scanning the directory for “some old bundle” is forbidden.

- [ ] **Step 2: Run the source validator test and confirm RED**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_source_v1_rejects_unsafe_members_and_metadata -v
```

Expected: FAIL because `openbao_recovery.py` and source-derived paths do not exist.

- [ ] **Step 3: Implement exact tar/schema validation**

Use typed members and an exact file set:

```python
@dataclasses.dataclass(frozen=True)
class SourceBundleFacts:
    schema: str
    archive_sha256: str
    source_sha: str
    public_key_sha256: str
    public_key_fingerprint: str
    platform_secret_fingerprint: str

def read_exact_tar(archive: pathlib.Path, expected: set[str]) -> dict[str, bytes]:
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers()
        names = {member.name for member in members if member.isfile()}
        if names != expected or any(
            member.issym() or member.islnk() or member.isdev()
            or pathlib.PurePosixPath(member.name).is_absolute()
            or '..' in pathlib.PurePosixPath(member.name).parts
            for member in members
        ):
            raise RecoveryValidationError('unsafe archive members')
        return {member.name: stream.extractfile(member).read() for member in members
                if member.isfile()}
```

Validate sidecar name/digest, v1 schema, source/docs/deviation/fingerprints, exact 5/3 encrypted payload, and encrypted root token without emitting their values. In Bash, validate root ownership/mode, `git cat-file -e "$source^{commit}"`, and `git merge-base --is-ancestor "$source" "$OPENBAO_RECOVERY_ID"` before invoking Python with `-I -B`.

`openbao_stage_180_check` must return `source-recovery-sha-required` when current-SHA recovery state is missing but live OpenBao is initialized. With a validated source, return `PASS_OPENBAO_RECOVERY_CHECK`, `REASON=recover-start-required`, and a next Stage 180 recovery command containing that exact source SHA.

- [ ] **Step 4: Run the full source matrix and confirm GREEN**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest -v
```

Expected: all source bundle, normal v1 initialization, and current-SHA path tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap/lib/openbao_recovery.py \
  scripts/bootstrap/lib/openbao-initialize.sh scripts/test_bootstrap.py
git commit -m "feat(openbao): validate source recovery bundles"
```

### Task 3: True-TTY unseal and root-session lifecycle

**Files:**
- Modify: `scripts/bootstrap/lib/openbao-initialize.sh:298-405,514-555,887-931`
- Test: `scripts/test_bootstrap.py:7607-7697`

**Interfaces:**
- Produces `openbao_require_interactive_tty() -> 0|1` checking fds 0, 1, and 2 before any secret read or OpenBao mutation.
- Produces `openbao_bao_public ARGS...` for noninteractive unauthenticated status/reset, `openbao_bao_tty_public ARGS...` for interactive unseal, and `openbao_bao_tty ARGS...` for commands that require the protected remote HOME token helper; the TTY functions use `kubectl exec --stdin --tty`.
- Produces `openbao_root_session_start()`, `openbao_apply_configuration()`, `openbao_root_session_revoke()`, and checked `openbao_remote_session_cleanup()`.
- Keeps `openbao_prompt_secret()` only for `rotate-keys KEY=-`; unseal and root login never use `OPENBAO_SECRET_INPUT`.

- [ ] **Step 1: Replace the static stdin test with an executable PTY regression**

Use Python `pty.openpty()` to execute a Bash harness that sources the real library and replaces `kubectl_run` with an argv logger:

```python
def test_unseal_and_root_login_use_true_tty_without_outer_capture(self) -> None:
    result, command_log = self.run_stage180_function_in_pty(
        'openbao_unseal_interactively; openbao_root_session_start',
    )
    self.assertEqual(result.returncode, 0, result.output)
    self.assertIn('exec --stdin --tty pod/openbao-0', command_log)
    self.assertIn('bao operator unseal -format=json', command_log)
    self.assertIn('bao login -no-print', command_log)
    self.assertNotIn('OPENBAO_SECRET_INPUT', self.unseal_function_source())
    self.assertNotIn('printf', self.unseal_function_source())
```

Add a non-PTY harness assertion that returns `interactive-tty-required` with an empty command log.
Add a source assertion that the TTY login, unseal, rotate-share, and token-helper lifecycle contain no `set -x`, `BAO_TOKEN=`, secret argv, or secret logging primitive.

- [ ] **Step 2: Run the PTY tests and confirm RED with the reproduced bug**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_unseal_and_root_login_use_true_tty_without_outer_capture \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_secret_operations_stop_before_read_without_tty -v
```

Expected: FAIL because current unseal captures a share and pipes it to a non-TTY CLI.

- [ ] **Step 3: Implement the TTY adapter and split root responsibilities**

Implement the command shape literally:

```bash
openbao_bao_tty_public() {
  kubectl_run --namespace=openbao exec --stdin --tty pod/openbao-0 -- env \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_bao_tty() {
  kubectl_run --namespace=openbao exec --stdin --tty pod/openbao-0 -- env \
    HOME="$OPENBAO_REMOTE_HOME" \
    BAO_ADDR=https://openbao.openbao.svc:8200 \
    BAO_CACERT=/openbao/userconfig/openbao-server-tls/ca.crt \
    bao "$@"
}

openbao_unseal_interactively() {
  openbao_require_interactive_tty || return 1
  openbao_bao_public operator unseal -reset -format=json >/dev/null || return 1
  for attempt in 1 2 3; do
    openbao_bao_tty_public operator unseal -format=json >/dev/null || return 1
    openbao_unseal_progress_is_safe "$attempt" || return 1
  done
  [[ "$(openbao_state_flags)" == 'true|false' ]]
}
```

`openbao_root_session_start` creates a root remote HOME and calls `openbao_bao_tty login -no-print`. `openbao_apply_configuration` assumes an authenticated session and performs only the idempotent config/readback. The normal `configure` route calls start → configure → revoke-self/readback → checked cleanup. The incident route will reuse start/configure but defer revocation.

Make cleanup return nonzero on token-helper removal failure in success paths; keep the EXIT trap as a best-effort fallback only.

- [ ] **Step 4: Run PTY, normal configure, and cleanup tests and confirm GREEN**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest -v
bash -n scripts/bootstrap/lib/openbao-initialize.sh
```

Expected: PTY command shape, no-TTY fail-closed, normal configure revocation, and cleanup-failure tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap/lib/openbao-initialize.sh scripts/test_bootstrap.py
git commit -m "fix(openbao): use true tty for stage 180 secrets"
```

### Task 4: Candidate and final v2 recovery artifacts

**Files:**
- Modify: `scripts/bootstrap/lib/openbao_recovery.py`
- Modify: `scripts/bootstrap/lib/openbao-initialize.sh:12-23,40-52,218-274,671-687`
- Test: `scripts/test_bootstrap.py:7607-7754`

**Interfaces:**
- Produces candidate archive `openbao-recovery-rotation-candidate-$CURRENT_SHA.tar.gz` with schema `engineering-platform/openbao-recovery-rotation-candidate/v1`.
- Produces final archive `openbao-recovery-$CURRENT_SHA.tar.gz` with schema `engineering-platform/openbao-recovery/v2`.
- Candidate contains `shares.json`, `metadata.json`, public key, and fingerprint; only candidate metadata may contain `verification_nonce`.
- Final contains the same exact files, but metadata omits nonce, says `rotation_state=verified` and `initial_root_token=revoked`, and contains per-ciphertext SHA-256 values.
- Produces `emit-item --archive PATH --sidecar PATH --item share1|...|share5|root`, enforcing schema-specific item permissions.

- [ ] **Step 1: Write candidate/final schema and noclobber tests**

```python
def test_candidate_and_v2_final_have_exact_safe_contents(self) -> None:
    candidate = self.normalize_rotation_response(self.valid_rotate_response())
    self.assertEqual(candidate.schema,
                     'engineering-platform/openbao-recovery-rotation-candidate/v1')
    self.assertEqual(candidate.key_shares, 5)
    self.assertEqual(candidate.key_threshold, 3)
    final = self.build_final(candidate)
    self.assertEqual(final.schema, 'engineering-platform/openbao-recovery/v2')
    self.assertEqual(final.metadata['initial_root_token'], 'revoked')
    self.assertNotIn('root_token', final.shares_document)
    self.assertNotIn('verification_nonce', final.metadata)
```

Add rejection cases for wrong `complete`, wrong key count, plaintext-like `keys`, missing/duplicate PGP fingerprints, unsafe members, checksum drift, mixed schemas, existing output, and marker-only state. Test that v1 permits `root`, while candidate/v2 reject `root` and permit only `share1..share5`.

- [ ] **Step 2: Run artifact tests and confirm RED**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_candidate_and_v2_final_have_exact_safe_contents \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_wizard_item_permissions_follow_bundle_schema -v
```

Expected: FAIL because only v1 `init.json` is supported.

- [ ] **Step 3: Implement allowlisted normalization and exclusive writers**

Normalize only encrypted keys and non-sensitive state from the CLI response:

```python
def normalize_rotation_response(document: dict[str, object]) -> dict[str, object]:
    keys = document.get('keys_base64')
    fingerprints = document.get('pgp_fingerprints')
    nonce = document.get('verification_nonce')
    if document.get('complete') is not True or not isinstance(keys, list) or len(keys) != 5:
        raise RecoveryValidationError('rotation response incomplete')
    if not isinstance(fingerprints, list) or len(fingerprints) != 5:
        raise RecoveryValidationError('PGP fingerprint count mismatch')
    if not isinstance(nonce, str) or not nonce:
        raise RecoveryValidationError('verification nonce missing')
    return {'unseal_keys_b64': keys, 'unseal_shares': 5, 'unseal_threshold': 3}
```

Never copy the raw response. Bash creates directories mode `0700`, files mode `0600`, archive and sidecar with `set -o noclobber`, and validates the completed artifact before reporting success. Derive a stable `cluster_identity_sha256` from canonical JSON containing live `cluster_id` and `cluster_name`; do not claim it came from v1 metadata.

- [ ] **Step 4: Run artifact and secret-shape tests and confirm GREEN**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest -v
```

Expected: exact candidate/final lifecycle, schema permissions, noclobber, and sensitive-shape tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap/lib/openbao_recovery.py \
  scripts/bootstrap/lib/openbao-initialize.sh scripts/test_bootstrap.py
git commit -m "feat(openbao): add rotated recovery bundle schemas"
```

### Task 5: Recover-start orchestration and crash-safe encrypted-key capture

**Files:**
- Modify: `scripts/bootstrap/lib/openbao-initialize.sh:784-931,995-1036`
- Test: `scripts/test_bootstrap.py:7607-7754`

**Interfaces:**
- Produces `openbao_stage_180_recover_start()`.
- Produces rotation helpers `openbao_rotation_status`, `openbao_rotation_initialize`, `openbao_rotation_submit_share`, `openbao_rotation_capture_candidate`.
- Success result: `RESULT=PASS_OPENBAO_RECOVERY_STARTED`, `REASON=openbao-key-rotation-verification-required`, next action is candidate download/verification followed by `recover-verify`.

- [ ] **Step 1: Write executable state-order and reentry tests**

Use a Bash harness that sources the real library and stubs each external fact/function into an ordered call log:

```python
def test_recover_start_orders_unseal_config_rotation_and_candidate(self) -> None:
    result, calls = self.run_recover_start(state='true|true', rotation='MISSING')
    self.assertEqual(result.returncode, 0, result.output)
    self.assertEqual(calls, [
        'preflight', 'source-validate', 'tty-check', 'unseal', 'root-login',
        'configure', 'rotation-init-5-3-pgp-verify-backup',
        'old-share-1', 'old-share-2', 'old-share-3',
        'candidate-write', 'candidate-validate', 'root-helper-cleanup',
    ])
```

Add cases for already-unsealed, partial old quorum with the same nonce, existing valid candidate reuse, second-init rejection, candidate checksum drift, configuration failure, and cleanup failure. Assert no root revoke occurs in `recover-start`.

- [ ] **Step 2: Run recover-start tests and confirm RED**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_recover_start_orders_unseal_config_rotation_and_candidate \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_recover_start_resumes_same_rotation_nonce -v
```

Expected: FAIL because the recovery state machine is absent.

- [ ] **Step 3: Implement recover-start with encrypted backup and strict reentry**

Initialize rotation exactly once:

```bash
openbao_bao operator rotate-keys -format=json -init -verify -backup \
  -key-shares=5 -key-threshold=3 "-pgp-keys=${pgp_keys}"
```

For each old share, call `openbao_prompt_secret`, then explicitly use stdin mode:

```bash
printf '%s\n' "$OPENBAO_SECRET_INPUT" |
  openbao_bao_stdin operator rotate-keys -format=json \
    "-nonce=${rotation_nonce}" - >"$response"
OPENBAO_SECRET_INPUT=
unset OPENBAO_SECRET_INPUT
```

Do not print the response. The PGP-encrypted OpenBao backup makes the final old-quorum response retrievable after interruption; normalize it into the candidate immediately, validate candidate and sidecar, then clean the root token helper without revoking the server-side root token. If rotation is already pending, read the live status/nonce and resume; never call `-init` again.

If the old quorum completed but the candidate was not durably written, recover only the PGP ciphertext with:

```bash
openbao_bao operator rotate-keys -format=json -backup-retrieve >"$response"
```

Normalize that response through the same allowlist; never print it and never request a plaintext backup.

The script cannot identify which old share was exposed. Prompts and runbook must say to use three other old shares. The verifiable security claim is made only after the complete old key set is invalidated by verified rotation.

- [ ] **Step 4: Run recover-start and existing Stage 180 tests and confirm GREEN**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest -v
bash -n scripts/bootstrap/lib/openbao-initialize.sh
```

Expected: first-run, partial progress, candidate reuse, no-overwrite, and cleanup failure behavior PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap/lib/openbao-initialize.sh scripts/test_bootstrap.py
git commit -m "feat(openbao): add recover-start rotation flow"
```

### Task 6: Recover-verify, root revocation, and incident acceptance

**Files:**
- Modify: `scripts/bootstrap/lib/openbao-initialize.sh:407-417,557-767,933-1036`
- Test: `scripts/test_bootstrap.py:7607-7754`

**Interfaces:**
- Produces `openbao_stage_180_recover_verify()` and `openbao_incident_acceptance_state()`.
- Produces marker `/root/openbao-recovery/openbao-rotation-$CURRENT_SHA.verified.json`, mode `0600`, only after verification, final bundle validation, encrypted-backup deletion, Runtime readback, root revoke, and failed post-revoke lookup.
- Success result: `RESULT=PASS_OPENBAO_RECOVERED`, `REASON=openbao-key-rotation-verified`, next operation `--accept`.
- Incident Evidence adds `UNSEAL_KEY_ROTATION=PASS`, `COMPROMISED_SHARE_INVALIDATED=true`, `RECOVERY_BUNDLE_SCHEMA=engineering-platform/openbao-recovery/v2`, and proven `INITIAL_ROOT_TOKEN=REVOKED`.

- [ ] **Step 1: Write verification-order and acceptance-gate tests**

```python
def test_recover_verify_revokes_root_only_after_all_readbacks(self) -> None:
    result, calls = self.run_recover_verify(verification='PENDING')
    self.assertEqual(result.returncode, 0, result.output)
    self.assertLess(calls.index('new-share-3'), calls.index('candidate-revalidate'))
    self.assertLess(calls.index('candidate-revalidate'), calls.index('backup-delete'))
    self.assertLess(calls.index('runtime-readback'), calls.index('root-revoke-self'))
    self.assertLess(calls.index('root-revoke-self'), calls.index('root-lookup-denied'))
    self.assertLess(calls.index('root-lookup-denied'), calls.index('root-helper-cleanup'))
    self.assertLess(calls.index('root-helper-cleanup'), calls.index('final-bundle-validate'))
    self.assertLess(calls.index('final-bundle-validate'), calls.index('verified-marker'))

def test_accept_rejects_candidate_marker_or_live_pending_state(self) -> None:
    for state in ('candidate-only', 'marker-only', 'checksum-drift', 'live-pending'):
        with self.subTest(state=state):
            result = self.run_incident_accept(state)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(result.evidence_created)
```

Also test partial verification nonce reuse, all failures before revoke, root revoke command failure, post-revoke lookup transport error versus authentication denial, helper cleanup failure, and old-format Evidence rejection on the incident path.
The Evidence test must reject `verification_nonce`, `keys_base64`, ciphertext bodies, token-like shapes, and any raw rotation response while accepting only the final bundle SHA-256 and public fingerprint.

- [ ] **Step 2: Run verification and acceptance tests and confirm RED**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_recover_verify_revokes_root_only_after_all_readbacks \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_accept_rejects_candidate_marker_or_live_pending_state -v
```

Expected: FAIL because verification, v2 marker, and live incident acceptance do not exist.

- [ ] **Step 3: Implement verification, finalization, revoke proof, and live accept**

Submit each new share with the verification nonce and explicit stdin mode:

```bash
printf '%s\n' "$OPENBAO_SECRET_INPUT" |
  openbao_bao_stdin operator rotate-keys -format=json -verify \
    "-nonce=${verification_nonce}" - >"$response"
```

After three shares, require both normal and verification status to report no pending rotation. Revalidate that the candidate contains every ciphertext needed for finalization, delete the OpenBao PGP-encrypted backup, rerun Auth/Audit/Runtime probes, then `token revoke -self`; a subsequent lookup must fail specifically as authentication denial, not network/CLI failure. Check helper cleanup, then build and validate final v2 with `initial_root_token=revoked`, and finally atomically write the verified marker. A final v2 bundle must never claim revocation before the revoke proof exists.

Add read-only capabilities for `sys/rotate/root` and `sys/rotate/root/verification` to the dedicated probe policy only so incident acceptance can compare the marker/final digest with live no-pending status; do not grant rotation mutation. Classify acceptance as:

```text
NORMAL_V1: current-SHA v1 bundle and no incident artifacts -> existing acceptance
INCIDENT_V2: source/candidate/final/marker state exists -> v2 hard gates
AMBIGUOUS: mixed/unsafe artifacts -> STOP_UNKNOWN_STATE
```

On `INCIDENT_V2`, validate all four required Evidence fields and all five `NOT_EXECUTED` fields in both new and existing Evidence paths.

```text
UNSEAL_KEY_ROTATION=PASS
COMPROMISED_SHARE_INVALIDATED=true
INITIAL_ROOT_TOKEN=REVOKED
RECOVERY_BUNDLE_SCHEMA=engineering-platform/openbao-recovery/v2
MINIO=NOT_EXECUTED
SNAPSHOT=NOT_EXECUTED
BACKUP=NOT_EXECUTED
RESTORE=NOT_EXECUTED
APP_SECRET_MIGRATION=NOT_EXECUTED
```

- [ ] **Step 4: Run all Stage 180 tests and confirm GREEN**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest -v
```

Expected: verification reentry, revoke ordering, marker/live binding, normal-v1 compatibility, and incident-v2 Evidence tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap/lib/openbao-initialize.sh scripts/test_bootstrap.py
git commit -m "feat(openbao): verify rotated keys before acceptance"
```

### Task 7: Schema-aware Chinese wizard and operator documentation

**Files:**
- Modify: `scripts/openbao/recovery-ceremony-wizard.sh:183-306`
- Modify: `scripts/openbao/README.md`
- Modify: `scripts/bootstrap/stages/180-openbao-initialize/README.md`
- Modify: `runbook/11-openbao-runtime.md`
- Modify: `scripts/test_bootstrap.py:7723-7753`
- Modify: `scripts/test_validate.py:97-160`

**Interfaces:**
- Consumes `openbao_recovery.py emit-item` and a verified local sidecar.
- v1 permits `share1..share5|root`; candidate and v2 permit only `share1..share5`.
- Keeps exactly five human stages and never edits the wizard library above `# STAGES`.

- [ ] **Step 1: Write failing wizard/runbook contract tests**

```python
def test_recovery_wizard_routes_all_three_bundle_schemas(self) -> None:
    wizard = OPENBAO_RECOVERY_WIZARD.read_text(encoding='utf-8')
    for schema in (
        'engineering-platform/openbao-recovery/v1',
        'engineering-platform/openbao-recovery-rotation-candidate/v1',
        'engineering-platform/openbao-recovery/v2',
    ):
        self.assertIn(schema, wizard)
    self.assertIn('候选恢复包尚未完成验证', wizard)
    self.assertIn('初始 root token 已撤销', wizard)
```

Extend the runbook contract test to require `recover-start`, `recover-verify`, `--source-recovery-sha=`, candidate/final download checks, rotation Evidence fields, and the five deferred systems.

- [ ] **Step 2: Run wizard and runbook tests and confirm RED**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest.test_recovery_wizard_routes_all_three_bundle_schemas \
  scripts.test_validate.OpenBaoGitOpsContractTest.test_runtime_runbook_and_acceptance_contract_are_explicit -v
```

Expected: FAIL because the wizard and runbook only describe v1 configure/accept.

- [ ] **Step 3: Update only the wizard stages and operator docs**

Below the `STAGES` marker, derive the helper path and replace wildcard extraction with the validated helper:

```bash
python "$OPENBAO_RECOVERY_HELPER" emit-item \
  --archive "$archive" --sidecar "${archive}.sha256" --item "$item" |
  base64 --decode |
  gpg --decrypt |
  powershell.exe -NoProfile -NonInteractive -Command \
    '$plain = [Console]::In.ReadToEnd(); Set-Clipboard -Value $plain'
```

Translate stage names, questions, warnings, and operator actions below the marker into Chinese. Stage 5 branches on schema: v1 instructs `recover-start` and forbids the exposed share; candidate instructs `recover-verify` and says it is not final; v2 confirms cloud upload of the final ciphertext bundle and clears the clipboard.

Document exact server order and expected results without secret values:

```text
check with source SHA -> recover-start -> candidate download/check ->
decrypt three new shares locally -> recover-verify -> final v2 download/check -> accept
```

State that source/candidate cleanup is separately approved work and that no backup/application migration is performed.

The Stage 180 README must include the existing emitted reasons plus these exact new reasons, and no reason that the implementation does not emit:

```text
source-recovery-sha-required
source-recovery-sha-invalid
source-recovery-bundle-unsafe
interactive-tty-required
openbao-root-login-failed
remote-session-cleanup-failed
openbao-cluster-identity-invalid
openbao-rotation-state-unsafe
openbao-rotation-init-failed
openbao-rotation-share-submit-failed
rotation-candidate-state-unsafe
rotation-candidate-write-failed
rotation-verification-failed
rotation-backup-delete-failed
recovery-final-bundle-state-unsafe
recovery-final-bundle-write-failed
initial-root-token-revoke-failed
initial-root-token-still-valid
recovery-verification-marker-unsafe
```

- [ ] **Step 4: Run documentation, syntax, and exact reason-set tests**

Run:

```bash
python3 -m unittest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest \
  scripts.test_validate.OpenBaoGitOpsContractTest -v
bash -n scripts/openbao/recovery-ceremony-wizard.sh \
  scripts/bootstrap/stages/180-openbao-initialize/run.sh
```

Expected: five-stage/schema tests, runbook contract, and exact Stage 180 README reason list PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/openbao/recovery-ceremony-wizard.sh scripts/openbao/README.md \
  scripts/bootstrap/stages/180-openbao-initialize/README.md \
  runbook/11-openbao-runtime.md scripts/test_bootstrap.py scripts/test_validate.py
git commit -m "docs(openbao): guide incident recovery ceremony"
```

### Task 8: Repository gates and delivery readiness

**Files:**
- Verify only; do not modify `docs/superpowers/progress/current.md`.

**Interfaces:**
- Consumes all prior task commits.
- Produces a clean branch whose focused tests, validation catalog, ShellCheck 0.9.0, manifests, and fast profile pass before push.

- [ ] **Step 1: Run the complete affected test classes**

```bash
python3 -m unittest \
  scripts.test_bootstrap.RunApprovedTest \
  scripts.test_bootstrap.OpenBaoInitializationStageTest \
  scripts.test_validate.OpenBaoGitOpsContractTest -v
```

Expected: all tests PASS with no secret-shaped output.

- [ ] **Step 2: Run syntax and pinned static checks**

```bash
bash -n scripts/bootstrap/lib/run-approved-args.sh \
  scripts/bootstrap/run-approved.sh \
  scripts/bootstrap/lib/openbao-initialize.sh \
  scripts/bootstrap/stages/180-openbao-initialize/run.sh \
  scripts/openbao/recovery-ceremony-wizard.sh
shellcheck scripts/bootstrap/lib/run-approved-args.sh \
  scripts/bootstrap/run-approved.sh \
  scripts/bootstrap/lib/openbao-initialize.sh \
  scripts/bootstrap/stages/180-openbao-initialize/run.sh \
  scripts/openbao/recovery-ceremony-wizard.sh
```

Expected: Bash syntax PASS and ShellCheck reports version 0.9.0 with no findings.

- [ ] **Step 3: Run repository validation in Linux/ext4/LF**

```bash
python3 -B scripts/run_validation.py --validate-catalog
./scripts/validate-fast.sh
git diff --check origin/main...HEAD
```

Expected: validation catalog PASS, fast profile PASS, GitOps manifests validated, and diff check clean.

- [ ] **Step 4: Review the final branch without changing it**

```bash
git status --short --branch
git log --oneline --decorate origin/main..HEAD
git diff --stat origin/main...HEAD
```

Expected: clean worktree; only the design, plan, Stage 180 implementation/tests, wizard, and operator documentation are present. Do not create an empty verification commit.

## Delivery after implementation

1. Use `superpowers:requesting-code-review` and fix verified findings test-first.
2. Push the branch, open a PR, and wait for the PR `validation-gate` to pass.
3. Merge only after review; then wait for the independent main push CI and `publish-validated`.
4. Confirm `origin/main == origin/validated == merged SHA`.
5. In the external Chrome bastion tab, first run the full Stage 180 incident `--check` command with the original source recovery SHA and wait for exact readback.
6. Run `recover-start`, download/verify the candidate on Windows, and have the operator decrypt three new shares through GPG pinentry/clipboard.
7. Run `recover-verify`, download/verify the final v2 bundle, then run `accept`.
8. Accept only `PASS_OPENBAO_RUNTIME_ACCEPTED / openbao-runtime-accepted` plus `/root/dev-infra-evidence/17-openbao-runtime-<UTC>.txt` and its SHA-256 sidecar with no sensitive values.
