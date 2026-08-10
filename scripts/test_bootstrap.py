from __future__ import annotations

import hashlib
import io
import os
import socket
import subprocess
import tarfile
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / 'scripts/bootstrap/lib/common.sh'
CIDR_CHECK = ROOT / 'scripts/bootstrap/check_cidrs.py'
PREFLIGHT = ROOT / 'scripts/bootstrap/00-preflight.sh'
STAGE_ARTIFACTS = ROOT / 'scripts/bootstrap/10-stage-artifacts.sh'
PREPARE_KERNEL = ROOT / 'scripts/bootstrap/20-prepare-kernel.sh'
INSTALL_CONTAINERD = ROOT / 'scripts/bootstrap/30-install-containerd.sh'


class BootstrapTestCase(unittest.TestCase):
    def temporary_directory(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def run_command(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            check=False,
            text=True,
        )


class CommonLibraryTest(BootstrapTestCase):
    def run_common(self, body: str) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            ['/bin/bash', '-c', f'source "$1"\n{body}', 'test-common', str(COMMON)]
        )

    def test_parse_mode_defaults_to_check(self) -> None:
        result = self.run_common('parse_mode\nprintf "%s\\n" "$MODE"')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'CHECK\n')

    def test_parse_mode_accepts_only_explicit_apply(self) -> None:
        apply_result = self.run_common(
            'parse_mode --apply\nprintf "%s\\n" "$MODE"'
        )
        invalid_result = self.run_common('parse_mode --force')

        self.assertEqual(apply_result.returncode, 0, apply_result.stderr)
        self.assertEqual(apply_result.stdout, 'APPLY\n')
        self.assertEqual(invalid_result.returncode, 10)

    def test_managed_file_reports_all_three_states(self) -> None:
        directory = self.temporary_directory()
        source = directory / 'source'
        target = directory / 'target'
        source.write_text('approved\n', encoding='utf-8')

        missing = self.run_common(
            f'managed_file_state "{source}" "{target}"'
        )
        target.write_text('approved\n', encoding='utf-8')
        compliant = self.run_common(
            f'managed_file_state "{source}" "{target}"'
        )
        target.write_text('unknown\n', encoding='utf-8')
        unknown = self.run_common(
            f'managed_file_state "{source}" "{target}"'
        )

        self.assertEqual(missing.stdout, 'MISSING\n')
        self.assertEqual(compliant.stdout, 'COMPLIANT\n')
        self.assertEqual(unknown.stdout, 'UNKNOWN\n')

    def test_install_managed_file_refuses_unknown_target(self) -> None:
        directory = self.temporary_directory()
        source = directory / 'source'
        target = directory / 'target'
        source.write_text('approved\n', encoding='utf-8')
        target.write_text('unknown\n', encoding='utf-8')

        result = self.run_common(
            f'install_managed_file "{source}" "{target}" 0644'
        )

        self.assertEqual(result.returncode, 30)
        self.assertEqual(target.read_text(encoding='utf-8'), 'unknown\n')

    def test_open_evidence_never_overwrites_existing_file(self) -> None:
        directory = self.temporary_directory()
        evidence = directory / '07-preflight-20260810T000000Z.txt'
        evidence.write_text('preserve\n', encoding='utf-8')

        result = self.run_common(
            f'open_evidence 07-preflight "{directory}" 20260810T000000Z'
        )

        self.assertEqual(result.returncode, 30)
        self.assertEqual(evidence.read_text(encoding='utf-8'), 'preserve\n')


class CidrCheckTest(BootstrapTestCase):
    def run_cidr(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_command(['/usr/bin/python3', str(CIDR_CHECK), *arguments])

    def base_arguments(self) -> list[str]:
        return [
            '--service-cidr',
            '172.20.0.0/16',
            '--pod-cidr',
            '172.21.0.0/16',
        ]

    def test_accepts_non_overlapping_local_networks(self) -> None:
        result = self.run_cidr(
            *self.base_arguments(),
            '--address',
            '10.93.1.27/24',
            '--route',
            '10.93.1.0/24',
            '--route',
            '10.0.0.0/8',
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_CIDRS', result.stdout)
        self.assertIn('SCOPE=SERVER_LOCAL_SCOPE_ONLY', result.stdout)

    def test_rejects_service_cidr_overlapping_address(self) -> None:
        result = self.run_cidr(
            *self.base_arguments(), '--address', '172.20.8.2/24'
        )

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_CIDR_OVERLAP', result.stdout)

    def test_rejects_pod_cidr_overlapping_route(self) -> None:
        result = self.run_cidr(
            *self.base_arguments(), '--route', '172.21.8.0/24'
        )

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_CIDR_OVERLAP', result.stdout)

    def test_rejects_service_and_pod_overlap(self) -> None:
        result = self.run_cidr(
            '--service-cidr',
            '172.20.0.0/16',
            '--pod-cidr',
            '172.20.128.0/17',
        )

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_CIDR_OVERLAP', result.stdout)


class PreflightTest(BootstrapTestCase):
    cleanup_digest = (
        'a68a3d2ff340bcdcb4265853107a3a2c22a9f7328728473d81d9be2d1486e635'
    )

    def write_executable(self, path: Path, source: str) -> None:
        path.write_text(textwrap.dedent(source).lstrip(), encoding='utf-8')
        path.chmod(0o755)

    def make_environment(self) -> tuple[dict[str, str], Path]:
        directory = self.temporary_directory()
        host = directory / 'host'
        fake_bin = directory / 'bin'
        (host / 'etc').mkdir(parents=True)
        (host / 'root/dev-infra-evidence').mkdir(parents=True)
        fake_bin.mkdir()
        (host / 'etc/os-release').write_text(
            'ID=ubuntu\nVERSION_ID="24.04"\n', encoding='utf-8'
        )
        (host / 'swap.img').write_bytes(b'')
        cleanup = (
            host
            / 'root/dev-infra-evidence'
            / '06-host-workflow-cleanup-20260810T033358Z.txt'
        )
        cleanup.write_text('fixture content is hashed by fake shasum\n', encoding='utf-8')

        self.write_executable(
            fake_bin / 'id',
            '''
            #!/bin/sh
            [ "$1" = "-u" ] || exit 2
            printf '%s\n' "${FAKE_ID_UID:-0}"
            ''',
        )
        self.write_executable(
            fake_bin / 'hostname',
            '''
            #!/bin/sh
            [ -z "${FAKE_CANARY:-}" ] || printf '%s\n' "$FAKE_CANARY" >&2
            printf '%s\n' "${FAKE_HOSTNAME:-retail-test-workflow}"
            ''',
        )
        self.write_executable(
            fake_bin / 'uname',
            '''
            #!/bin/sh
            printf '%s\n' "${FAKE_ARCH:-x86_64}"
            ''',
        )
        self.write_executable(
            fake_bin / 'ip',
            '''
            #!/bin/sh
            case "$*" in
              *address*) printf '%s\n' "${FAKE_IP_ADDRESS:-2: ens160    inet 10.93.1.27/24 scope global ens160}" ;;
              *route*) printf '%s\n' "${FAKE_IP_ROUTES:-10.93.1.0/24 dev ens160 proto kernel scope link src 10.93.1.27}" ;;
              *) exit 2 ;;
            esac
            ''',
        )
        self.write_executable(
            fake_bin / 'stat',
            '''
            #!/bin/sh
            if [ "$1" = "-fc" ]; then
              printf '%s\n' "${FAKE_CGROUP_FS:-cgroup2fs}"
            else
              exec /usr/bin/stat "$@"
            fi
            ''',
        )
        self.write_executable(
            fake_bin / 'swapon',
            '''
            #!/bin/sh
            printf '/swap.img 4294963200\n'
            ''',
        )
        self.write_executable(
            fake_bin / 'systemctl',
            '''
            #!/bin/sh
            case "$1" in
              is-active) printf 'active\n' ;;
              list-unit-files) exit 0 ;;
              *) exit 2 ;;
            esac
            ''',
        )
        self.write_executable(fake_bin / 'ss', '#!/bin/sh\nexit 0\n')
        self.write_executable(fake_bin / 'dpkg-query', '#!/bin/sh\nexit 1\n')
        self.write_executable(
            fake_bin / 'shasum',
            f'''
            #!/bin/sh
            case "$*" in
              *06-host-workflow-cleanup*)
                eval "last=\\${{${{#}}}}"
                printf '%s  %s\n' "${{FAKE_CLEANUP_SHA:-{self.cleanup_digest}}}" "$last"
                ;;
              *) exec /usr/bin/shasum "$@" ;;
            esac
            ''',
        )

        environment = os.environ.copy()
        environment.update(
            {
                'PATH': f'{fake_bin}:/usr/bin:/bin',
                'BOOTSTRAP_TEST_MODE': '1',
                'BOOTSTRAP_TEST_ROOT': str(host),
            }
        )
        return environment, host

    def run_preflight(
        self, **overrides: str
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        environment, host = self.make_environment()
        environment.update(overrides)
        result = self.run_command(
            ['/bin/bash', str(PREFLIGHT), '--check'], env=environment
        )
        return result, host

    def evidence_text(self, host: Path) -> str:
        evidence = sorted((host / 'root/dev-infra-evidence').glob('07-preflight-*.txt'))
        self.assertEqual(len(evidence), 1)
        return evidence[0].read_text(encoding='utf-8')

    def test_stops_when_not_root(self) -> None:
        result, _ = self.run_preflight(FAKE_ID_UID='1000')

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_HOST_IDENTITY', result.stdout)

    def test_stops_on_wrong_hostname(self) -> None:
        result, _ = self.run_preflight(FAKE_HOSTNAME='wrong-host')

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_HOST_IDENTITY', result.stdout)

    def test_stops_on_cleanup_evidence_digest_drift(self) -> None:
        result, _ = self.run_preflight(FAKE_CLEANUP_SHA='0' * 64)

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_CLEANUP_EVIDENCE', result.stdout)

    def test_stops_on_local_cidr_overlap(self) -> None:
        result, _ = self.run_preflight(
            FAKE_IP_ROUTES='172.21.8.0/24 dev ens160 scope link'
        )

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_CIDR_OVERLAP', result.stdout)

    def test_passes_without_leaking_command_stderr_canary(self) -> None:
        canary = 'SECRET_CANARY_DO_NOT_LOG'
        result, host = self.run_preflight(FAKE_CANARY=canary)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_PREFLIGHT', result.stdout)
        self.assertIn('SERVER_LOCAL_SCOPE_ONLY', result.stdout)
        self.assertNotIn(canary, result.stdout + result.stderr)
        self.assertNotIn(canary, self.evidence_text(host))


class KernelStageTest(BootstrapTestCase):
    modules_content = 'overlay\nbr_netfilter\n'
    sysctl_content = (
        'net.bridge.bridge-nf-call-iptables = 1\n'
        'net.bridge.bridge-nf-call-ip6tables = 1\n'
        'net.ipv4.ip_forward = 1\n'
    )

    def write_executable(self, path: Path, source: str) -> None:
        path.write_text(textwrap.dedent(source).lstrip(), encoding='utf-8')
        path.chmod(0o755)

    def make_environment(self) -> tuple[dict[str, str], Path, Path]:
        directory = self.temporary_directory()
        host = directory / 'host'
        fake_bin = directory / 'bin'
        command_log = directory / 'commands.log'
        (host / 'etc/modules-load.d').mkdir(parents=True)
        (host / 'etc/sysctl.d').mkdir(parents=True)
        (host / 'proc/sys/net/bridge').mkdir(parents=True)
        (host / 'proc/sys/net/ipv4').mkdir(parents=True)
        (host / 'sys/module').mkdir(parents=True)
        (host / 'root/dev-infra-evidence').mkdir(parents=True)
        (host / 'swap.img').write_bytes(b'preserve swap\n')
        fake_bin.mkdir()

        self.write_executable(fake_bin / 'id', '#!/bin/sh\nprintf "0\\n"\n')
        self.write_executable(
            fake_bin / 'modprobe',
            '''
            #!/bin/sh
            printf 'modprobe %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            [ "${FAKE_MODPROBE_FAIL:-}" != "$1" ] || exit 1
            mkdir -p "$FAKE_HOST_ROOT/sys/module/$1"
            ''',
        )
        self.write_executable(
            fake_bin / 'sysctl',
            '''
            #!/bin/sh
            printf 'sysctl %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            [ "${FAKE_SYSCTL_FAIL:-0}" != 1 ] || exit 1
            [ "$1" = "--load" ] && [ "$2" = "$FAKE_HOST_ROOT/etc/sysctl.d/99-kubernetes-cri.conf" ] || exit 2
            printf '%s\n' "${FAKE_BRIDGE_IPV4_VALUE:-1}" >"$FAKE_HOST_ROOT/proc/sys/net/bridge/bridge-nf-call-iptables"
            printf '%s\n' "${FAKE_BRIDGE_IPV6_VALUE:-1}" >"$FAKE_HOST_ROOT/proc/sys/net/bridge/bridge-nf-call-ip6tables"
            printf '%s\n' "${FAKE_IP_FORWARD_VALUE:-1}" >"$FAKE_HOST_ROOT/proc/sys/net/ipv4/ip_forward"
            ''',
        )
        self.write_executable(
            fake_bin / 'mktemp',
            '''
            #!/bin/sh
            temporary=$(/usr/bin/mktemp "$@") || exit
            printf '%s\n' "$temporary"
            if [ -n "${FAKE_MKTEMP_RACE_PARENT:-}" ]; then
              chmod 0700 "$FAKE_MKTEMP_RACE_PARENT"
            fi
            ''',
        )
        self.write_executable(
            fake_bin / 'mv',
            '''
            #!/bin/sh
            printf 'mv %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            if [ "${FAKE_MV_RACE_TARGET:-}" = "${3:-}" ]; then
              printf 'concurrent\n' >"$FAKE_MV_RACE_TARGET"
            fi
            exec /bin/mv "$@"
            ''',
        )
        self.write_executable(
            fake_bin / 'install',
            '''
            #!/bin/sh
            printf 'install %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            exec /usr/bin/install "$@"
            ''',
        )
        self.write_executable(
            fake_bin / 'sync',
            '''
            #!/bin/sh
            printf 'sync %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            [ "${FAKE_SYNC_FAIL:-0}" != 1 ]
            ''',
        )

        environment = os.environ.copy()
        environment.update(
            {
                'PATH': f'{fake_bin}:/usr/bin:/bin',
                'BOOTSTRAP_TEST_MODE': '1',
                'BOOTSTRAP_TEST_ROOT': str(host),
                'FAKE_COMMAND_LOG': str(command_log),
                'FAKE_HOST_ROOT': str(host),
            }
        )
        return environment, host, command_log

    def run_stage(
        self, environment: dict[str, str], mode: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            ['/bin/bash', str(PREPARE_KERNEL), mode], env=environment
        )

    def modules_file(self, host: Path) -> Path:
        return host / 'etc/modules-load.d/99-kubernetes.conf'

    def canonical_modules_file(self, host: Path) -> Path:
        return host / 'etc/modules-load.d/99-kubernetes.conf'

    def sysctl_file(self, host: Path) -> Path:
        return host / 'etc/sysctl.d/99-kubernetes-cri.conf'

    def set_persistent_files(self, host: Path) -> None:
        self.modules_file(host).write_text(self.modules_content, encoding='utf-8')
        self.sysctl_file(host).write_text(self.sysctl_content, encoding='utf-8')
        self.modules_file(host).chmod(0o644)
        self.sysctl_file(host).chmod(0o644)

    def set_runtime(self, host: Path, value: str = '1') -> None:
        (host / 'sys/module/overlay').mkdir(exist_ok=True)
        (host / 'sys/module/br_netfilter').mkdir(exist_ok=True)
        for path in (
            host / 'proc/sys/net/bridge/bridge-nf-call-iptables',
            host / 'proc/sys/net/bridge/bridge-nf-call-ip6tables',
            host / 'proc/sys/net/ipv4/ip_forward',
        ):
            path.write_text(f'{value}\n', encoding='utf-8')

    def test_check_rejects_unknown_managed_file_without_overwriting_it(self) -> None:
        """捕获把未知内容、类型或权限漂移误判为可安全覆盖的缺陷。"""
        cases = ('content', 'mode', 'symlink', 'directory')
        for target_name in ('modules', 'sysctl'):
            for drift in cases:
                with self.subTest(target=target_name, drift=drift):
                    environment, host, command_log = self.make_environment()
                    target = (
                        self.modules_file(host)
                        if target_name == 'modules'
                        else self.sysctl_file(host)
                    )
                    expected = (
                        self.modules_content
                        if target_name == 'modules'
                        else self.sysctl_content
                    )
                    if drift == 'content':
                        target.write_text('unknown\n', encoding='utf-8')
                    elif drift == 'mode':
                        target.write_text(expected, encoding='utf-8')
                        target.chmod(0o600)
                    elif drift == 'symlink':
                        target.symlink_to('/tmp/escape')
                    else:
                        target.mkdir()

                    result = self.run_stage(environment, '--check')

                    self.assertEqual(result.returncode, 30, result.stderr)
                    self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
                    self.assertTrue(target.exists() or target.is_symlink())
                    self.assertFalse(command_log.exists())

    def test_check_rejects_partial_persistent_installation(self) -> None:
        """捕获只存在一个受管文件时继续安装、掩盖部分安装的缺陷。"""
        for existing in ('modules', 'sysctl'):
            with self.subTest(existing=existing):
                environment, host, command_log = self.make_environment()
                target = (
                    self.modules_file(host)
                    if existing == 'modules'
                    else self.sysctl_file(host)
                )
                content = (
                    self.modules_content
                    if existing == 'modules'
                    else self.sysctl_content
                )
                target.write_text(content, encoding='utf-8')
                target.chmod(0o644)

                result = self.run_stage(environment, '--apply')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
                self.assertFalse(command_log.exists())

    def test_check_uses_canonical_modules_path_and_rejects_legacy_alias(self) -> None:
        """捕获继续管理旧 containerd.conf 或忽略该未知旧别名的缺陷。"""
        environment, host, _ = self.make_environment()
        self.canonical_modules_file(host).write_text(
            self.modules_content, encoding='utf-8'
        )
        self.canonical_modules_file(host).chmod(0o644)
        self.sysctl_file(host).write_text(self.sysctl_content, encoding='utf-8')
        self.sysctl_file(host).chmod(0o644)
        self.set_runtime(host)

        canonical = self.run_stage(environment, '--check')

        self.assertEqual(canonical.returncode, 0, canonical.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', canonical.stdout)

        legacy = host / 'etc/modules-load.d/containerd.conf'
        legacy.write_text(self.modules_content, encoding='utf-8')
        legacy.chmod(0o644)
        legacy_result = self.run_stage(environment, '--check')

        self.assertEqual(legacy_result.returncode, 30, legacy_result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', legacy_result.stdout)

    def test_check_is_read_only_when_kernel_changes_are_needed(self) -> None:
        """捕获默认 CHECK 调用写命令、创建目标或改动 swap 的缺陷。"""
        environment, host, command_log = self.make_environment()

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_KERNEL_CHECK', result.stdout)
        self.assertFalse(self.modules_file(host).exists())
        self.assertFalse(self.sysctl_file(host).exists())
        self.assertFalse(command_log.exists())
        self.assertEqual((host / 'swap.img').read_bytes(), b'preserve swap\n')
        self.assertEqual(list((host / 'root/dev-infra-evidence').iterdir()), [])

    def test_check_reports_only_fully_compliant_state_as_already_compliant(self) -> None:
        """捕获仅检查持久文件、遗漏 runtime 模块或 sysctl 的缺陷。"""
        environment, host, command_log = self.make_environment()
        self.set_persistent_files(host)
        self.set_runtime(host)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', result.stdout)
        self.assertFalse(command_log.exists())

        (host / 'sys/module/overlay').rmdir()
        result = self.run_stage(environment, '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_KERNEL_CHECK', result.stdout)
        self.assertFalse(command_log.exists())

    def test_apply_atomically_writes_contract_and_verifies_runtime(self) -> None:
        """捕获内容错误、非原子发布、漏加载模块、漏应用 sysctl 或改 swap 的缺陷。"""
        environment, host, command_log = self.make_environment()

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_KERNEL_PREPARED', result.stdout)
        self.assertEqual(
            self.modules_file(host).read_text(encoding='utf-8'),
            self.modules_content,
        )
        self.assertEqual(
            self.sysctl_file(host).read_text(encoding='utf-8'),
            self.sysctl_content,
        )
        self.assertEqual(self.modules_file(host).stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.sysctl_file(host).stat().st_mode & 0o777, 0o644)
        self.assertEqual((host / 'swap.img').read_bytes(), b'preserve swap\n')
        command_text = command_log.read_text(encoding='utf-8')
        self.assertIn('modprobe overlay\n', command_text)
        self.assertIn('modprobe br_netfilter\n', command_text)
        self.assertIn(
            f'sysctl --load {self.sysctl_file(host)}\n', command_text
        )
        evidence = list(
            (host / 'root/dev-infra-evidence').glob('09-prepare-kernel-*.txt')
        )
        self.assertEqual(len(evidence), 1)
        evidence_keys = {
            line.split('=', 1)[0]
            for line in evidence[0].read_text(encoding='utf-8').splitlines()
        }
        self.assertEqual(
            evidence_keys,
            {
                'MODULE_BR_NETFILTER',
                'MODULE_OVERLAY',
                'SYSCTL_BRIDGE_IPV4',
                'SYSCTL_BRIDGE_IPV6',
                'SYSCTL_IP_FORWARD',
                'PHASE',
                'MODE',
                'RESULT',
                'REASON',
                'EVIDENCE',
                'EXIT_CODE',
                'NEXT',
            },
        )

    def test_apply_does_not_rewrite_exact_files_when_only_runtime_drifted(self) -> None:
        """捕获 runtime 修复时无谓覆盖精确持久文件的缺陷。"""
        environment, host, command_log = self.make_environment()
        self.set_persistent_files(host)
        before = (
            self.modules_file(host).stat().st_ino,
            self.sysctl_file(host).stat().st_ino,
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_KERNEL_PREPARED', result.stdout)
        after = (
            self.modules_file(host).stat().st_ino,
            self.sysctl_file(host).stat().st_ino,
        )
        self.assertEqual(after, before)
        command_text = command_log.read_text(encoding='utf-8')
        self.assertNotIn('mv ', command_text)
        self.assertNotIn('install ', command_text)

    def test_apply_fails_when_sync_or_runtime_verification_fails(self) -> None:
        """捕获忽略 sync 失败或未逐项验证 /proc/sys 值的缺陷。"""
        environment, host, _ = self.make_environment()
        environment['FAKE_SYNC_FAIL'] = '1'

        sync_result = self.run_stage(environment, '--apply')

        self.assertEqual(sync_result.returncode, 40, sync_result.stderr)
        self.assertIn('RESULT=STOP_APPLY_FAILED', sync_result.stdout)
        self.assertFalse(self.modules_file(host).exists())
        self.assertFalse(self.sysctl_file(host).exists())

        environment, host, _ = self.make_environment()
        environment['FAKE_IP_FORWARD_VALUE'] = '0'
        verify_result = self.run_stage(environment, '--apply')

        self.assertEqual(verify_result.returncode, 50, verify_result.stderr)
        self.assertIn('RESULT=STOP_VERIFY_FAILED', verify_result.stdout)

    def test_apply_never_overwrites_target_that_appears_during_publish(self) -> None:
        """捕获发布竞态覆盖并发创建目标的缺陷。"""
        environment, host, _ = self.make_environment()
        target = self.modules_file(host)
        environment['FAKE_MV_RACE_TARGET'] = str(target)

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
        self.assertEqual(target.read_text(encoding='utf-8'), 'concurrent\n')
        self.assertFalse(self.sysctl_file(host).exists())

    def test_check_rejects_kernel_parent_and_file_owner_drift(self) -> None:
        """捕获忽略 kernel 受管 parent/file uid:gid 漂移的缺陷。"""
        for target_name in ('modules-parent', 'sysctl-parent', 'modules', 'sysctl'):
            with self.subTest(target=target_name):
                environment, host, _ = self.make_environment()
                self.set_persistent_files(host)
                self.set_runtime(host)
                paths = {
                    'modules-parent': self.modules_file(host).parent,
                    'sysctl-parent': self.sysctl_file(host).parent,
                    'modules': self.modules_file(host),
                    'sysctl': self.sysctl_file(host),
                }
                environment['BOOTSTRAP_TEST_OWNER_DRIFT_PATH'] = str(
                    paths[target_name]
                )

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_apply_revalidates_kernel_parent_after_mktemp_race(self) -> None:
        """捕获 mktemp 后 parent 权限竞态仍发布 kernel 文件的缺陷。"""
        environment, host, _ = self.make_environment()
        parent = self.modules_file(host).parent
        environment['FAKE_MKTEMP_RACE_PARENT'] = str(parent)

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
        self.assertFalse(self.modules_file(host).exists())


class BootstrapEntrySecurityTest(BootstrapTestCase):
    def write_executable(self, path: Path, source: str) -> None:
        path.write_text(textwrap.dedent(source).lstrip(), encoding='utf-8')
        path.chmod(0o755)

    def production_environment(self) -> tuple[dict[str, str], Path]:
        directory = self.temporary_directory()
        fake_bin = directory / 'fake-bin'
        fake_bin.mkdir()
        command_log = directory / 'commands.log'
        for name, output in (
            ('id', '0'),
            ('systemctl', 'active'),
            ('python3', 'FAKE_PYTHON_CONTROLLED'),
        ):
            self.write_executable(
                fake_bin / name,
                f'''#!/bin/sh
                printf '{name} controlled\\n' >>"$FAKE_COMMAND_LOG"
                printf '%s\\n' '{output}'
                ''',
            )
        environment = os.environ.copy()
        environment.update(
            {
                'PATH': f'{fake_bin}:/usr/bin:/bin',
                'FAKE_COMMAND_LOG': str(command_log),
            }
        )
        for name in tuple(environment):
            if name.startswith('BOOTSTRAP_TEST_'):
                del environment[name]
        return environment, command_log

    def test_production_fixes_safe_path_before_command_lookup(self) -> None:
        """捕获 production 从调用者 PATH 执行伪造 id/systemctl/python3 的缺陷。"""
        self.assertNotEqual(os.geteuid(), 0, '该用例必须由实际非 root 用户运行')
        for script in (PREPARE_KERNEL, INSTALL_CONTAINERD):
            with self.subTest(script=script.name):
                environment, command_log = self.production_environment()

                result = self.run_command(
                    ['/bin/bash', str(script), '--check'], env=environment
                )

                self.assertEqual(result.returncode, 10, result.stderr)
                self.assertIn('REASON=not-root', result.stdout)
                self.assertFalse(command_log.exists())

    def test_production_rejects_all_test_overrides_before_lookup(self) -> None:
        """捕获 production 接受 TEST_ROOT/LOCK/owner seam 或先执行不可信命令的缺陷。"""
        for script in (PREPARE_KERNEL, INSTALL_CONTAINERD):
            with self.subTest(script=script.name):
                environment, command_log = self.production_environment()
                environment.update(
                    {
                        'BOOTSTRAP_TEST_ROOT': '/',
                        'BOOTSTRAP_TEST_LOCK_FILE': '/tmp/unapproved.lock',
                        'BOOTSTRAP_TEST_OWNER_DRIFT_PATH': '/etc',
                    }
                )

                result = self.run_command(
                    ['/bin/bash', str(script), '--check'], env=environment
                )

                self.assertEqual(result.returncode, 10, result.stderr)
                self.assertIn('REASON=test-override-in-production', result.stderr)
                self.assertFalse(command_log.exists())

    def test_test_mode_requires_non_root_mapped_root(self) -> None:
        """捕获 test mode 映射到真实 `/` 或省略隔离 test root 的缺陷。"""
        for script in (PREPARE_KERNEL, INSTALL_CONTAINERD):
            with self.subTest(script=script.name):
                environment, command_log = self.production_environment()
                environment.update(
                    {
                        'BOOTSTRAP_TEST_MODE': '1',
                        'BOOTSTRAP_TEST_ROOT': '/',
                    }
                )

                result = self.run_command(
                    ['/bin/bash', str(script), '--check'], env=environment
                )

                self.assertEqual(result.returncode, 10, result.stderr)
                self.assertIn('REASON=test-root-must-be-isolated', result.stderr)
                self.assertFalse(command_log.exists())


class ArtifactStageTest(BootstrapTestCase):
    def write_executable(self, path: Path, source: str) -> None:
        path.write_text(textwrap.dedent(source).lstrip(), encoding='utf-8')
        path.chmod(0o755)

    def make_environment(
        self,
        artifact: bytes,
        *,
        name: str = 'runc',
        version: str = '1.3.6',
        url: str = 'https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64',
        digest: str | None = None,
        target: str = '/usr/local/sbin/runc',
        records: list[tuple[str, str, str, bytes, str]] | None = None,
    ) -> tuple[dict[str, str], Path, Path, Path]:
        directory = self.temporary_directory()
        host = directory / 'host'
        fake_bin = directory / 'bin'
        evidence = host / 'root/dev-infra-evidence'
        evidence.mkdir(parents=True)
        fake_bin.mkdir()
        lock = directory / 'artifacts.lock.tsv'
        if records is None:
            records = self.approved_records()
            records = [
                (
                    name,
                    version,
                    url,
                    artifact,
                    target,
                )
                if record_name == name
                else record
                for record in records
                for record_name, *_ in [record]
            ]
        fixtures = directory / 'download-fixtures'
        fixtures.mkdir()
        for _, _, record_url, record_artifact, _ in records:
            (fixtures / Path(record_url).name).write_bytes(record_artifact)
        lock.write_text(
            ''.join(
                '\t'.join(
                    [
                        record_name,
                        record_version,
                        record_url,
                        (
                            digest
                            if record_name == name and digest
                            else hashlib.sha256(record_artifact).hexdigest()
                        ),
                        record_target,
                    ]
                )
                + '\n'
                for record_name, record_version, record_url, record_artifact, record_target in records
            ),
            encoding='utf-8',
        )
        curl_log = directory / 'curl.log'

        self.write_executable(fake_bin / 'id', '#!/bin/sh\nprintf "0\\n"\n')
        self.write_executable(
            fake_bin / 'curl',
            '''
            #!/bin/sh
            printf '%s\n' "$*" >>"$FAKE_CURL_LOG"
            output=
            url=
            fail=false
            location=false
            protocol=false
            tls=false
            while [ "$#" -gt 0 ]; do
              case "$1" in
                --fail)
                  fail=true
                  shift
                  ;;
                --location)
                  location=true
                  shift
                  ;;
                --proto)
                  [ "$2" = '=https' ] || exit 64
                  protocol=true
                  shift 2
                  ;;
                --tlsv1.2)
                  tls=true
                  shift
                  ;;
                --output)
                  output=$2
                  shift 2
                  ;;
                https://*)
                  url=$1
                  shift
                  ;;
                *)
                  shift
                  ;;
              esac
            done
            [ "$fail" = true ] && [ "$location" = true ] && \
              [ "$protocol" = true ] && [ "$tls" = true ] && [ -n "$output" ] && [ -n "$url" ] || exit 64
            /bin/cp "$FAKE_DOWNLOAD_FIXTURES/${url##*/}" "$output"
            ''',
        )

        environment = os.environ.copy()
        environment.update(
            {
                'PATH': f'{fake_bin}:/usr/bin:/bin',
                'BOOTSTRAP_TEST_MODE': '1',
                'BOOTSTRAP_TEST_ROOT': str(host),
                'BOOTSTRAP_TEST_LOCK_FILE': str(lock),
                'FAKE_CURL_LOG': str(curl_log),
                'FAKE_DOWNLOAD_FIXTURES': str(fixtures),
            }
        )
        return environment, host, lock, curl_log

    def approved_records(self) -> list[tuple[str, str, str, bytes, str]]:
        return [
            (
                'containerd',
                '2.3.1',
                'https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz',
                self.archive_bytes(
                    [
                        ('bin/containerd', b'containerd\n'),
                        ('bin/ctr', b'ctr\n'),
                        ('bin/containerd-shim-runc-v2', b'shim\n'),
                    ]
                ),
                '/usr/local/bin',
            ),
            (
                'runc',
                '1.3.6',
                'https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64',
                b'runc\n',
                '/usr/local/sbin/runc',
            ),
            (
                'cni-plugins',
                '1.9.1',
                'https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz',
                self.archive_bytes(
                    [
                        ('bridge', b'bridge\n'),
                        ('host-local', b'host-local\n'),
                        ('loopback', b'loopback\n'),
                        ('portmap', b'portmap\n'),
                    ]
                ),
                '/opt/cni/bin',
            ),
            (
                'crictl',
                '1.36.0',
                'https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz',
                self.archive_bytes([('crictl', b'crictl\n')]),
                '/usr/local/bin/crictl',
            ),
            (
                'helm',
                '3.21.0',
                'https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
                self.archive_bytes([('linux-amd64/helm', b'helm\n')]),
                '/usr/local/bin/helm',
            ),
            (
                'gateway-api',
                '1.6.1',
                'https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml',
                b'gateway\n',
                'kubernetes://gateway-api/standard',
            ),
            (
                'cilium-chart',
                '1.20.0',
                'https://helm.cilium.io/cilium-1.20.0.tgz',
                b'cilium\n',
                'kubernetes://kube-system/cilium',
            ),
        ]

    def run_stage(
        self, environment: dict[str, str], mode: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            ['/bin/bash', str(STAGE_ARTIFACTS), mode], env=environment
        )

    def staged_path(self, host: Path, basename: str) -> Path:
        return (
            host
            / 'root/dev-infra-artifacts/pcs-2026-08-10.1'
            / basename
        )

    def stage_records(
        self, host: Path, records: list[tuple[str, str, str, bytes, str]]
    ) -> Path:
        staging = host / 'root/dev-infra-artifacts/pcs-2026-08-10.1'
        staging.mkdir(parents=True, mode=0o700)
        staging.parent.chmod(0o700)
        staging.chmod(0o700)
        for _, _, url, artifact, _ in records:
            staged = staging / Path(url).name
            staged.write_bytes(artifact)
            staged.chmod(0o600)
        return staging

    def compliant_environment(
        self,
    ) -> tuple[dict[str, str], Path, list[tuple[str, str, str, bytes, str]], Path]:
        records = self.approved_records()
        environment, host, _, _ = self.make_environment(b'ignored\n', records=records)
        staging = self.stage_records(host, records)
        return environment, host, records, staging

    def archive_bytes(self, members: list[tuple[str, bytes | str]]) -> bytes:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, content in members:
                member = tarfile.TarInfo(name)
                if isinstance(content, str):
                    member.type = tarfile.SYMTYPE
                    member.linkname = content
                    member.size = 0
                    archive.addfile(member)
                else:
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
        return stream.getvalue()

    def test_check_does_not_create_staging_directory(self) -> None:
        environment, _, _, curl_log = self.make_environment(b'runc fixture\n')
        host = Path(environment['BOOTSTRAP_TEST_ROOT'])

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_ARTIFACTS_CHECK', result.stdout)
        self.assertFalse((host / 'root/dev-infra-artifacts').exists())
        self.assertFalse(curl_log.exists())

    def test_apply_stages_verified_artifact(self) -> None:
        artifact = b'runc fixture\n'
        environment, host, _, _ = self.make_environment(artifact)

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_ARTIFACTS_STAGED', result.stdout)
        staged = self.staged_path(host, 'runc.amd64')
        self.assertEqual(staged.read_bytes(), artifact)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)

    def test_apply_rejects_download_digest_mismatch(self) -> None:
        environment, host, _, _ = self.make_environment(
            b'runc fixture\n', digest='0' * 64
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertFalse(self.staged_path(host, 'runc.amd64').exists())

    def test_check_refuses_existing_same_name_with_different_digest(self) -> None:
        environment, host, _, staging = self.compliant_environment()
        staged = self.staged_path(host, 'runc.amd64')
        self.assertEqual(staged.parent, staging)
        staged.write_bytes(b'unknown\n')

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertEqual(staged.read_bytes(), b'unknown\n')

    def test_check_rejects_non_official_url_before_curl(self) -> None:
        environment, _, _, curl_log = self.make_environment(
            b'payload\n', url='https://example.com/v1.3.6/runc.amd64'
        )

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertFalse(curl_log.exists())

    def test_check_rejects_http_url_before_curl(self) -> None:
        environment, _, _, curl_log = self.make_environment(
            b'payload\n', url='http://github.com/opencontainers/runc/runc.amd64'
        )

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertFalse(curl_log.exists())

    def test_apply_rejects_archive_path_traversal(self) -> None:
        artifact = self.archive_bytes([('../escape', b'escape\n')])
        environment, host, _, _ = self.make_environment(
            artifact,
            name='containerd',
            version='2.3.1',
            url='https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz',
            target='/usr/local/bin',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
        self.assertFalse(
            self.staged_path(host, 'containerd-2.3.1-linux-amd64.tar.gz').exists()
        )

    def test_apply_rejects_cni_archive_absolute_member(self) -> None:
        artifact = self.archive_bytes([('/escape', b'escape\n')])
        environment, host, _, _ = self.make_environment(
            artifact,
            name='cni-plugins',
            version='1.9.1',
            url='https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz',
            target='/opt/cni/bin',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
        self.assertFalse(self.staged_path(host, 'cni-plugins-linux-amd64-v1.9.1.tgz').exists())

    def test_apply_rejects_helm_archive_path_traversal(self) -> None:
        artifact = self.archive_bytes([('linux-amd64/../../escape', b'escape\n')])
        environment, host, _, _ = self.make_environment(
            artifact,
            name='helm',
            version='3.21.0',
            url='https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
            target='/usr/local/bin/helm',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
        self.assertFalse(self.staged_path(host, 'helm-v3.21.0-linux-amd64.tar.gz').exists())

    def test_apply_rejects_archive_symlink_escaping_member_root(self) -> None:
        artifact = self.archive_bytes(
            [('bin/containerd', b'binary\n'), ('bin/escape', '../../outside')]
        )
        environment, host, _, _ = self.make_environment(
            artifact,
            name='containerd',
            version='2.3.1',
            url='https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz',
            target='/usr/local/bin',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
        self.assertFalse(
            self.staged_path(host, 'containerd-2.3.1-linux-amd64.tar.gz').exists()
        )

    def test_apply_rejects_archive_missing_required_member(self) -> None:
        artifact = self.archive_bytes([('linux-amd64/README.md', b'missing helm\n')])
        environment, host, _, _ = self.make_environment(
            artifact,
            name='helm',
            version='3.21.0',
            url='https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
            target='/usr/local/bin/helm',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
        self.assertFalse(self.staged_path(host, 'helm-v3.21.0-linux-amd64.tar.gz').exists())

    def test_check_rejects_six_record_lock_without_crictl(self) -> None:
        """捕获 staging 继续接受缺少 crictl 的旧六项 schema 的缺陷。"""
        records = [
            record
            for record in self.approved_records()
            if record[0] != 'crictl'
        ]
        environment, host, _, _ = self.make_environment(
            b'ignored\n', records=records
        )
        self.stage_records(host, records)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertIn('REASON=lock-record-count-invalid', result.stdout)

    def test_apply_stages_locked_crictl_archive(self) -> None:
        """捕获 staging 拒绝批准 crictl 或未验证其 regular 成员的缺陷。"""
        artifact = self.archive_bytes([('crictl', b'crictl\n')])
        environment, host, _, _ = self.make_environment(
            artifact,
            name='crictl',
            version='1.36.0',
            url='https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz',
            target='/usr/local/bin/crictl',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_ARTIFACTS_STAGED', result.stdout)
        self.assertEqual(
            self.staged_path(
                host, 'crictl-v1.36.0-linux-amd64.tar.gz'
            ).read_bytes(),
            artifact,
        )

    def test_apply_rejects_crictl_archive_missing_regular_member(self) -> None:
        """捕获接受缺成员或同名 symlink 冒充 crictl binary 的缺陷。"""
        fixtures = (
            self.archive_bytes([('README.md', b'missing\n')]),
            self.archive_bytes([('crictl', 'bin/crictl')]),
        )
        for artifact in fixtures:
            with self.subTest(artifact=hashlib.sha256(artifact).hexdigest()):
                environment, host, _, _ = self.make_environment(
                    artifact,
                    name='crictl',
                    version='1.36.0',
                    url='https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz',
                    target='/usr/local/bin/crictl',
                )

                result = self.run_stage(environment, '--apply')

                self.assertEqual(result.returncode, 20)
                self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
                self.assertFalse(
                    self.staged_path(
                        host, 'crictl-v1.36.0-linux-amd64.tar.gz'
                    ).exists()
                )

    def test_apply_rejects_cni_archive_missing_portmap(self) -> None:
        """捕获 staging 未校验 Task 5 必装 portmap 成员的缺陷。"""
        artifact = self.archive_bytes(
            [
                ('bridge', b'bridge\n'),
                ('host-local', b'host-local\n'),
                ('loopback', b'loopback\n'),
            ]
        )
        environment, host, _, _ = self.make_environment(
            artifact,
            name='cni-plugins',
            version='1.9.1',
            url='https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz',
            target='/opt/cni/bin',
        )

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
        self.assertFalse(
            self.staged_path(
                host, 'cni-plugins-linux-amd64-v1.9.1.tgz'
            ).exists()
        )

    def test_apply_stages_archives_with_required_members(self) -> None:
        fixtures = [
            (
                'containerd',
                '2.3.1',
                'https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz',
                '/usr/local/bin',
                [('bin/containerd', b'containerd\n'), ('bin/ctr', b'ctr\n'), ('bin/containerd-shim-runc-v2', b'shim\n')],
            ),
            (
                'cni-plugins',
                '1.9.1',
                'https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz',
                '/opt/cni/bin',
                [('bridge', b'bridge\n'), ('host-local', b'host-local\n'), ('loopback', b'loopback\n'), ('portmap', b'portmap\n')],
            ),
            (
                'helm',
                '3.21.0',
                'https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
                '/usr/local/bin/helm',
                [('linux-amd64/helm', b'helm\n')],
            ),
            (
                'crictl',
                '1.36.0',
                'https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz',
                '/usr/local/bin/crictl',
                [('crictl', b'crictl\n')],
            ),
        ]
        for name, version, url, target, members in fixtures:
            with self.subTest(name=name):
                artifact = self.archive_bytes(members)
                environment, host, _, _ = self.make_environment(
                    artifact,
                    name=name,
                    version=version,
                    url=url,
                    target=target,
                )

                result = self.run_stage(environment, '--apply')

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('RESULT=PASS_ARTIFACTS_STAGED', result.stdout)
                self.assertEqual(self.staged_path(host, Path(url).name).read_bytes(), artifact)

    def test_check_reports_exact_existing_artifact_as_compliant(self) -> None:
        environment, _, _, _ = self.compliant_environment()

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', result.stdout)

    def test_check_rejects_unknown_staging_entries(self) -> None:
        for entry_type in ('file', 'directory', 'symlink'):
            with self.subTest(entry_type=entry_type):
                environment, _, _, staging = self.compliant_environment()
                unknown = staging / 'unapproved'
                if entry_type == 'file':
                    unknown.write_bytes(b'unknown\n')
                elif entry_type == 'directory':
                    unknown.mkdir()
                else:
                    unknown.symlink_to('runc.amd64')

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
                self.assertTrue(unknown.exists() or unknown.is_symlink())

    def test_check_rejects_existing_artifact_directory_mode_drift(self) -> None:
        environment, _, _, staging = self.compliant_environment()
        staging.chmod(0o755)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 30)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
        self.assertEqual(staging.stat().st_mode & 0o777, 0o755)

    def test_apply_rejects_existing_artifact_root_mode_drift(self) -> None:
        environment, host, _, _ = self.compliant_environment()
        artifact_root = host / 'root/dev-infra-artifacts'
        artifact_root.chmod(0o755)

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 30)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
        self.assertEqual(artifact_root.stat().st_mode & 0o777, 0o755)

    def test_check_rejects_truncated_lock_even_when_its_artifacts_match(self) -> None:
        records = self.approved_records()[:-1]
        environment, host, _, _ = self.make_environment(b'ignored\n', records=records)
        self.stage_records(host, records)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)

    def test_check_rejects_duplicate_lock_basename(self) -> None:
        records = self.approved_records()
        records[-1] = (
            'cilium-chart',
            '1.20.0',
            'https://helm.cilium.io/helm-v3.21.0-linux-amd64.tar.gz',
            records[3][3],
            'kubernetes://kube-system/cilium',
        )
        environment, host, _, _ = self.make_environment(b'ignored\n', records=records)
        self.stage_records(host, records)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertIn('REASON=lock-basename-duplicate', result.stdout)

    def test_check_rejects_unapproved_lock_name(self) -> None:
        records = self.approved_records()
        name, version, url, artifact, target = records[-1]
        records[-1] = ('unexpected-chart', version, url, artifact, target)
        environment, host, _, _ = self.make_environment(b'ignored\n', records=records)
        self.stage_records(host, records)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 20)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)


class ContainerdInstallTest(BootstrapTestCase):
    endpoint = 'unix:///run/containerd/containerd.sock'
    containerd_version = b'''#!/bin/sh
[ "$1" = "--version" ] || exit 64
printf '%s\n' "${FAKE_CONTAINERD_VERSION:-containerd github.com/containerd/containerd/v2 v2.3.1 test}"
'''
    ctr_binary = b'''#!/bin/sh
printf 'ctr %s\n' "$*" >>"$FAKE_COMMAND_LOG"
[ "$*" = "plugins ls" ] || exit 64
printf '%s\n' "${FAKE_CTR_OUTPUT:-TYPE ID PLATFORMS STATUS
io.containerd.snapshotter.v1 overlayfs linux/amd64 ok
io.containerd.cri.v1 images - ok
io.containerd.cri.v1 runtime linux/amd64 ok}"
'''
    shim_binary = b'#!/bin/sh\nexit 0\n'
    runc_binary = b'''#!/bin/sh
[ "$1" = "--version" ] || exit 64
printf '%s\n' "${FAKE_RUNC_VERSION:-runc version 1.3.6}"
'''
    crictl_binary = b'''#!/bin/sh
printf 'crictl %s\n' "$*" >>"$FAKE_COMMAND_LOG"
printf '%s\n' "${FAKE_CANARY:-}" >&2
case "$*" in
  --version) printf '%s\n' "${FAKE_CRICTL_VERSION:-crictl version v1.36.0}" ;;
  "--runtime-endpoint unix:///run/containerd/containerd.sock --image-endpoint unix:///run/containerd/containerd.sock info --output json")
    printf '%s\n' "$FAKE_CRICTL_INFO"
    ;;
  *) exit 64 ;;
esac
'''
    cni_binaries = {
        'bridge': b'#!/bin/sh\nexit 0\n',
        'host-local': b'#!/bin/sh\nexit 0\n',
        'loopback': b'#!/bin/sh\nexit 0\n',
        'portmap': b'#!/bin/sh\nexit 0\n',
    }

    def write_executable(self, path: Path, source: str | bytes) -> None:
        if isinstance(source, bytes):
            path.write_bytes(source)
        else:
            path.write_text(textwrap.dedent(source).lstrip(), encoding='utf-8')
        path.chmod(0o755)

    def create_cri_socket(self, host: Path) -> Path:
        socket_path = host / 'run/containerd/containerd.sock'
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o711)
        socket_path.parent.chmod(0o711)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(socket_path))
        listener.close()
        socket_path.chmod(0o660)
        return socket_path

    def archive_bytes(self, members: list[tuple[str, bytes | str]]) -> bytes:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for name, content in members:
                member = tarfile.TarInfo(name)
                if isinstance(content, str):
                    member.type = tarfile.SYMTYPE
                    member.linkname = content
                    member.size = 0
                else:
                    member.mode = 0o755
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
                    continue
                archive.addfile(member)
        return stream.getvalue()

    def artifact_records(
        self, overrides: dict[str, bytes] | None = None
    ) -> list[tuple[str, str, str, bytes, str]]:
        artifacts = {
            'containerd': self.archive_bytes(
                [
                    ('bin/containerd', self.containerd_version),
                    ('bin/ctr', self.ctr_binary),
                    ('bin/containerd-shim-runc-v2', self.shim_binary),
                ]
            ),
            'runc': self.runc_binary,
            'cni-plugins': self.archive_bytes(list(self.cni_binaries.items())),
            'crictl': self.archive_bytes([('crictl', self.crictl_binary)]),
            'helm': self.archive_bytes([('linux-amd64/helm', b'helm\n')]),
            'gateway-api': b'gateway\n',
            'cilium-chart': b'cilium\n',
        }
        artifacts.update(overrides or {})
        return [
            (
                'containerd',
                '2.3.1',
                'https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz',
                artifacts['containerd'],
                '/usr/local/bin',
            ),
            (
                'runc',
                '1.3.6',
                'https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64',
                artifacts['runc'],
                '/usr/local/sbin/runc',
            ),
            (
                'cni-plugins',
                '1.9.1',
                'https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz',
                artifacts['cni-plugins'],
                '/opt/cni/bin',
            ),
            (
                'crictl',
                '1.36.0',
                'https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.36.0/crictl-v1.36.0-linux-amd64.tar.gz',
                artifacts['crictl'],
                '/usr/local/bin/crictl',
            ),
            (
                'helm',
                '3.21.0',
                'https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
                artifacts['helm'],
                '/usr/local/bin/helm',
            ),
            (
                'gateway-api',
                '1.6.1',
                'https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml',
                artifacts['gateway-api'],
                'kubernetes://gateway-api/standard',
            ),
            (
                'cilium-chart',
                '1.20.0',
                'https://helm.cilium.io/cilium-1.20.0.tgz',
                artifacts['cilium-chart'],
                'kubernetes://kube-system/cilium',
            ),
        ]

    def valid_info(self, *, runtime_ready: object = True) -> str:
        import json

        return json.dumps(
            {
                'status': {
                    'conditions': [
                        {'type': 'RuntimeReady', 'status': runtime_ready},
                        {
                            'type': 'NetworkReady',
                            'status': False,
                            'reason': 'SECRET_CANARY_REASON',
                            'message': 'SECRET_CANARY_MESSAGE',
                        },
                    ]
                },
                'config': {
                    'containerd': {
                        'defaultRuntimeName': 'runc',
                        'runtimes': {
                            'runc': {
                                'runtimeType': 'io.containerd.runc.v2',
                                'options': {'SystemdCgroup': True},
                            }
                        },
                    }
                },
                'unapprovedExtra': 'SECRET_CANARY_EXTRA',
            }
        )

    def make_environment(
        self, overrides: dict[str, bytes] | None = None
    ) -> tuple[dict[str, str], Path, Path, dict[str, bytes]]:
        directory = self.temporary_directory()
        host = directory / 'host'
        fake_bin = directory / 'bin'
        command_log = directory / 'commands.log'
        lock = directory / 'artifacts.lock.tsv'
        approved_lock = directory / 'approved-artifacts.lock.tsv'
        staging = host / 'root/dev-infra-artifacts/pcs-2026-08-10.1'
        for path in (
            host / 'root/dev-infra-evidence',
            host / 'usr/local/bin',
            host / 'usr/local/sbin',
            host / 'usr/local/lib/systemd/system',
            host / 'opt/cni/bin',
            host / 'etc/containerd',
            host / 'var/lib',
            host / 'run',
            fake_bin,
            staging,
        ):
            path.mkdir(parents=True, exist_ok=True)
        (host / 'root/dev-infra-artifacts').chmod(0o700)
        staging.chmod(0o700)
        (host / 'swap.img').write_bytes(b'preserve swap\n')

        records = self.artifact_records(overrides)
        artifact_map: dict[str, bytes] = {}
        lock_lines = []
        for name, version, url, artifact, target in records:
            artifact_map[name] = artifact
            staged = staging / Path(url).name
            staged.write_bytes(artifact)
            staged.chmod(0o600)
            lock_lines.append(
                '\t'.join(
                    (
                        name,
                        version,
                        url,
                        hashlib.sha256(artifact).hexdigest(),
                        target,
                    )
                )
            )
        lock.write_text('\n'.join(lock_lines) + '\n', encoding='utf-8')
        approved_lock.write_text('\n'.join(lock_lines) + '\n', encoding='utf-8')

        self.write_executable(fake_bin / 'id', '#!/bin/sh\nprintf "0\\n"\n')
        self.write_executable(
            fake_bin / 'install',
            '''
            #!/bin/sh
            printf 'install %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            exec /usr/bin/install "$@"
            ''',
        )
        self.write_executable(
            fake_bin / 'mktemp',
            '''
            #!/bin/sh
            temporary=$(/usr/bin/mktemp "$@") || exit
            printf '%s\n' "$temporary"
            case "$temporary" in
              *"${FAKE_MKTEMP_RACE_MATCH:-}"*) matched=1 ;;
              *) matched=0 ;;
            esac
            if [ -n "${FAKE_MKTEMP_RACE_PARENT:-}" ] && [ "$matched" = 1 ]; then
              case "${FAKE_MKTEMP_RACE_ACTION:-mode}" in
                mode) chmod 0700 "$FAKE_MKTEMP_RACE_PARENT" ;;
                owner) : >"$FAKE_MKTEMP_RACE_OWNER_MARKER" ;;
                type)
                  /bin/mv "$FAKE_MKTEMP_RACE_PARENT" "$FAKE_MKTEMP_RACE_PARENT.raced"
                  ln -s /tmp "$FAKE_MKTEMP_RACE_PARENT"
                  ;;
              esac
            fi
            ''',
        )
        self.write_executable(
            fake_bin / 'mv',
            '''
            #!/bin/sh
            printf 'mv %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            if [ -n "${FAKE_MV_RACE_TARGET:-}" ]; then
              eval "last=\${${#}}"
              if [ "$last" = "$FAKE_MV_RACE_TARGET" ]; then
                printf 'concurrent\n' >"$last"
              fi
            fi
            exec /bin/mv "$@"
            ''',
        )
        self.write_executable(
            fake_bin / 'sync',
            '''
            #!/bin/sh
            printf 'sync %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            [ "${FAKE_SYNC_FAIL:-0}" != 1 ]
            ''',
        )
        self.write_executable(
            fake_bin / 'tar',
            '''
            #!/bin/sh
            [ "$1" != "-xzf" ] || printf 'tar-write %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            exec /usr/bin/tar "$@"
            ''',
        )
        self.write_executable(
            fake_bin / 'make-cri-socket',
            '''
            #!/usr/bin/python3
            import os
            import socket
            import sys

            path = sys.argv[1]
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(path)
            listener.close()
            os.chmod(path, 0o660)
            ''',
        )
        self.write_executable(
            fake_bin / 'systemctl',
            '''
            #!/bin/sh
            printf 'systemctl %s\n' "$*" >>"$FAKE_COMMAND_LOG"
            case "$1" in
              is-enabled) [ -f "$FAKE_SERVICE_ENABLED" ] ;;
              is-active) [ -f "$FAKE_SERVICE_ACTIVE" ] && printf 'active\n' ;;
              show)
                [ "${FAKE_SYSTEMCTL_SHOW_FAIL:-0}" != 1 ] || exit 1
                [ "${FAKE_SYSTEMCTL_SHOW_EMPTY:-0}" != 1 ] || exit 0
                if [ -f "$FAKE_SERVICE_UNIT_LOADED" ]; then
                  load_state=${FAKE_LOAD_STATE:-loaded}
                  fragment_path=$FAKE_FRAGMENT_PATH
                else
                  load_state=${FAKE_LOAD_STATE:-not-found}
                  fragment_path=${FAKE_NONLOADED_FRAGMENT_PATH:-}
                fi
                [ "${FAKE_LOAD_STATE_EMPTY:-0}" != 1 ] || load_state=
                printf 'LoadState=%s\nFragmentPath=%s\nDropInPaths=%s\n' \
                  "$load_state" "$fragment_path" "${FAKE_DROP_IN_PATHS:-}"
                ;;
              daemon-reload)
                [ ! -f "$FAKE_UNIT_TARGET" ] || : >"$FAKE_SERVICE_UNIT_LOADED"
                ;;
              enable) : >"$FAKE_SERVICE_ENABLED" ;;
              start)
                : >"$FAKE_SERVICE_ACTIVE"
                mkdir -p -m 0711 "$FAKE_HOST_ROOT/run/containerd"
                mkdir -p -m 0700 "$FAKE_HOST_ROOT/var/lib/containerd"
                "$FAKE_SOCKET_HELPER" "$FAKE_HOST_ROOT/run/containerd/containerd.sock"
                ;;
              *) exit 64 ;;
            esac
            ''',
        )
        environment = os.environ.copy()
        environment.update(
            {
                'PATH': f'{fake_bin}:/usr/bin:/bin',
                'BOOTSTRAP_TEST_MODE': '1',
                'BOOTSTRAP_TEST_ROOT': str(host),
                'BOOTSTRAP_TEST_LOCK_FILE': str(lock),
                'BOOTSTRAP_TEST_APPROVED_LOCK_FILE': str(approved_lock),
                'FAKE_COMMAND_LOG': str(command_log),
                'FAKE_HOST_ROOT': str(host),
                'FAKE_SERVICE_ENABLED': str(directory / 'service-enabled'),
                'FAKE_SERVICE_ACTIVE': str(directory / 'service-active'),
                'FAKE_SERVICE_UNIT_LOADED': str(directory / 'service-unit-loaded'),
                'FAKE_UNIT_TARGET': str(
                    host / 'usr/local/lib/systemd/system/containerd.service'
                ),
                'FAKE_FRAGMENT_PATH': str(
                    host / 'usr/local/lib/systemd/system/containerd.service'
                ),
                'FAKE_SOCKET_HELPER': str(fake_bin / 'make-cri-socket'),
                'FAKE_CRICTL_INFO': self.valid_info(),
            }
        )
        return environment, host, command_log, artifact_map

    def run_stage(
        self, environment: dict[str, str], mode: str
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            ['/bin/bash', str(INSTALL_CONTAINERD), mode], env=environment
        )

    def managed_targets(self, host: Path) -> dict[str, Path]:
        return {
            'containerd': host / 'usr/local/bin/containerd',
            'ctr': host / 'usr/local/bin/ctr',
            'shim': host / 'usr/local/bin/containerd-shim-runc-v2',
            'runc': host / 'usr/local/sbin/runc',
            'bridge': host / 'opt/cni/bin/bridge',
            'host-local': host / 'opt/cni/bin/host-local',
            'loopback': host / 'opt/cni/bin/loopback',
            'portmap': host / 'opt/cni/bin/portmap',
            'crictl': host / 'usr/local/bin/crictl',
            'config': host / 'etc/containerd/config.toml',
            'unit': host / 'usr/local/lib/systemd/system/containerd.service',
        }

    def install_compliant_targets(
        self, environment: dict[str, str], host: Path
    ) -> None:
        targets = self.managed_targets(host)
        binaries = {
            'containerd': self.containerd_version,
            'ctr': self.ctr_binary,
            'shim': self.shim_binary,
            'runc': self.runc_binary,
            **self.cni_binaries,
            'crictl': self.crictl_binary,
        }
        for name, content in binaries.items():
            targets[name].write_bytes(content)
            targets[name].chmod(0o755)
        targets['config'].write_bytes(
            (ROOT / 'bootstrap/containerd/config.toml').read_bytes()
        )
        targets['unit'].write_bytes(
            (ROOT / 'bootstrap/containerd/containerd.service').read_bytes()
        )
        targets['config'].chmod(0o644)
        targets['unit'].chmod(0o644)
        (host / 'var/lib/containerd').mkdir(mode=0o700)
        self.create_cri_socket(host)
        Path(environment['FAKE_SERVICE_ENABLED']).touch()
        Path(environment['FAKE_SERVICE_ACTIVE']).touch()
        Path(environment['FAKE_SERVICE_UNIT_LOADED']).touch()

    def test_check_is_read_only_for_clean_missing_state(self) -> None:
        """捕获 CHECK 解包、安装、启动服务、创建 evidence 或改 swap 的缺陷。"""
        environment, host, command_log, _ = self.make_environment()

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_CONTAINERD_CHECK', result.stdout)
        commands = command_log.read_text(encoding='utf-8')
        for forbidden in (
            'install ', 'mv ', 'sync ', 'tar-write ', 'daemon-reload',
            ' enable ', ' start ', ' restart ',
        ):
            self.assertNotIn(forbidden, commands)
        self.assertTrue(all(not path.exists() for path in self.managed_targets(host).values()))
        self.assertEqual((host / 'swap.img').read_bytes(), b'preserve swap\n')
        self.assertEqual(list((host / 'root/dev-infra-evidence').iterdir()), [])

    def test_check_rejects_unknown_and_partial_managed_targets(self) -> None:
        """捕获覆盖 binary/config/unit 漂移或把部分安装误判为幂等成功的缺陷。"""
        for name, drift in (
            ('containerd', 'content'),
            ('runc', 'symlink'),
            ('crictl', 'mode'),
            ('bridge', 'directory'),
            ('config', 'content'),
            ('unit', 'mode'),
        ):
            with self.subTest(name=name, drift=drift):
                environment, host, _, _ = self.make_environment()
                target = self.managed_targets(host)[name]
                if drift == 'symlink':
                    target.symlink_to('/tmp/escape')
                elif drift == 'directory':
                    target.mkdir()
                else:
                    target.write_bytes(b'unknown\n')
                    target.chmod(0o600 if drift == 'mode' else 0o755)
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

        environment, host, _, _ = self.make_environment()
        target = self.managed_targets(host)['containerd']
        target.write_bytes(self.containerd_version)
        target.chmod(0o755)
        result = self.run_stage(environment, '--check')
        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_unsafe_or_nonempty_data_root(self) -> None:
        """捕获接管非空、文件或 symlink data root 的缺陷。"""
        for drift in ('nonempty', 'file', 'symlink'):
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                data_root = host / 'var/lib/containerd'
                if drift == 'nonempty':
                    data_root.mkdir()
                    (data_root / 'unknown').write_text('preserve\n', encoding='utf-8')
                elif drift == 'file':
                    data_root.write_text('preserve\n', encoding='utf-8')
                else:
                    data_root.symlink_to('/tmp/escape')
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_unsafe_run_directory_before_install(self) -> None:
        """捕获 targets 尚缺时忽略 run dir 类型、mode 或 owner 漂移的缺陷。"""
        for drift in ('file', 'symlink', 'mode', 'owner'):
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                run_dir = host / 'run/containerd'
                if drift == 'file':
                    run_dir.write_bytes(b'unknown\n')
                elif drift == 'symlink':
                    run_dir.symlink_to('/tmp/escape')
                else:
                    run_dir.mkdir(mode=0o711)
                    run_dir.chmod(0o755 if drift == 'mode' else 0o711)
                    if drift == 'owner':
                        environment['BOOTSTRAP_TEST_OWNER_DRIFT_PATH'] = str(
                            run_dir
                        )

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_untrusted_run_parent(self) -> None:
        """捕获未验证 `/run` 类型、symlink、0755 mode 或 owner 的缺陷。"""
        for drift in ('file', 'symlink', 'mode', 'owner'):
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                run_parent = host / 'run'
                if drift in ('file', 'symlink'):
                    run_parent.rmdir()
                    if drift == 'file':
                        run_parent.write_bytes(b'unknown\n')
                    else:
                        run_parent.symlink_to('/tmp')
                elif drift == 'mode':
                    run_parent.chmod(0o700)
                else:
                    environment['BOOTSTRAP_TEST_OWNER_DRIFT_PATH'] = str(
                        run_parent
                    )

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_orphan_socket_before_install(self) -> None:
        """捕获 targets/service 尚缺时把孤立 socket entry 当作 fresh state 的缺陷。"""
        for drift in ('socket', 'file', 'symlink'):
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                run_dir = host / 'run/containerd'
                run_dir.mkdir(mode=0o711)
                run_dir.chmod(0o711)
                socket_path = run_dir / 'containerd.sock'
                if drift == 'socket':
                    self.create_cri_socket(host)
                elif drift == 'file':
                    socket_path.write_bytes(b'orphan\n')
                else:
                    socket_path.symlink_to('/tmp/escape')

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_shadow_unit_or_dropin_before_install(self) -> None:
        """捕获 targets 尚缺时忽略已加载 shadow unit 或 drop-in 的缺陷。"""
        for drift in ('fragment', 'dropin'):
            with self.subTest(drift=drift):
                environment, _, _, _ = self.make_environment()
                Path(environment['FAKE_SERVICE_UNIT_LOADED']).touch()
                if drift == 'fragment':
                    environment['FAKE_FRAGMENT_PATH'] = (
                        '/etc/systemd/system/containerd.service'
                    )
                else:
                    environment['FAKE_DROP_IN_PATHS'] = (
                        '/etc/systemd/system/containerd.service.d/override.conf'
                    )

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_accepts_load_state_not_found_as_clean_fresh_host(self) -> None:
        """捕获用 systemctl show exit0 误判 LoadState=not-found 为已加载 unit 的缺陷。"""
        environment, _, command_log, _ = self.make_environment()

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_CONTAINERD_CHECK', result.stdout)
        commands = command_log.read_text(encoding='utf-8')
        self.assertIn('systemctl show ', commands)
        for forbidden in ('daemon-reload', ' enable ', ' start ', ' restart '):
            self.assertNotIn(forbidden, commands)

    def test_check_rejects_unknown_empty_or_failed_unit_state(self) -> None:
        """捕获接受非 not-found/loaded、空输出或 show command failure 的缺陷。"""
        cases = (
            ('FAKE_LOAD_STATE', 'bad-setting'),
            ('FAKE_LOAD_STATE', 'error'),
            ('FAKE_LOAD_STATE', 'masked'),
            ('FAKE_LOAD_STATE_EMPTY', '1'),
            ('FAKE_SYSTEMCTL_SHOW_EMPTY', '1'),
            ('FAKE_SYSTEMCTL_SHOW_FAIL', '1'),
        )
        for variable, value in cases:
            with self.subTest(variable=variable, value=value):
                environment, host, _, _ = self.make_environment()
                environment[variable] = value

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
                self.assertTrue(
                    all(
                        not path.exists()
                        for path in self.managed_targets(host).values()
                    )
                )

    def test_check_allows_managed_runtime_data_after_successful_apply(self) -> None:
        """捕获首次启动填充 data root 后把精确安装误判为未知状态的缺陷。"""
        environment, host, command_log, _ = self.make_environment()

        applied = self.run_stage(environment, '--apply')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        data_root = host / 'var/lib/containerd'
        (data_root / 'io.containerd.metadata.v1.bolt').mkdir(parents=True)
        (data_root / 'io.containerd.metadata.v1.bolt/meta.db').write_bytes(
            b'runtime managed\n'
        )
        command_log.write_text('', encoding='utf-8')

        checked = self.run_stage(environment, '--check')

        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', checked.stdout)
        commands = command_log.read_text(encoding='utf-8')
        for forbidden in (
            'install ', 'mv ', 'tar-write ', 'daemon-reload',
            ' enable ', ' start ', ' restart ',
        ):
            self.assertNotIn(forbidden, commands)

    def test_check_revalidates_every_staged_digest_and_file_safety(self) -> None:
        """捕获信任前序结果、遗漏七项 digest 或接受不安全 staging 文件的缺陷。"""
        for name in ('containerd', 'runc', 'cni-plugins', 'crictl', 'helm', 'gateway-api', 'cilium-chart'):
            with self.subTest(name=name):
                environment, host, _, _ = self.make_environment()
                lock_line = next(
                    line
                    for line in Path(environment['BOOTSTRAP_TEST_LOCK_FILE']).read_text(encoding='utf-8').splitlines()
                    if line.startswith(f'{name}\t')
                )
                url = lock_line.split('\t')[2]
                staged = host / 'root/dev-infra-artifacts/pcs-2026-08-10.1' / Path(url).name
                staged.write_bytes(b'drift\n')
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 20, result.stderr)
                self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)

        environment, host, _, _ = self.make_environment()
        staged = host / 'root/dev-infra-artifacts/pcs-2026-08-10.1/crictl-v1.36.0-linux-amd64.tar.gz'
        staged.chmod(0o644)
        result = self.run_stage(environment, '--check')
        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_active_lock_digest_not_in_approved_contract(self) -> None:
        """捕获把 active lock 的任意匹配 digest 当作批准 digest 的缺陷。"""
        environment, host, command_log, _ = self.make_environment()
        lock = Path(environment['BOOTSTRAP_TEST_LOCK_FILE'])
        staged = (
            host
            / 'root/dev-infra-artifacts/pcs-2026-08-10.1/runc.amd64'
        )
        tampered = b'tampered but internally consistent\n'
        staged.write_bytes(tampered)
        staged.chmod(0o600)
        digest = hashlib.sha256(tampered).hexdigest()
        lines = [
            '\t'.join(
                [*line.split('\t')[:3], digest, line.split('\t')[4]]
            )
            if line.startswith('runc\t')
            else line
            for line in lock.read_text(encoding='utf-8').splitlines()
        ]
        lock.write_text('\n'.join(lines) + '\n', encoding='utf-8')

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 20, result.stderr)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)
        self.assertTrue(
            all(not path.exists() for path in self.managed_targets(host).values())
        )
        self.assertFalse(command_log.exists())

    def test_check_rejects_unsafe_target_parent(self) -> None:
        """捕获沿父目录 symlink 逃逸或容忍父目录权限漂移的缺陷。"""
        for drift in ('symlink', 'mode'):
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                parent = host / 'etc/containerd'
                parent.rmdir()
                if drift == 'symlink':
                    parent.symlink_to('/tmp')
                else:
                    parent.mkdir(mode=0o700)
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_apply_rejects_archive_missing_or_unsafe_expected_member(self) -> None:
        """捕获 archive 缺成员、路径逃逸或 symlink 冒充 executable 的缺陷。"""
        cases = {
            'containerd': self.archive_bytes([('bin/containerd', self.containerd_version)]),
            'cni-plugins': self.archive_bytes([('bridge', self.cni_binaries['bridge'])]),
            'crictl': self.archive_bytes([('crictl', 'bin/crictl')]),
            'escape': self.archive_bytes([('../escape', b'escape\n')]),
        }
        for name, artifact in cases.items():
            with self.subTest(name=name):
                artifact_name = 'containerd' if name == 'escape' else name
                environment, host, _, _ = self.make_environment(
                    {artifact_name: artifact}
                )
                result = self.run_stage(environment, '--apply')
                self.assertEqual(result.returncode, 20, result.stderr)
                self.assertIn('RESULT=STOP_ARCHIVE_UNSAFE', result.stdout)
                self.assertTrue(all(not path.exists() for path in self.managed_targets(host).values()))

    def test_apply_installs_exact_targets_and_verifies_health_without_leak(self) -> None:
        """捕获漏装 crictl/CNI、错误 endpoint、宽松健康解析或 raw output 泄漏的缺陷。"""
        environment, host, command_log, _ = self.make_environment()
        environment['FAKE_CANARY'] = 'SECRET_CANARY_STDERR'

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=PASS_CONTAINERD_INSTALLED', result.stdout)
        self.assertNotIn('SECRET_CANARY', result.stdout + result.stderr)
        for path in self.managed_targets(host).values():
            self.assertTrue(path.is_file(), path)
        self.assertEqual(self.managed_targets(host)['crictl'].stat().st_mode & 0o777, 0o755)
        self.assertEqual((host / 'swap.img').read_bytes(), b'preserve swap\n')
        commands = command_log.read_text(encoding='utf-8')
        self.assertIn(
            f'crictl --runtime-endpoint {self.endpoint} --image-endpoint {self.endpoint} info --output json\n',
            commands,
        )
        self.assertIn('systemctl daemon-reload\n', commands)
        self.assertIn('systemctl enable containerd.service\n', commands)
        self.assertIn('systemctl start containerd.service\n', commands)
        evidence = list((host / 'root/dev-infra-evidence').glob('10-containerd-*.txt'))
        self.assertEqual(len(evidence), 1)
        evidence_text = evidence[0].read_text(encoding='utf-8')
        self.assertNotIn('SECRET_CANARY', evidence_text)
        evidence_keys = {line.split('=', 1)[0] for line in evidence_text.splitlines()}
        self.assertEqual(
            evidence_keys,
            {
                'ARTIFACT_SET', 'CONTAINERD_VERSION', 'RUNC_VERSION',
                'CRICTL_VERSION', 'CRI_RUNTIME_READY', 'SNAPSHOTTER',
                'RUNTIME_NAME', 'RUNTIME_TYPE', 'SYSTEMD_CGROUP',
                'SERVICE_ACTIVE', 'SERVICE_ENABLED', 'CRI_SOCKET',
                'PHASE', 'MODE', 'RESULT', 'REASON', 'EVIDENCE',
                'EXIT_CODE', 'NEXT',
            },
        )

    def test_apply_fails_closed_on_sync_or_concurrent_target(self) -> None:
        """捕获忽略 sync 失败或覆盖并发出现目标的缺陷。"""
        environment, host, _, _ = self.make_environment()
        environment['FAKE_SYNC_FAIL'] = '1'
        result = self.run_stage(environment, '--apply')
        self.assertEqual(result.returncode, 40, result.stderr)
        self.assertIn('RESULT=STOP_APPLY_FAILED', result.stdout)
        self.assertTrue(all(not path.exists() for path in self.managed_targets(host).values()))

        environment, host, _, _ = self.make_environment()
        target = self.managed_targets(host)['containerd']
        environment['FAKE_MV_RACE_TARGET'] = str(target)
        result = self.run_stage(environment, '--apply')
        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
        self.assertEqual(target.read_bytes(), b'concurrent\n')

    def test_check_exact_install_is_idempotent_without_service_restart(self) -> None:
        """捕获精确已安装状态仍重写文件、reload、enable 或 restart 的缺陷。"""
        environment, host, command_log, _ = self.make_environment()
        self.install_compliant_targets(environment, host)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', result.stdout)
        commands = command_log.read_text(encoding='utf-8')
        for forbidden in ('install ', 'mv ', 'tar-write ', 'daemon-reload', ' enable ', ' start ', ' restart '):
            self.assertNotIn(forbidden, commands)

    def test_check_rejects_exact_files_with_service_state_drift(self) -> None:
        """捕获自动修复 inactive/disabled 精确安装而非 STOP 的缺陷。"""
        for missing_state in ('active', 'enabled'):
            with self.subTest(missing_state=missing_state):
                environment, host, _, _ = self.make_environment()
                self.install_compliant_targets(environment, host)
                Path(environment[f'FAKE_SERVICE_{missing_state.upper()}']).unlink()
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_shadow_unit_dropins_and_socket_drift(self) -> None:
        """捕获只看 active/enabled 而接受 shadow unit、drop-in 或伪 socket 的缺陷。"""
        cases = ('fragment', 'dropin', 'missing', 'file', 'symlink', 'mode')
        for drift in cases:
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                self.install_compliant_targets(environment, host)
                socket_path = host / 'run/containerd/containerd.sock'
                if drift == 'fragment':
                    environment['FAKE_FRAGMENT_PATH'] = (
                        '/etc/systemd/system/containerd.service'
                    )
                elif drift == 'dropin':
                    environment['FAKE_DROP_IN_PATHS'] = (
                        '/etc/systemd/system/containerd.service.d/override.conf'
                    )
                else:
                    socket_path.unlink()
                    if drift == 'file':
                        socket_path.write_bytes(b'not a socket\n')
                    elif drift == 'symlink':
                        socket_path.symlink_to('/tmp/escape')
                    elif drift == 'mode':
                        self.create_cri_socket(host).chmod(0o600)

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_check_rejects_owner_and_runtime_directory_mode_drift(self) -> None:
        """捕获 staging/target/data/run/socket owner 或 runtime dir mode 漂移的缺陷。"""
        cases = (
            'artifact-root', 'staged-file', 'target-parent', 'managed-target',
            'data-root', 'run-dir', 'socket', 'data-missing', 'data-mode',
            'run-mode',
        )
        for drift in cases:
            with self.subTest(drift=drift):
                environment, host, _, _ = self.make_environment()
                if drift in {
                    'managed-target', 'data-root', 'run-dir', 'socket',
                    'data-missing', 'data-mode', 'run-mode',
                }:
                    self.install_compliant_targets(environment, host)
                paths = {
                    'artifact-root': host / 'root/dev-infra-artifacts',
                    'staged-file': (
                        host / 'root/dev-infra-artifacts/pcs-2026-08-10.1/runc.amd64'
                    ),
                    'target-parent': host / 'usr/local/bin',
                    'managed-target': self.managed_targets(host)['containerd'],
                    'data-root': host / 'var/lib/containerd',
                    'run-dir': host / 'run/containerd',
                    'socket': host / 'run/containerd/containerd.sock',
                }
                if drift == 'data-missing':
                    (host / 'var/lib/containerd').rmdir()
                elif drift == 'data-mode':
                    (host / 'var/lib/containerd').chmod(0o755)
                elif drift == 'run-mode':
                    (host / 'run/containerd').chmod(0o755)
                else:
                    environment['BOOTSTRAP_TEST_OWNER_DRIFT_PATH'] = str(
                        paths[drift]
                    )

                result = self.run_stage(environment, '--check')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)

    def test_apply_revalidates_target_parent_after_mktemp_race(self) -> None:
        """捕获 extract/publish mktemp 后 parent 漂移仍继续安装的缺陷。"""
        environment, host, _, _ = self.make_environment()
        parent = host / 'usr/local/bin'
        environment['FAKE_MKTEMP_RACE_PARENT'] = str(parent)

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 30, result.stderr)
        self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
        self.assertTrue(
            all(not path.exists() for path in self.managed_targets(host).values())
        )

    def assert_extract_parent_race_stops_before_writes(
        self, *, match: str, parent_path: str
    ) -> None:
        for drift in ('mode', 'owner', 'type'):
            with self.subTest(match=match, drift=drift):
                environment, host, command_log, _ = self.make_environment()
                parent = host / parent_path
                marker = host.parent / f'{match.strip(".")}-{drift}.marker'
                environment.update(
                    {
                        'FAKE_MKTEMP_RACE_PARENT': str(parent),
                        'FAKE_MKTEMP_RACE_MATCH': match,
                        'FAKE_MKTEMP_RACE_ACTION': drift,
                        'FAKE_MKTEMP_RACE_OWNER_MARKER': str(marker),
                        'BOOTSTRAP_TEST_DEFERRED_OWNER_DRIFT_PATH': str(parent),
                        'BOOTSTRAP_TEST_OWNER_DRIFT_AFTER_MARKER': str(marker),
                    }
                )

                result = self.run_stage(environment, '--apply')

                self.assertEqual(result.returncode, 30, result.stderr)
                self.assertIn('RESULT=STOP_UNKNOWN_STATE', result.stdout)
                commands = command_log.read_text(encoding='utf-8')
                for forbidden in ('tar-write ', 'install ', 'mv '):
                    self.assertNotIn(forbidden, commands)
                self.assertTrue(
                    all(
                        not path.exists()
                        for path in self.managed_targets(host).values()
                    )
                )

    def test_apply_revalidates_cni_parent_after_its_mktemp(self) -> None:
        """捕获 CNI mktemp 后 parent mode/owner/type 漂移仍 tar 或发布的缺陷。"""
        self.assert_extract_parent_race_stops_before_writes(
            match='.cni.extract.', parent_path='opt/cni/bin'
        )

    def test_apply_revalidates_crictl_parent_after_its_mktemp(self) -> None:
        """捕获 crictl mktemp 后 parent mode/owner/type 漂移仍 tar 或发布的缺陷。"""
        self.assert_extract_parent_race_stops_before_writes(
            match='.crictl.extract.', parent_path='usr/local/bin'
        )

    def test_health_rejects_version_and_plugin_drift(self) -> None:
        """捕获宽松接受 containerd/runc/crictl 版本或 CRI/overlayfs plugin 漂移的缺陷。"""
        cases = {
            'FAKE_CONTAINERD_VERSION': 'containerd v2.3.0',
            'FAKE_RUNC_VERSION': 'runc version 1.3.5',
            'FAKE_CRICTL_VERSION': 'crictl version v1.35.0',
            'FAKE_CTR_OUTPUT': 'io.containerd.snapshotter.v1 overlayfs linux/amd64 error',
        }
        for variable, value in cases.items():
            with self.subTest(variable=variable):
                environment, host, _, _ = self.make_environment()
                self.install_compliant_targets(environment, host)
                environment[variable] = value
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 50, result.stderr)
                self.assertIn('RESULT=STOP_VERIFY_FAILED', result.stdout)

    def test_health_strictly_parses_runtime_ready_and_allowlisted_json(self) -> None:
        """捕获 RuntimeReady 非唯一/非 boolean、runtime config 漂移或 malformed JSON 被接受及泄漏的缺陷。"""
        duplicate = self.valid_info()
        import json

        duplicate_data = json.loads(duplicate)
        duplicate_data['status']['conditions'].append(
            {'type': 'RuntimeReady', 'status': True}
        )
        drifted = json.loads(self.valid_info())
        drifted['config']['containerd']['runtimes']['runc']['options'][
            'SystemdCgroup'
        ] = False
        cases = (
            self.valid_info(runtime_ready=False),
            self.valid_info(runtime_ready='true'),
            json.dumps(duplicate_data),
            json.dumps(drifted),
            '{SECRET_CANARY_MALFORMED',
        )
        for info in cases:
            with self.subTest(info=hashlib.sha256(info.encode()).hexdigest()):
                environment, host, _, _ = self.make_environment()
                self.install_compliant_targets(environment, host)
                environment['FAKE_CRICTL_INFO'] = info
                result = self.run_stage(environment, '--check')
                self.assertEqual(result.returncode, 50, result.stderr)
                self.assertIn('RESULT=STOP_VERIFY_FAILED', result.stdout)
                self.assertNotIn('SECRET_CANARY', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
