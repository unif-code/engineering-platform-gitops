#!/usr/bin/env python3
"""校验 DEV GitOps 清单的可渲染性与关键安全约束。"""

from __future__ import annotations

import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Tuple, Union
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOTS = (ROOT / 'clusters', ROOT / 'infrastructure', ROOT / 'apps')
EXACT_VERSION = re.compile(r'^v?\d+\.\d+\.\d+$')
FLOATING_IMAGE = re.compile(r':(?:latest|main|master)$')
PLACEHOLDER = re.compile(r'(?:REPLACE_ME|TODO_DIGEST|<[^>]+>)')
INSECURE_TLS = re.compile(
    r'(?:--insecure\b|insecureSkip(?:TLS)?Verify:\s*true)'
)

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

REQUIRED_METRICS_SERVER_RESOURCES = {
    (
        'helm.toolkit.fluxcd.io/v2',
        'HelmRelease',
        'monitoring',
        'metrics-server',
    ),
}

ACTIVE_ROOT_RESOURCES = ('flux-system',)
INACTIVE_ENTRYPOINTS = (
    'clusters/dev/reconcile-rbac.yaml',
    'clusters/dev/infrastructure.yaml',
    'clusters/dev/apps.yaml',
    'clusters/dev/flux-system/gotk-components.yaml',
    'clusters/dev/flux-system/gotk-sync.yaml',
)

BOOTSTRAP_ARTIFACTS = {
    'containerd': (
        '2.3.1',
        'https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz',
        '628448bd973610c656c1cbea8e88b32fafd85b23cc1aa4a3372eb7198478c054',
        '/usr/local/bin',
    ),
    'runc': (
        '1.3.6',
        'https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64',
        '3f3921dbbee7723e9868f97e88e51ffc910206e3ba55646e74d93d24ea76023c',
        '/usr/local/sbin/runc',
    ),
    'crictl': (
        '1.36.0',
        'https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz',
        '83855e114566a8a8c44c548d515670f51de3a5e1da8b2effb59870e2f10c25a3',
        '/usr/local/bin/crictl',
    ),
    'helm': (
        '3.21.0',
        'https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
        '0093eb572e3d2380f094df162ddb525e219249de88957afe24cfbb19632acd36',
        '/usr/local/bin/helm',
    ),
    'gateway-api': (
        '1.6.1',
        'https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml',
        '24d931f22abd8e40c973264319ead7cfa09d0fb7716b7ab1ee2ff174cb063a73',
        'kubernetes://gateway-api/standard',
    ),
    'cilium-chart': (
        '1.20.0',
        'https://helm.cilium.io/cilium-1.20.0.tgz',
        'c5f013912360d1a334f44ef25f36da59ba3414cdb48f466ee12d0c4fdff27883',
        'kubernetes://kube-system/cilium',
    ),
}

BOOTSTRAP_ARTIFACT_HOSTS = {
    'github.com',
    'get.helm.sh',
    'helm.cilium.io',
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


def validate_active_root(root: Path = ROOT) -> None:
    root_kustomization = root / 'clusters/dev/kustomization.yaml'
    if not root_kustomization.is_file():
        fail('clusters/dev/kustomization.yaml 不存在')

    try:
        document = yaml.safe_load(root_kustomization.read_text(encoding='utf-8'))
    except yaml.YAMLError as error:
        fail(f'clusters/dev/kustomization.yaml YAML 解析失败：{error}')
    if not isinstance(document, dict):
        fail('clusters/dev/kustomization.yaml 顶层必须是 YAML mapping')

    resources = document.get('resources')
    if resources != list(ACTIVE_ROOT_RESOURCES):
        fail(
            'clusters/dev 活动根只允许引用 flux-system；'
            f'实测 resources={resources!r}'
        )

    required_headers = (
        '# STATUS: ',
        '# ACTIVE: false',
        '# REASON: ',
        '# ACTIVATION_GATES: ',
    )
    for relative_path in INACTIVE_ENTRYPOINTS:
        path = root / relative_path
        if not path.exists():
            continue
        header = '\n'.join(path.read_text(encoding='utf-8').splitlines()[:8])
        for required in required_headers:
            if required not in header:
                fail(f'{relative_path} 缺少 inactive 审计字段：{required.strip()}')


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


def validate_artifact_lock(path: Path) -> None:
    if not path.is_file():
        fail('bootstrap/artifacts.lock.tsv 不存在')

    seen: dict[str, tuple[str, str, str, str]] = {}
    for line_number, line in enumerate(
        path.read_text(encoding='utf-8').splitlines(), start=1
    ):
        if not line:
            fail(f'artifacts.lock.tsv 第 {line_number} 行不能为空')
        fields = line.split('\t')
        if len(fields) != 5:
            fail(f'artifacts.lock.tsv 第 {line_number} 行必须恰好为五列')
        name, version, url, digest, target = fields
        if name in seen:
            fail(f'artifacts.lock.tsv 重复 artifact：{name}')
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            fail(f'artifacts.lock.tsv {name} 版本不是精确三段版本：{version}')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in BOOTSTRAP_ARTIFACT_HOSTS:
            fail(f'artifacts.lock.tsv {name} URL 不是获准官方 HTTPS 来源')
        if parsed.query or parsed.fragment or version not in parsed.path:
            fail(f'artifacts.lock.tsv {name} URL 未固定同一精确版本')
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            fail(f'artifacts.lock.tsv {name} SHA-256 格式无效')
        seen[name] = (version, url, digest, target)

    if seen != BOOTSTRAP_ARTIFACTS:
        missing = sorted(set(BOOTSTRAP_ARTIFACTS) - set(seen))
        unexpected = sorted(set(seen) - set(BOOTSTRAP_ARTIFACTS))
        drifted = sorted(
            name
            for name in set(seen) & set(BOOTSTRAP_ARTIFACTS)
            if seen[name] != BOOTSTRAP_ARTIFACTS[name]
        )
        fail(
            'artifacts.lock.tsv 与批准锁不一致：'
            f'missing={missing}, unexpected={unexpected}, drifted={drifted}'
        )


def expect_contract(label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        fail(f'{label} 期望 {expected!r}，实测 {actual!r}')


def validate_bootstrap_contracts(root: Path = ROOT) -> None:
    bootstrap = root / 'bootstrap'
    validate_artifact_lock(bootstrap / 'artifacts.lock.tsv')

    containerd_config = bootstrap / 'containerd/config.toml'
    containerd_unit = bootstrap / 'containerd/containerd.service'
    kubeadm_config = bootstrap / 'kubeadm/init.yaml'
    cilium_values = bootstrap / 'cilium/values.yaml'
    for path in (
        containerd_config,
        containerd_unit,
        kubeadm_config,
        cilium_values,
    ):
        if not path.is_file():
            fail(f'{path.relative_to(root)} 不存在')

    containerd_source = containerd_config.read_text(encoding='utf-8')
    containerd_fragments = (
        'version = 4',
        'root = "/var/lib/containerd"',
        'state = "/run/containerd"',
        '[plugins."io.containerd.server.v1.grpc"]',
        'address = "/run/containerd/containerd.sock"',
        '[plugins."io.containerd.cri.v1.images"]',
        'snapshotter = "overlayfs"',
        '[plugins."io.containerd.cri.v1.runtime"]',
        'default_runtime_name = "runc"',
        'runtime_type = "io.containerd.runc.v2"',
        'BinaryName = "/usr/local/sbin/runc"',
        'SystemdCgroup = true',
        'bin_dirs = ["/opt/cni/bin"]',
        'conf_dir = "/etc/cni/net.d"',
    )
    for fragment in containerd_fragments:
        if containerd_source.count(fragment) != 1:
            fail(f'bootstrap/containerd/config.toml 必须且只能包含一次：{fragment}')
    if 'io.containerd.grpc.v1.cri' in containerd_source:
        fail('bootstrap/containerd/config.toml 禁止使用 containerd 1.x CRI plugin ID')

    unit_source = containerd_unit.read_text(encoding='utf-8')
    unit_fragments = (
        '[Unit]',
        'After=network.target dbus.service',
        '[Service]',
        'ExecStart=/usr/local/bin/containerd',
        'Type=notify',
        'Delegate=yes',
        'KillMode=process',
        'Restart=always',
        'OOMScoreAdjust=-999',
        '[Install]',
        'WantedBy=multi-user.target',
    )
    for fragment in unit_fragments:
        if unit_source.count(fragment) != 1:
            fail(f'bootstrap/containerd/containerd.service 合同漂移：{fragment}')

    try:
        kubeadm_documents = {
            document.get('kind'): document
            for document in yaml.safe_load_all(
                kubeadm_config.read_text(encoding='utf-8')
            )
            if isinstance(document, dict)
        }
    except yaml.YAMLError as error:
        fail(f'bootstrap/kubeadm/init.yaml YAML 解析失败：{error}')
    expect_contract(
        'kubeadm kinds',
        set(kubeadm_documents),
        {'InitConfiguration', 'ClusterConfiguration', 'KubeletConfiguration'},
    )

    init = kubeadm_documents['InitConfiguration']
    expect_contract('InitConfiguration apiVersion', init.get('apiVersion'), 'kubeadm.k8s.io/v1beta4')
    expect_contract('API advertiseAddress', value_at(init, ('localAPIEndpoint', 'advertiseAddress')), '10.93.1.27')
    expect_contract('API bindPort', value_at(init, ('localAPIEndpoint', 'bindPort')), 6443)
    expect_contract('Node name', value_at(init, ('nodeRegistration', 'name')), 'retail-test-workflow')
    expect_contract('CRI socket', value_at(init, ('nodeRegistration', 'criSocket')), 'unix:///run/containerd/containerd.sock')
    expect_contract('single-node taints', value_at(init, ('nodeRegistration', 'taints')), [])
    expect_contract('kube-proxy skip phase', init.get('skipPhases'), ['addon/kube-proxy'])

    cluster = kubeadm_documents['ClusterConfiguration']
    expect_contract('ClusterConfiguration apiVersion', cluster.get('apiVersion'), 'kubeadm.k8s.io/v1beta4')
    expect_contract('Kubernetes version', cluster.get('kubernetesVersion'), 'v1.36.3')
    expect_contract('controlPlaneEndpoint', cluster.get('controlPlaneEndpoint'), '10.93.1.27:6443')
    expect_contract('API certificate SANs', value_at(cluster, ('apiServer', 'certSANs')), ['10.93.1.27'])
    expect_contract('Service CIDR', value_at(cluster, ('networking', 'serviceSubnet')), '172.20.0.0/16')
    expect_contract('Pod CIDR', value_at(cluster, ('networking', 'podSubnet')), '172.21.0.0/16')
    expect_contract('kube-proxy disabled', value_at(cluster, ('proxy', 'disabled')), True)

    kubelet = kubeadm_documents['KubeletConfiguration']
    expect_contract('KubeletConfiguration apiVersion', kubelet.get('apiVersion'), 'kubelet.config.k8s.io/v1beta1')
    expect_contract('kubelet cgroup driver', kubelet.get('cgroupDriver'), 'systemd')
    expect_contract('kubelet failSwapOn', kubelet.get('failSwapOn'), False)
    expect_contract('kubelet swap behavior', value_at(kubelet, ('memorySwap', 'swapBehavior')), 'NoSwap')
    expect_contract('kubelet serverTLSBootstrap', kubelet.get('serverTLSBootstrap'), True)

    try:
        cilium = yaml.safe_load(cilium_values.read_text(encoding='utf-8'))
    except yaml.YAMLError as error:
        fail(f'bootstrap/cilium/values.yaml YAML 解析失败：{error}')
    if not isinstance(cilium, dict):
        fail('bootstrap/cilium/values.yaml 顶层必须是 YAML mapping')
    cilium_contracts = (
        (('kubeProxyReplacement',), True, 'kube-proxy replacement'),
        (('k8sServiceHost',), '10.93.1.27', 'Cilium API host'),
        (('k8sServicePort',), 6443, 'Cilium API port'),
        (('ipam', 'mode'), 'kubernetes', 'Cilium IPAM'),
        (('gatewayAPI', 'enabled'), True, 'Cilium Gateway API'),
        (('cgroup', 'autoMount', 'enabled'), False, 'Cilium cgroup automount'),
        (('cgroup', 'hostRoot'), '/sys/fs/cgroup', 'Cilium cgroup root'),
        (('operator', 'replicas'), 1, 'Cilium operator replicas'),
        (('hubble', 'enabled'), False, 'Hubble staged state'),
    )
    for path, expected, label in cilium_contracts:
        expect_contract(label, value_at(cilium, path), expected)


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
            'metrics-server',
            'infrastructure/observability/controller/metrics-server-release.yaml',
            'HelmRelease',
            'metrics-server',
            ('spec', 'values', 'resources'),
            '20m', '64Mi', '100m', '128Mi', True,
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


def validate_metrics_server() -> None:
    repository_path = (
        ROOT
        / 'infrastructure/observability/controller/metrics-server-repository.yaml'
    )
    release_path = (
        ROOT
        / 'infrastructure/observability/controller/metrics-server-release.yaml'
    )
    for path in (repository_path, release_path):
        if not path.exists():
            fail(f'缺少 {path.relative_to(ROOT)}')

    expect_value(
        'infrastructure/observability/controller/metrics-server-repository.yaml',
        'HelmRepository',
        'metrics-server',
        ('spec', 'url'),
        'https://kubernetes-sigs.github.io/metrics-server',
    )

    release_contracts = (
        (('spec', 'chart', 'spec', 'chart'), 'metrics-server'),
        (('spec', 'chart', 'spec', 'reconcileStrategy'), 'ChartVersion'),
        (('spec', 'chart', 'spec', 'sourceRef', 'kind'), 'HelmRepository'),
        (('spec', 'chart', 'spec', 'sourceRef', 'name'), 'metrics-server'),
        (('spec', 'chart', 'spec', 'version'), '3.13.1'),
        (('spec', 'targetNamespace'), 'kube-system'),
        (('spec', 'values', 'apiService', 'insecureSkipTLSVerify'), False),
        (
            ('spec', 'values', 'image', 'repository'),
            'registry.k8s.io/metrics-server/metrics-server',
        ),
        (
            ('spec', 'values', 'image', 'tag'),
            'v0.8.1@sha256:6231fb0a1ffab76c92ab880f51a0d11b290f688373647bcedff85af025dfd8a9',
        ),
        (('spec', 'values', 'replicas'), 1),
        (('spec', 'values', 'tls', 'type'), 'cert-manager'),
        (
            (
                'spec',
                'values',
                'tls',
                'certManager',
                'existingIssuer',
                'enabled',
            ),
            True,
        ),
        (
            (
                'spec',
                'values',
                'tls',
                'certManager',
                'existingIssuer',
                'kind',
            ),
            'ClusterIssuer',
        ),
        (
            (
                'spec',
                'values',
                'tls',
                'certManager',
                'existingIssuer',
                'name',
            ),
            'dev-selfsigned',
        ),
        (('spec', 'values', 'resources', 'requests', 'cpu'), '20m'),
        (('spec', 'values', 'resources', 'requests', 'memory'), '64Mi'),
        (('spec', 'values', 'resources', 'limits', 'cpu'), '100m'),
        (('spec', 'values', 'resources', 'limits', 'memory'), '128Mi'),
    )
    for path, expected in release_contracts:
        expect_value(
            'infrastructure/observability/controller/metrics-server-release.yaml',
            'HelmRelease',
            'metrics-server',
            path,
            expected,
        )

    controller_kustomization = next(
        load_documents(
            ROOT / 'infrastructure/observability/controller/kustomization.yaml'
        )
    )
    resources = set(controller_kustomization.get('resources', []))
    required_resources = {
        'metrics-server-repository.yaml',
        'metrics-server-release.yaml',
    }
    if not required_resources.issubset(resources):
        fail('observability controller Kustomization 未接入 metrics-server')

    infrastructure = document_by_identity(
        ROOT / 'clusters/dev/infrastructure.yaml',
        'Kustomization',
        'observability-controller',
    )
    dependencies = {
        dependency.get('name')
        for dependency in value_at(infrastructure, ('spec', 'dependsOn'))
        if isinstance(dependency, dict)
    }
    required_dependencies = {'cert-manager-config', 'infrastructure-foundation'}
    if not required_dependencies.issubset(dependencies):
        fail('observability-controller 必须等待 cert-manager-config 与 foundation')

    pcs = (ROOT / 'pcs/candidate-1.md').read_text(encoding='utf-8')
    pcs_contracts = (
        'Metrics Server',
        '0.8.1',
        '3.13.1',
        'sha256:084e6edb680cf4e2acc30bd496568c53fdf663cbacf6e17876b25785c35b7a13',
        'sha256:b2d2efaf5ac3b366ed0f839d2412a2c4279d4fc2a2a733f12c52133faed36c41',
        'sha256:6231fb0a1ffab76c92ab880f51a0d11b290f688373647bcedff85af025dfd8a9',
    )
    for expected in pcs_contracts:
        if expected not in pcs:
            fail(f'PCS 缺少 Metrics Server 供应链事实：{expected}')


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

    missing = sorted(REQUIRED_METRICS_SERVER_RESOURCES - found)
    if missing:
        formatted = ', '.join(
            f'{kind}/{namespace or "_cluster"}/{name}'
            for _, kind, namespace, name in missing
        )
        fail(f'DEV-002 Metrics API 缺少资源：{formatted}')


def main() -> None:
    validate_active_root()
    validate_bootstrap_contracts()
    validate_kustomize_builds()
    validate_documents()
    validate_single_user_storage()
    validate_single_user_resources()
    validate_metrics_server()
    print('GitOps manifests validated successfully.')


if __name__ == '__main__':
    main()
