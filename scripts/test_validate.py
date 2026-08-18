from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
import validate as validator

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
            'current-server-resumes-at-40-after-gate': (
                'runbook',
                r'当前暂停中的服务器已完成 stage `00`～`30`。GitHub '
                r'`validation-gate` 成功后重跑 orchestrator，它必须依据各 stage 的'
                r'检查结果跳过这些已完成 stage，并从 stage `40` 继续',
            ),
            'individual-stages-emergency-only': (
                'runbook',
                r'下表保留为诊断和人工应急入口，不是正常 bootstrap 路径',
            ),
            'stage-50-success-alternatives': (
                'runbook',
                r'\| 12 \| `50-kubeadm-init\.sh` \| `--check` 后批准 '
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

    def test_metrics_server_contract(self) -> None:
        validate_metrics_server()

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
            'current-server-resumes-at-40-after-gate': (
                '当前暂停中的服务器已完成 stage `00`～`30`。GitHub '
                '`validation-gate` 成功后重跑\n'
                'orchestrator，它必须依据各 stage 的检查结果跳过这些已完成 stage，'
                '并从 stage `40` 继续',
                '当前暂停中的服务器尚未完成 stage `00`～`30`。GitHub '
                '`validation-gate` 成功前重跑\n'
                'orchestrator，它必须从 stage `00` 继续，不能从 stage `40` 继续',
            ),
            'individual-stages-emergency-only': (
                '下表保留为诊断和人工应急入口，不是正常 bootstrap 路径',
                '下表不是诊断和人工应急入口，而是正常 bootstrap 路径',
            ),
            'stage-50-success-alternatives': (
                '| 12 | `50-kubeadm-init.sh` | `--check` 后批准 `--apply` | '
                '`PASS_KUBEADM_INITIALIZED` 或 `ALREADY_COMPLIANT` |',
                '| 12 | `50-kubeadm-init.sh` | `--check` 后批准 `--apply` | '
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
        environment = os.environ.copy()
        environment.update(
            {
                'FAKE_RUNNER_EXIT': str(runner_exit),
                'FAKE_SHELLCHECK_EXIT': str(shellcheck_exit),
                'PATH': f'{self.fake_bin}:/usr/bin:/bin',
                'PYTHONDONTWRITEBYTECODE': '1',
                'VALIDATE_COMMAND_LOG': str(self.command_log),
            }
        )
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

    def test_fast_entrypoint_runs_fast_profile_without_apply(self) -> None:
        result = self.run_validate('validate-fast.sh')

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        command_log = self.read_command_log()
        self.assertIn('run_validation.py\t--profile\tfast', command_log)
        self.assertNotIn('--apply', command_log)


class ValidationCatalogTest(unittest.TestCase):
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
            set(document['jobs']), {'plan', 'tests', 'static', 'validation-gate'}
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
