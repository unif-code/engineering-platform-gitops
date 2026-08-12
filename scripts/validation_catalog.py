from __future__ import annotations

import collections
import importlib
import inspect
import unittest


SHARD_ORDER = (
    'contracts', 'artifacts', 'kernel', 'containerd',
    'kubernetes', 'kubeadm', 'cilium', 'final-verify',
)

SHARDS = {
    'contracts': (
        'test_validate.ProfileValidationTest',
        'test_validate.RepositoryProfileContractTest',
        'test_validate.ActiveRootIsolationTest',
        'test_validate.BootstrapContractTest',
        'test_validate.ValidateEntrypointTest',
        'test_validate.ValidationCatalogTest',
        'test_bootstrap.CommonLibraryTest',
        'test_bootstrap.CidrCheckTest',
        'test_bootstrap.PreflightTest',
        'test_bootstrap.BootstrapEntrySecurityTest',
    ),
    'artifacts': ('test_bootstrap.ArtifactStageTest',),
    'kernel': ('test_bootstrap.KernelStageTest',),
    'containerd': ('test_bootstrap.ContainerdInstallTest',),
    'kubernetes': ('test_bootstrap.KubernetesInstallTest',),
    'kubeadm': ('test_bootstrap.KubeadmInitTest',),
    'cilium': ('test_bootstrap.CiliumInstallTest',),
    'final-verify': ('test_bootstrap.FinalVerifyTest',),
}

FAST_SHARDS = ('contracts',)


def discover_concrete_test_cases() -> tuple[str, ...]:
    loader = unittest.defaultTestLoader
    discovered: list[str] = []
    for module_name in ('test_validate', 'test_bootstrap'):
        module = importlib.import_module(module_name)
        for class_name, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate.__module__ != module_name:
                continue
            if not issubclass(candidate, unittest.TestCase):
                continue
            if not loader.getTestCaseNames(candidate):
                continue
            discovered.append(f'{module_name}.{class_name}')
    return tuple(sorted(discovered))


def validate_catalog() -> None:
    assigned = [
        selector for name in SHARD_ORDER for selector in SHARDS.get(name, ())
    ]
    counts = collections.Counter(assigned)
    duplicate = sorted(name for name, count in counts.items() if count != 1)
    discovered = set(discover_concrete_test_cases())
    unknown = sorted(set(assigned) - discovered)
    missing = sorted(discovered - set(assigned))
    empty = sorted(name for name in SHARD_ORDER if not SHARDS.get(name))
    if duplicate or unknown or missing or empty or set(SHARDS) != set(SHARD_ORDER):
        raise ValueError(
            f'catalog invalid: duplicate={duplicate}; unknown={unknown}; '
            f'missing={missing}; empty={empty}'
        )


def selectors_for_profile(name: str) -> tuple[str, ...]:
    if name == 'full':
        shards = SHARD_ORDER
    elif name == 'fast':
        shards = FAST_SHARDS
    else:
        raise ValueError(f'unknown validation profile: {name}')
    return tuple(selector for shard in shards for selector in SHARDS[shard])


def selectors_for_shard(name: str) -> tuple[str, ...]:
    try:
        return SHARDS[name]
    except KeyError:
        raise ValueError(f'unknown validation shard: {name}') from None


def matrix_document() -> dict[str, list[dict[str, str]]]:
    return {'include': [{'shard': name} for name in SHARD_ORDER]}
