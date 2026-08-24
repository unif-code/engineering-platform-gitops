#!/usr/bin/env python3
"""校验 DEV GitOps 清单的可渲染性与关键安全约束。"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Tuple, Union
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
CURRENT_PCS = ROOT / 'pcs/candidate-2.md'
CURRENT_DOCS_ARCHITECTURE_COMMIT = 'd6d846a612c974991f4d0ffc0685d06adf2ddfe7'
CURRENT_DOCS_ARCHITECTURE_PLAN = (
    'docs/superpowers/plans/2026-08-23-pcs-runtime-reconciliation.md'
)
CURRENT_FRONTEND_SOURCE = 'da72238abc87a19c07a5cac96e41d88d5f6bf2d3'
CURRENT_FRONTEND_CI_RUN = '32683635240'
CURRENT_FRONTEND_PUBLISH_IMAGE_JOB = '97305929974'
CURRENT_FRONTEND_TAG = 'sha-da72238'
HISTORICAL_FRONTEND_SOURCE = 'c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c'
CURRENT_FRONTEND_OCI_INDEX_DIGEST = (
    'sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1'
)
CURRENT_FRONTEND_LINUX_AMD64_MANIFEST = (
    'sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c'
)
NOT_VERIFIED = 'NOT_VERIFIED'
CURRENT_MINIO_SERVER_STATUS = (
    'BLOCKED：精确摘要供应链证据或获批风险决定未满足；清单引用不代表获准或已部署'
)
CURRENT_FRONTEND_DOCUMENTS = (
    'pcs/candidate-2.md',
    'runbook/06-apps.md',
    'runbook/10-image-owner-handoff.md',
)
CURRENT_RUNTIME_DOCUMENTS = (
    'pcs/candidate-2.md',
    'runbook/01-bootstrap.md',
    'runbook/06-apps.md',
    'runbook/09-acceptance.md',
    'runbook/10-image-owner-handoff.md',
)
CURRENT_RUNTIME_FACTS = (
    ('采样时间', '2026-08-24 03:42Z'),
    ('GIT_COMMIT', '1c5034b9a9c29ab72fde63644c57fa88604c45b6'),
    ('RESULT', 'PASS_BOOTSTRAP_ALL_CHECK'),
    ('REASON', 'bootstrap-check-complete'),
    ('STAGE_00', 'PASS_PREFLIGHT'),
    (
        'STAGE_00 evidence',
        '/root/dev-infra-evidence/07-preflight-20260824T034100Z.txt',
    ),
    (
        'STAGE_00 SHA256',
        '14e4ca38101d8aead55c5a28a19ddd495a7bb94f5b736cc432bbd8fe5d55361a',
    ),
    ('STAGE_10-60', 'ALREADY_COMPLIANT'),
    ('STAGE_90', 'PASS_BOOTSTRAP_VERIFIED'),
    (
        'STAGE_90 evidence',
        '/root/dev-infra-evidence/14-verify-20260824T034246Z.txt',
    ),
    (
        'STAGE_90 SHA256',
        '0064b11860ec708491f290b7fb0594e02fcbc0737aed7674690ae1ded82ce4d5',
    ),
    ('NEXT_STAGE', 'NONE'),
    ('EXIT_CODE', '0'),
    ('COMMAND_EXIT_CODE', '0'),
    (
        'Namespace inventory',
        'cilium-secrets/default/gitlab-runner/kube-node-lease/kube-public/kube-system',
    ),
    ('Pod inventory', 'gitlab-runner and kube-system control plane/Cilium/CoreDNS only'),
    ('Inactive inventory', 'flux-system/platform/openbao absent; GitRepository query empty'),
)
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


HOST_ENV_KEYS = (
    'HOST_NAME', 'HOST_NODE_IP', 'HOST_CLUSTER_NAME', 'HOST_POD_CIDR',
    'HOST_SERVICE_CIDR', 'HOST_SWAP_FILE', 'HOST_SWAP_MIN_BYTES',
    'HOST_SWAP_MAX_BYTES',
)
HOST_FILES = ('host.env', 'kubeadm-init.yaml', 'cilium-values.yaml', 'pins.sha256')
PIN_FILES = ('kubeadm-init.yaml', 'cilium-values.yaml')
LABEL_RE = re.compile(r'^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$')
HOST_ENV_LINE_RE = re.compile(r'^(HOST_[A-Z_]+)=([A-Za-z0-9./_-]+)$')
SWAP_FILE_RE = re.compile(r'^/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$')
PIN_LINE_RE = re.compile(r'^([0-9a-f]{64})  (kubeadm-init\.yaml|cilium-values\.yaml)$')

# cilium-values.yaml 的锁死骨架：唯一可变的是 {node_ip}（取 host.env 的 HOST_NODE_IP）。
# 运行期孪生在 scripts/bootstrap/stages/60-install-cilium/run.sh 的 values_semantics_are_exact，
# 改这里必须同步改那里。
CILIUM_VALUES_SKELETON = '''kubeProxyReplacement: true
k8sServiceHost: {node_ip}
k8sServicePort: 6443

cgroup:
  autoMount:
    enabled: false
  hostRoot: /sys/fs/cgroup

gatewayAPI:
  enabled: true

hubble:
  enabled: false

image:
  digest: sha256:383968cd5e8873f7976fa76aa6196045643558f4cc9518a207b9335cb24a0e93
  useDigest: true

ipam:
  mode: kubernetes

operator:
  image:
    genericDigest: sha256:80744a8cc7c91c2f9e6347629406844eb35d79b30a732c6d41c15b17232a74f3
    useDigest: true
  replicas: 1
'''


def parse_host_env(path: Path) -> dict[str, str]:
    label = path.as_posix()
    try:
        text = path.read_bytes().decode('utf-8')
    except (OSError, UnicodeDecodeError) as error:
        # 仅注释行可含非 ASCII；键与值的 ASCII 约束由 HOST_ENV_LINE_RE 保证。
        fail(f'{label} 必须是可读的 UTF-8 文件：{error}')
    if not text.endswith('\n'):
        fail(f'{label} 末行必须以换行结束')
    values: dict[str, str] = {}
    for number, line in enumerate(text.split('\n')[:-1], 1):
        if not line or line.startswith('#'):
            continue
        match = HOST_ENV_LINE_RE.match(line)
        if match is None:
            fail(f'{label}:{number} 不符合 KEY=VALUE 语法（无引号、无空格、值仅含 [A-Za-z0-9./_-]）')
        key, value = match.groups()
        if key not in HOST_ENV_KEYS:
            fail(f'{label}:{number} 未知键 {key}')
        if key in values:
            fail(f'{label}:{number} 重复键 {key}')
        values[key] = value
    missing = [key for key in HOST_ENV_KEYS if key not in values]
    if missing:
        fail(f'{label} 缺少键：{", ".join(missing)}')
    for key in ('HOST_NAME', 'HOST_CLUSTER_NAME'):
        if LABEL_RE.match(values[key]) is None:
            fail(f'{label} {key} 必须是 RFC 1123 label：{values[key]}')
    octet = r'(0|[1-9][0-9]{0,2})'
    if re.fullmatch(rf'{octet}(\.{octet}){{3}}', values['HOST_NODE_IP']) is None:
        fail(f'{label} HOST_NODE_IP 不是点分四段且无前导零：{values["HOST_NODE_IP"]}')
    try:
        ipaddress.IPv4Address(values['HOST_NODE_IP'])
    except ValueError:
        fail(f'{label} HOST_NODE_IP 不是合法 IPv4：{values["HOST_NODE_IP"]}')
    for key in ('HOST_POD_CIDR', 'HOST_SERVICE_CIDR'):
        try:
            ipaddress.IPv4Network(values[key], strict=True)
        except ValueError:
            fail(f'{label} {key} 不是合法 IPv4 网络：{values[key]}')
        if '/' not in values[key]:
            fail(f'{label} {key} 必须带前缀长度：{values[key]}')
    if SWAP_FILE_RE.match(values['HOST_SWAP_FILE']) is None or '..' in values['HOST_SWAP_FILE']:
        fail(f'{label} HOST_SWAP_FILE 必须是绝对路径：{values["HOST_SWAP_FILE"]}')
    for key in ('HOST_SWAP_MIN_BYTES', 'HOST_SWAP_MAX_BYTES'):
        if not re.fullmatch(r'[1-9][0-9]{0,17}', values[key]):
            fail(f'{label} {key} 必须是正整数：{values[key]}')
    if int(values['HOST_SWAP_MIN_BYTES']) >= int(values['HOST_SWAP_MAX_BYTES']):
        fail(f'{label} HOST_SWAP_MIN_BYTES 必须小于 HOST_SWAP_MAX_BYTES')
    return values


def validate_host_kubeadm(path: Path, host: dict[str, str]) -> None:
    label = path.as_posix()
    try:
        documents = {
            document.get('kind'): document
            for document in yaml.safe_load_all(path.read_text(encoding='utf-8'))
            if isinstance(document, dict)
        }
    except yaml.YAMLError as error:
        fail(f'{label} YAML 解析失败：{error}')
    expect_contract(
        f'{label} kinds', set(documents),
        {'InitConfiguration', 'ClusterConfiguration', 'KubeletConfiguration'},
    )
    node_ip = host['HOST_NODE_IP']
    init = documents['InitConfiguration']
    expect_contract('InitConfiguration apiVersion', init.get('apiVersion'), 'kubeadm.k8s.io/v1beta4')
    expect_contract('API advertiseAddress', value_at(init, ('localAPIEndpoint', 'advertiseAddress')), node_ip)
    expect_contract('API bindPort', value_at(init, ('localAPIEndpoint', 'bindPort')), 6443)
    expect_contract('Node name', value_at(init, ('nodeRegistration', 'name')), host['HOST_NAME'])
    expect_contract('CRI socket', value_at(init, ('nodeRegistration', 'criSocket')), 'unix:///run/containerd/containerd.sock')
    expect_contract('single-node taints', value_at(init, ('nodeRegistration', 'taints')), [])
    expect_contract(
        'kubelet node-ip',
        value_at(init, ('nodeRegistration', 'kubeletExtraArgs')),
        [{'name': 'node-ip', 'value': node_ip}],
    )
    expect_contract('kube-proxy skip phase', init.get('skipPhases'), ['addon/kube-proxy'])

    cluster = documents['ClusterConfiguration']
    expect_contract('ClusterConfiguration apiVersion', cluster.get('apiVersion'), 'kubeadm.k8s.io/v1beta4')
    expect_contract('Kubernetes version', cluster.get('kubernetesVersion'), 'v1.36.3')
    expect_contract('clusterName', cluster.get('clusterName'), host['HOST_CLUSTER_NAME'])
    expect_contract('controlPlaneEndpoint', cluster.get('controlPlaneEndpoint'), f'{node_ip}:6443')
    expect_contract('API certificate SANs', value_at(cluster, ('apiServer', 'certSANs')), [node_ip])
    expect_contract('Service CIDR', value_at(cluster, ('networking', 'serviceSubnet')), host['HOST_SERVICE_CIDR'])
    expect_contract('Pod CIDR', value_at(cluster, ('networking', 'podSubnet')), host['HOST_POD_CIDR'])
    expect_contract('DNS domain', value_at(cluster, ('networking', 'dnsDomain')), 'cluster.local')
    expect_contract('kube-proxy disabled', value_at(cluster, ('proxy', 'disabled')), True)

    kubelet = documents['KubeletConfiguration']
    expect_contract('KubeletConfiguration apiVersion', kubelet.get('apiVersion'), 'kubelet.config.k8s.io/v1beta1')
    expect_contract('kubelet cgroup driver', kubelet.get('cgroupDriver'), 'systemd')
    expect_contract('kubelet failSwapOn', kubelet.get('failSwapOn'), False)
    expect_contract('kubelet swap behavior', value_at(kubelet, ('memorySwap', 'swapBehavior')), 'NoSwap')
    expect_contract('kubelet serverTLSBootstrap', kubelet.get('serverTLSBootstrap'), True)


def validate_host_cilium(path: Path, host: dict[str, str]) -> None:
    label = path.as_posix()
    try:
        cilium = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as error:
        fail(f'{label} YAML 解析失败：{error}')
    if not isinstance(cilium, dict):
        fail(f'{label} 顶层必须是 YAML mapping')
    expect_contract(
        f'{label} 顶层键集', set(cilium),
        {'kubeProxyReplacement', 'k8sServiceHost', 'k8sServicePort', 'cgroup',
         'gatewayAPI', 'hubble', 'image', 'ipam', 'operator'},
    )
    contracts = (
        (('kubeProxyReplacement',), True, 'kube-proxy replacement'),
        (('k8sServiceHost',), host['HOST_NODE_IP'], 'Cilium API host'),
        (('k8sServicePort',), 6443, 'Cilium API port'),
        (('ipam', 'mode'), 'kubernetes', 'Cilium IPAM'),
        (('gatewayAPI', 'enabled'), True, 'Cilium Gateway API'),
        (('cgroup', 'autoMount', 'enabled'), False, 'Cilium cgroup automount'),
        (('cgroup', 'hostRoot'), '/sys/fs/cgroup', 'Cilium cgroup root'),
        (('operator', 'replicas'), 1, 'Cilium operator replicas'),
        (('hubble', 'enabled'), False, 'Hubble staged state'),
        (('image', 'useDigest'), True, 'Cilium image useDigest'),
        (('image', 'digest'), 'sha256:383968cd5e8873f7976fa76aa6196045643558f4cc9518a207b9335cb24a0e93', 'Cilium image digest'),
        (('operator', 'image', 'useDigest'), True, 'Cilium operator useDigest'),
        (('operator', 'image', 'genericDigest'), 'sha256:80744a8cc7c91c2f9e6347629406844eb35d79b30a732c6d41c15b17232a74f3', 'Cilium operator digest'),
    )
    for path_tokens, expected, name in contracts:
        expect_contract(name, value_at(cilium, path_tokens), expected)
    # 结构化断言给出可读的失败原因；最后再按字节锁死排版、注释与键序。
    expected_text = CILIUM_VALUES_SKELETON.replace('{node_ip}', host['HOST_NODE_IP'])
    if path.read_text(encoding='utf-8') != expected_text:
        fail(f'{label} 内容必须与锁死骨架逐字一致（仅 k8sServiceHost 取 host.env）')


def validate_host_pins(host_dir: Path) -> None:
    pins = host_dir / 'pins.sha256'
    label = pins.as_posix()
    try:
        text = pins.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as error:
        fail(f'{label} 必须是可读的 UTF-8 文件：{error}')
    if not text.endswith('\n'):
        fail(f'{label} 末行必须以换行结束')
    lines = text.split('\n')[:-1]
    if len(lines) != len(PIN_FILES):
        fail(f'{label} 必须恰好 {len(PIN_FILES)} 行')
    hint = f'运行 scripts/bootstrap/pin-host.sh {host_dir.as_posix()}'
    for line, expected_name in zip(lines, PIN_FILES):
        match = PIN_LINE_RE.match(line)
        if match is None or match.group(2) != expected_name:
            fail(f'{label} 第 {PIN_FILES.index(expected_name) + 1} 行必须是 "<sha256>  {expected_name}"；{hint}')
        actual = hashlib.sha256((host_dir / expected_name).read_bytes()).hexdigest()
        if match.group(1) != actual:
            fail(f'{label} 中 {expected_name} 的 digest 与文件不一致；{hint}')


def validate_host_directory(host_dir: Path) -> None:
    label = host_dir.as_posix()
    if host_dir.is_symlink() or not host_dir.is_dir():
        fail(f'{label} 必须是真实目录')
    if LABEL_RE.match(host_dir.name) is None:
        fail(f'{label} 目录名必须是 RFC 1123 label')
    entries = sorted(entry.name for entry in host_dir.iterdir())
    if entries != sorted(HOST_FILES):
        fail(f'{label} 文件集必须精确为 {", ".join(HOST_FILES)}，实际：{", ".join(entries)}')
    for name in HOST_FILES:
        entry = host_dir / name
        if entry.is_symlink() or not entry.is_file():
            fail(f'{entry.as_posix()} 必须是常规文件（非软链）')
    host = parse_host_env(host_dir / 'host.env')
    if host['HOST_NAME'] != host_dir.name:
        fail(f'{label} 目录名必须等于 HOST_NAME={host["HOST_NAME"]}')
    validate_host_kubeadm(host_dir / 'kubeadm-init.yaml', host)
    validate_host_cilium(host_dir / 'cilium-values.yaml', host)
    validate_host_pins(host_dir)


def validate_bootstrap_contracts(root: Path = ROOT) -> None:
    bootstrap = root / 'bootstrap'
    validate_artifact_lock(bootstrap / 'artifacts.lock.tsv')

    containerd_config = bootstrap / 'containerd/config.toml'
    containerd_unit = bootstrap / 'containerd/containerd.service'
    for path in (containerd_config, containerd_unit):
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

    for legacy in ('kubeadm', 'cilium'):
        if (bootstrap / legacy).exists():
            fail(f'bootstrap/{legacy}/ 已迁入 bootstrap/hosts/<hostname>/，禁止保留旧目录')
    hosts_root = bootstrap / 'hosts'
    if hosts_root.is_symlink() or not hosts_root.is_dir():
        fail('bootstrap/hosts/ 必须是真实目录')
    host_dirs = sorted(entry for entry in hosts_root.iterdir())
    if not host_dirs:
        fail('bootstrap/hosts/ 至少需要一个主机目录')
    for host_dir in host_dirs:
        validate_host_directory(host_dir)


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

    pcs = CURRENT_PCS.read_text(encoding='utf-8')
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


def validate_rejected_chainguard_minio_candidate() -> None:
    pcs = CURRENT_PCS.read_text(encoding='utf-8')
    required_facts = (
        '已拒绝的 MinIO 替代候选',
        '候选结论：`REJECTED`',
        'sha256:cc18cac5456a3718bde96c368beaed53b9b876233f28c5f68b8fb667b9a528a7',
        'sha256:c9680a1ad80b56c67b2b9e44cc480a8fd0fb4362dab01f68b8bfbccae9d77596',
        'sha256:b456af84dd3aa6883e67a74e2cc9aca9b1e060197dcd040d73bdec9e8c6b99fb',
        'sha256:043d0ad5c2b297c0f0382dcac9b9436483d9f4a1d16cecdcc9471affb5e643e4',
    )
    for expected in required_facts:
        if expected not in pcs:
            fail(f'PCS 缺少 MinIO 被拒候选事实：{expected}')
    if (
        '供应链证据：`NOT_VERIFIED`' not in pcs
        or '激活结论：`BLOCKED`' not in pcs
    ):
        fail('MinIO 被拒候选缺少精确 digest 供应链证据或 BLOCKED 激活结论')

    minio_component = re.search(
        r'^\| Object Storage \| MinIO Server \|.*$',
        pcs,
        re.MULTILINE,
    )
    if minio_component is None:
        fail('PCS 缺少当前 MinIO Server 组件行')
    if (
        markdown_table_status_cell(minio_component.group(0))
        != CURRENT_MINIO_SERVER_STATUS
    ):
        fail('PCS 当前 MinIO Server 状态必须为 BLOCKED 且不得含正向激活语义')

    deployment = document_by_identity(
        ROOT / 'infrastructure/minio/deployment.yaml',
        'Deployment',
        'minio',
    )
    bootstrap = document_by_identity(
        ROOT / 'infrastructure/minio/bootstrap-job.yaml',
        'Job',
        'minio-bootstrap-v1',
    )
    active_images = {
        value_at(
            deployment,
            (
                'spec',
                'template',
                'spec',
                'containers',
                ('name', 'minio'),
                'image',
            ),
        ),
        value_at(
            bootstrap,
            (
                'spec',
                'template',
                'spec',
                'containers',
                ('name', 'mc'),
                'image',
            ),
        ),
    }
    rejected_digests = (
        'sha256:cc18cac5456a3718bde96c368beaed53b9b876233f28c5f68b8fb667b9a528a7',
        'sha256:c9680a1ad80b56c67b2b9e44cc480a8fd0fb4362dab01f68b8bfbccae9d77596',
        'sha256:b456af84dd3aa6883e67a74e2cc9aca9b1e060197dcd040d73bdec9e8c6b99fb',
        'sha256:043d0ad5c2b297c0f0382dcac9b9436483d9f4a1d16cecdcc9471affb5e643e4',
    )
    for image in active_images:
        if any(digest in image for digest in rejected_digests):
            fail(f'MinIO 清单引用了未获风险批准的 Chainguard 候选：{image}')


def markdown_section(document: str, heading: str) -> str:
    matches = list(re.finditer(rf'^{re.escape(heading)}\s*$', document, re.MULTILINE))
    if not matches:
        fail(f'文档缺少事实区段：{heading}')
    if len(matches) != 1:
        fail(f'文档事实区段重复：{heading}')
    start = matches[0].start()
    next_heading = re.search(r'^##\s+', document[matches[0].end() :], re.MULTILINE)
    if next_heading is None:
        return document[start:]
    return document[start : matches[0].end() + next_heading.start()]


def markdown_table_value(section: str, field: str) -> str:
    pattern = re.compile(rf'^\|\s*{re.escape(field)}\s*\|\s*(.*?)\s*\|\s*$', re.MULTILINE)
    match = pattern.search(section)
    if match is None:
        fail(f'事实区段缺少字段：{field}')
    return match.group(1).strip().strip('`')


def markdown_table_row(section: str, field: str) -> str:
    pattern = re.compile(rf'^\|\s*{re.escape(field)}\s*\|.*$', re.MULTILINE)
    match = pattern.search(section)
    if match is None:
        fail(f'事实区段缺少行：{field}')
    return match.group(0)


def markdown_table_status_cell(row: str) -> str:
    cells = [cell.strip() for cell in row.strip().split('|')[1:-1]]
    if not cells:
        fail('Markdown 表格行缺少状态单元格')
    return cells[-1].strip('`* ')


def is_blocked_status(status: str) -> bool:
    return re.match(r'^BLOCKED(?:$|[（(:：])', status) is not None


def validate_current_runtime_evidence() -> None:
    for relative_path in CURRENT_RUNTIME_DOCUMENTS:
        document = (ROOT / relative_path).read_text(encoding='utf-8')
        runtime = markdown_section(document, '## 当前 DEV Runtime 观测')
        for field, expected in CURRENT_RUNTIME_FACTS:
            if markdown_table_value(runtime, field) != expected:
                fail(f'当前 DEV Runtime 观测 {field} 与当前审计快照不一致')


def validate_current_frontend_evidence() -> None:
    for relative_path in CURRENT_FRONTEND_DOCUMENTS:
        document = (ROOT / relative_path).read_text(encoding='utf-8')
        current = markdown_section(document, '## 当前 frontend 候选')
        historical = markdown_section(document, '## 2026-08-22 frontend 历史证据')
        current_source = markdown_table_value(current, 'Source Commit')
        historical_source = markdown_table_value(historical, 'Source Commit')

        if current_source == historical_source or current_source == HISTORICAL_FRONTEND_SOURCE:
            fail('当前 frontend Source Commit 不能复用历史 Source Commit')
        if historical_source != HISTORICAL_FRONTEND_SOURCE:
            fail('frontend 历史证据必须保留已审计的 2026-08-22 Source Commit')
        if current_source != CURRENT_FRONTEND_SOURCE:
            fail('当前 frontend Source Commit 与当前审计快照不一致')

        if markdown_table_value(current, 'CI provenance') != 'VERIFIED':
            fail('当前 frontend CI provenance 必须为 VERIFIED')
        verified_facts = (
            ('Source Commit', CURRENT_FRONTEND_SOURCE),
            ('CI run', CURRENT_FRONTEND_CI_RUN),
            ('publish-image job', CURRENT_FRONTEND_PUBLISH_IMAGE_JOB),
            ('Image tag', CURRENT_FRONTEND_TAG),
            ('Artifact / OCI index digest', CURRENT_FRONTEND_OCI_INDEX_DIGEST),
            (
                'linux/amd64 manifest digest',
                CURRENT_FRONTEND_LINUX_AMD64_MANIFEST,
            ),
        )
        for field, expected in verified_facts:
            if markdown_table_value(current, field) != expected:
                fail(f'当前 frontend {field} 与当前审计快照不一致')
        if markdown_table_value(current, 'Runtime Image ID') != NOT_VERIFIED:
            fail('当前 frontend Runtime Image ID 在未部署前必须为 NOT_VERIFIED')


def validate_current_frontend_summary_evidence() -> None:
    pcs = CURRENT_PCS.read_text(encoding='utf-8')
    component = re.search(
        r'^\| Application \| engineering-platform frontend \|.*$',
        pcs,
        re.MULTILINE,
    )
    if component is None:
        fail('PCS 缺少 frontend 组件表行')
    component_facts = (
        CURRENT_FRONTEND_SOURCE,
        CURRENT_FRONTEND_CI_RUN,
        CURRENT_FRONTEND_PUBLISH_IMAGE_JOB,
        CURRENT_FRONTEND_TAG,
        CURRENT_FRONTEND_OCI_INDEX_DIGEST,
        CURRENT_FRONTEND_LINUX_AMD64_MANIFEST,
        NOT_VERIFIED,
    )
    if not all(expected in component.group(0) for expected in component_facts):
        fail('PCS frontend 组件表与当前审计快照不一致')

    handoff = (ROOT / 'runbook/10-image-owner-handoff.md').read_text(
        encoding='utf-8'
    )
    table_header = '| 字段 | frontend | backend |'
    table_start = handoff.find(table_header)
    if table_start == -1:
        fail('Image Owner Handoff 缺少汇总表')
    summary = handoff[table_start:]
    summary_facts = (
        ('Source commit（完整 40 位 SHA）', (CURRENT_FRONTEND_SOURCE,)),
        (
            'CI run URL',
            (CURRENT_FRONTEND_CI_RUN, CURRENT_FRONTEND_PUBLISH_IMAGE_JOB),
        ),
        ('Image tag `sha-<short-sha>`', (CURRENT_FRONTEND_TAG,)),
        ('OCI index digest', (CURRENT_FRONTEND_OCI_INDEX_DIGEST,)),
        (
            '`linux/amd64` manifest digest',
            (CURRENT_FRONTEND_LINUX_AMD64_MANIFEST,),
        ),
        ('Runtime Image ID', (NOT_VERIFIED,)),
    )
    for field, expected_values in summary_facts:
        row = markdown_table_row(summary, field)
        if not all(expected in row for expected in expected_values):
            fail(f'Image Owner Handoff 汇总表 {field} 与当前审计快照不一致')


def validate_current_docs_architecture_commit() -> None:
    pcs = CURRENT_PCS.read_text(encoding='utf-8')
    facts = markdown_section(pcs, '## 事实采样')
    if (
        markdown_table_value(facts, 'docs 架构事实提交')
        != CURRENT_DOCS_ARCHITECTURE_COMMIT
    ):
        fail('当前 docs 架构事实提交与已推送 main 不一致')

    plan = (ROOT / CURRENT_DOCS_ARCHITECTURE_PLAN).read_text(encoding='utf-8')
    plan_facts = (
        f'事实提交为远端可追溯的 `{CURRENT_DOCS_ARCHITECTURE_COMMIT}`',
        f'事实提交为 `{CURRENT_DOCS_ARCHITECTURE_COMMIT}`',
        f'| docs 架构事实提交 | `{CURRENT_DOCS_ARCHITECTURE_COMMIT}` |',
    )
    if (
        '6267120f345e7ad967daf08fb244c6018054281d' in plan
        or not all(expected in plan for expected in plan_facts)
    ):
        fail('当前 docs 架构事实提交计划与已推送 main 不一致')


def validate_blocked_storage_acceptance() -> None:
    pcs = CURRENT_PCS.read_text(encoding='utf-8')
    dependencies = markdown_section(pcs, '## 当前阻塞依赖')
    flux = markdown_table_value(dependencies, 'Flux')
    minio = markdown_table_value(dependencies, 'MinIO')
    if flux != 'BLOCKED' or minio != 'BLOCKED':
        fail('当前 Candidate Flux/MinIO 依赖状态必须均为 BLOCKED')

    acceptance = (ROOT / 'runbook/09-acceptance.md').read_text(encoding='utf-8')
    required_rows = (
        ('3', 'PG PITR 与 etcd 隔离 restore', ('Flux', 'MinIO')),
        ('4', '三 bucket Versioning/Object Lock', ('MinIO',)),
        ('6', '容量与整机重启', ('Flux', 'MinIO')),
    )
    for number, criterion, dependencies in required_rows:
        row = re.search(rf'^\|\s*{number}\s*\|.*$', acceptance, re.MULTILINE)
        if row is None:
            fail(f'Flux/MinIO 仍 BLOCKED 时，{criterion} 验收状态必须为 BLOCKED')
        status = markdown_table_status_cell(row.group(0))
        if (
            not is_blocked_status(status)
            or re.search(r'\b(?:PASS|APPROVED)\b', status) is not None
            or not all(expected in row.group(0) for expected in dependencies)
        ):
            fail(
                f'Flux/MinIO 仍 BLOCKED 时，{criterion} 验收状态必须为 BLOCKED'
            )


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
    validate_rejected_chainguard_minio_candidate()
    validate_current_runtime_evidence()
    validate_current_frontend_evidence()
    validate_current_frontend_summary_evidence()
    validate_current_docs_architecture_commit()
    validate_blocked_storage_acceptance()
    print('GitOps manifests validated successfully.')


if __name__ == '__main__':
    main()
