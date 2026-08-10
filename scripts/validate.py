#!/usr/bin/env python3
"""校验 DEV GitOps 清单的可渲染性与关键安全约束。"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Tuple, Union

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOTS = (ROOT / 'clusters', ROOT / 'infrastructure', ROOT / 'apps')
EXACT_VERSION = re.compile(r'^v?\d+\.\d+\.\d+$')
FLOATING_IMAGE = re.compile(r':(?:latest|main|master)$')
PLACEHOLDER = re.compile(r'(?:REPLACE_ME|TODO_DIGEST|<[^>]+>)')
INSECURE_TLS = re.compile(r'(?:--insecure\b|insecureSkipVerify:\s*true)')

REQUIRED_TASK4_RESOURCES = {
    ('storage.k8s.io/v1', 'StorageClass', '', 'stateful-rwo-lowlatency'),
    ('helm.toolkit.fluxcd.io/v2', 'HelmRelease', 'cert-manager', 'cert-manager'),
    ('cert-manager.io/v1', 'ClusterIssuer', '', 'dev-selfsigned'),
    ('apps/v1', 'Deployment', 'minio', 'minio'),
    ('batch/v1', 'Job', 'minio', 'minio-bootstrap-v1'),
    (
        'helm.toolkit.fluxcd.io/v2',
        'HelmRelease',
        'monitoring',
        'kube-prometheus-stack',
    ),
    ('monitoring.coreos.com/v1', 'PrometheusRule', 'monitoring', 'dev-infra-alerts'),
}

REQUIRED_TASK5_RESOURCES = {
    (
        'helm.toolkit.fluxcd.io/v2',
        'HelmRelease',
        'cnpg-system',
        'cloudnative-pg',
    ),
    (
        'helm.toolkit.fluxcd.io/v2',
        'HelmRelease',
        'cnpg-system',
        'plugin-barman-cloud',
    ),
    ('barmancloud.cnpg.io/v1', 'ObjectStore', 'platform', 'platform-backup'),
    ('postgresql.cnpg.io/v1', 'Cluster', 'platform', 'platform'),
    (
        'postgresql.cnpg.io/v1',
        'ScheduledBackup',
        'platform',
        'platform-daily',
    ),
    (
        'monitoring.coreos.com/v1',
        'PodMonitor',
        'monitoring',
        'platform-postgres',
    ),
}

REQUIRED_TASK6_RESOURCES = {
    ('batch/v1', 'CronJob', 'kube-system', 'etcd-backup'),
}

REQUIRED_TASK8_FOUNDATION_RESOURCES = {
    ('cert-manager.io/v1', 'Certificate', 'platform', 'platform-gateway-tls'),
    ('gateway.networking.k8s.io/v1', 'Gateway', 'platform', 'platform-gateway'),
}


def fail(message: str) -> None:
    print(f'ERROR: {message}', file=sys.stderr)
    raise SystemExit(1)


def yaml_files() -> Iterable[Path]:
    for root in MANIFEST_ROOTS:
        yield from sorted(root.rglob('*.yaml'))
        yield from sorted(root.rglob('*.yml'))


def load_documents(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(encoding='utf-8') as stream:
            for document in yaml.safe_load_all(stream):
                if document is None:
                    continue
                if not isinstance(document, dict):
                    fail(f'{path.relative_to(ROOT)} 顶层必须是 YAML mapping')
                yield document
    except yaml.YAMLError as error:
        fail(f'{path.relative_to(ROOT)} YAML 解析失败：{error}')


PathToken = Union[str, Tuple[str, str]]


def document_by_identity(path: Path, kind: str, name: str) -> dict[str, Any]:
    for document in load_documents(path):
        metadata = document.get('metadata', {})
        if document.get('kind') == kind and metadata.get('name') == name:
            return document
    fail(f'{path.relative_to(ROOT)} 缺少 {kind}/{name}')


def value_at(value: Any, path: Tuple[PathToken, ...]) -> Any:
    current = value
    for token in path:
        if isinstance(token, tuple):
            key, expected = token
            if not isinstance(current, list):
                fail(f'路径 selector {key}={expected} 的父值不是 list')
            current = next(
                (
                    item
                    for item in current
                    if isinstance(item, dict) and item.get(key) == expected
                ),
                None,
            )
            if current is None:
                fail(f'路径缺少 selector {key}={expected}')
        else:
            if not isinstance(current, dict) or token not in current:
                fail(f'路径缺少 key {token}')
            current = current[token]
    return current


def expect_value(
    relative_path: str,
    kind: str,
    name: str,
    path: Tuple[PathToken, ...],
    expected: Any,
) -> None:
    document = document_by_identity(ROOT / relative_path, kind, name)
    actual = value_at(document, path)
    if actual != expected:
        fail(f'{relative_path} 期望 {expected!r}，实测 {actual!r}')


def validate_single_user_storage() -> None:
    contracts = (
        (
            'infrastructure/minio/pvc.yaml',
            'PersistentVolumeClaim',
            'minio-data',
            ('spec', 'resources', 'requests', 'storage'),
            '50Gi',
        ),
        (
            'infrastructure/cnpg/database/cluster.yaml',
            'Cluster',
            'platform',
            ('spec', 'storage', 'size'),
            '20Gi',
        ),
        (
            'runbook/examples/postgres-restore.yaml',
            'Cluster',
            'platform-restore',
            ('metadata', 'namespace'),
            'platform',
        ),
        (
            'runbook/examples/postgres-restore.yaml',
            'Cluster',
            'platform-restore',
            ('spec', 'storage', 'size'),
            '20Gi',
        ),
        (
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            (
                'spec',
                'values',
                'alertmanager',
                'alertmanagerSpec',
                'storage',
                'volumeClaimTemplate',
                'spec',
                'resources',
                'requests',
                'storage',
            ),
            '1Gi',
        ),
        (
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'grafana', 'persistence', 'size'),
            '2Gi',
        ),
        (
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            (
                'spec',
                'values',
                'prometheus',
                'prometheusSpec',
                'storageSpec',
                'volumeClaimTemplate',
                'spec',
                'resources',
                'requests',
                'storage',
            ),
            '10Gi',
        ),
        (
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'prometheus', 'prometheusSpec', 'retention'),
            '7d',
        ),
        (
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'prometheus', 'prometheusSpec', 'retentionSize'),
            '8GB',
        ),
    )
    for relative_path, kind, name, path, expected in contracts:
        expect_value(relative_path, kind, name, path, expected)

    quota_documents = load_documents(
        ROOT / 'infrastructure/foundation/resource-quotas.yaml'
    )
    quotas = {
        document.get('metadata', {}).get('namespace'): document
        for document in quota_documents
        if document.get('kind') == 'ResourceQuota'
    }
    expected_quotas = {
        'minio': ('1', '50Gi'),
        'monitoring': ('3', '13Gi'),
        'platform': ('2', '45Gi'),
    }
    for namespace, (claim_count, storage) in expected_quotas.items():
        document = quotas.get(namespace)
        if document is None:
            fail(f'resource-quotas.yaml 缺少 namespace {namespace}')
        hard = value_at(document, ('spec', 'hard'))
        if hard.get('persistentvolumeclaims') != claim_count:
            fail(f'{namespace} PVC 数量额度必须为 {claim_count}')
        if hard.get('requests.storage') != storage:
            fail(f'{namespace} PVC 存储额度必须为 {storage}')

    bootstrap = document_by_identity(
        ROOT / 'infrastructure/minio/bootstrap-job.yaml',
        'Job',
        'minio-bootstrap-v1',
    )
    args = value_at(
        bootstrap,
        ('spec', 'template', 'spec', 'containers', ('name', 'mc'), 'args'),
    )
    script = '\n'.join(args)
    quota_commands = (
        'mc quota set dev/postgres-backup --size 30Gi',
        'mc quota set dev/etcd-backup --size 5Gi',
        'mc quota set dev/audit-worm --size 5Gi',
    )
    for command in quota_commands:
        if script.splitlines().count(command) != 1:
            fail(f'MinIO bootstrap 必须且只能执行一次：{command}')

    rules_document = document_by_identity(
        ROOT / 'infrastructure/observability/config/alerts.yaml',
        'PrometheusRule',
        'dev-infra-alerts',
    )
    rules = value_at(
        rules_document,
        ('spec', 'groups', ('name', 'dev-infrastructure'), 'rules'),
    )
    alerts = {
        rule.get('alert'): rule for rule in rules if isinstance(rule, dict)
    }
    expected_expressions = {
        'NodeRootFilesystemUsageHigh': '>= 80',
        'NodeRootFilesystemUsageCritical': '>= 90',
    }
    for alert, threshold in expected_expressions.items():
        rule = alerts.get(alert)
        if rule is None:
            fail(f'alerts.yaml 缺少 {alert}')
        if threshold not in str(rule.get('expr', '')):
            fail(f'{alert} 必须使用阈值 {threshold}')


def resource_id(document: dict[str, Any]) -> tuple[str, str, str, str] | None:
    api_version = document.get('apiVersion')
    kind = document.get('kind')
    metadata = document.get('metadata', {})
    name = metadata.get('name') if isinstance(metadata, dict) else None
    if not all(isinstance(value, str) for value in (api_version, kind, name)):
        return None
    namespace = metadata.get('namespace', '')
    return api_version, kind, namespace, name


def images(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'image' and isinstance(child, str):
                yield child
            else:
                yield from images(child)
    elif isinstance(value, list):
        for child in value:
            yield from images(child)


def validate_kustomize_builds() -> None:
    kustomizations = sorted(
        path
        for root in MANIFEST_ROOTS
        for path in root.rglob('kustomization.yaml')
    )
    if not kustomizations:
        fail('未找到任何 kustomization.yaml')

    for path in kustomizations:
        result = subprocess.run(
            ['kubectl', 'kustomize', str(path.parent)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            fail(
                f'{path.parent.relative_to(ROOT)} 无法渲染：'
                f'{result.stderr.strip() or result.stdout.strip()}'
            )


def validate_documents() -> None:
    found: set[tuple[str, str, str, str]] = set()

    for path in yaml_files():
        source = path.read_text(encoding='utf-8')
        if PLACEHOLDER.search(source):
            fail(f'{path.relative_to(ROOT)} 含未关闭的占位符')
        if INSECURE_TLS.search(source):
            fail(f'{path.relative_to(ROOT)} 禁止跳过 TLS 证书校验')

        for document in load_documents(path):
            identity = resource_id(document)
            if identity is not None:
                found.add(identity)

            kind = document.get('kind')
            api_version = document.get('apiVersion', '')
            spec = document.get('spec', {})

            if kind == 'Secret':
                fail(f'{path.relative_to(ROOT)} 禁止提交 Secret 资源')

            is_flux_kustomization = (
                kind == 'Kustomization'
                and api_version.startswith('kustomize.toolkit.fluxcd.io/')
            )
            if kind == 'HelmRelease' or is_flux_kustomization:
                if not isinstance(spec, dict) or not spec.get('serviceAccountName'):
                    fail(f'{path.relative_to(ROOT)} 缺少 spec.serviceAccountName')

            if kind == 'HelmRelease':
                version = (
                    spec.get('chart', {}).get('spec', {}).get('version')
                    if isinstance(spec, dict)
                    else None
                )
                if not isinstance(version, str) or not EXACT_VERSION.fullmatch(version):
                    fail(f'{path.relative_to(ROOT)} Helm Chart 必须锁定精确版本')

            for image in images(document):
                if FLOATING_IMAGE.search(image):
                    fail(f'{path.relative_to(ROOT)} 使用浮动镜像 {image}')
                if '@sha256:' not in image:
                    fail(f'{path.relative_to(ROOT)} 直接工作负载镜像未按 digest 固定：{image}')

    missing = sorted(REQUIRED_TASK4_RESOURCES - found)
    if missing:
        formatted = ', '.join(
            f'{kind}/{namespace or "_cluster"}/{name}'
            for _, kind, namespace, name in missing
        )
        fail(f'Task 4 缺少资源：{formatted}')

    missing = sorted(REQUIRED_TASK5_RESOURCES - found)
    if missing:
        formatted = ', '.join(
            f'{kind}/{namespace or "_cluster"}/{name}'
            for _, kind, namespace, name in missing
        )
        fail(f'Task 5 缺少资源：{formatted}')

    missing = sorted(REQUIRED_TASK6_RESOURCES - found)
    if missing:
        formatted = ', '.join(
            f'{kind}/{namespace or "_cluster"}/{name}'
            for _, kind, namespace, name in missing
        )
        fail(f'Task 6 缺少资源：{formatted}')

    missing = sorted(REQUIRED_TASK8_FOUNDATION_RESOURCES - found)
    if missing:
        formatted = ', '.join(
            f'{kind}/{namespace or "_cluster"}/{name}'
            for _, kind, namespace, name in missing
        )
        fail(f'Task 8 入口基础资源缺少：{formatted}')


def main() -> None:
    validate_kustomize_builds()
    validate_documents()
    validate_single_user_storage()
    print('GitOps manifests validated successfully.')


if __name__ == '__main__':
    main()
