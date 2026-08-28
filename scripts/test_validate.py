from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
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


class OpenBaoGitOpsContractTest(unittest.TestCase):
    DOCS_COMMIT = '0039d697237eb3f3a4a6238f47d4b971974a031e'
    BASELINE_ID = '2026-08-28.2'

    @staticmethod
    def documents(path: Path) -> list[dict[str, object]]:
        return [
            document
            for document in yaml.safe_load_all(path.read_text(encoding='utf-8'))
            if isinstance(document, dict)
        ]

    @staticmethod
    def identity(document: dict[str, object]) -> tuple[str, str, str]:
        metadata = document.get('metadata', {})
        assert isinstance(metadata, dict)
        return (
            str(document.get('kind', '')),
            str(metadata.get('namespace', '')),
            str(metadata.get('name', '')),
        )

    def test_supply_chain_is_immutable(self) -> None:
        self.assertEqual(
            validator.OPENBAO_DOCS_ARCHITECTURE_COMMIT,
            self.DOCS_COMMIT,
        )
        self.assertEqual(validator.OPENBAO_CHART_VERSION, '0.28.6')
        self.assertEqual(validator.OPENBAO_APP_VERSION, '2.6.1')

        chart_root = validator.ROOT / 'vendor/charts/openbao'
        chart = yaml.safe_load(
            (chart_root / 'Chart.yaml').read_text(encoding='utf-8')
        )
        self.assertEqual(chart['name'], 'openbao')
        self.assertEqual(chart['version'], validator.OPENBAO_CHART_VERSION)
        self.assertEqual(
            str(chart['appVersion']).lstrip('v'),
            validator.OPENBAO_APP_VERSION,
        )

        digest_names = (
            'OPENBAO_CHART_PACKAGE_SHA256',
            'OPENBAO_CHART_REGISTRY_DIGEST',
            'OPENBAO_SERVER_AMD64_DIGEST',
            'OPENBAO_INJECTOR_AMD64_DIGEST',
            'OPENBAO_AGENT_AMD64_DIGEST',
        )
        candidate = (
            validator.ROOT / 'pcs/candidate-3.md'
        ).read_text(encoding='utf-8')
        chart_readme = (
            validator.ROOT / 'vendor/charts/README.md'
        ).read_text(encoding='utf-8')
        for name in digest_names:
            digest = getattr(validator, name)
            self.assertRegex(digest, r'^sha256:[0-9a-f]{64}$')
            self.assertIn(digest, candidate)
            self.assertIn(digest, chart_readme)

        package = validator.ROOT / 'vendor/charts/openbao-0.28.6.tgz'
        self.assertTrue(package.is_file())
        self.assertEqual(
            'sha256:' + hashlib.sha256(package.read_bytes()).hexdigest(),
            validator.OPENBAO_CHART_PACKAGE_SHA256,
        )
        self.assertIn(self.DOCS_COMMIT, candidate)
        self.assertIn(self.BASELINE_ID, candidate)

    def test_activation_is_dormant_and_repository_owned(self) -> None:
        active_root = yaml.safe_load(
            (validator.ROOT / 'clusters/dev/kustomization.yaml').read_text(
                encoding='utf-8'
            )
        )
        self.assertNotIn('openbao-bootstrap.yaml', active_root['resources'])
        self.assertNotIn('openbao-runtime.yaml', active_root['resources'])

        bootstrap = self.documents(
            validator.ROOT / 'clusters/dev/openbao-bootstrap.yaml'
        )
        identities = {self.identity(document) for document in bootstrap}
        self.assertIn(('Namespace', '', 'openbao'), identities)
        self.assertIn(
            ('ServiceAccount', 'flux-system', 'flux-openbao-reconciler'),
            identities,
        )
        self.assertIn(
            ('ServiceAccount', 'flux-system', 'helm-openbao-reconciler'),
            identities,
        )

        activation = self.documents(
            validator.ROOT / 'clusters/dev/openbao-runtime.yaml'
        )
        self.assertEqual(len(activation), 1)
        kustomization = activation[0]
        self.assertEqual(
            self.identity(kustomization),
            ('Kustomization', 'flux-system', 'openbao-runtime'),
        )
        spec = kustomization['spec']
        self.assertEqual(spec['path'], './infrastructure/openbao')
        self.assertTrue(spec['prune'])
        self.assertTrue(spec['wait'])
        self.assertEqual(
            spec['serviceAccountName'], 'flux-openbao-reconciler'
        )
        self.assertEqual(
            spec['sourceRef'],
            {'kind': 'GitRepository', 'name': 'flux-system'},
        )

        desired_state = yaml.safe_load(
            (validator.ROOT / 'infrastructure/openbao/kustomization.yaml')
            .read_text(encoding='utf-8')
        )
        self.assertNotIn('namespace.yaml', desired_state['resources'])
        self.assertNotIn('rendered.yaml', desired_state['resources'])

    def test_values_lock_non_ha_tls_raft_and_persistent_audit(self) -> None:
        values = yaml.safe_load(
            (validator.ROOT / 'infrastructure/openbao/values.yaml').read_text(
                encoding='utf-8'
            )
        )
        self.assertFalse(values['global']['tlsDisable'])
        self.assertTrue(values['injector']['enabled'])
        self.assertEqual(values['injector']['replicas'], 1)
        self.assertEqual(values['injector']['webhook']['failurePolicy'], 'Fail')
        self.assertEqual(
            values['injector']['image']['tag'],
            '1.7.2@' + validator.OPENBAO_INJECTOR_AMD64_DIGEST,
        )
        self.assertEqual(
            values['injector']['agentImage']['tag'],
            '2.6.1@' + validator.OPENBAO_AGENT_AMD64_DIGEST,
        )
        self.assertEqual(
            values['server']['image']['tag'],
            '2.6.1@' + validator.OPENBAO_SERVER_AMD64_DIGEST,
        )
        self.assertFalse(values['server']['dev']['enabled'])
        self.assertFalse(values['server']['standalone']['enabled'])
        self.assertTrue(values['server']['ha']['enabled'])
        self.assertEqual(values['server']['ha']['replicas'], 1)
        self.assertTrue(values['server']['ha']['raft']['enabled'])
        self.assertTrue(values['server']['ha']['raft']['setNodeId'])
        self.assertEqual(values['server']['dataStorage']['size'], '10Gi')
        self.assertEqual(values['server']['auditStorage']['size'], '5Gi')
        self.assertEqual(
            values['server']['persistentVolumeClaimRetentionPolicy'],
            {'whenDeleted': 'Retain', 'whenScaled': 'Retain'},
        )
        self.assertFalse(values['server']['ingress']['enabled'])
        self.assertFalse(values['server']['gateway']['tlsRoute']['enabled'])
        self.assertFalse(values['server']['gateway']['httpRoute']['enabled'])
        self.assertFalse(values['server']['route']['enabled'])
        self.assertFalse(values['ui']['enabled'])
        self.assertFalse(values['csi']['enabled'])
        self.assertFalse(values['snapshotAgent']['enabled'])
        config = values['server']['ha']['raft']['config']
        self.assertIn('storage "raft"', config)
        self.assertIn('tls_disable = 0', config)
        self.assertIn('tls_cert_file', config)
        self.assertIn('tls_key_file', config)
        self.assertIn('audit "file" "to-file"', config)
        self.assertIn('file_path = "/openbao/audit/openbao-audit.log"', config)
        self.assertIn('audit "file" "to-stdout"', config)
        self.assertIn('file_path = "stdout"', config)
        self.assertGreaterEqual(config.count('log_raw = "false"'), 2)
        self.assertGreaterEqual(config.count('hmac_accessor = "true"'), 2)
        self.assertNotIn('auto_unseal', config.lower())

    def test_runtime_resources_are_private_and_backup_free(self) -> None:
        result = subprocess.run(
            [
                'kubectl',
                'kustomize',
                str(validator.ROOT / 'infrastructure/openbao'),
            ],
            cwd=validator.ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        documents = [
            document
            for document in yaml.safe_load_all(result.stdout)
            if isinstance(document, dict)
        ]
        identities = {self.identity(document) for document in documents}
        required = {
            ('ResourceQuota', 'openbao', 'openbao-runtime'),
            ('Certificate', 'openbao', 'openbao-server-tls'),
            ('HelmRelease', 'flux-system', 'openbao'),
            ('NetworkPolicy', 'openbao', 'default-deny'),
            ('ServiceAccount', 'openbao', 'openbao-runtime-probe'),
        }
        self.assertTrue(required.issubset(identities))
        self.assertIn(
            ('ConfigMap', 'flux-system', 'openbao-helm-values'),
            identities,
        )
        helm_release = next(
            document
            for document in documents
            if self.identity(document)
            == ('HelmRelease', 'flux-system', 'openbao')
        )
        self.assertEqual(helm_release['spec']['targetNamespace'], 'openbao')
        self.assertEqual(
            helm_release['spec']['chart']['spec']['sourceRef'],
            {
                'kind': 'GitRepository',
                'name': 'flux-system',
                'namespace': 'flux-system',
            },
        )
        forbidden_kinds = {
            'Ingress', 'Gateway', 'HTTPRoute', 'TLSRoute', 'CronJob',
            'ScheduledBackup', 'Backup', 'VolumeSnapshot',
        }
        self.assertTrue(
            forbidden_kinds.isdisjoint(
                {str(document.get('kind', '')) for document in documents}
            )
        )
        identity_text = '\n'.join(
            '/'.join(self.identity(document)).lower() for document in documents
        )
        for forbidden in (
            'minio', 'snapshot', 'objectstore', 'scheduledbackup',
            'backup', 'restore',
        ):
            self.assertNotIn(forbidden, identity_text)
        serialized = yaml.safe_dump_all(documents, sort_keys=True).lower()
        for forbidden in ('platform-secret', 'secretstore', 'externalsecret'):
            self.assertNotIn(forbidden, serialized)

    def test_rendered_chart_contract_is_digest_locked(self) -> None:
        rendered_path = validator.ROOT / 'infrastructure/openbao/rendered.yaml'
        documents = self.documents(rendered_path)
        canonical_documents = sorted(
            documents,
            key=lambda document: (
                str(document.get('apiVersion', '')),
                *self.identity(document),
            ),
        )
        canonical = json.dumps(
            canonical_documents,
            ensure_ascii=False,
            separators=(',', ':'),
            sort_keys=True,
        ).encode('utf-8')
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            validator.OPENBAO_RENDERED_CANONICAL_SHA256,
        )
        expected_identities = {
            ('ClusterRole', '', 'openbao-agent-injector-clusterrole'),
            ('ClusterRoleBinding', '', 'openbao-agent-injector-binding'),
            ('ClusterRoleBinding', '', 'openbao-server-binding'),
            ('ConfigMap', 'openbao', 'openbao-config'),
            ('Deployment', 'openbao', 'openbao-agent-injector'),
            (
                'MutatingWebhookConfiguration',
                '',
                'openbao-agent-injector-cfg',
            ),
            ('Pod', 'openbao', 'openbao-server-test'),
            ('Role', 'openbao', 'openbao-discovery-role'),
            ('RoleBinding', 'openbao', 'openbao-discovery-rolebinding'),
            ('Service', 'openbao', 'openbao'),
            ('Service', 'openbao', 'openbao-active'),
            ('Service', 'openbao', 'openbao-agent-injector-svc'),
            ('Service', 'openbao', 'openbao-internal'),
            ('ServiceAccount', 'openbao', 'openbao'),
            ('ServiceAccount', 'openbao', 'openbao-agent-injector'),
            ('StatefulSet', 'openbao', 'openbao'),
        }
        self.assertEqual(
            {self.identity(document) for document in documents},
            expected_identities,
        )

        by_identity = {
            self.identity(document): document for document in documents
        }
        injector = by_identity[
            ('Deployment', 'openbao', 'openbao-agent-injector')
        ]
        server = by_identity[('StatefulSet', 'openbao', 'openbao')]
        self.assertEqual(injector['spec']['replicas'], 1)
        self.assertEqual(server['spec']['replicas'], 1)
        self.assertEqual(
            server['spec']['persistentVolumeClaimRetentionPolicy'],
            {'whenDeleted': 'Retain', 'whenScaled': 'Retain'},
        )
        claims = {
            claim['metadata']['name']: claim['spec']['resources']['requests'][
                'storage'
            ]
            for claim in server['spec']['volumeClaimTemplates']
        }
        self.assertEqual(claims, {'audit': '5Gi', 'data': '10Gi'})

        expected_images = {
            'docker.io/hashicorp/vault-k8s:1.7.2@'
            + validator.OPENBAO_INJECTOR_AMD64_DIGEST,
            'quay.io/openbao/openbao:2.6.1@'
            + validator.OPENBAO_SERVER_AMD64_DIGEST,
        }
        actual_images: set[str] = set()
        for document in documents:
            spec = document.get('spec', {})
            if not isinstance(spec, dict):
                continue
            pod_spec = spec.get('template', {}).get('spec', spec)
            if not isinstance(pod_spec, dict):
                continue
            for container_key in ('containers', 'initContainers'):
                for container in pod_spec.get(container_key, []):
                    image = container.get('image')
                    if image:
                        actual_images.add(str(image))
        self.assertEqual(actual_images, expected_images)

        for workload in (injector, server):
            pod_spec = workload['spec']['template']['spec']
            self.assertTrue(pod_spec['securityContext']['runAsNonRoot'])
            self.assertEqual(
                pod_spec['securityContext']['seccompProfile']['type'],
                'RuntimeDefault',
            )
            for container in pod_spec['containers']:
                security = container['securityContext']
                self.assertFalse(security['allowPrivilegeEscalation'])
                self.assertEqual(security['capabilities']['drop'], ['ALL'])

        for document in documents:
            if document.get('kind') != 'Service':
                continue
            self.assertIn(
                document.get('spec', {}).get('type', 'ClusterIP'),
                ('ClusterIP',),
            )
        rendered_text = rendered_path.read_text(encoding='utf-8').lower()
        for forbidden in (
            'kind: ingress',
            'kind: httproute',
            'kind: tlsroute',
            'kind: cronjob',
            'kind: volumesnapshot',
            'image: minio',
        ):
            self.assertNotIn(forbidden, rendered_text)


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
            '541b186878d1e28e1aa9308111a2962cdfefb91b'
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
| backend Source Commit | `4aaf721fa91abd729b33765e4e329b02aa2ece02` |

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

## 当前 backend 可用输入

| 字段 | 值 |
| --- | --- |
| Source Commit | `4aaf721fa91abd729b33765e4e329b02aa2ece02` |
| CI run | `32802909349` |
| verify | `success（Ruff、mypy、lint-imports、Alembic、全量 pytest、OpenAPI）` |
| publish-image job | `97667504061` |
| Image tag | `sha-4aaf721` |
| Immutable image | `ghcr.io/unif-code/engineering-platform-backend@sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857` |
| Runtime Image ID | `NOT_VERIFIED` |
| Deployment | `NOT_EXECUTED` |
| Migration | `NOT_EXECUTED` |
| Account initialization | `NOT_EXECUTED` |

临时密码只允许在受控初始化输出中一次性显示，不得写入 Git、日志或长期证据。

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
            + f'''\n| Application | engineering-platform frontend | Source `{frontend_source}` / CI run `{frontend_ci_run}`、publish-image job `{frontend_publish_job}`（均 `success`） | `ghcr.io/unif-code/engineering-platform:{frontend_tag}`；OCI index `{frontend_artifact}` | linux/amd64 manifest `{frontend_manifest}`；运行 Image ID `{frontend_image_id}` | business-ready 候选已锁定 workload；运行未部署 |
| Application | engineering-platform-backend | Source `4aaf721fa91abd729b33765e4e329b02aa2ece02` / CI run `32802909349`；verify、publish-image 均 `success` | `ghcr.io/unif-code/engineering-platform-backend:sha-4aaf721`；OCI index `sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857` | 不可变输入 `ghcr.io/unif-code/engineering-platform-backend@sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857`；运行 Image ID `NOT_VERIFIED` | business-ready 候选已锁定 migration/backend；运行与账号初始化均未执行 |\n''',
            encoding='utf-8',
        )
        handoff = root / 'runbook/10-image-owner-handoff.md'
        handoff.write_text(
            handoff.read_text(encoding='utf-8')
            + f'''\n| 字段 | frontend | backend |\n| --- | --- | --- |\n| Source commit（完整 40 位 SHA） | `{frontend_source}` | `4aaf721fa91abd729b33765e4e329b02aa2ece02` |\n| CI run URL | `https://github.com/unif-code/engineering-platform/actions/runs/{frontend_ci_run}`（`success`；publish-image job `{frontend_publish_job}`） | `https://github.com/unif-code/engineering-platform-backend/actions/runs/32802909349`（`success`；verify、publish-image 均成功） |\n| Image tag `sha-<short-sha>` | `{frontend_tag}` | `sha-4aaf721` |\n| OCI index digest | `{frontend_artifact}` | `sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857` |\n| `linux/amd64` manifest digest | `{frontend_manifest}` | `NOT_SEPARATELY_VERIFIED`（build 固定 `linux/amd64`；部署锁定 OCI index digest） |\n| Runtime Image ID | `{frontend_image_id}` | `NOT_VERIFIED` |\n| Migration | 不适用 | `NOT_EXECUTED` |\n| Account initialization | 不适用 | `NOT_EXECUTED` |\n''',
            encoding='utf-8',
        )

        runtime = '''## 当前 DEV Runtime 观测

| 字段 | 值 |
| --- | --- |
| 采样时间 | `2026-08-24 12:16:47Z` |
| GIT_COMMIT | `685198db15299fdb6b8cdffd72162a4864c8666b` |
| RESULT | `PASS_FLUX_PHASE_A` |
| REASON | `four-controller-runtime-accepted` |
| FLUX_CHECK | `all checks passed` |
| CONTROLLERS | `source v1.9.3/kustomize v1.9.4/helm v1.6.3/notification v1.9.2` |
| FLUX_CRD_COUNT | `11` |
| SECRET_COUNT | `0` |
| SYNC_INVENTORY | `empty` |
| DOWNSTREAM_NAMESPACE_INVENTORY | `empty` |
| NETWORK_PROBE_V2 | `PASS` |
| EVIDENCE | `/root/dev-infra-evidence/15-flux-phase-a-20260824T105630Z.txt` |
| EVIDENCE SHA256 | `2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7` |
| OPENBAO | `NOT_EXECUTED` |
| BACKUPS | `NOT_EXECUTED` |
| NEXT_STAGE | `PHASE_B_REQUIRES_SEPARATE_APPROVAL` |
| EXIT_CODE | `0` |
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

    def test_current_backend_delivery_is_pinned_but_not_deployed(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_current_backend_delivery'),
            'backend delivery input must have a fail-closed validator',
        )
        validator.validate_current_backend_delivery()

    def test_current_backend_delivery_rejects_fact_or_runtime_drift(self) -> None:
        mutations = (
            (
                'pcs/candidate-2.md',
                '4aaf721fa91abd729b33765e4e329b02aa2ece02',
                'bad-source',
                '当前 backend Source Commit',
            ),
            (
                'runbook/06-apps.md',
                'ghcr.io/unif-code/engineering-platform-backend@sha256:'
                'f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857',
                'ghcr.io/unif-code/engineering-platform-backend@sha256:bad-digest',
                '当前 backend Immutable image',
            ),
            (
                'runbook/10-image-owner-handoff.md',
                '| Deployment | `NOT_EXECUTED` |',
                '| Deployment | `DEPLOYED` |',
                '当前 backend Deployment',
            ),
            (
                'pcs/candidate-2.md',
                '| Account initialization | `NOT_EXECUTED` |',
                '| Account initialization | `EXECUTED` |',
                '当前 backend Account initialization',
            ),
        )
        documents = (
            'pcs/candidate-2.md',
            'runbook/06-apps.md',
            'runbook/10-image-owner-handoff.md',
        )
        for relative_path, old, new, expected in mutations:
            with self.subTest(document=relative_path, mutation=new):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for document in documents:
                        source = validator.ROOT / document
                        target = root / document
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, target)
                    path = root / relative_path
                    source = path.read_text(encoding='utf-8')
                    self.assertIn(old, source)
                    path.write_text(source.replace(old, new, 1), encoding='utf-8')
                    stderr = io.StringIO()
                    with (
                        contextlib.redirect_stderr(stderr),
                        self.assertRaises(SystemExit) as raised,
                    ):
                        validator.validate_current_backend_delivery(root)
                self.assertEqual(raised.exception.code, 1)
                self.assertIn(expected, stderr.getvalue())

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
                '541b186878d1e28e1aa9308111a2962cdfefb91b',
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
            'docs 架构事实提交为 `541b186878d1e28e1aa9308111a2962cdfefb91b`',
            '| docs 架构事实提交 | `541b186878d1e28e1aa9308111a2962cdfefb91b` |',
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
                                '541b186878d1e28e1aa9308111a2962cdfefb91b',
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
                    '`541b186878d1e28e1aa9308111a2962cdfefb91b`',
                    'docs 架构事实提交为远端可追溯的 '
                    '`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`',
                    1,
                ),
                encoding='utf-8',
            )
            stderr = self.assert_main_rejects_release_fact_documents(root)

        self.assertIn('当前 docs 架构事实提交计划与已推送 main 不一致', stderr)

    def test_current_docs_plan_rejects_appended_conflicting_sha(self) -> None:
        # Would fail if a valid current SHA can hide an additional conflicting value.
        current = '541b186878d1e28e1aa9308111a2962cdfefb91b'
        conflicting = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        mutations = (
            (
                f'docs 架构事实提交为远端可追溯的 `{current}`。',
                f'docs 架构事实提交为远端可追溯的 `{current}`；冲突 `{conflicting}`。',
            ),
            (
                f'docs 架构事实提交为 `{current}`。',
                f'docs 架构事实提交为 `{current}`；冲突 `{conflicting}`。',
            ),
            (
                f'| docs 架构事实提交 | `{current}` |',
                f'| docs 架构事实提交 | `{current}` |\n'
                f'| docs 架构事实提交 | `{conflicting}` |',
            ),
        )
        for expected, mutation in mutations:
            with self.subTest(expected=expected):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    path = root / (
                        'docs/superpowers/plans/'
                        '2026-08-23-pcs-runtime-reconciliation.md'
                    )
                    path.write_text(
                        path.read_text(encoding='utf-8').replace(expected, mutation, 1),
                        encoding='utf-8',
                    )
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn(
                    '当前 docs 架构事实提交计划与已推送 main 不一致', stderr
                )

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

    def test_frontend_summary_rejects_appended_conflicting_facts_and_rows(
        self,
    ) -> None:
        # Would fail if a correct first summary value can hide a conflicting append.
        source = 'da72238abc87a19c07a5cac96e41d88d5f6bf2d3'
        artifact = (
            'sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1'
        )
        component_mutations = (
            (f'Source `{source}`', f'Source `{source}`；冲突 `bad-source`'),
            ('CI run `32683635240`', 'CI run `32683635240`；冲突 `00000000000`'),
            (
                'publish-image job `97305929974`',
                'publish-image job `97305929974`；冲突 `00000000000`',
            ),
            (
                'engineering-platform:sha-da72238',
                'engineering-platform:sha-da72238；冲突 `sha-bad`',
            ),
            (f'OCI index `{artifact}`', f'OCI index `{artifact}`；冲突 `sha256:bad`'),
            (
                'linux/amd64 manifest '
                '`sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`',
                'linux/amd64 manifest '
                '`sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`'
                '；冲突 `sha256:bad`',
            ),
        )
        for expected, mutation in component_mutations:
            with self.subTest(summary='component', expected=expected):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    path = root / 'pcs/candidate-2.md'
                    lines = path.read_text(encoding='utf-8').splitlines()
                    for index, line in enumerate(lines):
                        if line.startswith(
                            '| Application | engineering-platform frontend |'
                        ):
                            lines[index] = line.replace(expected, mutation, 1)
                            break
                    else:
                        self.fail('missing frontend component summary row')
                    path.write_text(
                        '\n'.join(lines) + '\n',
                        encoding='utf-8',
                    )
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn('PCS frontend 组件表与当前审计快照不一致', stderr)

        handoff_fields = (
            ('Source commit（完整 40 位 SHA）', '；冲突 `bad-source`'),
            ('CI run URL', '；冲突 `00000000000`'),
            ('Image tag `sha-<short-sha>`', '；冲突 `sha-bad`'),
            ('OCI index digest', '；冲突 `sha256:bad`'),
            ('`linux/amd64` manifest digest', '；冲突 `sha256:bad`'),
        )
        for field, conflict in handoff_fields:
            with self.subTest(summary='handoff', field=field):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    path = root / 'runbook/10-image-owner-handoff.md'
                    lines = path.read_text(encoding='utf-8').splitlines()
                    summary_started = False
                    for index, line in enumerate(lines):
                        if line.strip() == '| 字段 | frontend | backend |':
                            summary_started = True
                            continue
                        if summary_started and line.startswith(f'| {field} |'):
                            cells = line.split('|')
                            cells[2] = cells[2].rstrip() + conflict + ' '
                            lines[index] = '|'.join(cells)
                            break
                    else:
                        self.fail(f'missing handoff summary row: {field}')
                    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                    stderr = self.assert_main_rejects_release_fact_documents(root)

                self.assertIn(
                    f'Image Owner Handoff 汇总表 {field} 与当前审计快照不一致',
                    stderr,
                )

        for summary in ('component', 'handoff'):
            with self.subTest(summary=summary, mutation='duplicate-row'):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_release_fact_documents(root)
                    if summary == 'component':
                        path = root / 'pcs/candidate-2.md'
                        row_prefix = '| Application | engineering-platform frontend |'
                        conflicting_row = lambda line: line.replace(
                            source, 'bad-source', 1
                        )
                        error = 'PCS frontend 组件表与当前审计快照不一致'
                    else:
                        path = root / 'runbook/10-image-owner-handoff.md'
                        row_prefix = '| OCI index digest |'
                        conflicting_row = lambda line: line.replace(
                            artifact, 'sha256:bad', 1
                        )
                        error = (
                            'Image Owner Handoff 汇总表 OCI index digest '
                            '与当前审计快照不一致'
                        )
                    lines = path.read_text(encoding='utf-8').splitlines()
                    summary_started = False
                    for index, line in enumerate(lines):
                        if summary == 'handoff' and line.strip() == '| 字段 | frontend | backend |':
                            summary_started = True
                            continue
                        if line.startswith(row_prefix) and (
                            summary != 'handoff' or summary_started
                        ):
                            lines.insert(index + 1, conflicting_row(line))
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
                    '| 采样时间 | `2026-08-24 12:16:47Z` |',
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
                    '| 采样时间 | `2026-08-24 12:16:47Z` |',
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
        self.assertEqual(validate_single_user_resources(), (1480, 3456))

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
    APPROVED_RESOURCES = [
        'infrastructure.yaml',
        'apps.yaml',
    ]
    APPROVED_ROOT_RECONCILER_RULES = [
        {
            'apiGroups': ['kustomize.toolkit.fluxcd.io'],
            'resources': ['kustomizations'],
            'verbs': [
                'create',
                'delete',
                'get',
                'list',
                'patch',
                'update',
                'watch',
            ],
        }
    ]

    def make_root(
        self,
        resources: list[str],
        root_reconciler_rules: list[dict[str, object]] | None = None,
        extra_bindings: list[dict[str, object]] | None = None,
    ) -> Path:
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
        (cluster / 'reconcile-rbac.yaml').write_text(
            yaml.safe_dump_all(
                [
                    {
                        'apiVersion': 'rbac.authorization.k8s.io/v1',
                        'kind': 'ClusterRole',
                        'metadata': {'name': 'flux-root-reconciler'},
                        'rules': (
                            self.APPROVED_ROOT_RECONCILER_RULES
                            if root_reconciler_rules is None
                            else root_reconciler_rules
                        ),
                    },
                    {
                        'apiVersion': 'rbac.authorization.k8s.io/v1',
                        'kind': 'ClusterRoleBinding',
                        'metadata': {'name': 'flux-root-reconciler'},
                        'roleRef': {
                            'apiGroup': 'rbac.authorization.k8s.io',
                            'kind': 'ClusterRole',
                            'name': 'flux-root-reconciler',
                        },
                        'subjects': [
                            {
                                'kind': 'ServiceAccount',
                                'name': 'flux-root-reconciler',
                                'namespace': 'flux-system',
                            }
                        ],
                    },
                    *(extra_bindings or []),
                ],
                sort_keys=False,
            ),
            encoding='utf-8',
        )
        return root

    def test_active_root_rejects_unapproved_entrypoint(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_active_root'),
            'validate_active_root must enforce the active-root allowlist',
        )
        root = self.make_root([*self.APPROVED_RESOURCES, 'backups.yaml'])

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validator.validate_active_root(root)

    def test_active_root_rejects_bootstrap_owned_entrypoints(self) -> None:
        for entrypoint in ('flux-system', 'reconcile-rbac.yaml'):
            with self.subTest(entrypoint=entrypoint):
                root = self.make_root(
                    [entrypoint, *self.APPROVED_RESOURCES]
                )
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        validator.validate_active_root(root)

    def test_active_root_accepts_exact_business_ready_entrypoints(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_active_root'),
            'validate_active_root must enforce the active-root allowlist',
        )
        root = self.make_root(self.APPROVED_RESOURCES)

        validator.validate_active_root(root)

    def test_active_root_rejects_broad_root_reconciler_rbac(self) -> None:
        broad_rules = [
            *self.APPROVED_ROOT_RECONCILER_RULES,
            {
                'apiGroups': [''],
                'resources': ['configmaps', 'namespaces'],
                'verbs': ['create', 'delete', 'get', 'list', 'patch', 'update'],
            },
        ]
        root = self.make_root(self.APPROVED_RESOURCES, broad_rules)

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validator.validate_active_root(root)

    def test_active_root_rejects_extra_root_reconciler_binding(self) -> None:
        root = self.make_root(
            self.APPROVED_RESOURCES,
            extra_bindings=[
                {
                    'apiVersion': 'rbac.authorization.k8s.io/v1',
                    'kind': 'ClusterRoleBinding',
                    'metadata': {'name': 'flux-root-reconciler-extra'},
                    'roleRef': {
                        'apiGroup': 'rbac.authorization.k8s.io',
                        'kind': 'ClusterRole',
                        'name': 'cluster-admin',
                    },
                    'subjects': [
                        {
                            'kind': 'ServiceAccount',
                            'name': 'flux-root-reconciler',
                            'namespace': 'flux-system',
                        }
                    ],
                }
            ],
        )

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validator.validate_active_root(root)

    def test_repository_uses_exact_business_ready_entrypoints(self) -> None:
        validator.validate_active_root(validator.ROOT)


class _FluxPhaseAContractBase:
    CONTROLLERS = {
        'source-controller': {
            'tag': 'v1.9.3',
            'digest': (
                'sha256:'
                'c6c82b3182f48b833252c71aefa0741957ca18296612bc6d2b9b5fb276f926e4'
            ),
            'resources': {
                'limits': {'cpu': '400m', 'memory': '512Mi'},
                'requests': {'cpu': '100m', 'memory': '256Mi'},
            },
            'args': (
                '--events-addr=http://notification-controller.$(RUNTIME_NAMESPACE).svc.cluster.local./',
                '--watch-all-namespaces=false',
                '--log-level=info',
                '--log-encoding=json',
                '--enable-leader-election',
                '--storage-path=/data',
                '--storage-adv-addr=source-controller.$(RUNTIME_NAMESPACE).svc.cluster.local.',
            ),
        },
        'kustomize-controller': {
            'tag': 'v1.9.4',
            'digest': (
                'sha256:'
                '3e57aecb74419be93d09ba062cfc882bea405193c474009e0da1826de71a4ebd'
            ),
            'resources': {
                'limits': {'cpu': '1000m', 'memory': '1Gi'},
                'requests': {'cpu': '250m', 'memory': '512Mi'},
            },
            'args': (
                '--events-addr=http://notification-controller.$(RUNTIME_NAMESPACE).svc.cluster.local./',
                '--watch-all-namespaces=false',
                '--log-level=info',
                '--log-encoding=json',
                '--enable-leader-election',
                '--default-service-account=default',
                '--no-cross-namespace-refs=true',
                '--no-remote-bases=true',
                '--custom-apply-stage-kinds=rbac.authorization.k8s.io/Role',
            ),
        },
        'helm-controller': {
            'tag': 'v1.6.3',
            'digest': (
                'sha256:'
                '22c0a585d0d9b1f792b9d5638144b7810e273d28e310da37740f01226bd044a2'
            ),
            'resources': {
                'limits': {'cpu': '400m', 'memory': '512Mi'},
                'requests': {'cpu': '100m', 'memory': '256Mi'},
            },
            'args': (
                '--events-addr=http://notification-controller.$(RUNTIME_NAMESPACE).svc.cluster.local./',
                '--watch-all-namespaces=false',
                '--log-level=info',
                '--log-encoding=json',
                '--enable-leader-election',
                '--default-service-account=default',
                '--no-cross-namespace-refs=true',
            ),
        },
        'notification-controller': {
            'tag': 'v1.9.2',
            'digest': (
                'sha256:'
                'cb17eefffbc442412ba6f63336defd04c0fc387d5082d951998d1ff163a9180d'
            ),
            'resources': {
                'limits': {'cpu': '200m', 'memory': '256Mi'},
                'requests': {'cpu': '50m', 'memory': '128Mi'},
            },
            'args': (
                '--watch-all-namespaces=false',
                '--log-level=info',
                '--log-encoding=json',
                '--enable-leader-election',
                '--no-cross-namespace-refs=true',
            ),
        },
    }
    PSS_LABELS = {
        'pod-security.kubernetes.io/audit': 'restricted',
        'pod-security.kubernetes.io/audit-version': 'v1.36',
        'pod-security.kubernetes.io/enforce': 'restricted',
        'pod-security.kubernetes.io/enforce-version': 'v1.36',
        'pod-security.kubernetes.io/warn': 'restricted',
        'pod-security.kubernetes.io/warn-version': 'v1.36',
    }
    SECURITY_CONTEXT = {
        'allowPrivilegeEscalation': False,
        'capabilities': {'drop': ['ALL']},
        'readOnlyRootFilesystem': True,
        'runAsNonRoot': True,
        'seccompProfile': {'type': 'RuntimeDefault'},
    }
    CRDS = (
        'alerts.notification.toolkit.fluxcd.io',
        'buckets.source.toolkit.fluxcd.io',
        'externalartifacts.source.toolkit.fluxcd.io',
        'gitrepositories.source.toolkit.fluxcd.io',
        'helmcharts.source.toolkit.fluxcd.io',
        'helmreleases.helm.toolkit.fluxcd.io',
        'helmrepositories.source.toolkit.fluxcd.io',
        'kustomizations.kustomize.toolkit.fluxcd.io',
        'ocirepositories.source.toolkit.fluxcd.io',
        'providers.notification.toolkit.fluxcd.io',
        'receivers.notification.toolkit.fluxcd.io',
    )
    SERVICES = {
        'notification-controller': {
            'ports': [
                {
                    'name': 'http',
                    'port': 80,
                    'protocol': 'TCP',
                    'targetPort': 'http',
                }
            ],
            'selector': {'app': 'notification-controller'},
            'type': 'ClusterIP',
        },
        'source-controller': {
            'ports': [
                {
                    'name': 'http',
                    'port': 80,
                    'protocol': 'TCP',
                    'targetPort': 'http',
                }
            ],
            'selector': {'app': 'source-controller'},
            'type': 'ClusterIP',
        },
        'webhook-receiver': {
            'ports': [
                {
                    'name': 'http',
                    'port': 80,
                    'protocol': 'TCP',
                    'targetPort': 'http-webhook',
                }
            ],
            'selector': {'app': 'notification-controller'},
            'type': 'ClusterIP',
        },
    }
    CONTROLLER_SERVICE_ACCOUNTS = tuple(CONTROLLERS)

    def test_stage_100_pins_the_raw_rendered_bundle(self) -> None:
        stage = (
            validator.ROOT
            / 'scripts/bootstrap/stages/100-flux-phase-a/run.sh'
        )
        self.assertTrue(stage.is_file(), 'Stage 100 Flux Phase A entry is missing')
        source = stage.read_text(encoding='utf-8')
        match = re.search(
            r'^readonly RAW_RENDERED_SHA256=([0-9a-f]{64})$',
            source,
            re.MULTILINE,
        )
        self.assertIsNotNone(match, 'Stage 100 does not pin raw rendered SHA-256')
        assert match is not None
        self.assertEqual(
            match.group(1),
            validator.FLUX_PHASE_A_RAW_RENDERED_SHA256,
        )

        orchestrator = (
            validator.ROOT / 'scripts/bootstrap/bootstrap-all.sh'
        ).read_text(encoding='utf-8')
        self.assertIn(
            'readonly -a STAGES=(00 10 20 30 40 50 60 90 100 110 120 130 140 150 160)',
            orchestrator,
        )
        self.assertIn('100:PASS_FLUX_PHASE_A_INSTALLED', orchestrator)

    @classmethod
    def setUpClass(cls) -> None:
        rendered = subprocess.run(
            [
                'kubectl',
                'kustomize',
                str(validator.ROOT / 'clusters/dev/flux-system/phase-a'),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if rendered.returncode != 0:
            raise AssertionError(rendered.stderr or rendered.stdout)
        cls.RENDERED_TEXT = rendered.stdout
        cls.RENDERED_BASELINE = [
            document
            for document in yaml.safe_load_all(rendered.stdout)
            if isinstance(document, dict)
        ]

    def test_kustomize_builds_rejects_flux_raw_rendered_byte_drift(self) -> None:
        baseline_render = subprocess.CompletedProcess(
            args=[
                'kubectl',
                'kustomize',
                str(validator.ROOT / 'clusters/dev/flux-system/phase-a'),
            ],
            returncode=0,
            stdout=self.RENDERED_TEXT.encode('utf-8'),
            stderr=b'',
        )
        altered_render = copy.copy(baseline_render)
        altered_render.stdout = b'# byte-level drift\n' + baseline_render.stdout
        manifest_roots = (validator.ROOT / 'clusters/dev/flux-system/phase-a',)
        with (
            mock.patch.object(validator, 'MANIFEST_ROOTS', manifest_roots),
            mock.patch.object(
                validator.subprocess,
                'run',
                return_value=baseline_render,
            ),
        ):
            validator.validate_kustomize_builds()

        stderr = io.StringIO()
        with (
            mock.patch.object(validator, 'MANIFEST_ROOTS', manifest_roots),
            mock.patch.object(
                validator.subprocess,
                'run',
                return_value=altered_render,
            ),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            validator.validate_kustomize_builds()

        self.assertEqual(raised.exception.code, 1)
        self.assertRegex(
            stderr.getvalue(),
            'Flux Phase A rendered bundle raw SHA-256 漂移',
        )

    def setUp(self) -> None:
        self.assertTrue(
            hasattr(validator, 'validate_flux_phase_a'),
            'validate_flux_phase_a must enforce the fail-closed Phase A contract',
        )
        self.assertTrue(
            hasattr(validator, 'validate_flux_phase_a_runbook'),
            'validate_flux_phase_a_runbook must enforce dependency-safe staging',
        )
        self.assertTrue(
            hasattr(validator, 'validate_flux_phase_a_runtime_record'),
            'validate_flux_phase_a_runtime_record must reject stale runtime facts',
        )
        self.assertTrue(
            hasattr(validator, 'validate_flux_phase_a_probes'),
            'validate_flux_phase_a_probes must enforce transient probe safety',
        )

    def make_deployment(
        self,
        name: str,
        image: str,
    ) -> dict[str, object]:
        contract = self.CONTROLLERS[name]
        return {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {
                'name': name,
                'namespace': 'flux-system',
                'labels': {'app.kubernetes.io/part-of': 'flux'},
            },
            'spec': {
                'strategy': {
                    'rollingUpdate': {'maxSurge': 1, 'maxUnavailable': 0},
                    'type': 'RollingUpdate',
                },
                'template': {
                    'spec': {
                        'serviceAccountName': name,
                        'containers': [
                            {
                                'name': 'manager',
                                'image': image,
                                'args': list(contract['args']),
                                'resources': copy.deepcopy(contract['resources']),
                                'securityContext': copy.deepcopy(
                                    self.SECURITY_CONTEXT
                                ),
                            }
                        ],
                    }
                },
            },
        }

    def controller_subjects(self) -> list[dict[str, str]]:
        return [
            {
                'kind': 'ServiceAccount',
                'name': name,
                'namespace': 'flux-system',
            }
            for name in self.CONTROLLER_SERVICE_ACCOUNTS
        ]

    def phase_a_rbac_documents(self) -> list[dict[str, object]]:
        path = (
            validator.ROOT
            / 'clusters/dev/flux-system/phase-a/phase-a-rbac.yaml'
        )
        return [
            document
            for document in yaml.safe_load_all(path.read_text(encoding='utf-8'))
            if isinstance(document, dict)
        ]


class BusinessReadyGitOpsContractTest(unittest.TestCase):
    """Fail-closed contract for the no-backup DEV business-ready slice."""

    APPROVED_NAMESPACES = {
        'cert-manager',
        'cnpg-system',
        'flux-system',
        'local-path-storage',
        'platform',
    }
    FORBIDDEN_NAMES = {
        'barman',
        'backup',
        'etcd-backup',
        'minio',
        'monitoring',
        'objectstore',
        'openbao',
        'scheduledbackup',
    }
    BACKEND_IMAGE = (
        'ghcr.io/unif-code/engineering-platform-backend@sha256:'
        'f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857'
    )
    FRONTEND_IMAGE = (
        'ghcr.io/unif-code/engineering-platform@sha256:'
        '21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c'
    )
    POSTGRES_IMAGE = (
        'ghcr.io/cloudnative-pg/postgresql:18.4-standard-trixie@sha256:'
        'ae0ec6943c3c24b0de87f93b73ac531a8e546a4cc895655f793547eed2fdbef1'
    )
    RUNTIME_ROLES = {
        'audit_rw',
        'authorization_rw',
        'configuration_rw',
        'identity_rw',
        'organization_rw',
        'workspace_rw',
    }

    @classmethod
    def setUpClass(cls) -> None:
        roots = (
            'clusters/dev',
            'clusters/dev/flux-system',
            'infrastructure/foundation',
            'infrastructure/cert-manager/controller',
            'infrastructure/cert-manager/config',
            'infrastructure/cnpg/controller',
            'infrastructure/cnpg/database',
            'apps/migration',
            'apps',
        )
        cls.RENDERED = []
        cls.RENDERED_BY_ROOT = {}
        for root in roots:
            rendered = subprocess.run(
                ['kubectl', 'kustomize', str(validator.ROOT / root)],
                capture_output=True,
                check=False,
                text=True,
            )
            if rendered.returncode != 0:
                raise AssertionError(rendered.stderr or rendered.stdout)
            documents = [
                document
                for document in yaml.safe_load_all(rendered.stdout)
                if isinstance(document, dict)
            ]
            cls.RENDERED_BY_ROOT[root] = documents
            cls.RENDERED.extend(documents)
        rbac_root = 'clusters/dev/reconcile-rbac.yaml'
        rbac_documents = [
            document
            for document in yaml.safe_load_all(
                (validator.ROOT / rbac_root).read_text(encoding='utf-8')
            )
            if isinstance(document, dict)
        ]
        cls.RENDERED_BY_ROOT[rbac_root] = rbac_documents
        cls.RENDERED.extend(rbac_documents)

    def test_root_sync_only_owns_business_dag_kustomizations(self) -> None:
        identities = {
            self.identity(document)
            for document in self.RENDERED_BY_ROOT['clusters/dev']
        }
        self.assertEqual(
            identities,
            {
                (
                    'kustomize.toolkit.fluxcd.io/v1',
                    'Kustomization',
                    'flux-system',
                    name,
                )
                for name in {
                    'infrastructure-foundation',
                    'cert-manager-controller',
                    'cert-manager-config',
                    'cnpg-controller',
                    'platform-database',
                    'platform-migration',
                    'platform-apps',
                }
            },
        )

    @staticmethod
    def identity(document: dict[str, object]) -> tuple[str, str, str, str]:
        metadata = document.get('metadata', {})
        assert isinstance(metadata, dict)
        return (
            str(document.get('apiVersion', '')),
            str(document.get('kind', '')),
            str(metadata.get('namespace', '')),
            str(metadata.get('name', '')),
        )

    def find(
        self,
        api_version: str,
        kind: str,
        namespace: str,
        name: str,
    ) -> dict[str, object]:
        matches = [
            document
            for document in self.RENDERED
            if self.identity(document)
            == (api_version, kind, namespace, name)
        ]
        self.assertEqual(
            len(matches),
            1,
            f'expected one {api_version}/{kind} {namespace}/{name}, '
            f'found {len(matches)}',
        )
        return matches[0]

    def test_public_validated_sync_has_no_git_secret(self) -> None:
        source = self.find(
            'source.toolkit.fluxcd.io/v1',
            'GitRepository',
            'flux-system',
            'flux-system',
        )
        spec = source['spec']
        assert isinstance(spec, dict)
        self.assertEqual(
            spec.get('url'),
            'https://github.com/unif-code/engineering-platform-gitops.git',
        )
        self.assertEqual(spec.get('ref'), {'branch': 'validated'})
        self.assertNotIn('secretRef', spec)

        sync = self.find(
            'kustomize.toolkit.fluxcd.io/v1',
            'Kustomization',
            'flux-system',
            'flux-system',
        )
        sync_spec = sync['spec']
        assert isinstance(sync_spec, dict)
        self.assertEqual(sync_spec.get('path'), './clusters/dev')
        self.assertEqual(sync_spec.get('serviceAccountName'), 'flux-root-reconciler')
        self.assertIs(sync_spec.get('wait'), False)

        egress = self.find(
            'cilium.io/v2',
            'CiliumNetworkPolicy',
            'flux-system',
            'allow-approved-git-egress',
        )
        self.assertEqual(
            egress.get('spec'),
            {
                'endpointSelector': {
                    'matchLabels': {
                        'k8s:app.kubernetes.io/component': 'source-controller'
                    }
                },
                'egress': [
                    {
                        'toEndpoints': [
                            {
                                'matchLabels': {
                                    'k8s:io.kubernetes.pod.namespace': (
                                        'kube-system'
                                    ),
                                    'k8s:k8s-app': 'kube-dns',
                                }
                            }
                        ],
                        'toPorts': [
                            {
                                'ports': [
                                    {'port': '53', 'protocol': 'ANY'}
                                ],
                                'rules': {
                                    'dns': [{'matchPattern': '*'}]
                                },
                            }
                        ],
                    },
                    {
                        'toFQDNs': [{'matchName': 'github.com'}],
                        'toPorts': [
                            {
                                'ports': [
                                    {'port': '443', 'protocol': 'TCP'}
                                ]
                            }
                        ],
                    }
                ],
            },
        )

    def test_active_namespaces_and_exclusions_are_exact(self) -> None:
        namespaces = {
            self.identity(document)[3]
            for document in self.RENDERED
            if document.get('kind') == 'Namespace'
        }
        self.assertEqual(namespaces, self.APPROVED_NAMESPACES)
        active_identities = {
            f'{kind}/{name}'.lower()
            for _, kind, _, name in map(self.identity, self.RENDERED)
            if kind != 'CustomResourceDefinition'
        }
        active_identities.discard('configmap/cnpg-default-monitoring')
        for forbidden in self.FORBIDDEN_NAMES:
            self.assertFalse(
                any(forbidden in identity for identity in active_identities),
                f'forbidden active resource matched {forbidden}',
            )

    def test_reconcile_rbac_has_no_privilege_escape(self) -> None:
        bindings = [
            document
            for document in self.RENDERED
            if document.get('kind') in {'RoleBinding', 'ClusterRoleBinding'}
        ]
        for binding in bindings:
            role_ref = binding.get('roleRef', {})
            assert isinstance(role_ref, dict)
            self.assertNotEqual(role_ref.get('name'), 'cluster-admin')

        roles = [
            document
            for document in self.RENDERED
            if document.get('kind') in {'Role', 'ClusterRole'}
            and str(document.get('metadata', {}).get('name', '')).startswith('flux-')
        ]
        deny_verbs = {'bind', 'escalate', 'impersonate'}
        for role in roles:
            for rule in role.get('rules', []):
                self.assertFalse(deny_verbs & set(rule.get('verbs', [])))
                self.assertNotIn('serviceaccounts/token', rule.get('resources', []))
                self.assertNotIn('certificatesigningrequests/approval', rule.get('resources', []))
                if 'secrets' in rule.get('resources', []):
                    self.assertFalse({'get', 'list', 'watch'} & set(rule.get('verbs', [])))

    def test_each_downstream_reconciler_has_exact_rendered_resource_permissions(
        self,
    ) -> None:
        kind_resources = {
            'Certificate': 'certificates',
            'Cluster': 'clusters',
            'ClusterIssuer': 'clusterissuers',
            'ClusterRole': 'clusterroles',
            'ClusterRoleBinding': 'clusterrolebindings',
            'CiliumNetworkPolicy': 'ciliumnetworkpolicies',
            'ConfigMap': 'configmaps',
            'CustomResourceDefinition': 'customresourcedefinitions',
            'Deployment': 'deployments',
            'Gateway': 'gateways',
            'HTTPRoute': 'httproutes',
            'Job': 'jobs',
            'MutatingWebhookConfiguration': 'mutatingwebhookconfigurations',
            'Namespace': 'namespaces',
            'NetworkPolicy': 'networkpolicies',
            'PodDisruptionBudget': 'poddisruptionbudgets',
            'ResourceQuota': 'resourcequotas',
            'Role': 'roles',
            'RoleBinding': 'rolebindings',
            'Service': 'services',
            'ServiceAccount': 'serviceaccounts',
            'StorageClass': 'storageclasses',
            'ValidatingWebhookConfiguration': 'validatingwebhookconfigurations',
        }
        assignments = {
            'infrastructure/foundation': ('ClusterRole', '', 'flux-foundation-reconciler'),
            'infrastructure/cert-manager/controller': (
                'ClusterRole', '', 'cert-manager-controller-reconciler'
            ),
            'infrastructure/cert-manager/config': (
                'ClusterRole', '', 'cert-manager-config-reconciler'
            ),
            'infrastructure/cnpg/controller': (
                'ClusterRole', '', 'cnpg-controller-reconciler'
            ),
            'infrastructure/cnpg/database': (
                'ClusterRole', '', 'flux-platform-database-reconciler'
            ),
            'apps/migration': ('Role', 'platform', 'flux-platform-migration-reconciler'),
            'apps': ('Role', 'platform', 'flux-platform-app-reconciler'),
        }
        full_verbs = {'create', 'delete', 'get', 'list', 'patch', 'update', 'watch'}
        read_verbs = {'get', 'list', 'watch'}
        health_observation_rules = {
            'Deployment': [
                {
                    'apiGroups': [''],
                    'resources': ['pods'],
                    'verbs': sorted(read_verbs),
                },
                {
                    'apiGroups': ['apps'],
                    'resources': ['replicasets'],
                    'verbs': sorted(read_verbs),
                },
            ],
            'Job': [
                {
                    'apiGroups': [''],
                    'resources': ['pods'],
                    'verbs': sorted(read_verbs),
                },
            ],
        }

        def permission_atoms(
            rules: object,
        ) -> set[tuple[str, str, str, tuple[str, ...] | None]]:
            self.assertIsInstance(rules, list)
            scopes: dict[tuple[str, str, str], set[str] | None] = {}
            for rule in rules:
                self.assertIsInstance(rule, dict)
                self.assertNotIn('nonResourceURLs', rule)
                resource_names = rule.get('resourceNames', [])
                names = (
                    {str(name) for name in resource_names}
                    if resource_names
                    else None
                )
                for api_group in rule.get('apiGroups', []):
                    for resource in rule.get('resources', []):
                        for verb in rule.get('verbs', []):
                            key = (str(api_group), str(resource), str(verb))
                            if names is None:
                                scopes[key] = None
                            elif key not in scopes:
                                scopes[key] = set(names)
                            elif scopes[key] is not None:
                                scopes[key].update(names)
            return {
                (*key, None if names is None else tuple(sorted(names)))
                for key, names in scopes.items()
            }

        for root, (kind, namespace, name) in assignments.items():
            with self.subTest(root=root):
                role = self.find('rbac.authorization.k8s.io/v1', kind, namespace, name)
                granted = permission_atoms(role.get('rules', []))
                expected_rules: list[dict[str, object]] = []
                for document in self.RENDERED_BY_ROOT[root]:
                    api_version = str(document.get('apiVersion', ''))
                    document_kind = str(document.get('kind', ''))
                    api_group = '' if api_version == 'v1' else api_version.split('/', 1)[0]
                    resource = kind_resources.get(document_kind)
                    self.assertIsNotNone(resource, self.identity(document))
                    expected_rules.append({
                        'apiGroups': [api_group],
                        'resources': [str(resource)],
                        'verbs': sorted(full_verbs),
                    })
                    expected_rules.extend(
                        health_observation_rules.get(document_kind, [])
                    )
                    if document.get('kind') in {'Role', 'ClusterRole'}:
                        expected_rules.extend(document.get('rules', []))
                expected = permission_atoms(expected_rules)
                self.assertEqual(granted, expected)

    def test_vendored_charts_render_to_digest_pinned_manifests(self) -> None:
        self.assertFalse(
            any(
                document.get('kind') in {'HelmRelease', 'HelmRepository'}
                for document in self.RENDERED
            )
        )
        for chart in ('cert-manager', 'cloudnative-pg'):
            chart_root = validator.ROOT / 'vendor/charts' / chart
            self.assertTrue((chart_root / 'Chart.yaml').is_file())
            self.assertTrue((chart_root / 'values.yaml').is_file())

        expected_images = {
            ('cert-manager', 'cert-manager'): (
                'quay.io/jetstack/cert-manager-controller@sha256:'
                '4c2b5201fd66085b777dc6b256d96d7d346b6445404cec34db5f8aea86182cc5'
            ),
            ('cert-manager', 'cert-manager-webhook'): (
                'quay.io/jetstack/cert-manager-webhook@sha256:'
                '741084291faf115a2909bfe3515458b54926c67f039ac20effd821bac69817a4'
            ),
            ('cert-manager', 'cert-manager-cainjector'): (
                'quay.io/jetstack/cert-manager-cainjector@sha256:'
                '1910ad7e134880e27d229e07affb43da1b07841a77f70c364f17467cb4e49bd9'
            ),
            ('cnpg-system', 'cloudnative-pg'): (
                'ghcr.io/cloudnative-pg/cloudnative-pg@sha256:'
                '091d306935cfdf646debfe78010d59ebfb572150eb6eb922b0203873c0c68841'
            ),
        }
        for (namespace, name), image in expected_images.items():
            deployment = self.find('apps/v1', 'Deployment', namespace, name)
            self.assertEqual(
                deployment['spec']['template']['spec']['containers'][0]['image'],
                image,
            )

    def test_database_is_no_backup_and_has_all_runtime_roles(self) -> None:
        cluster = self.find(
            'postgresql.cnpg.io/v1', 'Cluster', 'platform', 'platform'
        )
        spec = cluster['spec']
        assert isinstance(spec, dict)
        self.assertEqual(spec.get('instances'), 1)
        self.assertEqual(spec.get('imageName'), self.POSTGRES_IMAGE)
        self.assertEqual(spec.get('storage'), {
            'size': '20Gi',
            'storageClass': 'stateful-rwo-lowlatency',
        })
        roles = spec.get('managed', {}).get('roles', [])
        self.assertEqual({role.get('name') for role in roles}, self.RUNTIME_ROLES)
        for role in roles:
            self.assertTrue(role.get('login'))
            self.assertFalse(role.get('superuser'))
            self.assertIn('name', role.get('passwordSecret', {}))
        self.assertNotIn('plugins', spec)
        self.assertFalse(
            any(
                document.get('kind') in {'ObjectStore', 'ScheduledBackup'}
                for document in self.RENDERED
            )
        )

        restore_documents = yaml.safe_load_all(
            (validator.ROOT / 'runbook/examples/postgres-restore.yaml').read_text(
                encoding='utf-8'
            )
        )
        restore_cluster = next(
            document
            for document in restore_documents
            if document.get('kind') == 'Cluster'
        )
        self.assertEqual(
            restore_cluster['spec'].get('imageName'), self.POSTGRES_IMAGE
        )

    def test_migration_and_apps_are_immutable_and_ordered(self) -> None:
        migration = self.find(
            'batch/v1',
            'Job',
            'platform',
            'platform-migrate-4aaf721-g2',
        )
        self.assertEqual(
            migration['metadata']['annotations'].get(
                'platform.unif.internal/migration-generation'
            ),
            '2',
        )
        migration_container = migration['spec']['template']['spec']['containers'][0]
        self.assertEqual(migration_container.get('image'), self.BACKEND_IMAGE)
        self.assertEqual(migration['spec'].get('backoffLimit'), 0)

        images = {
            'frontend': self.FRONTEND_IMAGE,
            'backend': self.BACKEND_IMAGE,
        }
        for name, image in images.items():
            deployment = self.find('apps/v1', 'Deployment', 'platform', name)
            pod_spec = deployment['spec']['template']['spec']
            container = pod_spec['containers'][0]
            self.assertEqual(container.get('image'), image)
            self.assertTrue(container.get('securityContext', {}).get('runAsNonRoot'))
            self.assertTrue(container.get('securityContext', {}).get('readOnlyRootFilesystem'))
            self.assertEqual(
                container.get('securityContext', {}).get('capabilities', {}).get('drop'),
                ['ALL'],
            )

        apps = self.find(
            'kustomize.toolkit.fluxcd.io/v1',
            'Kustomization',
            'flux-system',
            'platform-apps',
        )
        self.assertEqual(
            apps['spec'].get('dependsOn'),
            [
                {'name': 'platform-migration'},
                {'name': 'cert-manager-config'},
            ],
        )

    def test_backend_secret_contract_is_file_only(self) -> None:
        deployment = self.find('apps/v1', 'Deployment', 'platform', 'backend')
        pod_spec = deployment['spec']['template']['spec']
        container = pod_spec['containers'][0]
        self.assertNotIn('env', container)
        self.assertNotIn('envFrom', container)
        mounts = {mount['mountPath']: mount for mount in container.get('volumeMounts', [])}
        self.assertIn('/app/.env', mounts)
        self.assertTrue(mounts['/app/.env'].get('readOnly'))
        secret_volumes = [
            volume for volume in pod_spec.get('volumes', []) if 'secret' in volume
        ]
        self.assertEqual(len(secret_volumes), 4)

    def test_gateway_is_https_only_and_routes_same_origin(self) -> None:
        certificate = self.find(
            'cert-manager.io/v1',
            'Certificate',
            'platform',
            'platform-gateway-tls',
        )
        self.assertEqual(
            certificate['spec'].get('commonName'),
            'platform.dev.local',
        )
        self.assertEqual(
            certificate['spec'].get('dnsNames'),
            ['platform.dev.local'],
        )
        self.assertEqual(
            certificate['spec'].get('issuerRef'),
            {
                'kind': 'ClusterIssuer',
                'name': 'dev-selfsigned',
            },
        )
        issuer = self.find(
            'cert-manager.io/v1',
            'ClusterIssuer',
            '',
            'dev-selfsigned',
        )
        self.assertEqual(issuer.get('spec'), {'selfSigned': {}})

        gateway = self.find(
            'gateway.networking.k8s.io/v1',
            'Gateway',
            'platform',
            'platform-gateway',
        )
        listeners = gateway['spec'].get('listeners', [])
        self.assertEqual(len(listeners), 1)
        self.assertEqual(listeners[0].get('protocol'), 'HTTPS')
        self.assertEqual(listeners[0].get('port'), 443)

        route = self.find(
            'gateway.networking.k8s.io/v1',
            'HTTPRoute',
            'platform',
            'platform',
        )
        self.assertEqual(route['spec'].get('hostnames'), ['platform.dev.local'])
        backend_names = {
            backend.get('name')
            for rule in route['spec'].get('rules', [])
            for backend in rule.get('backendRefs', [])
        }
        self.assertEqual(backend_names, {'backend', 'frontend'})
        self.assertFalse(any(document.get('kind') == 'Ingress' for document in self.RENDERED))
        for document in self.RENDERED:
            if document.get('kind') == 'Service':
                self.assertNotIn(
                    document.get('spec', {}).get('type'),
                    {'LoadBalancer', 'NodePort'},
                )

    def test_every_active_namespace_is_default_deny_with_exact_dns_egress(
        self,
    ) -> None:
        default_deny_namespaces = {
            self.identity(document)[2]
            for document in self.RENDERED
            if document.get('kind') == 'NetworkPolicy'
            and self.identity(document)[3] == 'default-deny'
            and document.get('spec') == {
                'podSelector': {},
                'policyTypes': ['Ingress', 'Egress'],
            }
        }
        dns_namespaces = {
            self.identity(document)[2]
            for document in self.RENDERED
            if document.get('kind') == 'NetworkPolicy'
            and self.identity(document)[3] == 'allow-dns-egress'
        }
        self.assertEqual(default_deny_namespaces, self.APPROVED_NAMESPACES)
        self.assertEqual(dns_namespaces, self.APPROVED_NAMESPACES)

    def test_cnpg_operator_can_read_instance_status_only_on_tcp_8000(
        self,
    ) -> None:
        ingress_policy = self.find(
            'networking.k8s.io/v1',
            'NetworkPolicy',
            'platform',
            'platform-postgres-ingress',
        )
        self.assertEqual(
            ingress_policy.get('spec'),
            {
                'podSelector': {
                    'matchLabels': {'cnpg.io/cluster': 'platform'}
                },
                'policyTypes': ['Ingress'],
                'ingress': [
                    {
                        'from': [
                            {
                                'podSelector': {
                                    'matchExpressions': [
                                        {
                                            'key': 'app.kubernetes.io/name',
                                            'operator': 'In',
                                            'values': [
                                                'backend',
                                                'platform-migration',
                                            ],
                                        }
                                    ]
                                }
                            }
                        ],
                        'ports': [{'port': 5432, 'protocol': 'TCP'}],
                    },
                    {
                        'from': [
                            {
                                'namespaceSelector': {
                                    'matchLabels': {
                                        'kubernetes.io/metadata.name': (
                                            'cnpg-system'
                                        )
                                    }
                                },
                                'podSelector': {
                                    'matchLabels': {
                                        'app.kubernetes.io/name': (
                                            'cloudnative-pg'
                                        ),
                                        'app.kubernetes.io/instance': (
                                            'cloudnative-pg'
                                        ),
                                    }
                                },
                            }
                        ],
                        'ports': [{'port': 8000, 'protocol': 'TCP'}],
                    },
                ],
            },
        )
        egress_policy = self.find(
            'networking.k8s.io/v1',
            'NetworkPolicy',
            'cnpg-system',
            'allow-instance-status-egress',
        )
        self.assertEqual(
            egress_policy.get('spec'),
            {
                'podSelector': {
                    'matchLabels': {
                        'app.kubernetes.io/name': 'cloudnative-pg',
                        'app.kubernetes.io/instance': 'cloudnative-pg',
                    }
                },
                'policyTypes': ['Egress'],
                'egress': [
                    {
                        'to': [
                            {
                                'namespaceSelector': {
                                    'matchLabels': {
                                        'kubernetes.io/metadata.name': (
                                            'platform'
                                        )
                                    }
                                },
                                'podSelector': {
                                    'matchLabels': {
                                        'cnpg.io/cluster': 'platform'
                                    }
                                },
                            }
                        ],
                        'ports': [{'port': 8000, 'protocol': 'TCP'}],
                    }
                ],
            },
        )

    def test_gateway_and_control_plane_exceptions_use_cilium_entities(self) -> None:
        expected = {
            ('cert-manager', 'allow-kube-apiserver-egress'),
            ('cert-manager', 'allow-kube-apiserver-webhook-ingress'),
            ('cnpg-system', 'allow-kube-apiserver-egress'),
            ('cnpg-system', 'allow-kube-apiserver-webhook-ingress'),
            ('local-path-storage', 'allow-kube-apiserver-egress'),
            ('platform', 'allow-kube-apiserver-egress'),
            ('platform', 'allow-gateway-backend-ingress'),
            ('platform', 'allow-gateway-frontend-ingress'),
        }
        policies = {
            (self.identity(document)[2], self.identity(document)[3]): document
            for document in self.RENDERED
            if document.get('kind') == 'CiliumNetworkPolicy'
        }
        for identity in expected:
            with self.subTest(identity=identity):
                self.assertIn(identity, policies)
        for name in ('allow-gateway-backend-ingress', 'allow-gateway-frontend-ingress'):
            ingress_rules = policies[('platform', name)]['spec'].get('ingress', [])
            self.assertEqual(ingress_rules[0].get('fromEntities'), ['ingress'])
        for namespace, name in expected - {
            ('platform', 'allow-gateway-backend-ingress'),
            ('platform', 'allow-gateway-frontend-ingress'),
        }:
            rules = policies[(namespace, name)]['spec']
            direction = 'ingress' if name.endswith('webhook-ingress') else 'egress'
            entity_key = 'fromEntities' if direction == 'ingress' else 'toEntities'
            self.assertEqual(rules[direction][0].get(entity_key), ['kube-apiserver'])

class FluxPhaseAContractTest(_FluxPhaseAContractBase, unittest.TestCase):
    def phase_a_network_policy_documents(self) -> list[dict[str, object]]:
        return [
            {
                'apiVersion': 'networking.k8s.io/v1',
                'kind': 'NetworkPolicy',
                'metadata': {
                    'name': 'default-deny',
                    'namespace': 'flux-system',
                },
                'spec': {
                    'podSelector': {},
                    'policyTypes': ['Ingress', 'Egress'],
                },
            },
            {
                'apiVersion': 'networking.k8s.io/v1',
                'kind': 'NetworkPolicy',
                'metadata': {
                    'name': 'allow-dns-egress',
                    'namespace': 'flux-system',
                },
                'spec': {
                    'podSelector': {
                        'matchLabels': {'app.kubernetes.io/part-of': 'flux'}
                    },
                    'policyTypes': ['Egress'],
                    'egress': [
                        {
                            'to': [
                                {
                                    'namespaceSelector': {
                                        'matchLabels': {
                                            'kubernetes.io/metadata.name': (
                                                'kube-system'
                                            )
                                        }
                                    },
                                    'podSelector': {
                                        'matchLabels': {'k8s-app': 'kube-dns'}
                                    },
                                }
                            ],
                            'ports': [
                                {'port': 53, 'protocol': 'TCP'},
                                {'port': 53, 'protocol': 'UDP'},
                            ],
                        }
                    ],
                },
            },
            {
                'apiVersion': 'networking.k8s.io/v1',
                'kind': 'NetworkPolicy',
                'metadata': {
                    'name': 'allow-controller-internal-ingress',
                    'namespace': 'flux-system',
                },
                'spec': {
                    'podSelector': {
                        'matchExpressions': [
                            {
                                'key': 'app.kubernetes.io/component',
                                'operator': 'In',
                                'values': [
                                    'source-controller',
                                    'notification-controller',
                                ],
                            }
                        ]
                    },
                    'policyTypes': ['Ingress'],
                    'ingress': [
                        {
                            'from': [
                                {
                                    'podSelector': {
                                        'matchLabels': {
                                            'app.kubernetes.io/part-of': 'flux'
                                        }
                                    },
                                }
                            ],
                            'ports': [{'port': 9090, 'protocol': 'TCP'}],
                        }
                    ],
                },
            },
            {
                'apiVersion': 'networking.k8s.io/v1',
                'kind': 'NetworkPolicy',
                'metadata': {
                    'name': 'allow-controller-internal-egress',
                    'namespace': 'flux-system',
                },
                'spec': {
                    'podSelector': {
                        'matchLabels': {'app.kubernetes.io/part-of': 'flux'}
                    },
                    'policyTypes': ['Egress'],
                    'egress': [
                        {
                            'to': [
                                {
                                    'podSelector': {
                                        'matchExpressions': [
                                            {
                                                'key': (
                                                    'app.kubernetes.io/component'
                                                ),
                                                'operator': 'In',
                                                'values': [
                                                    'source-controller',
                                                    'notification-controller',
                                                ],
                                            }
                                        ]
                                    },
                                }
                            ],
                            'ports': [{'port': 9090, 'protocol': 'TCP'}],
                        }
                    ],
                },
            },
            {
                'apiVersion': 'cilium.io/v2',
                'kind': 'CiliumNetworkPolicy',
                'metadata': {
                    'name': 'allow-kube-apiserver-egress',
                    'namespace': 'flux-system',
                },
                'spec': {
                    'endpointSelector': {
                        'matchLabels': {
                            'k8s:app.kubernetes.io/part-of': 'flux'
                        }
                    },
                    'egress': [{'toEntities': ['kube-apiserver']}],
                },
            },
        ]

    def make_root(self) -> tuple[Path, list[dict[str, object]]]:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        cluster = root / 'clusters/dev'
        flux = cluster / 'flux-system'
        phase_a = flux / 'phase-a'
        phase_a.mkdir(parents=True)

        (cluster / 'kustomization.yaml').write_text(
            yaml.safe_dump(
                {
                    'apiVersion': 'kustomize.config.k8s.io/v1beta1',
                    'kind': 'Kustomization',
                    'resources': ['flux-system'],
                },
                sort_keys=False,
            ),
            encoding='utf-8',
        )
        (phase_a / 'kustomization.yaml').write_text(
            yaml.safe_dump(
                {
                    'apiVersion': 'kustomize.config.k8s.io/v1beta1',
                    'kind': 'Kustomization',
                    'resources': [
                        'gotk-components.yaml',
                        'phase-a-rbac.yaml',
                        'phase-a-network-policy.yaml',
                    ],
                    'images': [
                        {
                            'name': f'ghcr.io/fluxcd/{name}',
                            'digest': contract['digest'],
                        }
                        for name, contract in self.CONTROLLERS.items()
                    ],
                },
                sort_keys=False,
            ),
            encoding='utf-8',
        )
        namespace = {
            'apiVersion': 'v1',
            'kind': 'Namespace',
            'metadata': {'name': 'flux-system', 'labels': self.PSS_LABELS},
        }
        component_documents = [
            namespace,
            {
                'apiVersion': 'v1',
                'kind': 'ResourceQuota',
                'metadata': {
                    'name': 'critical-pods-flux-system',
                    'namespace': 'flux-system',
                },
            },
            *(
                {
                    'apiVersion': 'apiextensions.k8s.io/v1',
                    'kind': 'CustomResourceDefinition',
                    'metadata': {'name': name},
                }
                for name in self.CRDS
            ),
            *(
                {
                    'apiVersion': 'v1',
                    'kind': 'ServiceAccount',
                    'metadata': {'name': name, 'namespace': 'flux-system'},
                }
                for name in self.CONTROLLER_SERVICE_ACCOUNTS
            ),
            *(
                {
                    'apiVersion': 'v1',
                    'kind': 'Service',
                    'metadata': {'name': name, 'namespace': 'flux-system'},
                    'spec': copy.deepcopy(spec),
                }
                for name, spec in self.SERVICES.items()
            ),
            *(
                self.make_deployment(
                    name,
                    f'ghcr.io/fluxcd/{name}:{contract["tag"]}',
                )
                for name, contract in self.CONTROLLERS.items()
            ),
        ]
        (phase_a / 'gotk-components.yaml').write_bytes(
            (
                validator.ROOT
                / 'clusters/dev/flux-system/phase-a/gotk-components.yaml'
            ).read_bytes()
        )
        rbac_documents = self.phase_a_rbac_documents()
        (phase_a / 'phase-a-rbac.yaml').write_text(
            yaml.safe_dump_all(rbac_documents, sort_keys=False),
            encoding='utf-8',
        )
        network_policy_documents = self.phase_a_network_policy_documents()
        (phase_a / 'phase-a-network-policy.yaml').write_text(
            yaml.safe_dump_all(network_policy_documents, sort_keys=False),
            encoding='utf-8',
        )

        rendered_documents = copy.deepcopy(self.RENDERED_BASELINE)
        return root, rendered_documents

    def deployment(
        self,
        documents: list[dict[str, object]],
        name: str,
    ) -> dict[str, object]:
        return next(
            document
            for document in documents
            if document.get('kind') == 'Deployment'
            and document.get('metadata', {}).get('name') == name
        )

    def resource(
        self,
        documents: list[dict[str, object]],
        kind: str,
        name: str,
    ) -> dict[str, object]:
        return next(
            document
            for document in documents
            if document.get('kind') == kind
            and document.get('metadata', {}).get('name') == name
        )

    def validate(
        self,
        root: Path,
        rendered_documents: list[dict[str, object]],
    ) -> None:
        render = subprocess.CompletedProcess(
            args=[
                'kubectl',
                'kustomize',
                str(root / 'clusters/dev/flux-system/phase-a'),
            ],
            returncode=0,
            stdout='rendered fixture',
            stderr='',
        )
        original_parse = validator.parse_yaml_documents

        def parse_documents(
            source: str,
            label: str,
        ) -> list[dict[str, object]]:
            if label == 'Flux Phase A rendered output':
                return copy.deepcopy(rendered_documents)
            return original_parse(source, label)

        with (
            mock.patch.object(validator.subprocess, 'run', return_value=render),
            mock.patch.object(
                validator,
                'parse_yaml_documents',
                side_effect=parse_documents,
            ),
        ):
            validator.validate_flux_phase_a(root)

    def assert_contract_fails(
        self,
        root: Path,
        rendered_documents: list[dict[str, object]],
        expected: str,
    ) -> None:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            self.validate(root, rendered_documents)
        self.assertEqual(raised.exception.code, 1)
        self.assertRegex(stderr.getvalue(), expected)

    def make_probe_root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for relative in (
            'runbook/01-bootstrap.md',
            'runbook/examples/flux-phase-a-network-probe.yaml',
            'runbook/examples/flux-phase-a-external-network-probe.yaml',
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(validator.ROOT / relative, target)
        return root

    def make_runtime_record_root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for relative in (
            'docs/superpowers/plans/2026-08-24-flux-phase-a.md',
            'docs/superpowers/progress/current.md',
            'pcs/candidate-2.md',
            'runbook/01-bootstrap.md',
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(validator.ROOT / relative, target)
        return root

    def assert_probe_contract_fails(self, root: Path, expected: str) -> None:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            validator.validate_flux_phase_a_probes(root)
        self.assertEqual(raised.exception.code, 1)
        self.assertRegex(stderr.getvalue(), expected)

    def assert_runbook_contract_fails(self, root: Path, expected: str) -> None:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            validator.validate_flux_phase_a_runbook(root)
        self.assertEqual(raised.exception.code, 1)
        self.assertRegex(stderr.getvalue(), expected)

    def assert_runtime_record_fails(self, root: Path, expected: str) -> None:
        stderr = io.StringIO()
        with (
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            validator.validate_flux_phase_a_runtime_record(root)
        self.assertEqual(raised.exception.code, 1)
        self.assertRegex(stderr.getvalue(), expected)

    def write_client_create_runbook(self, root: Path) -> None:
        path = root / 'runbook/01-bootstrap.md'
        source = path.read_text(encoding='utf-8')
        client_apply = (
            'kubectl --kubeconfig="$KC" apply --dry-run=client \\\n'
            '  -k clusters/dev/flux-system/phase-a'
        )
        client_create = (
            'kubectl --kubeconfig="$KC" create --dry-run=client \\\n'
            '  -k clusters/dev/flux-system/phase-a'
        )
        if client_create not in source:
            self.assertEqual(source.count(client_apply), 1)
            source = source.replace(client_apply, client_create)
        self.assertEqual(source.count(client_create), 1)
        path.write_text(source, encoding='utf-8')

    def test_valid_four_controller_fixture_is_accepted(self) -> None:
        root, rendered_documents = self.make_root()

        self.validate(root, rendered_documents)

    def test_valid_phase_a_runbook_stages_namespace_before_server_validation(
        self,
    ) -> None:
        validator.validate_flux_phase_a_runbook(self.make_probe_root())

    def test_accepts_phase_a_client_create_dry_run(self) -> None:
        root = self.make_probe_root()
        self.write_client_create_runbook(root)

        validator.validate_flux_phase_a_runbook(root)

    def test_rejects_phase_a_client_apply_patch_simulation(self) -> None:
        root = self.make_probe_root()
        self.write_client_create_runbook(root)
        path = root / 'runbook/01-bootstrap.md'
        source = path.read_text(encoding='utf-8')
        client_create = (
            'kubectl --kubeconfig="$KC" create --dry-run=client \\\n'
            '  -k clusters/dev/flux-system/phase-a'
        )
        client_apply = (
            'kubectl --kubeconfig="$KC" apply --dry-run=client \\\n'
            '  -k clusters/dev/flux-system/phase-a'
        )
        self.assertEqual(source.count(client_create), 1)
        path.write_text(
            source.replace(client_create, client_apply),
            encoding='utf-8',
        )

        self.assert_runbook_contract_fails(
            root, 'client dry-run.*kubectl apply'
        )

    def test_rejects_phase_a_runbook_staging_regressions(self) -> None:
        mutations = (
            (
                'missing-namespace-persistence',
                "render_flux_namespace |\n  kubectl --kubeconfig=\"$KC\" apply "
                "--server-side \\\n    --field-manager=\"$FIELD_MANAGER\" \\\n    -f -\n",
                '',
                'Namespace 持久化',
            ),
            (
                'full-dry-run-before-namespace',
                "render_flux_namespace |\n  kubectl --kubeconfig=\"$KC\" apply "
                "--server-side \\\n    --field-manager=\"$FIELD_MANAGER\" \\\n    -f -\n",
                "kubectl --kubeconfig=\"$KC\" apply --server-side \\\n"
                "  --dry-run=server \\\n"
                "  --field-manager=\"$FIELD_MANAGER\" \\\n"
                "  -k clusters/dev/flux-system/phase-a\n\n"
                "render_flux_namespace |\n"
                "  kubectl --kubeconfig=\"$KC\" apply --server-side \\\n"
                "    --field-manager=\"$FIELD_MANAGER\" \\\n"
                "    -f -\n",
                '执行顺序',
            ),
            (
                'diff-exit-one-rejected',
                '  0|1)\n',
                '  0)\n',
                'diff.*0/1',
            ),
        )
        for mutation, old, new, expected in mutations:
            with self.subTest(mutation=mutation):
                root = self.make_probe_root()
                path = root / 'runbook/01-bootstrap.md'
                source = path.read_text(encoding='utf-8')
                self.assertEqual(source.count(old), 1)
                path.write_text(source.replace(old, new), encoding='utf-8')
                self.assert_runbook_contract_fails(root, expected)

    def test_phase_a_runtime_record_is_complete_and_cross_file_consistent(
        self,
    ) -> None:
        validator.validate_flux_phase_a_runtime_record(
            self.make_runtime_record_root()
        )

    def test_rejects_stale_or_inconsistent_phase_a_runtime_record(self) -> None:
        mutations = (
            (
                'runbook-status',
                'runbook/01-bootstrap.md',
                'PHASE_A_CONTROLLERS_DEPLOYED_SYNC_INACTIVE',
                'NOT_EXECUTED',
                'Runbook.*状态',
            ),
            (
                'approved-sha',
                'pcs/candidate-2.md',
                '685198db15299fdb6b8cdffd72162a4864c8666b',
                '785198db15299fdb6b8cdffd72162a4864c8666b',
                '批准 SHA',
            ),
            (
                'evidence-sha',
                'runbook/01-bootstrap.md',
                '2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7',
                '3e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7',
                '证据 SHA-256',
            ),
            (
                'plan-status',
                'docs/superpowers/plans/2026-08-24-flux-phase-a.md',
                '执行状态：`COMPLETED`',
                '执行状态：`IN_PROGRESS`',
                '计划状态',
            ),
            (
                'progress-plan',
                'docs/superpowers/progress/current.md',
                'Active Plan: docs/superpowers/plans/2026-08-24-flux-phase-a.md',
                'Active Plan: docs/superpowers/plans/2026-08-19-bootstrap-stage-decoupling.md',
                'current.md',
            ),
        )
        for mutation, relative, old, new, expected in mutations:
            with self.subTest(mutation=mutation):
                root = self.make_runtime_record_root()
                path = root / relative
                source = path.read_text(encoding='utf-8')
                self.assertGreaterEqual(source.count(old), 1)
                path.write_text(source.replace(old, new, 1), encoding='utf-8')
                self.assert_runtime_record_fails(root, expected)

    def test_valid_transient_probe_contract_is_accepted(self) -> None:
        validator.validate_flux_phase_a_probes(self.make_probe_root())

    def test_rejects_transient_probe_manifest_drift(self) -> None:
        mutations = (
            'fixed-name',
            'missing-generate-name',
            'tag-image',
            'token',
            'restart',
            'root-filesystem',
            'resources',
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                root = self.make_probe_root()
                path = (
                    root
                    / 'runbook/examples/flux-phase-a-network-probe.yaml'
                )
                document = yaml.safe_load(path.read_text(encoding='utf-8'))
                if mutation == 'fixed-name':
                    document['metadata']['name'] = 'flux-phase-a-probe'
                elif mutation == 'missing-generate-name':
                    del document['metadata']['generateName']
                elif mutation == 'tag-image':
                    document['spec']['containers'][0]['image'] = 'busybox:latest'
                elif mutation == 'token':
                    document['spec']['automountServiceAccountToken'] = True
                elif mutation == 'restart':
                    document['spec']['restartPolicy'] = 'Always'
                elif mutation == 'root-filesystem':
                    document['spec']['containers'][0]['securityContext'][
                        'readOnlyRootFilesystem'
                    ] = False
                else:
                    del document['spec']['containers'][0]['resources']
                path.write_text(
                    yaml.safe_dump(document, sort_keys=False),
                    encoding='utf-8',
                )
                self.assert_probe_contract_fails(
                    root,
                    'probe|generateName|namespace|labels|BusyBox|Token|Never|'
                    'non-root|RootFS|资源',
                )

    def test_rejects_transient_probe_runbook_drift(self) -> None:
        mutations = (
            'apply',
            'missing-uid-capture',
            'missing-uid-check',
            'missing-ignore-not-found',
            'swallowed-get-error',
            'missing-public-control',
            'old-probes-file',
            'label-delete',
            'missing-8080-negative',
            'missing-9292-negative',
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                root = self.make_probe_root()
                path = root / 'runbook/01-bootstrap.md'
                source = path.read_text(encoding='utf-8')
                if mutation == 'apply':
                    source = source.replace(
                        'create -f runbook/examples/flux-phase-a-network-probe.yaml',
                        'apply -f runbook/examples/flux-phase-a-network-probe.yaml',
                        1,
                    )
                elif mutation == 'missing-uid-capture':
                    source = source.replace(
                        "{.metadata.name}:{.metadata.uid}",
                        '{.metadata.name}',
                    )
                elif mutation == 'missing-uid-check':
                    source = source.replace(
                        'if [ "$current_uid" != "$expected_uid" ]',
                        'if [ "$current_uid" = "$expected_uid" ]',
                        1,
                    )
                elif mutation == 'missing-ignore-not-found':
                    source = source.replace(
                        'get pod "$pod_name" --ignore-not-found',
                        'get pod "$pod_name"',
                        1,
                    )
                elif mutation == 'swallowed-get-error':
                    source = source.replace(
                        "-o jsonpath='{.metadata.uid}'); then",
                        "-o jsonpath='{.metadata.uid}' || true); then",
                        1,
                    )
                elif mutation == 'missing-public-control':
                    source = source.replace(
                        'exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- '
                        'nc -z -w 5 github.com 443',
                        'exec "$FLUX_PHASE_A_EXTERNAL_PROBE_POD" -- '
                        'nc -z -w 5 example.invalid 443',
                        1,
                    )
                elif mutation == 'old-probes-file':
                    section_end = source.find(
                        '\n判定：', source.find('网络证据使用')
                    )
                    source = (
                        source[:section_end]
                        + '\nlegacy: runbook/examples/probes.yaml\n'
                        + source[section_end:]
                    )
                elif mutation == 'label-delete':
                    section_end = source.find(
                        '\n判定：', source.find('网络证据使用')
                    )
                    source = (
                        source[:section_end]
                        + '\nkubectl delete pods -l app=network-probe\n'
                        + source[section_end:]
                    )
                elif mutation == 'missing-8080-negative':
                    source = source.replace(
                        '"$FLUX_PHASE_A_SOURCE_POD_IP" 8080',
                        '"$FLUX_PHASE_A_SOURCE_POD_IP" 8081',
                        1,
                    )
                else:
                    source = source.replace(
                        '"$FLUX_PHASE_A_NOTIFICATION_POD_IP" 9292',
                        '"$FLUX_PHASE_A_NOTIFICATION_POD_IP" 9293',
                        1,
                    )
                path.write_text(source, encoding='utf-8')
                self.assert_probe_contract_fails(
                    root,
                    'probe runbook|kubectl create|name:uid|UID|8080|9292|'
                    'github.com|正向|probes.yaml|apply|标签',
                )

    def test_rejects_blocked_public_probe_control(self) -> None:
        root = self.make_probe_root()
        path = root / 'runbook/01-bootstrap.md'
        source = path.read_text(encoding='utf-8').replace(
            'github.com 443',
            '1.1.1.1 443',
        )
        path.write_text(source, encoding='utf-8')
        self.assert_probe_contract_fails(
            root,
            'github.com|公网正对照|1.1.1.1',
        )

    def test_rejects_components_bundle_sha_drift(self) -> None:
        root, rendered_documents = self.make_root()
        components = (
            root / 'clusters/dev/flux-system/phase-a/gotk-components.yaml'
        )
        components.write_bytes(components.read_bytes() + b'\n# drift\n')

        self.assert_contract_fails(
            root, rendered_documents, 'gotk-components|SHA-256|sha256|bundle'
        )

    def test_rejects_missing_or_extra_controller_deployment(self) -> None:
        for name in self.CONTROLLERS:
            with self.subTest(missing=name):
                root, rendered_documents = self.make_root()
                rendered_documents.remove(
                    self.deployment(rendered_documents, name)
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'Deployment|controller'
                )

        for name in (
            'image-reflector-controller',
            'image-automation-controller',
            'source-watcher',
        ):
            with self.subTest(extra=name):
                root, rendered_documents = self.make_root()
                extra = copy.deepcopy(
                    self.deployment(rendered_documents, 'source-controller')
                )
                extra['metadata']['name'] = name
                rendered_documents.append(extra)
                self.assert_contract_fails(
                    root, rendered_documents, 'Deployment|controller'
                )

    def test_requires_exact_controller_service_accounts(self) -> None:
        for name in self.CONTROLLER_SERVICE_ACCOUNTS:
            with self.subTest(missing=name):
                root, rendered_documents = self.make_root()
                rendered_documents.remove(
                    self.resource(rendered_documents, 'ServiceAccount', name)
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'ServiceAccount|controller|四'
                )

        root, rendered_documents = self.make_root()
        rendered_documents.append(
            {
                'apiVersion': 'v1',
                'kind': 'ServiceAccount',
                'metadata': {
                    'name': 'image-reflector-controller',
                    'namespace': 'flux-system',
                },
            }
        )
        self.assert_contract_fails(
            root, rendered_documents, 'ServiceAccount|controller|四'
        )

        root, rendered_documents = self.make_root()
        rendered_documents.append(
            copy.deepcopy(
                self.resource(
                    rendered_documents,
                    'ServiceAccount',
                    'source-controller',
                )
            )
        )
        self.assert_contract_fails(
            root, rendered_documents, 'ServiceAccount|controller|四'
        )

    def test_requires_exact_rendered_identity_inventory(self) -> None:
        mutations = (
            'extra-configmap',
            'missing-service',
            'renamed-quota',
            'missing-crd',
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                root, rendered_documents = self.make_root()
                if mutation == 'extra-configmap':
                    rendered_documents.append(
                        {
                            'apiVersion': 'v1',
                            'kind': 'ConfigMap',
                            'metadata': {
                                'name': 'unexpected',
                                'namespace': 'flux-system',
                            },
                        }
                    )
                elif mutation == 'missing-service':
                    rendered_documents.remove(
                        self.resource(
                            rendered_documents, 'Service', 'source-controller'
                        )
                    )
                elif mutation == 'renamed-quota':
                    self.resource(
                        rendered_documents,
                        'ResourceQuota',
                        'critical-pods-flux-system',
                    )['metadata']['name'] = 'other-quota'
                else:
                    rendered_documents.remove(
                        self.resource(
                            rendered_documents,
                            'CustomResourceDefinition',
                            self.CRDS[0],
                        )
                    )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'identity|inventory|39|ConfigMap|Service|ResourceQuota|'
                    'CustomResourceDefinition',
                )

    def test_rejects_service_contract_drift(self) -> None:
        mutations = (
            ('notification-controller', 'targetPort', 8080),
            ('source-controller', 'selector', {'app': 'other'}),
            ('webhook-receiver', 'port', 8080),
        )
        for name, field, value in mutations:
            with self.subTest(service=name, field=field):
                root, rendered_documents = self.make_root()
                service = self.resource(rendered_documents, 'Service', name)
                if field == 'selector':
                    service['spec']['selector'] = value
                else:
                    service['spec']['ports'][0][field] = value
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'Service|selector|port|targetPort|ClusterIP',
                )

    def test_rejects_rollout_strategy_drift(self) -> None:
        for name in self.CONTROLLERS:
            with self.subTest(controller=name):
                root, rendered_documents = self.make_root()
                deployment = self.deployment(rendered_documents, name)
                deployment['spec']['strategy']['rollingUpdate'][
                    'maxUnavailable'
                ] = 1
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'RollingUpdate|maxSurge|maxUnavailable|strategy',
                )

        root, rendered_documents = self.make_root()
        self.deployment(rendered_documents, 'source-controller')['spec'][
            'strategy'
        ] = {'type': 'Recreate'}
        self.assert_contract_fails(
            root,
            rendered_documents,
            'RollingUpdate|maxSurge|maxUnavailable|strategy',
        )

    def test_rendered_bundle_digest_rejects_unlisted_field_drift(self) -> None:
        mutations = (
            'replicas',
            'runtime-namespace',
            'automount-token',
            'image-pull-policy',
            'source-data-mount',
            'selector-template-mismatch',
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                root, rendered_documents = self.make_root()
                deployment = self.deployment(
                    rendered_documents, 'source-controller'
                )
                pod_spec = deployment['spec']['template']['spec']
                manager = pod_spec['containers'][0]
                if mutation == 'replicas':
                    deployment['spec']['replicas'] = 0
                elif mutation == 'runtime-namespace':
                    runtime_namespace = next(
                        item
                        for item in manager['env']
                        if item.get('name') == 'RUNTIME_NAMESPACE'
                    )
                    runtime_namespace['valueFrom']['fieldRef'][
                        'fieldPath'
                    ] = 'metadata.name'
                elif mutation == 'automount-token':
                    pod_spec['automountServiceAccountToken'] = False
                elif mutation == 'image-pull-policy':
                    manager['imagePullPolicy'] = 'Never'
                elif mutation == 'source-data-mount':
                    manager['volumeMounts'] = [
                        mount
                        for mount in manager['volumeMounts']
                        if mount.get('mountPath') != '/data'
                    ]
                else:
                    deployment['spec']['selector']['matchLabels']['app'] = (
                        'other-controller'
                    )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'rendered bundle|canonical|SHA-256|digest',
                )

    def test_rejects_tag_only_or_wrong_rendered_image(self) -> None:
        for name, contract in self.CONTROLLERS.items():
            with self.subTest(controller=name, mutation='tag-only'):
                root, rendered_documents = self.make_root()
                container = self.deployment(
                    rendered_documents, name
                )['spec']['template']['spec']['containers'][0]
                container['image'] = f'ghcr.io/fluxcd/{name}:{contract["tag"]}'
                self.assert_contract_fails(
                    root, rendered_documents, 'digest|image'
                )

            with self.subTest(controller=name, mutation='wrong-digest'):
                root, rendered_documents = self.make_root()
                container = self.deployment(
                    rendered_documents, name
                )['spec']['template']['spec']['containers'][0]
                container['image'] = f'ghcr.io/fluxcd/{name}@sha256:{"0" * 64}'
                self.assert_contract_fails(
                    root, rendered_documents, 'digest|image'
                )

    def test_rejects_active_sync_reference(self) -> None:
        root, rendered_documents = self.make_root()
        flux = root / 'clusters/dev/flux-system/phase-a'
        kustomization = yaml.safe_load(
            (flux / 'kustomization.yaml').read_text(encoding='utf-8')
        )
        kustomization['resources'].append('gotk-sync.yaml')
        (flux / 'kustomization.yaml').write_text(
            yaml.safe_dump(kustomization, sort_keys=False), encoding='utf-8'
        )

        self.assert_contract_fails(
            root, rendered_documents, 'gotk-components|gotk-sync|resources|sync'
        )

    def test_requires_exact_phase_a_managed_resources(self) -> None:
        required = (
            'gotk-components.yaml',
            'phase-a-rbac.yaml',
            'phase-a-network-policy.yaml',
        )
        for missing in required:
            with self.subTest(missing=missing):
                root, rendered_documents = self.make_root()
                path = root / 'clusters/dev/flux-system/phase-a/kustomization.yaml'
                kustomization = yaml.safe_load(path.read_text(encoding='utf-8'))
                kustomization['resources'].remove(missing)
                path.write_text(
                    yaml.safe_dump(kustomization, sort_keys=False),
                    encoding='utf-8',
                )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'gotk-components|phase-a-rbac|phase-a-network-policy|resources',
                )

    def test_rejects_any_flux_custom_resource_instance(self) -> None:
        resources = (
            ('source.toolkit.fluxcd.io/v1', 'GitRepository'),
            ('source.toolkit.fluxcd.io/v1', 'HelmRepository'),
            ('source.toolkit.fluxcd.io/v1beta2', 'OCIRepository'),
            ('source.toolkit.fluxcd.io/v1', 'Bucket'),
            ('kustomize.toolkit.fluxcd.io/v1', 'Kustomization'),
            ('helm.toolkit.fluxcd.io/v2', 'HelmRelease'),
            ('notification.toolkit.fluxcd.io/v1beta3', 'Alert'),
            ('notification.toolkit.fluxcd.io/v1beta3', 'Provider'),
            ('notification.toolkit.fluxcd.io/v1', 'Receiver'),
            ('image.toolkit.fluxcd.io/v1beta2', 'ImageRepository'),
            ('source.extensions.fluxcd.io/v1beta1', 'ArtifactGenerator'),
        )
        for api_version, kind in resources:
            with self.subTest(kind=kind):
                root, rendered_documents = self.make_root()
                sync = {
                    'apiVersion': api_version,
                    'kind': kind,
                    'metadata': {'name': 'flux-system', 'namespace': 'flux-system'},
                }
                rendered_documents.append(sync)
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'Flux CR|custom resource|sync|Phase A',
                )

    def test_rejects_downstream_namespace(self) -> None:
        for name in (
            'platform',
            'minio',
            'cert-manager',
            'monitoring',
            'cnpg-system',
            'openbao',
        ):
            with self.subTest(namespace=name):
                root, rendered_documents = self.make_root()
                rendered_documents.append(
                    {
                        'apiVersion': 'v1',
                        'kind': 'Namespace',
                        'metadata': {'name': name},
                    }
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'Namespace|namespace|下游'
                )

    def test_rejects_pss_label_drift(self) -> None:
        for label in self.PSS_LABELS:
            with self.subTest(label=label):
                root, rendered_documents = self.make_root()
                namespace = next(
                    document
                    for document in rendered_documents
                    if document.get('kind') == 'Namespace'
                )
                namespace['metadata']['labels'][label] = (
                    'latest' if label.endswith('-version') else 'baseline'
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'Pod Security|PSS|restricted|v1.36'
                )

    def test_rejects_container_security_context_drift(self) -> None:
        mutations = {
            'allow-privilege-escalation': ('allowPrivilegeEscalation', True),
            'capabilities': ('capabilities', {'drop': []}),
            'privileged': ('privileged', True),
            'read-only-root': ('readOnlyRootFilesystem', False),
            'run-as-non-root': ('runAsNonRoot', False),
            'seccomp': ('seccompProfile', {'type': 'Unconfined'}),
        }
        for name, (key, value) in mutations.items():
            with self.subTest(mutation=name):
                root, rendered_documents = self.make_root()
                container = self.deployment(
                    rendered_documents, 'source-controller'
                )['spec']['template']['spec']['containers'][0]
                container['securityContext'][key] = value
                self.assert_contract_fails(
                    root, rendered_documents, 'securityContext|安全上下文'
                )

    def test_rejects_workload_identity_or_container_inventory_drift(
        self,
    ) -> None:
        for name in self.CONTROLLERS:
            with self.subTest(controller=name, mutation='service-account'):
                root, rendered_documents = self.make_root()
                pod_spec = self.deployment(rendered_documents, name)['spec'][
                    'template'
                ]['spec']
                pod_spec['serviceAccountName'] = 'default'
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'serviceAccountName|ServiceAccount|controller',
                )

            with self.subTest(controller=name, mutation='sidecar'):
                root, rendered_documents = self.make_root()
                containers = self.deployment(rendered_documents, name)['spec'][
                    'template'
                ]['spec']['containers']
                containers.append({'name': 'sidecar', 'image': 'example.invalid/x'})
                self.assert_contract_fails(
                    root, rendered_documents, 'container|单容器|manager'
                )

            with self.subTest(controller=name, mutation='command'):
                root, rendered_documents = self.make_root()
                container = self.deployment(rendered_documents, name)['spec'][
                    'template'
                ]['spec']['containers'][0]
                container['command'] = ['/bin/false']
                self.assert_contract_fails(
                    root, rendered_documents, 'command|manager|container'
                )

            for field in ('hostNetwork', 'hostPID', 'hostIPC'):
                with self.subTest(controller=name, mutation=field):
                    root, rendered_documents = self.make_root()
                    pod_spec = self.deployment(rendered_documents, name)[
                        'spec'
                    ]['template']['spec']
                    pod_spec[field] = True
                    self.assert_contract_fails(
                        root,
                        rendered_documents,
                        'hostNetwork|hostPID|hostIPC|Pod|pod',
                    )

    def test_rejects_missing_multitenancy_argument(self) -> None:
        multitenancy_flags = {
            '--custom-apply-stage-kinds',
            '--default-service-account',
            '--no-cross-namespace-refs',
            '--no-remote-bases',
            '--watch-all-namespaces',
        }
        for controller, contract in self.CONTROLLERS.items():
            arguments = (
                argument
                for argument in contract['args']
                if argument.split('=', 1)[0] in multitenancy_flags
            )
            for argument in arguments:
                with self.subTest(controller=controller, argument=argument):
                    root, rendered_documents = self.make_root()
                    container = self.deployment(
                        rendered_documents, controller
                    )['spec']['template']['spec']['containers'][0]
                    container['args'].remove(argument)
                    self.assert_contract_fails(
                        root, rendered_documents, 'arg|参数|多租户'
                    )

    def test_rejects_watch_all_namespaces_true(self) -> None:
        for controller in self.CONTROLLERS:
            with self.subTest(controller=controller):
                root, rendered_documents = self.make_root()
                container = self.deployment(
                    rendered_documents, controller
                )['spec']['template']['spec']['containers'][0]
                container['args'].remove('--watch-all-namespaces=false')
                container['args'].append('--watch-all-namespaces=true')
                self.assert_contract_fails(
                    root, rendered_documents, 'watch-all-namespaces|arg|参数'
                )

    def test_requires_role_custom_apply_stage_only_on_kustomize_controller(
        self,
    ) -> None:
        argument = (
            '--custom-apply-stage-kinds=rbac.authorization.k8s.io/Role'
        )
        _, rendered_documents = self.make_root()
        kustomize_args = self.deployment(
            rendered_documents, 'kustomize-controller'
        )['spec']['template']['spec']['containers'][0]['args']
        self.assertIn(argument, kustomize_args)

        for controller in self.CONTROLLERS.keys() - {'kustomize-controller'}:
            with self.subTest(controller=controller):
                args = self.deployment(rendered_documents, controller)['spec'][
                    'template'
                ]['spec']['containers'][0]['args']
                self.assertNotIn(argument, args)

    def test_rejects_duplicate_conflicting_or_unapproved_feature_flags(
        self,
    ) -> None:
        mutations = (
            (
                'kustomize-controller',
                '--no-cross-namespace-refs=false',
            ),
            ('source-controller', '--watch-all-namespaces=true'),
            ('source-controller', '--default-service-account=evil'),
            (
                'source-controller',
                '--feature-gates=ObjectLevelWorkloadIdentity=true',
            ),
            ('source-controller', '--unknown-controller-flag=true'),
            ('source-controller', '--feature-gates=UnknownFeature=true'),
        )
        for controller, argument in mutations:
            with self.subTest(controller=controller, argument=argument):
                root, rendered_documents = self.make_root()
                container = self.deployment(
                    rendered_documents, controller
                )['spec']['template']['spec']['containers'][0]
                container['args'].append(argument)
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'arg|flag|ObjectLevelWorkloadIdentity|feature gate|'
                    'default-service-account',
                )

    def test_rejects_workload_identity_defaults_without_feature_gate(self) -> None:
        forbidden = {
            'source-controller': ('--default-service-account=default',),
            'kustomize-controller': (
                '--default-decryption-service-account=default',
                '--default-kubeconfig-service-account=default',
            ),
            'helm-controller': (
                '--default-kubeconfig-service-account=default',
            ),
            'notification-controller': ('--default-service-account=default',),
        }
        for controller, arguments in forbidden.items():
            for argument in arguments:
                with self.subTest(controller=controller, argument=argument):
                    root, rendered_documents = self.make_root()
                    container = self.deployment(
                        rendered_documents, controller
                    )['spec']['template']['spec']['containers'][0]
                    container['args'].append(argument)
                    self.assert_contract_fails(
                        root,
                        rendered_documents,
                        'ObjectLevelWorkloadIdentity|feature gate|default-.*'
                        'service-account',
                    )

    def test_rejects_resource_contract_drift(self) -> None:
        for controller in self.CONTROLLERS:
            for boundary, resource in (
                ('requests', 'cpu'),
                ('requests', 'memory'),
                ('limits', 'cpu'),
                ('limits', 'memory'),
            ):
                with self.subTest(
                    controller=controller, boundary=boundary, resource=resource
                ):
                    root, rendered_documents = self.make_root()
                    container = self.deployment(
                        rendered_documents, controller
                    )['spec']['template']['spec']['containers'][0]
                    container['resources'][boundary][resource] = '1m'
                    self.assert_contract_fails(
                        root, rendered_documents, 'resources|资源'
                    )

    def test_rejects_cluster_admin_role_binding(self) -> None:
        root, rendered_documents = self.make_root()
        binding = self.resource(
            rendered_documents,
            'ClusterRoleBinding',
            'flux-controller-api-health',
        )
        binding['roleRef']['name'] = 'cluster-admin'

        self.assert_contract_fails(
            root, rendered_documents, 'cluster-admin|roleRef|RBAC'
        )

    def test_controller_bindings_require_exact_controller_subjects(
        self,
    ) -> None:
        for name in self.CONTROLLER_SERVICE_ACCOUNTS:
            with self.subTest(binding=name, mutation='wrong-subject'):
                root, rendered_documents = self.make_root()
                binding = self.resource(rendered_documents, 'RoleBinding', name)
                binding['subjects'][0]['name'] = 'source-watcher'
                self.assert_contract_fails(
                    root, rendered_documents, 'subject|ServiceAccount|controller'
                )

            with self.subTest(binding=name, mutation='extra-subject'):
                root, rendered_documents = self.make_root()
                binding = self.resource(rendered_documents, 'RoleBinding', name)
                binding['subjects'].append(
                    {
                        'kind': 'ServiceAccount',
                        'name': 'image-automation-controller',
                        'namespace': 'flux-system',
                    }
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'subject|ServiceAccount|controller'
                )

            with self.subTest(binding='api-health', missing=name):
                root, rendered_documents = self.make_root()
                binding = self.resource(
                    rendered_documents,
                    'ClusterRoleBinding',
                    'flux-controller-api-health',
                )
                binding['subjects'] = [
                    subject
                    for subject in binding['subjects']
                    if subject['name'] != name
                ]
                self.assert_contract_fails(
                    root, rendered_documents, 'subject|ServiceAccount|controller'
                )

    def test_rejects_generated_cluster_wide_rbac(self) -> None:
        resources = (
            (
                'ClusterRole',
                'crd-controller-flux-system',
                {
                    'rules': [
                        {
                            'apiGroups': ['*'],
                            'resources': ['*'],
                            'verbs': ['*'],
                        }
                    ]
                },
            ),
            (
                'ClusterRoleBinding',
                'cluster-reconciler',
                {
                    'roleRef': {
                        'apiGroup': 'rbac.authorization.k8s.io',
                        'kind': 'ClusterRole',
                        'name': 'crd-controller-flux-system',
                    },
                    'subjects': self.controller_subjects(),
                },
            ),
        )
        for kind, name, body in resources:
            with self.subTest(kind=kind):
                root, rendered_documents = self.make_root()
                rendered_documents.append(
                    {
                        'apiVersion': 'rbac.authorization.k8s.io/v1',
                        'kind': kind,
                        'metadata': {'name': name},
                        **body,
                    }
                )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'crd-controller|cluster-reconciler|cluster-wide|RBAC',
                )

    def test_rejects_flux_edit_or_view_aggregate_cluster_role(self) -> None:
        for name in ('flux-edit-flux-system', 'flux-view-flux-system'):
            with self.subTest(cluster_role=name):
                root, rendered_documents = self.make_root()
                rendered_documents.append(
                    {
                        'apiVersion': 'rbac.authorization.k8s.io/v1',
                        'kind': 'ClusterRole',
                        'metadata': {
                            'name': name,
                            'labels': {
                                'rbac.authorization.k8s.io/aggregate-to-admin': (
                                    'true'
                                )
                            },
                        },
                        'rules': [],
                    }
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'flux-edit|flux-view|aggregate|聚合'
                )

    def test_rejects_image_automation_or_source_watcher_rbac_group(self) -> None:
        for api_group in (
            'image.toolkit.fluxcd.io',
            'source.extensions.fluxcd.io',
        ):
            with self.subTest(api_group=api_group):
                root, rendered_documents = self.make_root()
                role = self.resource(
                    rendered_documents,
                    'Role',
                    'source-controller',
                )
                role['rules'].append(
                    {
                        'apiGroups': [api_group],
                        'resources': ['*'],
                        'verbs': ['get'],
                    }
                )
                self.assert_contract_fails(
                    root, rendered_documents, 'apiGroup|image.toolkit|source.extensions'
                )

    def test_rejects_service_account_token_creation(self) -> None:
        root, rendered_documents = self.make_root()
        role = self.resource(
            rendered_documents, 'Role', 'source-controller'
        )
        role['rules'].append(
            {
                'apiGroups': [''],
                'resources': ['serviceaccounts/token'],
                'verbs': ['create'],
            }
        )

        self.assert_contract_fails(
            root, rendered_documents, 'serviceaccounts/token|Workload Identity|token'
        )

    def test_rejects_controller_role_rule_expansion(self) -> None:
        mutations = (
            ('source-controller', 'cross-controller-api-group'),
            ('kustomize-controller', 'configmap-write'),
            ('helm-controller', 'cross-controller-write'),
            ('notification-controller', 'lease-broadening'),
        )
        for controller, mutation in mutations:
            with self.subTest(controller=controller, mutation=mutation):
                root, rendered_documents = self.make_root()
                role = self.resource(rendered_documents, 'Role', controller)
                if mutation == 'cross-controller-api-group':
                    role['rules'].append(
                        {
                            'apiGroups': ['kustomize.toolkit.fluxcd.io'],
                            'resources': ['kustomizations'],
                            'verbs': ['create'],
                        }
                    )
                elif mutation == 'configmap-write':
                    core = next(
                        rule
                        for rule in role['rules']
                        if 'configmaps' in rule.get('resources', [])
                    )
                    core['verbs'].append('update')
                elif mutation == 'cross-controller-write':
                    source_read = next(
                        rule
                        for rule in role['rules']
                        if rule.get('apiGroups')
                        == ['source.toolkit.fluxcd.io']
                        and 'helmcharts' in rule.get('resources', [])
                        and 'list' in rule.get('verbs', [])
                    )
                    source_read['verbs'].append('patch')
                else:
                    lease = next(
                        rule
                        for rule in role['rules']
                        if rule.get('resources') == ['leases']
                    )
                    lease['verbs'].extend(['list', 'watch', 'patch', 'delete'])
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'Role|RBAC|namespaced|Lease|跨 Controller|权限',
                )

    def test_rejects_api_health_cluster_role_expansion(self) -> None:
        mutations = (
            ('non-resource-url', 'nonResourceURLs', ['*']),
            ('non-resource-verb', 'verbs', ['get']),
        )
        for name, key, value in mutations:
            with self.subTest(mutation=name):
                root, rendered_documents = self.make_root()
                role = self.resource(
                    rendered_documents,
                    'ClusterRole',
                    'flux-controller-api-health',
                )
                role['rules'][0][key] = value
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'livez|ping|head|ClusterRole|health',
                )

        root, rendered_documents = self.make_root()
        role = self.resource(
            rendered_documents,
            'ClusterRole',
            'flux-controller-api-health',
        )
        role['rules'].append(
            {
                'apiGroups': [''],
                'resources': ['namespaces'],
                'verbs': ['get', 'list', 'watch'],
            }
        )
        self.assert_contract_fails(
            root, rendered_documents, 'livez|ping|head|ClusterRole|health'
        )

    def test_requires_default_deny_dns_and_apiserver_egress(self) -> None:
        for policy_type in ('Ingress', 'Egress'):
            with self.subTest(default_deny=policy_type):
                root, rendered_documents = self.make_root()
                default_deny = self.resource(
                    rendered_documents, 'NetworkPolicy', 'default-deny'
                )
                default_deny['spec']['policyTypes'].remove(policy_type)
                self.assert_contract_fails(
                    root, rendered_documents, 'default.deny|NetworkPolicy|网络策略'
                )

        for kind, name in (
            ('NetworkPolicy', 'allow-dns-egress'),
            ('NetworkPolicy', 'allow-controller-internal-ingress'),
            ('NetworkPolicy', 'allow-controller-internal-egress'),
            ('CiliumNetworkPolicy', 'allow-kube-apiserver-egress'),
        ):
            with self.subTest(missing=name):
                root, rendered_documents = self.make_root()
                rendered_documents.remove(
                    self.resource(rendered_documents, kind, name)
                )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'DNS|controller|kube-apiserver|Cilium|egress|NetworkPolicy',
                )

    def test_rejects_controller_internal_network_expansion(self) -> None:
        for mutation in (
            'ingress-selected-pods',
            'ingress-namespace',
            'ingress-peer',
            'metrics-port',
            'egress-selected-pods',
            'egress-destination',
            'webhook-port',
        ):
            with self.subTest(mutation=mutation):
                root, rendered_documents = self.make_root()
                ingress_policy = self.resource(
                    rendered_documents,
                    'NetworkPolicy',
                    'allow-controller-internal-ingress',
                )
                egress_policy = self.resource(
                    rendered_documents,
                    'NetworkPolicy',
                    'allow-controller-internal-egress',
                )
                if mutation == 'ingress-selected-pods':
                    ingress_policy['spec']['podSelector'] = {
                        'matchLabels': {'app.kubernetes.io/part-of': 'flux'}
                    }
                elif mutation == 'ingress-namespace':
                    ingress_policy['spec']['ingress'][0]['from'][0][
                        'namespaceSelector'
                    ] = {}
                elif mutation == 'ingress-peer':
                    ingress_policy['spec']['ingress'][0]['from'][0][
                        'podSelector'
                    ] = {}
                elif mutation == 'metrics-port':
                    ingress_policy['spec']['ingress'][0]['ports'].append(
                        {'port': 8080, 'protocol': 'TCP'}
                    )
                elif mutation == 'egress-selected-pods':
                    egress_policy['spec']['podSelector'] = {}
                elif mutation == 'egress-destination':
                    egress_policy['spec']['egress'][0]['to'][0][
                        'podSelector'
                    ] = {
                        'matchLabels': {'app.kubernetes.io/part-of': 'flux'}
                    }
                else:
                    egress_policy['spec']['egress'][0]['ports'].append(
                        {'port': 9292, 'protocol': 'TCP'}
                    )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'allow-controller-internal|9090|selector|NetworkPolicy',
                )

    def test_rejects_phase_a_egress_selector_broadening(self) -> None:
        mutations = (
            ('NetworkPolicy', 'allow-dns-egress', 'podSelector'),
            (
                'CiliumNetworkPolicy',
                'allow-kube-apiserver-egress',
                'endpointSelector',
            ),
        )
        for kind, name, selector in mutations:
            with self.subTest(policy=name):
                root, rendered_documents = self.make_root()
                policy = self.resource(rendered_documents, kind, name)
                policy['spec'][selector] = {}
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'podSelector|endpointSelector|NetworkPolicy|Cilium',
                )

    def test_rejects_network_policy_scope_or_clusterwide_expansion(self) -> None:
        root, rendered_documents = self.make_root()
        dns = self.resource(
            rendered_documents, 'NetworkPolicy', 'allow-dns-egress'
        )
        duplicate = copy.deepcopy(dns)
        duplicate['metadata']['namespace'] = 'default'
        rendered_documents.append(duplicate)
        self.assert_contract_fails(
            root,
            rendered_documents,
            'namespace|flux-system|NetworkPolicy|inventory',
        )

        root, rendered_documents = self.make_root()
        rendered_documents.append(
            {
                'apiVersion': 'cilium.io/v2',
                'kind': 'CiliumClusterwideNetworkPolicy',
                'metadata': {'name': 'allow-kube-apiserver-egress'},
                'spec': {
                    'endpointSelector': {},
                    'egress': [{'toEntities': ['kube-apiserver']}],
                },
            }
        )
        self.assert_contract_fails(
            root,
            rendered_documents,
            'CiliumClusterwideNetworkPolicy|clusterwide|NetworkPolicy|inventory',
        )

    def test_rejects_broad_egress_or_metrics_webhook_ingress(self) -> None:
        unsafe_policies = (
            (
                'allow-egress',
                {
                    'podSelector': {},
                    'policyTypes': ['Egress'],
                    'egress': [{}],
                },
            ),
            (
                'empty-namespace-selector',
                {
                    'podSelector': {},
                    'policyTypes': ['Egress'],
                    'egress': [{'to': [{'namespaceSelector': {}}]}],
                },
            ),
            (
                'allow-scraping',
                {
                    'podSelector': {},
                    'policyTypes': ['Ingress'],
                    'ingress': [{'ports': [{'port': 8080, 'protocol': 'TCP'}]}],
                },
            ),
            (
                'allow-webhooks',
                {
                    'podSelector': {},
                    'policyTypes': ['Ingress'],
                    'ingress': [{'ports': [{'port': 9443, 'protocol': 'TCP'}]}],
                },
            ),
        )
        for name, spec in unsafe_policies:
            with self.subTest(network_policy=name):
                root, rendered_documents = self.make_root()
                rendered_documents.append(
                    {
                        'apiVersion': 'networking.k8s.io/v1',
                        'kind': 'NetworkPolicy',
                        'metadata': {'name': name, 'namespace': 'flux-system'},
                        'spec': spec,
                    }
                )
                self.assert_contract_fails(
                    root,
                    rendered_documents,
                    'allow-egress|namespaceSelector|metrics|scraping|webhook|'
                    'NetworkPolicy',
                )


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

    def test_cilium_gateway_contract_rolls_operator_on_config_change(self) -> None:
        """HostNetwork 只有进入新 operator 进程后才能驱动 Gateway 地址分配。"""
        values = yaml.safe_load(
            (
                validator.ROOT
                / 'bootstrap/hosts/retail-test-workflow/cilium-values.yaml'
            ).read_text(encoding='utf-8')
        )

        self.assertIs(values['gatewayAPI']['hostNetwork']['enabled'], True)
        self.assertIs(values['operator']['rollOutPods'], True)
        capabilities = values['envoy']['securityContext']['capabilities']
        self.assertIs(capabilities['keepCapNetBindService'], True)
        self.assertEqual(
            capabilities['envoy'],
            ['NET_ADMIN', 'SYS_ADMIN', 'NET_BIND_SERVICE'],
        )

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
