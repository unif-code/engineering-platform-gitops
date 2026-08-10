from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / 'scripts/bootstrap/lib/common.sh'
CIDR_CHECK = ROOT / 'scripts/bootstrap/check_cidrs.py'
PREFLIGHT = ROOT / 'scripts/bootstrap/00-preflight.sh'


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


if __name__ == '__main__':
    unittest.main()
