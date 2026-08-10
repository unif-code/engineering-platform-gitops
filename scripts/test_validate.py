from __future__ import annotations

import contextlib
import io
import shutil
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
    def test_metrics_server_contract(self) -> None:
        validate_metrics_server()

    def test_single_user_resource_contract(self) -> None:
        self.assertEqual(validate_single_user_resources(), (1115, 2720))

    def test_single_user_storage_contract(self) -> None:
        validate_single_user_storage()


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
        path = root / 'bootstrap' / 'kubeadm' / 'init.yaml'
        path.write_text(
            path.read_text(encoding='utf-8').replace(
                '172.21.0.0/16', '10.244.0.0/16', 1
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    def test_cilium_contract_rejects_disabled_kube_proxy_replacement(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / 'bootstrap' / 'cilium' / 'values.yaml'
        path.write_text(
            path.read_text(encoding='utf-8').replace(
                'kubeProxyReplacement: true', 'kubeProxyReplacement: false', 1
            ),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)


if __name__ == '__main__':
    unittest.main()
