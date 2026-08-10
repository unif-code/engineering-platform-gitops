#!/usr/bin/env python3
"""校验 DEV GitOps 清单的可渲染性与关键安全约束。"""

from __future__ import annotations

import re
import subprocess
import sys
from decimal import Decimal
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


def cpu_millicores(quantity: str) -> int:
    if quantity.endswith('m'):
        return int(quantity[:-1])
    return int(Decimal(quantity) * 1000)


def memory_mib(quantity: str) -> int:
    if quantity.endswith('Mi'):
        return int(quantity[:-2])
    if quantity.endswith('Gi'):
        return int(Decimal(quantity[:-2]) * 1024)
    fail(f'不支持的内存 quantity：{quantity}')


def validate_single_user_resources() -> Tuple[int, int]:
    total_cpu_millicores = 0
    total_memory_mib = 0

    def check_resources(
        label: str,
        resources: dict[str, Any],
        request_cpu: str,
        request_memory: str,
        limit_cpu: str,
        limit_memory: str,
        steady: bool,
    ) -> None:
        nonlocal total_cpu_millicores, total_memory_mib
        expected = {
            'limits': {'cpu': limit_cpu, 'memory': limit_memory},
            'requests': {'cpu': request_cpu, 'memory': request_memory},
        }
        if resources != expected:
            fail(f'{label} resources 期望 {expected!r}，实测 {resources!r}')
        if steady:
            total_cpu_millicores += cpu_millicores(request_cpu)
            total_memory_mib += memory_mib(request_memory)

    flux_kustomization = next(
        load_documents(ROOT / 'clusters/dev/flux-system/kustomization.yaml')
    )
    flux_contracts = (
        ('source-controller', '25m', '96Mi', '200m', '256Mi'),
        ('kustomize-controller', '50m', '128Mi', '500m', '512Mi'),
        ('helm-controller', '50m', '128Mi', '500m', '512Mi'),
        ('notification-controller', '10m', '64Mi', '100m', '128Mi'),
    )
    patches = flux_kustomization.get('patches', [])
    for controller, request_cpu, request_memory, limit_cpu, limit_memory in flux_contracts:
        resources = None
        for patch_entry in patches:
            target = patch_entry.get('target', {})
            if target.get('kind') != 'Deployment' or target.get('name') != controller:
                continue
            patch_document = yaml.safe_load(patch_entry.get('patch', ''))
            if not isinstance(patch_document, dict) or 'spec' not in patch_document:
                continue
            resources = value_at(
                patch_document,
                (
                    'spec',
                    'template',
                    'spec',
                    'containers',
                    ('name', 'manager'),
                    'resources',
                ),
            )
            break
        if resources is None:
            fail(f'Flux 缺少 {controller} resources patch')
        check_resources(
            f'Flux {controller}',
            resources,
            request_cpu,
            request_memory,
            limit_cpu,
            limit_memory,
            True,
        )

    contracts = (
        (
            'local-path-provisioner',
            'infrastructure/foundation/local-path-provisioner.yaml',
            'Deployment',
            'local-path-provisioner',
            ('spec', 'template', 'spec', 'containers', ('name', 'local-path-provisioner'), 'resources'),
            '20m', '32Mi', '100m', '96Mi', True,
        ),
        (
            'cert-manager controller',
            'infrastructure/cert-manager/controller/release.yaml',
            'HelmRelease',
            'cert-manager',
            ('spec', 'values', 'resources'),
            '30m', '64Mi', '300m', '256Mi', True,
        ),
        (
            'cert-manager cainjector',
            'infrastructure/cert-manager/controller/release.yaml',
            'HelmRelease',
            'cert-manager',
            ('spec', 'values', 'cainjector', 'resources'),
            '30m', '64Mi', '300m', '256Mi', True,
        ),
        (
            'cert-manager webhook',
            'infrastructure/cert-manager/controller/release.yaml',
            'HelmRelease',
            'cert-manager',
            ('spec', 'values', 'webhook', 'resources'),
            '20m', '64Mi', '200m', '128Mi', True,
        ),
        (
            'cert-manager startupapicheck',
            'infrastructure/cert-manager/controller/release.yaml',
            'HelmRelease',
            'cert-manager',
            ('spec', 'values', 'startupapicheck', 'resources'),
            '10m', '32Mi', '100m', '64Mi', False,
        ),
        (
            'MinIO server',
            'infrastructure/minio/deployment.yaml',
            'Deployment',
            'minio',
            ('spec', 'template', 'spec', 'containers', ('name', 'minio'), 'resources'),
            '100m', '256Mi', '1', '2Gi', True,
        ),
        (
            'MinIO bootstrap',
            'infrastructure/minio/bootstrap-job.yaml',
            'Job',
            'minio-bootstrap-v1',
            ('spec', 'template', 'spec', 'containers', ('name', 'mc'), 'resources'),
            '10m', '32Mi', '100m', '128Mi', False,
        ),
        (
            'CloudNativePG operator',
            'infrastructure/cnpg/controller/cnpg-release.yaml',
            'HelmRelease',
            'cloudnative-pg',
            ('spec', 'values', 'resources'),
            '50m', '128Mi', '300m', '256Mi', True,
        ),
        (
            'Barman operator',
            'infrastructure/cnpg/controller/barman-release.yaml',
            'HelmRelease',
            'plugin-barman-cloud',
            ('spec', 'values', 'resources'),
            '50m', '128Mi', '300m', '256Mi', True,
        ),
        (
            'PostgreSQL primary',
            'infrastructure/cnpg/database/cluster.yaml',
            'Cluster',
            'platform',
            ('spec', 'resources'),
            '250m', '512Mi', '2', '4Gi', True,
        ),
        (
            'Barman instance sidecar',
            'infrastructure/cnpg/database/object-store.yaml',
            'ObjectStore',
            'platform-backup',
            ('spec', 'instanceSidecarConfiguration', 'resources'),
            '50m', '64Mi', '500m', '256Mi', True,
        ),
        (
            'Alertmanager',
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'alertmanager', 'alertmanagerSpec', 'resources'),
            '20m', '64Mi', '200m', '256Mi', True,
        ),
        (
            'Grafana',
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'grafana', 'resources'),
            '50m', '128Mi', '500m', '512Mi', True,
        ),
        (
            'kube-state-metrics',
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'kube-state-metrics', 'resources'),
            '20m', '64Mi', '200m', '128Mi', True,
        ),
        (
            'Prometheus',
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'prometheus', 'prometheusSpec', 'resources'),
            '200m', '512Mi', '1', '2Gi', True,
        ),
        (
            'node-exporter',
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'prometheus-node-exporter', 'resources'),
            '20m', '32Mi', '100m', '64Mi', True,
        ),
        (
            'Prometheus Operator',
            'infrastructure/observability/controller/release.yaml',
            'HelmRelease',
            'kube-prometheus-stack',
            ('spec', 'values', 'prometheusOperator', 'resources'),
            '50m', '128Mi', '300m', '256Mi', True,
        ),
        (
            'etcd backup upload',
            'infrastructure/etcd-backup/cronjob.yaml',
            'CronJob',
            'etcd-backup',
            ('spec', 'jobTemplate', 'spec', 'template', 'spec', 'containers', ('name', 'upload'), 'resources'),
            '10m', '32Mi', '200m', '128Mi', False,
        ),
        (
            'etcd backup snapshot',
            'infrastructure/etcd-backup/cronjob.yaml',
            'CronJob',
            'etcd-backup',
            ('spec', 'jobTemplate', 'spec', 'template', 'spec', 'initContainers', ('name', 'snapshot'), 'resources'),
            '50m', '64Mi', '500m', '256Mi', False,
        ),
        (
            'etcd backup validate',
            'infrastructure/etcd-backup/cronjob.yaml',
            'CronJob',
            'etcd-backup',
            ('spec', 'jobTemplate', 'spec', 'template', 'spec', 'initContainers', ('name', 'validate'), 'resources'),
            '10m', '32Mi', '200m', '128Mi', False,
        ),
        (
            'PostgreSQL restore',
            'runbook/examples/postgres-restore.yaml',
            'Cluster',
            'platform-restore',
            ('spec', 'resources'),
            '250m', '512Mi', '2', '4Gi', False,
        ),
        (
            'Barman restore sidecar',
            'runbook/examples/postgres-restore.yaml',
            'ObjectStore',
            'platform-restore-source',
            ('spec', 'instanceSidecarConfiguration', 'resources'),
            '50m', '64Mi', '500m', '256Mi', False,
        ),
        (
            'etcd restore download',
            'runbook/examples/etcd-restore-drill.yaml',
            'Job',
            'etcd-restore-drill',
            ('spec', 'template', 'spec', 'initContainers', ('name', 'download'), 'resources'),
            '10m', '32Mi', '200m', '128Mi', False,
        ),
        (
            'etcd restore',
            'runbook/examples/etcd-restore-drill.yaml',
            'Job',
            'etcd-restore-drill',
            ('spec', 'template', 'spec', 'initContainers', ('name', 'restore'), 'resources'),
            '50m', '64Mi', '500m', '256Mi', False,
        ),
        (
            'etcd restore status',
            'runbook/examples/etcd-restore-drill.yaml',
            'Job',
            'etcd-restore-drill',
            ('spec', 'template', 'spec', 'containers', ('name', 'status'), 'resources'),
            '10m', '32Mi', '200m', '128Mi', False,
        ),
        (
            'MinIO lock verify',
            'runbook/examples/minio-lock-verify.yaml',
            'Job',
            'minio-lock-verify',
            ('spec', 'template', 'spec', 'containers', ('name', 'verify'), 'resources'),
            '10m', '32Mi', '100m', '128Mi', False,
        ),
    )

    for (
        label,
        relative_path,
        kind,
        name,
        path,
        request_cpu,
        request_memory,
        limit_cpu,
        limit_memory,
        steady,
    ) in contracts:
        document = document_by_identity(ROOT / relative_path, kind, name)
        resources = value_at(document, path)
        check_resources(
            label,
            resources,
            request_cpu,
            request_memory,
            limit_cpu,
            limit_memory,
            steady,
        )

    local_path_config = document_by_identity(
        ROOT / 'infrastructure/foundation/local-path-provisioner.yaml',
        'ConfigMap',
        'local-path-config',
    )
    helper_pod = yaml.safe_load(
        value_at(local_path_config, ('data', 'helperPod.yaml'))
    )
    helper_resources = value_at(
        helper_pod,
        ('spec', 'containers', ('name', 'helper-pod'), 'resources'),
    )
    check_resources(
        'local-path helper Pod',
        helper_resources,
        '10m',
        '16Mi',
        '100m',
        '64Mi',
        False,
    )

    expect_value(
        'infrastructure/cnpg/database/object-store.yaml',
        'ObjectStore',
        'platform-backup',
        ('spec', 'configuration', 'data', 'jobs'),
        1,
    )
    expect_value(
        'infrastructure/cnpg/database/object-store.yaml',
        'ObjectStore',
        'platform-backup',
        ('spec', 'configuration', 'wal', 'maxParallel'),
        1,
    )
    expect_value(
        'runbook/examples/postgres-restore.yaml',
        'ObjectStore',
        'platform-restore-source',
        ('spec', 'configuration', 'wal', 'maxParallel'),
        1,
    )

    if total_cpu_millicores > 2000:
        fail(f'DEV-002 稳态 CPU requests 超预算：{total_cpu_millicores}m')
    if total_memory_mib > 6144:
        fail(f'DEV-002 稳态内存 requests 超预算：{total_memory_mib}Mi')
    return total_cpu_millicores, total_memory_mib


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
    validate_single_user_resources()
    print('GitOps manifests validated successfully.')


if __name__ == '__main__':
    main()
