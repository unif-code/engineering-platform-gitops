from __future__ import annotations

import contextlib
import io
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


if __name__ == '__main__':
    unittest.main()
