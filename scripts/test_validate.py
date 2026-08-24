from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from typing import Iterator
from pathlib import Path

import yaml
import validate as validator
from test_bootstrap import BootstrapTestCase

from validate import (
    INSECURE_TLS,
    document_by_identity,
    validate_metrics_server,
    validate_single_user_resources,
    validate_single_user_storage,
    value_at,
)


class ProfileValidationTest(unittest.TestCase):
    def test_insecure_metrics_tls_is_detected(self) -> None:
        self.assertIsNotNone(
            INSECURE_TLS.search('insecureSkipTLSVerify: true')
        )

    def test_document_and_named_list_item_are_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deployment.yaml'
            path.write_text(
                yaml.safe_dump_all(
                    [
                        {
                            'apiVersion': 'v1',
                            'kind': 'ConfigMap',
                            'metadata': {'name': 'not-minio'},
                        },
                        {
                            'apiVersion': 'apps/v1',
                            'kind': 'Deployment',
                            'metadata': {'name': 'minio'},
                            'spec': {
                                'template': {
                                    'spec': {
                                        'containers': [
                                            {
                                                'name': 'sidecar',
                                                'resources': {
                                                    'requests': {'cpu': '999m'}
                                                },
                                            },
                                            {
                                                'name': 'minio',
                                                'resources': {
                                                    'requests': {'cpu': '100m'}
                                                },
                                            }
                                        ]
                                    }
                                }
                            },
                        }
                    ]
                ),
                encoding='utf-8',
            )

            document = document_by_identity(path, 'Deployment', 'minio')
            cpu = value_at(
                document,
                (
                    'spec',
                    'template',
                    'spec',
                    'containers',
                    ('name', 'minio'),
                    'resources',
                    'requests',
                    'cpu',
                ),
            )

            self.assertEqual(cpu, '100m')


class RepositoryProfileContractTest(unittest.TestCase):
    def assert_documentation_contract(
        self,
        agents: str,
        readme: str,
        runbook: str,
        labels: tuple[str, ...] | None = None,
    ) -> None:
        documents = {
            'agents': ' '.join(agents.split()),
            'readme': ' '.join(readme.split()),
            'runbook': ' '.join(runbook.split()),
        }
        contracts = {
            'local-pre-commit': (
                'agents',
                r'本地提交前运行受影响的 focused tests 和 '
                r'`\./scripts/validate-fast\.sh`',
            ),
            'push-gate-before-deployment': (
                'agents',
                r'普通 push 后必须等待 GitHub `validation-gate` 全部通过，'
                r'才可继续服务器部署或验收',
            ),
            'manual-full-not-per-commit': (
                'agents',
                r'`\./scripts/validate\.sh` 保留为人工完整顺序验证入口，'
                r'不再要求每次本地提交运行',
            ),
            'readme-local-fast-manual-full': (
                'readme',
                r'\./scripts/validate-fast\.sh\s+# 本地提交前运行，目标不超过 '
                r'2 分钟\s+\./scripts/validate\.sh\s+# 可选的人工 full '
                r'sequential diagnostic',
            ),
            'readme-validation-layers': (
                'readme',
                r'`validation-gate` 是完整 suite 的权威部署门禁；'
                r'普通 push 后必须等待该门禁成功，\s*'
                r'才能继续服务器部署或验收',
            ),
            'direct-main-fix-forward': (
                'readme',
                r'当前 direct-main 批次是用户明确批准的例外；门禁失败时只允许\s*'
                r'新增 fix-forward commit，禁止 force push 或改写历史',
            ),
            'orchestrator-normal-commands': (
                'runbook',
                r'### 正常路径 .*\./scripts/bootstrap/bootstrap-all\.sh '
                r'--check .*\./scripts/bootstrap/bootstrap-all\.sh --apply',
            ),
            'check-read-only-stop-first-apply-required': (
                'runbook',
                r'`--check` 全程只读，在第一个需要 APPLY 的 stage 停止，'
                r'不执行任何 APPLY',
            ),
            'apply-check-skip-post-check': (
                'runbook',
                r'`--apply` 会先检查每个 stage，跳过返回 '
                r'`ALREADY_COMPLIANT` 的 stage，仅对需要变更的 stage 执行 '
                r'apply，并要求 apply 后的 post-check 回到 compliant',
            ),
            'resume-real-state-no-progress-file': (
                'runbook',
                r'重跑同一条命令即可恢复：orchestrator 根据真实主机状态重建进度，'
                r'不读取或维护 progress file',
            ),
            'current-server-completed-all-stages': (
                'runbook',
                r'当前服务器已完成全部 stage `00`～`90`。GitHub '
                r'`validation-gate` 成功后重跑 orchestrator，它必须依据各 stage 的'
                r'检查结果跳过这些已完成 stage，并直接抵达 stage `90`',
            ),
            'individual-stages-emergency-only': (
                'runbook',
                r'下表保留为诊断和人工应急入口，不是正常 bootstrap 路径',
            ),
            'stage-50-success-alternatives': (
                'runbook',
                r'\| 12 \| `stages/50-kubeadm-init/run\.sh` \| `--check` 后批准 '
                r'`--apply` \| `PASS_KUBEADM_INITIALIZED` 或 '
                r'`ALREADY_COMPLIANT` \|',
            ),
        }

        selected = labels if labels is not None else tuple(contracts)
        for label in selected:
            document_name, pattern = contracts[label]
            self.assertRegex(
                documents[document_name],
                re.compile(pattern),
                label,
            )

    def test_metrics_server_reads_current_pcs_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            current_pcs = Path(directory) / 'candidate-2.md'
            current_pcs.write_text(
                'current candidate without metrics facts\n', encoding='utf-8'
            )
            stderr = io.StringIO()
            with (
                mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                validate_metrics_server()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn(
            'PCS 缺少 Metrics Server 供应链事实：Metrics Server',
            stderr.getvalue(),
        )

    def test_metrics_server_contract(self) -> None:
        validate_metrics_server()

    def test_runtime_check_docs_disclose_checkout_sync_side_effect(self) -> None:
        # Would fail if wrapper wording hides checkout synchronization or weakens its inner check.
        wrapper_contract = (
            '上层 `run-approved.sh --check` 对集群和主机配置只读，但会 `fetch` '
            '并以 `ff-only` 更新服务器 Git checkout'
        )
        for relative_path in (
            'pcs/candidate-2.md',
            'runbook/01-bootstrap.md',
            'runbook/06-apps.md',
            'runbook/09-acceptance.md',
            'runbook/10-image-owner-handoff.md',
        ):
            with self.subTest(document=relative_path):
                document = (validator.ROOT / relative_path).read_text(encoding='utf-8')
                self.assertIn(wrapper_contract, document)
                self.assertNotRegex(
                    document,
                    r'(?:只读执行|只读) `run-approved(?:\.sh)? --check`',
                )

        bootstrap = (validator.ROOT / 'runbook/01-bootstrap.md').read_text(
            encoding='utf-8'
        )
        self.assertIn('底层 `bootstrap-all.sh --check` 全程只读', bootstrap)

    def test_minio_component_row_cannot_gain_activation_approval(self) -> None:
        # Would fail if the component table can approve MinIO while its summary is blocked.
        statuses = (
            '**APPROVED：允许激活；历史结论曾为 BLOCKED**',
            '**BLOCKED：但已获准激活**',
            '**BLOCKED：获准**',
        )
        for status in statuses:
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    minio = root / 'infrastructure/minio'
                    minio.mkdir(parents=True)
                    current_pcs = root / 'candidate-2.md'
                    lines = validator.CURRENT_PCS.read_text(encoding='utf-8').splitlines()
                    for index, line in enumerate(lines):
                        if line.startswith('| Object Storage | MinIO Server |'):
                            lines[index] = line.replace(
                                '**BLOCKED：精确摘要供应链证据或获批风险决定未满足；'
                                '清单引用不代表获准或已部署**',
                                status,
                            )
                            break
                    else:
                        self.fail('missing MinIO Server component row')
                    current_pcs.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                    for filename in ('deployment.yaml', 'bootstrap-job.yaml'):
                        shutil.copy(
                            validator.ROOT / 'infrastructure/minio' / filename,
                            minio / filename,
                        )
                    stderr = io.StringIO()
                    with (
                        mock.patch.object(validator, 'ROOT', root),
                        mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
                        contextlib.redirect_stderr(stderr),
                        self.assertRaises(SystemExit) as raised,
                    ):
                        validator.validate_rejected_chainguard_minio_candidate()

                self.assertEqual(raised.exception.code, 1)
                self.assertIn(
                    'PCS 当前 MinIO Server 状态必须为 BLOCKED',
                    stderr.getvalue(),
                )

    def test_blocked_storage_acceptance_rejects_pass_status_with_blocked_prose(
        self,
    ) -> None:
        # Would fail if the acceptance status column can mask PASS with dependency prose.
        criteria = (
            ('3', 'PG PITR 与 etcd 隔离 restore'),
            ('4', '三 bucket Versioning/Object Lock'),
            ('6', '容量与整机重启'),
        )
        for number, criterion in criteria:
            with self.subTest(criterion=number):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    path = root / 'runbook/09-acceptance.md'
                    lines = path.read_text(encoding='utf-8').splitlines()
                    for index, line in enumerate(lines):
                        if line.startswith(f'| {number} |'):
                            cells = line.split('|')
                            cells[-2] = ' PASS（忽略仍 BLOCKED 的 Flux 与 MinIO） '
                            lines[index] = '|'.join(cells)
                            break
                    else:
                        self.fail(f'missing acceptance row: {number}')
                    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn(
                    f'Flux/MinIO 仍 BLOCKED 时，{criterion} 验收状态必须为 BLOCKED',
                    stderr,
                )

    def test_rejected_chainguard_minio_candidate_contract(self) -> None:
        validator.validate_rejected_chainguard_minio_candidate()

    def test_rejected_chainguard_minio_candidate_cannot_be_activated(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            minio = root / 'infrastructure/minio'
            minio.mkdir(parents=True)
            current_pcs = root / 'candidate-2.md'
            current_pcs.write_text(
                validator.CURRENT_PCS.read_text(encoding='utf-8'),
                encoding='utf-8',
            )
            (minio / 'deployment.yaml').write_text(
                yaml.safe_dump(
                    {
                        'apiVersion': 'apps/v1',
                        'kind': 'Deployment',
                        'metadata': {'name': 'minio'},
                        'spec': {
                            'template': {
                                'spec': {
                                    'containers': [
                                        {
                                            'name': 'minio',
                                            'image': 'cgr.dev/chainguard/minio@sha256:'
                                            'c9680a1ad80b56c67b2b9e44cc480a8fd0fb4362d'
                                            'ab01f68b8bfbccae9d77596',
                                        }
                                    ]
                                }
                            }
                        },
                    }
                ),
                encoding='utf-8',
            )
            (minio / 'bootstrap-job.yaml').write_text(
                yaml.safe_dump(
                    {
                        'apiVersion': 'batch/v1',
                        'kind': 'Job',
                        'metadata': {'name': 'minio-bootstrap-v1'},
                        'spec': {
                            'template': {
                                'spec': {
                                    'containers': [
                                        {'name': 'mc', 'image': 'safe@example'}
                                    ]
                                }
                            }
                        },
                    }
                ),
                encoding='utf-8',
            )
            stderr = io.StringIO()
            with (
                mock.patch.object(validator, 'ROOT', root),
                mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                validator.validate_rejected_chainguard_minio_candidate()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn(
            'MinIO 清单引用了未获风险批准的 Chainguard 候选',
            stderr.getvalue(),
        )

    @staticmethod
    def write_release_fact_documents(
        root: Path,
        *,
        frontend_source: str = 'da72238abc87a19c07a5cac96e41d88d5f6bf2d3',
        frontend_ci_run: str = '32683635240',
        frontend_publish_job: str = '97305929974',
        frontend_tag: str = 'sha-da72238',
        frontend_provenance: str = 'VERIFIED',
        frontend_artifact: str = (
            'sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1'
        ),
        frontend_manifest: str = (
            'sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c'
        ),
        frontend_image_id: str = 'NOT_VERIFIED',
        docs_architecture_commit: str = (
            'd6d846a612c974991f4d0ffc0685d06adf2ddfe7'
        ),
        flux_status: str = 'BLOCKED',
        minio_status: str = 'BLOCKED',
        backup_status: str = 'BLOCKED',
        capacity_status: str = 'BLOCKED',
    ) -> Path:
        historical_source = 'c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c'
        historical_digest = (
            'sha256:ee548974e159916ba7ca0fafe8bb30d72722a34625ffbce31d6e495324d06c0c'
        )
        current = f'''## 事实采样

| 事实 | 值 |
| --- | --- |
| docs 架构事实提交 | `{docs_architecture_commit}` |

## 当前 frontend 候选

| 字段 | 值 |
| --- | --- |
| Source Commit | `{frontend_source}` |
| CI run | `{frontend_ci_run}` |
| publish-image job | `{frontend_publish_job}` |
| Image tag | `{frontend_tag}` |
| CI provenance | `{frontend_provenance}` |
| Artifact / OCI index digest | `{frontend_artifact}` |
| linux/amd64 manifest digest | `{frontend_manifest}` |
| Runtime Image ID | `{frontend_image_id}` |

## 2026-08-22 frontend 历史证据

| 字段 | 值 |
| --- | --- |
| Source Commit | `{historical_source}` |
| OCI index digest | `{historical_digest}` |

## 当前阻塞依赖

| 依赖 | 状态 |
| --- | --- |
| Flux | `{flux_status}` |
| MinIO | `{minio_status}` |
'''
        for relative_path in (
            'pcs/candidate-2.md',
            'runbook/06-apps.md',
            'runbook/10-image-owner-handoff.md',
        ):
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(current, encoding='utf-8')

        pcs = root / 'pcs/candidate-2.md'
        pcs.write_text(
            pcs.read_text(encoding='utf-8')
            + f'''\n| Application | engineering-platform frontend | Source `{frontend_source}` / CI run `{frontend_ci_run}`、publish-image job `{frontend_publish_job}` | `ghcr.io/unif-code/engineering-platform:{frontend_tag}`；OCI index `{frontend_artifact}` | linux/amd64 manifest `{frontend_manifest}`；Runtime Image ID `{frontend_image_id}` | verified facts |\n''',
            encoding='utf-8',
        )
        handoff = root / 'runbook/10-image-owner-handoff.md'
        handoff.write_text(
            handoff.read_text(encoding='utf-8')
            + f'''\n| 字段 | frontend | backend |\n| --- | --- | --- |\n| Source commit（完整 40 位 SHA） | `{frontend_source}` | `NOT_AVAILABLE` |\n| CI run URL | `{frontend_ci_run}` / publish-image job `{frontend_publish_job}` | `NOT_AVAILABLE` |\n| Image tag `sha-<short-sha>` | `{frontend_tag}` | `NOT_AVAILABLE` |\n| OCI index digest | `{frontend_artifact}` | `NOT_AVAILABLE` |\n| `linux/amd64` manifest digest | `{frontend_manifest}` | `NOT_AVAILABLE` |\n| Runtime Image ID | `{frontend_image_id}` | `NOT_AVAILABLE` |\n''',
            encoding='utf-8',
        )

        runtime = '''## 当前 DEV Runtime 观测

| 字段 | 值 |
| --- | --- |
| 采样时间 | `2026-08-24 03:42Z` |
| GIT_COMMIT | `1c5034b9a9c29ab72fde63644c57fa88604c45b6` |
| RESULT | `PASS_BOOTSTRAP_ALL_CHECK` |
| REASON | `bootstrap-check-complete` |
| STAGE_00 | `PASS_PREFLIGHT` |
| STAGE_00 evidence | `/root/dev-infra-evidence/07-preflight-20260824T034100Z.txt` |
| STAGE_00 SHA256 | `14e4ca38101d8aead55c5a28a19ddd495a7bb94f5b736cc432bbd8fe5d55361a` |
| STAGE_10-60 | `ALREADY_COMPLIANT` |
| STAGE_90 | `PASS_BOOTSTRAP_VERIFIED` |
| STAGE_90 evidence | `/root/dev-infra-evidence/14-verify-20260824T034246Z.txt` |
| STAGE_90 SHA256 | `0064b11860ec708491f290b7fb0594e02fcbc0737aed7674690ae1ded82ce4d5` |
| NEXT_STAGE | `NONE` |
| EXIT_CODE | `0` |
| COMMAND_EXIT_CODE | `0` |
| Namespace inventory | `cilium-secrets/default/gitlab-runner/kube-node-lease/kube-public/kube-system` |
| Pod inventory | gitlab-runner and kube-system control plane/Cilium/CoreDNS only |
| Inactive inventory | flux-system/platform/openbao absent; GitRepository query empty |
'''
        for relative_path in (
            'pcs/candidate-2.md',
            'runbook/01-bootstrap.md',
            'runbook/06-apps.md',
            'runbook/10-image-owner-handoff.md',
        ):
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                (path.read_text(encoding='utf-8') if path.exists() else '')
                + '\n'
                + runtime,
                encoding='utf-8',
            )

        plan = root / 'docs/superpowers/plans/2026-08-23-pcs-runtime-reconciliation.md'
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(
            f'''# Current docs facts

## Final reconciliation result

- docs 架构事实提交为远端可追溯的 `{docs_architecture_commit}`。

## Global Constraints

- docs 架构事实提交为 `{docs_architecture_commit}`。

| 事实 | 值 |
| --- | --- |
| docs 架构事实提交 | `{docs_architecture_commit}` |
''',
            encoding='utf-8',
        )

        acceptance = root / 'runbook/09-acceptance.md'
        acceptance.write_text(
            f'''| # | 验收标准 | 证据 | 状态 |
| --- | --- | --- | --- |
| 1 | Flux 单向 Reconcile | Flux 输出 | BLOCKED（Flux 未激活） |
| 3 | PG PITR 与 etcd 隔离 restore 各完成一次 | restore drill | {backup_status}（依赖 Flux 与 MinIO） |
| 4 | 三 bucket Versioning/Object Lock | MinIO verify | BLOCKED（MinIO 供应链阻塞） |
| 6 | 容量与重启证据 | capacity drill | {capacity_status}（依赖 Flux 与 MinIO） |
''' + '\n' + runtime,
            encoding='utf-8',
        )
        return root / 'pcs/candidate-2.md'

    def assert_main_rejects_release_fact_documents(self, root: Path) -> str:
        stderr = io.StringIO()
        current_pcs = root / 'pcs/candidate-2.md'
        with (
            mock.patch.object(validator, 'ROOT', root),
            mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
            mock.patch.object(validator, 'validate_active_root'),
            mock.patch.object(validator, 'validate_bootstrap_contracts'),
            mock.patch.object(validator, 'validate_kustomize_builds'),
            mock.patch.object(validator, 'validate_documents'),
            mock.patch.object(validator, 'validate_single_user_storage'),
            mock.patch.object(validator, 'validate_single_user_resources'),
            mock.patch.object(validator, 'validate_metrics_server'),
            mock.patch.object(
                validator, 'validate_rejected_chainguard_minio_candidate'
            ),
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            validator.main()

        self.assertEqual(raised.exception.code, 1)
        return stderr.getvalue()

    def test_current_frontend_cannot_reuse_historical_source(self) -> None:
        # Would fail if the current-candidate check stops separating dated history.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(
                root,
                frontend_source='c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 frontend Source Commit 不能复用历史', stderr)

    def test_current_frontend_duplicate_heading_is_rejected(self) -> None:
        # Would fail if a bad later candidate section is silently ignored.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(root)
            path = root / 'pcs/candidate-2.md'
            path.write_text(
                path.read_text(encoding='utf-8')
                + '''\n## 当前 frontend 候选

| 字段 | 值 |
| --- | --- |
| Source Commit | `bad-source` |
| CI provenance | `NOT_VERIFIED` |
''',
                encoding='utf-8',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('文档事实区段重复：## 当前 frontend 候选', stderr)

    def test_current_frontend_unproven_provenance_is_rejected(self) -> None:
        # Would fail if a current candidate could erase already-bound provenance.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(
                root,
                frontend_provenance='NOT_VERIFIED',
                frontend_artifact='sha256:unverified-artifact',
                frontend_manifest='NOT_VERIFIED',
                frontend_image_id='sha256:unverified-image-id',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 frontend CI provenance 必须为 VERIFIED', stderr)

    def test_current_frontend_cannot_synchronously_downgrade_provenance(
        self,
    ) -> None:
        # Would fail if all three dedicated tables can erase known provenance together.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(
                root,
                frontend_provenance='NOT_VERIFIED',
                frontend_artifact='NOT_VERIFIED',
                frontend_manifest='NOT_VERIFIED',
            )
            stderr = io.StringIO()
            with (
                mock.patch.object(validator, 'ROOT', root),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                validator.validate_current_frontend_evidence()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn('当前 frontend CI provenance 必须为 VERIFIED', stderr.getvalue())

    def test_verified_frontend_provenance_binds_published_index_only(self) -> None:
        # Would fail if a successful CI run did not bind its published index digest.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(
                root,
                frontend_provenance='VERIFIED',
                frontend_artifact='NOT_VERIFIED',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn(
            '当前 frontend Artifact / OCI index digest 与当前审计快照不一致',
            stderr,
        )

    def test_verified_frontend_manifest_requires_confirmed_amd64_digest(self) -> None:
        # Would fail if a build-log value can remain unbound after independent review.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(
                root,
                frontend_manifest='NOT_VERIFIED',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 frontend linux/amd64 manifest digest 与当前审计快照不一致', stderr)

    def test_current_frontend_release_facts_reject_single_document_mutations(
        self,
    ) -> None:
        # Would fail if any one document can drift from the confirmed release facts.
        mutations = (
            (
                'pcs/candidate-2.md',
                'Source Commit',
                'da72238abc87a19c07a5cac96e41d88d5f6bf2d3',
                'bad-source',
                '当前 frontend Source Commit',
            ),
            ('runbook/06-apps.md', 'CI run', '32683635240', '00000000000', '当前 frontend CI run'),
            (
                'runbook/10-image-owner-handoff.md',
                'publish-image job',
                '97305929974',
                '00000000000',
                '当前 frontend publish-image job',
            ),
            ('pcs/candidate-2.md', 'Image tag', 'sha-da72238', 'sha-bad', '当前 frontend Image tag'),
            (
                'runbook/06-apps.md',
                'Artifact / OCI index digest',
                'sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1',
                'sha256:bad-index',
                '当前 frontend Artifact / OCI index digest',
            ),
            (
                'pcs/candidate-2.md',
                'docs 架构事实提交',
                'd6d846a612c974991f4d0ffc0685d06adf2ddfe7',
                '6267120f345e7ad967daf08fb244c6018054281d',
                '当前 docs 架构事实提交',
            ),
        )
        for relative_path, field, expected, mutation, error in mutations:
            with self.subTest(field=field, document=relative_path):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    path = root / relative_path
                    current = path.read_text(encoding='utf-8')
                    path.write_text(
                        current.replace(
                            f'| {field} | `{expected}` |',
                            f'| {field} | `{mutation}` |',
                            1,
                        ),
                        encoding='utf-8',
                    )
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn(error, stderr)

    def test_current_docs_architecture_plan_rejects_orphan_sha(self) -> None:
        # Would fail if the current plan can retain the inaccessible sibling SHA.
        mutations = (
            'docs 架构事实提交为 `d6d846a612c974991f4d0ffc0685d06adf2ddfe7`',
            '| docs 架构事实提交 | `d6d846a612c974991f4d0ffc0685d06adf2ddfe7` |',
        )
        for expected in mutations:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    path = root / (
                        'docs/superpowers/plans/'
                        '2026-08-23-pcs-runtime-reconciliation.md'
                    )
                    path.write_text(
                        path.read_text(encoding='utf-8').replace(
                            expected,
                            expected.replace(
                                'd6d846a612c974991f4d0ffc0685d06adf2ddfe7',
                                '6267120f345e7ad967daf08fb244c6018054281d',
                            ),
                            1,
                        ),
                        encoding='utf-8',
                    )
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn('当前 docs 架构事实提交计划与已推送 main 不一致', stderr)

    def test_final_reconciliation_docs_sha_rejects_any_drift(self) -> None:
        # Would fail if a duplicate current docs fact can diverge from the constraints.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(root)
            path = root / (
                'docs/superpowers/plans/'
                '2026-08-23-pcs-runtime-reconciliation.md'
            )
            path.write_text(
                path.read_text(encoding='utf-8').replace(
                    'docs 架构事实提交为远端可追溯的 '
                    '`d6d846a612c974991f4d0ffc0685d06adf2ddfe7`',
                    'docs 架构事实提交为远端可追溯的 '
                    '`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`',
                    1,
                ),
                encoding='utf-8',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 docs 架构事实提交计划与已推送 main 不一致', stderr)

    def test_frontend_component_and_handoff_summary_rows_reject_drift(self) -> None:
        # Would fail if duplicated release facts drift outside the dedicated table.
        mutations = (
            (
                'pcs/candidate-2.md',
                '| Application | engineering-platform frontend |',
                'da72238abc87a19c07a5cac96e41d88d5f6bf2d3',
                'bad-source',
                'PCS frontend 组件表',
            ),
            (
                'runbook/10-image-owner-handoff.md',
                '| Image tag `sha-<short-sha>` |',
                'sha-da72238',
                'sha-bad',
                'Image Owner Handoff 汇总表',
            ),
        )
        documents = (
            'pcs/candidate-2.md',
            'runbook/01-bootstrap.md',
            'runbook/06-apps.md',
            'runbook/09-acceptance.md',
            'runbook/10-image-owner-handoff.md',
        )
        for relative_path, row_prefix, expected, mutation, error in mutations:
            with self.subTest(document=relative_path, row=row_prefix):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for source_relative_path in documents:
                        source = validator.ROOT / source_relative_path
                        target = root / source_relative_path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(source, target)
                    path = root / relative_path
                    lines = path.read_text(encoding='utf-8').splitlines()
                    for index, line in enumerate(lines):
                        if line.startswith(row_prefix):
                            lines[index] = line.replace(expected, mutation, 1)
                            break
                    else:
                        self.fail(f'missing summary row: {row_prefix}')
                    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn(error, stderr)

    def test_current_runtime_observation_rejects_single_document_drift(self) -> None:
        # Would fail if a stale runtime sample can coexist with the latest check.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(root)
            path = root / 'runbook/06-apps.md'
            path.write_text(
                path.read_text(encoding='utf-8').replace(
                    '| 采样时间 | `2026-08-24 03:42Z` |',
                    '| 采样时间 | `2026-08-22 16:58 +08:00` |',
                    1,
                ),
                encoding='utf-8',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 DEV Runtime 观测 采样时间 与当前审计快照不一致', stderr)

    def test_current_runtime_observation_rejects_acceptance_drift(self) -> None:
        # Would fail if the acceptance checklist can retain a stale runtime sample.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(root)
            path = root / 'runbook/09-acceptance.md'
            path.write_text(
                path.read_text(encoding='utf-8').replace(
                    '| 采样时间 | `2026-08-24 03:42Z` |',
                    '| 采样时间 | `2026-08-22 16:58 +08:00` |',
                    1,
                ),
                encoding='utf-8',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 DEV Runtime 观测 采样时间 与当前审计快照不一致', stderr)

    def test_blocked_flux_and_minio_block_backup_restore_and_capacity_acceptance(
        self,
    ) -> None:
        # Would fail if storage-dependent acceptance is relabeled PENDING.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_release_fact_documents(
                root,
                frontend_source='da72238abc87a19c07a5cac96e41d88d5f6bf2d3',
                backup_status='PENDING',
                capacity_status='PENDING',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('Flux/MinIO 仍 BLOCKED 时，PG PITR', stderr)

    def test_unknown_storage_dependency_never_allows_pending_acceptance(
        self,
    ) -> None:
        # Would fail if an unknown storage dependency bypasses the blocked gate.
        for dependency, statuses in (
            ('Flux', {'flux_status': 'NOT_VERIFIED'}),
            ('MinIO', {'minio_status': 'NOT_VERIFIED'}),
        ):
            with self.subTest(dependency=dependency):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(
                        root,
                        backup_status='PENDING',
                        capacity_status='PENDING',
                        **statuses,
                    )
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn(
                    '当前 Candidate Flux/MinIO 依赖状态必须均为 BLOCKED',
                    stderr,
                )

    def test_rejected_chainguard_minio_index_candidate_cannot_be_activated(
        self,
    ) -> None:
        # Would fail if an index digest escapes the rejected-candidate gate.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            minio = root / 'infrastructure/minio'
            minio.mkdir(parents=True)
            current_pcs = root / 'candidate-2.md'
            current_pcs.write_text(
                validator.CURRENT_PCS.read_text(encoding='utf-8'),
                encoding='utf-8',
            )
            (minio / 'deployment.yaml').write_text(
                yaml.safe_dump(
                    {
                        'apiVersion': 'apps/v1',
                        'kind': 'Deployment',
                        'metadata': {'name': 'minio'},
                        'spec': {
                            'template': {
                                'spec': {
                                    'containers': [
                                        {
                                            'name': 'minio',
                                            'image': 'cgr.dev/chainguard/minio@sha256:'
                                            'cc18cac5456a3718bde96c368beaed53b9b876233f28c5f68b8fb667b9a528a7',
                                        }
                                    ]
                                }
                            }
                        },
                    }
                ),
                encoding='utf-8',
            )
            shutil.copy(
                validator.ROOT / 'infrastructure/minio/bootstrap-job.yaml',
                minio / 'bootstrap-job.yaml',
            )
            stderr = io.StringIO()
            with (
                mock.patch.object(validator, 'ROOT', root),
                mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                validator.validate_rejected_chainguard_minio_candidate()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn('MinIO 清单引用了未获风险批准的 Chainguard 候选', stderr.getvalue())

    def test_rejected_minio_candidate_requires_exact_digest_evidence_to_activate(
        self,
    ) -> None:
        # Would fail if a mutable vendor-page claim could replace digest evidence.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            minio = root / 'infrastructure/minio'
            minio.mkdir(parents=True)
            current_pcs = root / 'candidate-2.md'
            current_pcs.write_text(
                validator.CURRENT_PCS.read_text(encoding='utf-8').replace(
                    '供应链证据：`NOT_VERIFIED`',
                    '供应链证据：`VERIFIED`',
                ),
                encoding='utf-8',
            )
            shutil.copy(
                validator.ROOT / 'infrastructure/minio/deployment.yaml',
                minio / 'deployment.yaml',
            )
            shutil.copy(
                validator.ROOT / 'infrastructure/minio/bootstrap-job.yaml',
                minio / 'bootstrap-job.yaml',
            )
            stderr = io.StringIO()
            with (
                mock.patch.object(validator, 'ROOT', root),
                mock.patch.object(validator, 'CURRENT_PCS', current_pcs),
                contextlib.redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                validator.validate_rejected_chainguard_minio_candidate()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn('MinIO 被拒候选缺少精确 digest 供应链证据', stderr.getvalue())

    def test_single_user_resource_contract(self) -> None:
        self.assertEqual(validate_single_user_resources(), (1115, 2720))

    def test_single_user_storage_contract(self) -> None:
        validate_single_user_storage()

    def test_validation_and_orchestrator_are_documented(self) -> None:
        agents = (validator.ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        readme = (validator.ROOT / 'README.md').read_text(encoding='utf-8')
        runbook = (validator.ROOT / 'runbook/01-bootstrap.md').read_text(
            encoding='utf-8'
        )

        self.assert_documentation_contract(agents, readme, runbook)

    def test_validation_contract_rejects_reversed_governance(self) -> None:
        agents = (validator.ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        readme = (validator.ROOT / 'README.md').read_text(encoding='utf-8')
        runbook = (validator.ROOT / 'runbook/01-bootstrap.md').read_text(
            encoding='utf-8'
        )

        mutations = {
            'local-pre-commit': (
                agents,
                '本地提交前运行受影响的 focused tests 和 '
                '`./scripts/validate-fast.sh`',
                '本地提交后才运行受影响的 focused tests 和 '
                '`./scripts/validate-fast.sh`',
            ),
            'push-gate-before-deployment': (
                agents,
                '普通 push 后必须等待 GitHub `validation-gate` 全部通过，'
                '才可继续服务器部署或验收',
                '普通 push 后无需等待 GitHub `validation-gate` 全部通过，'
                '即可继续服务器部署或验收',
            ),
        }

        self.assertTrue(
            hasattr(self, 'assert_documentation_contract'),
            'strict documentation contract helper is required',
        )
        for label, (document, old, new) in mutations.items():
            with self.subTest(contract=label):
                self.assertEqual(document.count(old), 1)
                for mutation, replacement in (
                    ('reversed', new),
                    ('deleted', ''),
                ):
                    with self.subTest(contract=label, mutation=mutation):
                        mutated_agents = document.replace(old, replacement, 1)
                        with self.assertRaisesRegex(AssertionError, label):
                            self.assert_documentation_contract(
                                mutated_agents,
                                readme,
                                runbook,
                                (label,),
                            )

    def test_orchestrator_contract_rejects_reversed_semantics(self) -> None:
        agents = (validator.ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        readme = (validator.ROOT / 'README.md').read_text(encoding='utf-8')
        runbook = (validator.ROOT / 'runbook/01-bootstrap.md').read_text(
            encoding='utf-8'
        )

        mutations = {
            'check-read-only-stop-first-apply-required': (
                '`--check` 全程只读，在第一个需要 APPLY 的 stage 停止，'
                '不执行任何 APPLY',
                '`--check` 不是只读，不在第一个需要 APPLY 的 stage 停止，'
                '允许执行 APPLY',
            ),
            'apply-check-skip-post-check': (
                '`--apply` 会先检查每个 stage，跳过返回 '
                '`ALREADY_COMPLIANT` 的 stage，仅对需要变更的\n'
                'stage 执行 apply，并要求 apply 后的 post-check 回到 compliant',
                '`--apply` 不会先检查每个 stage，也不跳过返回 '
                '`ALREADY_COMPLIANT` 的 stage，可对不需要变更的\n'
                'stage 执行 apply，且不要求 apply 后的 post-check 回到 compliant',
            ),
            'resume-real-state-no-progress-file': (
                '重跑同一条命令即可恢复：orchestrator 根据真实主机状态重建进度，'
                '不读取或维护 progress file',
                '不重跑同一条命令也可恢复：orchestrator 不根据真实主机状态重建进度，'
                '而是读取 progress file',
            ),
            'current-server-completed-all-stages': (
                '当前服务器已完成全部 stage `00`～`90`。GitHub '
                '`validation-gate` 成功后重跑\n'
                'orchestrator，它必须依据各 stage 的检查结果跳过这些已完成 stage，'
                '并直接抵达 stage `90`',
                '当前服务器尚未完成全部 stage `00`～`90`。GitHub '
                '`validation-gate` 成功前重跑\n'
                'orchestrator，它必须从 stage `00` 继续，不能直接抵达 stage `90`',
            ),
            'individual-stages-emergency-only': (
                '下表保留为诊断和人工应急入口，不是正常 bootstrap 路径',
                '下表不是诊断和人工应急入口，而是正常 bootstrap 路径',
            ),
            'stage-50-success-alternatives': (
                '| 12 | `stages/50-kubeadm-init/run.sh` | `--check` 后批准 `--apply` | '
                '`PASS_KUBEADM_INITIALIZED` 或 `ALREADY_COMPLIANT` |',
                '| 12 | `stages/50-kubeadm-init/run.sh` | `--check` 后批准 `--apply` | '
                '不是 `PASS_KUBEADM_INITIALIZED` 或 `ALREADY_COMPLIANT` |',
            ),
        }

        self.assertTrue(
            hasattr(self, 'assert_documentation_contract'),
            'strict documentation contract helper is required',
        )
        for label, (old, new) in mutations.items():
            with self.subTest(contract=label):
                self.assertEqual(runbook.count(old), 1)
                for mutation, replacement in (
                    ('reversed', new),
                    ('deleted', ''),
                ):
                    with self.subTest(contract=label, mutation=mutation):
                        mutated_runbook = runbook.replace(old, replacement, 1)
                        with self.assertRaisesRegex(AssertionError, label):
                            self.assert_documentation_contract(
                                agents,
                                readme,
                                mutated_runbook,
                                (label,),
                            )


class ActiveRootIsolationTest(unittest.TestCase):
    def make_root(self, resources: list[str]) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        cluster = root / 'clusters' / 'dev'
        cluster.mkdir(parents=True)
        (cluster / 'kustomization.yaml').write_text(
            yaml.safe_dump(
                {
                    'apiVersion': 'kustomize.config.k8s.io/v1beta1',
                    'kind': 'Kustomization',
                    'resources': resources,
                },
                sort_keys=False,
            ),
            encoding='utf-8',
        )
        return root

    def test_active_root_rejects_staged_entrypoint(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_active_root'),
            'validate_active_root must enforce the active-root allowlist',
        )
        root = self.make_root(['flux-system', 'apps.yaml'])

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validator.validate_active_root(root)

    def test_active_root_accepts_flux_only(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_active_root'),
            'validate_active_root must enforce the active-root allowlist',
        )
        root = self.make_root(['flux-system'])

        validator.validate_active_root(root)

    def test_repository_inactive_entrypoints_are_annotated(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_active_root'),
            'validate_active_root must validate inactive audit headers',
        )

        validator.validate_active_root(validator.ROOT)


class BootstrapContractTest(unittest.TestCase):
    def assert_contract_fails(self, root: Path) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_bootstrap_contracts'),
            'validate_bootstrap_contracts must enforce locked bootstrap inputs',
        )
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validator.validate_bootstrap_contracts(root)

    def copy_bootstrap_root(self) -> Path:
        self.assertTrue(
            (validator.ROOT / 'bootstrap').is_dir(),
            'bootstrap contracts must exist before mutation tests can run',
        )
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        shutil.copytree(validator.ROOT / 'bootstrap', root / 'bootstrap')
        return root

    def test_repository_bootstrap_contracts(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_bootstrap_contracts'),
            'validate_bootstrap_contracts must enforce locked bootstrap inputs',
        )

        validator.validate_bootstrap_contracts(validator.ROOT)

    def test_artifact_lock_rejects_floating_version(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'artifacts.lock.tsv'
        path.write_text(
            path.read_text(encoding='utf-8').replace(
                'containerd\t2.3.1\t', 'containerd\tlatest\t', 1
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)


    def test_artifact_lock_accepts_six_records_without_cni_archive(self) -> None:
        """捕获 validator 继续要求 Task 5 拥有 CNI archive 的缺陷。"""
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'artifacts.lock.tsv'
        path.write_text(
            ''.join(
                line
                for line in path.read_text(encoding='utf-8').splitlines(True)
                if not line.startswith('cni-plugins\t')
            ),
            encoding='utf-8',
        )

        validator.validate_bootstrap_contracts(root)

    def test_artifact_lock_rejects_cni_archive_reintroduced(self) -> None:
        """捕获重新引入 CNI release artifact、恢复双重 ownership 的缺陷。"""
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'artifacts.lock.tsv'
        with path.open('a', encoding='utf-8') as stream:
            stream.write(
                'cni-plugins\t1.9.1\t'
                'https://github.com/containernetworking/plugins/releases/'
                'download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz\t'
                'b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303\t'
                '/opt/cni/bin\n'
            )

        self.assert_contract_fails(root)

    def test_artifact_lock_rejects_five_records_without_crictl(self) -> None:
        """捕获移除 CNI 后又遗漏 crictl 的 supply-chain 缺陷。"""
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'artifacts.lock.tsv'
        path.write_text(
            ''.join(
                line
                for line in path.read_text(encoding='utf-8').splitlines(True)
                if not line.startswith(('cni-plugins\t', 'crictl\t'))
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    def test_artifact_lock_accepts_exact_locked_crictl_record(self) -> None:
        """捕获把六项合同中的 crictl 误判为 unexpected artifact 的缺陷。"""
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'artifacts.lock.tsv'
        path.write_text(
            ''.join(
                line
                for line in path.read_text(encoding='utf-8').splitlines(True)
                if not line.startswith(('cni-plugins\t', 'crictl\t'))
            ),
            encoding='utf-8',
        )
        with path.open('a', encoding='utf-8') as stream:
            stream.write(
                'crictl\t1.36.0\t'
                'https://github.com/kubernetes-sigs/cri-tools/releases/'
                'download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz\t'
                '83855e114566a8a8c44c548d515670f51de3a5e1da8b2effb59870e2f10c25a3\t'
                '/usr/local/bin/crictl\n'
            )

        validator.validate_bootstrap_contracts(root)

    def test_containerd_contract_rejects_non_systemd_cgroup(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'containerd' / 'config.toml'
        path.write_text(
            path.read_text(encoding='utf-8').replace(
                'SystemdCgroup = true', 'SystemdCgroup = false', 1
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    def test_kubeadm_contract_rejects_pod_cidr_drift(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml'
        path.write_text(
            path.read_text(encoding='utf-8').replace(
                '172.21.0.0/16', '10.244.0.0/16', 1
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    def test_cilium_contract_rejects_disabled_kube_proxy_replacement(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap/hosts/retail-test-workflow/cilium-values.yaml'
        path.write_text(
            path.read_text(encoding='utf-8').replace(
                'kubeProxyReplacement: true', 'kubeProxyReplacement: false', 1
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    HOST_DIR = Path('bootstrap/hosts/retail-test-workflow')

    def rewrite_host_env(self, root: Path, old: str, new: str) -> None:
        path = root / self.HOST_DIR / 'host.env'
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding='utf-8')

    def test_host_env_is_parsed_strictly(self) -> None:
        root = self.copy_bootstrap_root()
        parsed = validator.parse_host_env(root / self.HOST_DIR / 'host.env')

        self.assertEqual(parsed['HOST_NAME'], 'retail-test-workflow')
        self.assertEqual(parsed['HOST_NODE_IP'], '10.93.1.27')
        self.assertEqual(sorted(parsed), sorted(validator.HOST_ENV_KEYS))

    def test_host_env_drift_is_rejected(self) -> None:
        cases = (
            ('missing-key', 'HOST_SWAP_FILE=/swap.img\n', ''),
            ('extra-key', 'HOST_SWAP_MAX_BYTES=4400000000\n',
             'HOST_SWAP_MAX_BYTES=4400000000\nHOST_EXTRA=1\n'),
            ('duplicate-key', 'HOST_NODE_IP=10.93.1.27\n',
             'HOST_NODE_IP=10.93.1.27\nHOST_NODE_IP=10.93.1.27\n'),
            ('bad-ip', 'HOST_NODE_IP=10.93.1.27', 'HOST_NODE_IP=10.93.1.256'),
            ('bad-cidr', 'HOST_POD_CIDR=172.21.0.0/16', 'HOST_POD_CIDR=172.21.0.1/16'),
            ('quoted', 'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE="/swap.img"'),
            ('swap-range', 'HOST_SWAP_MAX_BYTES=4400000000', 'HOST_SWAP_MAX_BYTES=1'),
            ('name-mismatch', 'HOST_NAME=retail-test-workflow', 'HOST_NAME=other-host'),
        )
        for name, old, new in cases:
            with self.subTest(case=name):
                root = self.copy_bootstrap_root()
                self.rewrite_host_env(root, old, new)
                self.assert_contract_fails(root)

    def test_host_env_without_trailing_newline_is_rejected(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / self.HOST_DIR / 'host.env'
        path.write_text(path.read_text(encoding='utf-8').rstrip('\n'), encoding='utf-8')

        self.assert_contract_fails(root)

    def test_host_yaml_must_match_host_env(self) -> None:
        cases = (
            ('kubeadm-init.yaml', '10.93.1.27', '10.93.1.28'),
            ('kubeadm-init.yaml', 'clusterName: engineering-platform-dev', 'clusterName: other'),
            ('kubeadm-init.yaml', 'name: retail-test-workflow', 'name: other-host'),
            ('cilium-values.yaml', 'k8sServiceHost: 10.93.1.27', 'k8sServiceHost: 10.93.1.28'),
        )
        for filename, old, new in cases:
            with self.subTest(file=filename, old=old):
                root = self.copy_bootstrap_root()
                path = root / self.HOST_DIR / filename
                text = path.read_text(encoding='utf-8')
                self.assertIn(old, text)
                path.write_text(text.replace(old, new), encoding='utf-8')
                # 同步 pins，确保失败来自一致性校验而非 digest 校验。
                subprocess.run(
                    ['/bin/bash', str(validator.ROOT / 'scripts/bootstrap/pin-host.sh'),
                     str(root / self.HOST_DIR)],
                    check=True, capture_output=True,
                )

                self.assert_contract_fails(root)

    def repin_host(self, root: Path) -> None:
        subprocess.run(
            ['/bin/bash', str(validator.ROOT / 'scripts/bootstrap/pin-host.sh'),
             str(root / self.HOST_DIR)],
            check=True, capture_output=True,
        )

    def test_host_cilium_values_must_match_locked_skeleton(self) -> None:
        """结构化断言之外，cilium-values.yaml 必须与锁死骨架逐字一致。"""
        original = (validator.ROOT / self.HOST_DIR / 'cilium-values.yaml').read_text(
            encoding='utf-8'
        )
        node_ip = validator.parse_host_env(
            validator.ROOT / self.HOST_DIR / 'host.env'
        )['HOST_NODE_IP']
        validator.validate_bootstrap_contracts(self.copy_bootstrap_root())
        cases = (
            (
                'extra-blank-line',
                original.replace(
                    'k8sServicePort: 6443\n', 'k8sServicePort: 6443\n\n', 1
                ),
            ),
            ('comment', '# 说明：这行不该被接受\n' + original),
            (
                'reordered-keys',
                original.replace(
                    f'k8sServiceHost: {node_ip}\nk8sServicePort: 6443\n',
                    f'k8sServicePort: 6443\nk8sServiceHost: {node_ip}\n',
                    1,
                ),
            ),
        )
        for name, content in cases:
            with self.subTest(case=name):
                self.assertNotEqual(content, original)
                root = self.copy_bootstrap_root()
                (root / self.HOST_DIR / 'cilium-values.yaml').write_text(
                    content, encoding='utf-8'
                )
                # 同步 pins，确保失败来自骨架比对而非 digest 校验。
                self.repin_host(root)

                self.assert_contract_fails(root)

    def test_pins_must_match_files(self) -> None:
        root = self.copy_bootstrap_root()
        pins = root / self.HOST_DIR / 'pins.sha256'
        pins.write_text(
            pins.read_text(encoding='utf-8').replace('e37b38f1', '00000000', 1),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    def test_pins_must_be_readable_utf8(self) -> None:
        """非 UTF-8 的 pins 必须走 fail()，而不是抛未捕获的解码异常。"""
        root = self.copy_bootstrap_root()
        (root / self.HOST_DIR / 'pins.sha256').write_bytes(b'\xff\xfe pins\n')

        self.assert_contract_fails(root)

    def test_pins_shape_is_exact(self) -> None:
        good = (validator.ROOT / self.HOST_DIR / 'pins.sha256').read_text(encoding='utf-8')
        for name, content in (
            ('reversed', ''.join(reversed(good.splitlines(keepends=True)))),
            ('third-line', good + 'x\n'),
            ('single-space', good.replace('  kubeadm', ' kubeadm', 1)),
            ('no-newline', good.rstrip('\n')),
        ):
            with self.subTest(case=name):
                root = self.copy_bootstrap_root()
                (root / self.HOST_DIR / 'pins.sha256').write_text(content, encoding='utf-8')
                self.assert_contract_fails(root)

    def test_host_directory_file_set_is_exact(self) -> None:
        for name in ('extra-file', 'missing-file', 'symlinked-file', 'legacy-directory'):
            with self.subTest(case=name):
                root = self.copy_bootstrap_root()
                host_dir = root / self.HOST_DIR
                if name == 'extra-file':
                    (host_dir / 'notes.txt').write_text('x\n', encoding='utf-8')
                elif name == 'missing-file':
                    (host_dir / 'pins.sha256').unlink()
                elif name == 'symlinked-file':
                    (host_dir / 'host.env').unlink()
                    (host_dir / 'host.env').symlink_to(root / 'outside.env')
                    (root / 'outside.env').write_text('HOST_NAME=x\n', encoding='utf-8')
                else:
                    (root / 'bootstrap/kubeadm').mkdir()
                    (root / 'bootstrap/kubeadm/init.yaml').write_text('x\n', encoding='utf-8')
                self.assert_contract_fails(root)

    def test_pin_host_tool_rewrites_only_pins(self) -> None:
        root = self.copy_bootstrap_root()
        host_dir = root / self.HOST_DIR
        (host_dir / 'pins.sha256').write_text('broken\n', encoding='utf-8')
        before = {p.name: p.read_bytes() for p in host_dir.iterdir() if p.name != 'pins.sha256'}

        result = subprocess.run(
            ['/bin/bash', str(validator.ROOT / 'scripts/bootstrap/pin-host.sh'), str(host_dir)],
            capture_output=True, text=True, check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (host_dir / 'pins.sha256').read_text(encoding='utf-8'),
            (validator.ROOT / self.HOST_DIR / 'pins.sha256').read_text(encoding='utf-8'),
        )
        self.assertEqual({p.name: p.read_bytes() for p in host_dir.iterdir() if p.name != 'pins.sha256'}, before)
        self.assertEqual(oct((host_dir / 'pins.sha256').stat().st_mode & 0o777), '0o644')
        validator.validate_bootstrap_contracts(root)

    def test_pin_host_tool_aborts_when_digest_fails(self) -> None:
        """digest 计算失败必须中止，而不是写入空 digest 的 pins。"""
        root = self.copy_bootstrap_root()
        host_dir = root / self.HOST_DIR
        before = (host_dir / 'pins.sha256').read_bytes()
        fake_bin = root / 'bin'
        fake_bin.mkdir()
        for name in ('sha256sum', 'shasum'):
            tool = fake_bin / name
            tool.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
            tool.chmod(0o755)
        environment = dict(os.environ)
        environment['PATH'] = f'{fake_bin}:{environment["PATH"]}'

        result = subprocess.run(
            ['/bin/bash', str(validator.ROOT / 'scripts/bootstrap/pin-host.sh'),
             str(host_dir)],
            capture_output=True, text=True, check=False, env=environment,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual((host_dir / 'pins.sha256').read_bytes(), before)
        self.assertEqual(
            sorted(entry.name for entry in host_dir.iterdir()),
            sorted(validator.HOST_FILES),
        )


class ValidateEntrypointTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for entrypoint in (
            'validation_catalog.py',
            'run_validation.py',
            'validate-static.sh',
            'validate-fast.sh',
            'validate.sh',
        ):
            shutil.copy2(validator.ROOT / 'scripts' / entrypoint, scripts)

        # validate-static.sh 递归收集 scripts/bootstrap 下的 shell 脚本；fixture 必须
        # 建出这个目录，否则 find 报错、静态入口整体失败，而那与被测契约无关。
        bootstrap = scripts / 'bootstrap'
        bootstrap.mkdir()
        (bootstrap / 'sample.sh').write_text(
            '#!/bin/bash\nset -Eeuo pipefail\n', encoding='utf-8'
        )

        self.command_log = self.root / 'commands.log'
        self.fake_bin = self.root / 'bin'
        self.fake_bin.mkdir()
        self.write_fake(
            'python3',
            '''#!/bin/bash
set -eu
{
  printf 'python3'
  printf '\\t%s' "$@"
  printf '\\n'
  printf 'ENV_NAMES=%s\\n' "$(env | sed 's/=.*//' | sort | tr '\\n' ',')"
} >>"$VALIDATE_COMMAND_LOG"
case " $* " in
  *"run_validation.py --profile "*) exit "${FAKE_RUNNER_EXIT:-0}" ;;
esac
exit 0
''',
        )
        self.write_fake(
            'shellcheck',
            '''#!/bin/bash
set -eu
{
  printf 'shellcheck'
  printf '\\t%s' "$@"
  printf '\\n'
} >>"$VALIDATE_COMMAND_LOG"
exit "${FAKE_SHELLCHECK_EXIT:-0}"
''',
        )
        self.write_fake('kubectl', '#!/bin/bash\nexit 0\n')

    def write_fake(self, name: str, content: str) -> None:
        path = self.fake_bin / name
        path.write_text(content, encoding='utf-8')
        path.chmod(0o755)

    def run_validate(
        self,
        entrypoint: str = 'validate.sh',
        *,
        runner_exit: int = 0,
        shellcheck_exit: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        # 从白名单起手，绝不整体继承调用者的 shell：入口必须自己保证不把任何
        # stage 会拒绝的变量交给套件，而调用者环境里若已有同名变量（例如本套件
        # 正被打补丁前的 validate-fast.sh 启动），就看不出入口是否泄漏。
        environment = {
            'FAKE_RUNNER_EXIT': str(runner_exit),
            'FAKE_SHELLCHECK_EXIT': str(shellcheck_exit),
            'PATH': f'{self.fake_bin}:/usr/bin:/bin',
            'VALIDATE_COMMAND_LOG': str(self.command_log),
        }
        if 'TMPDIR' in os.environ:
            environment['TMPDIR'] = os.environ['TMPDIR']
        return subprocess.run(
            ['/bin/bash', str(self.root / 'scripts' / entrypoint)],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def read_command_log(self) -> str:
        return self.command_log.read_text(encoding='utf-8')

    def test_runner_failure_stops_validation_without_apply(self) -> None:
        result = self.run_validate(runner_exit=23)

        self.assertEqual(result.returncode, 23, result.stdout + result.stderr)
        command_log = self.read_command_log()
        self.assertIn('run_validation.py\t--profile\tfull', command_log)
        self.assertNotIn('shellcheck', command_log)
        self.assertNotIn('--apply', command_log)

    def test_shellcheck_failure_stops_validation_without_apply(self) -> None:
        result = self.run_validate(shellcheck_exit=24)

        self.assertEqual(result.returncode, 24, result.stdout + result.stderr)
        command_log = self.read_command_log()
        self.assertIn('run_validation.py\t--profile\tfull', command_log)
        self.assertIn('shellcheck\t', command_log)
        self.assertNotIn('--apply', command_log)

    def test_entrypoints_never_export_python_env_to_the_suite(self) -> None:
        """捕获入口用环境变量而非 -B 关闭字节码写入的缺陷。

        `PYTHONDONTWRITEBYTECODE=1 python3 …` 是前缀赋值，会被导出并一路继承进
        用例派生的 stage 子进程。stage 60/90 的不可信环境守卫含 `${!PYTHON@}`
        前缀通配且排在测试变量守卫之前，于是
        `BootstrapEntrySecurityTest.test_production_rejects_all_test_overrides_before_lookup`
        在本地恒红两条、而 CI 全绿（CI 直接调 run_validation.py，不经过入口）。
        `-B` 效果相同但只作用于本进程、不进环境。
        """
        for entrypoint in ('validate.sh', 'validate-fast.sh', 'validate-static.sh'):
            with self.subTest(entrypoint=entrypoint):
                self.command_log.write_text('', encoding='utf-8')

                result = self.run_validate(entrypoint)

                command_log = self.read_command_log()
                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )
                lines = command_log.splitlines()
                python_calls = [
                    (lines[index], lines[index + 1])
                    for index in range(len(lines) - 1)
                    if lines[index].startswith('python3\t')
                    and lines[index + 1].startswith('ENV_NAMES=')
                ]
                self.assertTrue(python_calls, '入口没有调用 python3')
                # 按**名字**判定而不是盯某个具名变量的某个值：stage 守卫按名字
                # （含 HELM_/PYTHON/OPENSSL_/KUBECTL_ 四组前缀通配）判死，与值无关。
                # 早先只记录 PYTHONDONTWRITEBYTECODE 且断言它等于某值，于是改泄漏
                # PYTHONPATH、或把值写成 =0，两条用例都照绿（独立评审实测）。
                names, prefixes = (
                    BootstrapTestCase.untrusted_environment_guard()
                )
                self.assertGreaterEqual(len(names), 20, '守卫清单解析异常')
                self.assertGreaterEqual(len(prefixes), 5, '前缀通配解析异常')
                for argv, env_names in python_calls:
                    with self.subTest(call=argv):
                        self.assertEqual(
                            argv.split('\t')[1], '-B',
                            f'{entrypoint} 的 python3 调用缺少 -B: {argv}',
                        )
                        seen = set(
                            env_names[len('ENV_NAMES='):].strip(',').split(',')
                        )
                        # 前缀匹配，不是集合求交：守卫按 PYTHON*/HELM_* 这样的
                        # 前缀判死，示例名集合抓不到 PYTHONPATH 这类真实泄漏。
                        self.assertEqual(
                            BootstrapTestCase.environment_names_stages_reject(
                                seen
                            ),
                            [],
                            f'{entrypoint} 把 stage 会拒绝的变量交给了套件',
                        )

    def test_fast_entrypoint_runs_fast_profile_without_apply(self) -> None:
        result = self.run_validate('validate-fast.sh')

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        command_log = self.read_command_log()
        self.assertIn('run_validation.py\t--profile\tfast', command_log)
        self.assertNotIn('--apply', command_log)


class ValidationCatalogTest(unittest.TestCase):
    def test_github_workflow_never_exports_python_env_to_the_suite(self) -> None:
        """捕获 CI 用环境变量而非 -B 关闭字节码写入的缺陷。

        job 级 `env: PYTHONDONTWRITEBYTECODE` 会被导出并继承进用例派生的 stage
        子进程，撞上 stage 60/90 的 `${!PYTHON@}` 不可信环境守卫（它排在测试变量
        守卫之前），把 BootstrapEntrySecurityTest 的两个子用例判成假红——2026-08-19
        的 3f080d4 就是这样让 tests (contracts) 全红的。三个本地入口已改用 -B，
        CI 是同一缺陷的第四个调用方。
        """
        workflow_path = validator.ROOT / '.github/workflows/validate.yml'
        workflow_text = workflow_path.read_text(encoding='utf-8')
        document = yaml.load(workflow_text, Loader=yaml.BaseLoader)

        def exported_names(node: object) -> Iterator[str]:
            """逐层收集所有 env: 映射的键名。"""
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == 'env' and isinstance(value, dict):
                        yield from value
                    yield from exported_names(value)
            elif isinstance(node, list):
                for item in node:
                    yield from exported_names(item)

        # 断言的是"没有任何 job 把它设成环境变量"，不是"这个词不许出现"——
        # 否则连解释为何用 -B 的注释都写不了。
        exported = sorted(set(exported_names(document)))
        # 非空转守卫：这条 YAML 递归是唯一能抓"run: 带 -B 但 job 级 env: 仍设了它"
        # 这一形态的探测器。解析一旦失灵（把 'env' 键名写错即可），缺陷原样加回去
        # 也会绿（独立评审实测）。先钉住它确实解析到了东西。
        self.assertIn('PLAN_RESULT', exported, exported)
        self.assertGreaterEqual(len(exported), 5, exported)
        self.assertNotIn('PYTHONDONTWRITEBYTECODE', exported)
        # 另一种泄漏形态：run: 里的前缀赋值，同样会被导出。
        for line in workflow_text.splitlines():
            with self.subTest(line=line.strip()):
                self.assertNotIn('PYTHONDONTWRITEBYTECODE=', line)
        suite_calls = [
            line.strip() for line in workflow_text.splitlines()
            if 'run_validation.py' in line
        ]
        self.assertTrue(suite_calls, 'workflow 未调用 run_validation.py')
        for line in suite_calls:
            with self.subTest(line=line):
                self.assertIn('python3 -B scripts/run_validation.py', line)

    def test_github_workflow_has_dynamic_full_gate(self) -> None:
        """捕获 CI 未执行完整动态分片验证或未聚合其结果的缺陷。"""
        workflow_path = validator.ROOT / '.github/workflows/validate.yml'
        self.assertTrue(workflow_path.is_file())
        document = yaml.load(
            workflow_path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader
        )
        self.assertEqual(document['permissions'], {'contents': 'read'})
        self.assertEqual(document['on']['push']['branches'], ['main'])
        self.assertEqual(document['on']['pull_request']['branches'], ['main'])
        self.assertIn('workflow_dispatch', document['on'])
        self.assertEqual(
            set(document['jobs']),
            {'plan', 'tests', 'static', 'validation-gate', 'publish-validated'},
        )
        self.assertEqual(
            set(document['jobs']['validation-gate']['needs']),
            {'plan', 'tests', 'static'},
        )
        gate = document['jobs']['validation-gate']
        self.assertIn('if', gate)
        self.assertEqual(gate['if'], '${{ always() }}')
        gate_environment = gate['steps'][0]['env']
        self.assertEqual(
            gate_environment,
            {
                'PLAN_RESULT': '${{ needs.plan.result }}',
                'TESTS_RESULT': '${{ needs.tests.result }}',
                'STATIC_RESULT': '${{ needs.static.result }}',
            },
        )
        gate_command = gate['steps'][0]['run']
        self.assertIn('test "$PLAN_RESULT" = success', gate_command)
        self.assertIn('test "$TESTS_RESULT" = success', gate_command)
        self.assertIn('test "$STATIC_RESULT" = success', gate_command)
        for job in document['jobs'].values():
            self.assertEqual(job['runs-on'], 'ubuntu-24.04')
        self.assertEqual(document['jobs']['tests']['strategy']['fail-fast'], 'false')
        self.assertEqual(document['jobs']['tests']['timeout-minutes'], '45')
        workflow_text = workflow_path.read_text(encoding='utf-8')
        self.assertIn('fromJSON(needs.plan.outputs.matrix)', workflow_text)
        self.assertIn(
            'actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10',
            workflow_text,
        )
        self.assertNotRegex(workflow_text, r'uses:\s+[^\s]+@(main|master|v\d+)\s*$')

    def test_github_workflow_publishes_validated_ref_least_privilege(self) -> None:
        """捕获 validated 引用被未过门禁的提交、非 main 事件或过宽权限污染的缺陷。"""
        workflow_path = validator.ROOT / '.github/workflows/validate.yml'
        document = yaml.load(
            workflow_path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader
        )
        publish = document['jobs']['publish-validated']
        self.assertEqual(set(publish['needs']), {'validation-gate'})
        self.assertEqual(
            publish['if'],
            "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}",
        )
        self.assertEqual(publish['permissions'], {'contents': 'write'})
        for name, job in document['jobs'].items():
            if name == 'publish-validated':
                continue
            self.assertNotIn(
                'permissions', job, f'{name} must inherit read-only permissions'
            )
        step = publish['steps'][0]
        self.assertEqual(len(publish['steps']), 1, 'write-token job stays minimal')
        self.assertNotIn('uses', step, 'never check out source under a write token')
        self.assertEqual(
            step['env'],
            {
                'GH_TOKEN': '${{ github.token }}',
                'GATED_SHA': '${{ github.sha }}',
                'TARGET_REPOSITORY': '${{ github.repository }}',
            },
        )
        command = step['run']
        self.assertIn('refs/heads/validated', command)
        self.assertIn('"$GATED_SHA"', command)
        self.assertNotIn('github.ref_name', command)
        self.assertIn('force=false', command)

    def test_every_workflow_declares_read_only_default_permissions(self) -> None:
        """仓库默认令牌放开为写之后，捕获任何 workflow 静默继承写权限的缺陷。"""
        workflow_directory = validator.ROOT / '.github/workflows'
        workflows = sorted(
            path
            for path in workflow_directory.iterdir()
            if path.suffix in {'.yml', '.yaml'}
        )
        self.assertTrue(workflows)
        for path in workflows:
            document = yaml.load(
                path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader
            )
            self.assertEqual(
                document.get('permissions'),
                {'contents': 'read'},
                f'{path.name} must pin read-only default permissions',
            )
            for name, job in document['jobs'].items():
                declared = job.get('permissions')
                if declared is None:
                    continue
                self.assertEqual(
                    (path.name, name, declared),
                    ('validate.yml', 'publish-validated', {'contents': 'write'}),
                    'only the validated-ref publisher may hold a write token',
                )

    def test_static_workflow_pins_python_validation_dependency(self) -> None:
        """捕获 static 验证依赖 runner 预装 PyYAML 的缺陷。"""
        workflow_path = validator.ROOT / '.github/workflows/validate.yml'
        document = yaml.load(
            workflow_path.read_text(encoding='utf-8'), Loader=yaml.BaseLoader
        )
        static_steps = document['jobs']['static']['steps']
        python_steps = [
            step
            for step in static_steps
            if step.get('name') == 'Install Python validation dependency'
        ]
        self.assertEqual(len(python_steps), 1)
        install_command = python_steps[0]['run']

        self.assertIn(
            'python3 -m venv "$RUNNER_TEMP/validation-venv"', install_command
        )
        self.assertIn('PyYAML==6.0.3', install_command)
        self.assertIn(
            'echo "$RUNNER_TEMP/validation-venv/bin" >>"$GITHUB_PATH"',
            install_command,
        )

    def test_catalog_covers_every_concrete_test_case_once(self) -> None:
        import validation_catalog

        validation_catalog.validate_catalog()

    def test_fast_profile_excludes_heavy_bootstrap_classes(self) -> None:
        import validation_catalog

        selectors = set(validation_catalog.selectors_for_profile('fast'))
        heavy = {
            'test_bootstrap.ArtifactStageTest',
            'test_bootstrap.KernelStageTest',
            'test_bootstrap.ContainerdInstallTest',
            'test_bootstrap.KubernetesInstallTest',
            'test_bootstrap.KubeadmInitTest',
            'test_bootstrap.CiliumInstallTest',
            'test_bootstrap.FinalVerifyTest',
        }
        self.assertTrue(selectors)
        self.assertTrue(selectors.isdisjoint(heavy))

    def test_fast_profile_uses_focused_contract_smoke_selectors(self) -> None:
        import validation_catalog

        selectors = set(validation_catalog.selectors_for_profile('fast'))
        self.assertNotIn('test_bootstrap.PreflightTest', selectors)
        self.assertNotIn('test_bootstrap.BootstrapOrchestratorTest', selectors)
        self.assertIn(
            'test_bootstrap.PreflightTest.'
            'test_stage30_owned_runtime_footprint_does_not_fail_preflight',
            selectors,
        )
        self.assertIn(
            'test_bootstrap.BootstrapOrchestratorTest.'
            'test_check_resumes_from_every_legal_checkpoint',
            selectors,
        )
        contract_classes = set(validation_catalog.SHARDS['contracts'])
        self.assertTrue(
            all('.'.join(selector.split('.')[:2]) in contract_classes
                for selector in selectors)
        )

    def test_catalog_rejects_missing_and_duplicate_selectors(self) -> None:
        import validation_catalog
        from unittest import mock

        missing = dict(validation_catalog.SHARDS)
        missing['contracts'] = missing['contracts'][1:]
        with mock.patch.object(validation_catalog, 'SHARDS', missing):
            with self.assertRaisesRegex(ValueError, 'missing'):
                validation_catalog.validate_catalog()

        duplicate = dict(validation_catalog.SHARDS)
        duplicate['artifacts'] = (
            *duplicate['artifacts'], duplicate['contracts'][0]
        )
        with mock.patch.object(validation_catalog, 'SHARDS', duplicate):
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                validation_catalog.validate_catalog()

    def test_catalog_rejects_invalid_fast_selectors(self) -> None:
        import validation_catalog
        from unittest import mock

        original = validation_catalog.FAST_SELECTORS
        cases = (
            ('duplicate', (*original, original[0]), 'fast_duplicate'),
            (
                'unknown-method',
                (*original, 'test_bootstrap.PreflightTest.test_missing'),
                'fast_unknown',
            ),
            (
                'outside-contracts',
                (*original, 'test_bootstrap.ArtifactStageTest'),
                'fast_outside_contracts',
            ),
            ('malformed', (*original, 'malformed'), 'fast_unknown'),
        )
        for name, selectors, expected in cases:
            with self.subTest(name=name):
                with mock.patch.object(
                    validation_catalog, 'FAST_SELECTORS', selectors
                ):
                    with self.assertRaisesRegex(ValueError, expected):
                        validation_catalog.validate_catalog()


if __name__ == '__main__':
    unittest.main()
