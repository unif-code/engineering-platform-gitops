from __future__ import annotations

import hashlib
import io
import os
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
        fixture = directory / 'download.fixture'
        fixture.write_bytes(artifact)
        lock = directory / 'artifacts.lock.tsv'
        if records is None:
            records = [(name, version, url, artifact, target)]
        lock.write_text(
            ''.join(
                '\t'.join(
                    [
                        record_name,
                        record_version,
                        record_url,
                        (
                            digest
                            if len(records) == 1 and record_name == name and digest
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
                *)
                  shift
                  ;;
              esac
            done
            [ "$fail" = true ] && [ "$location" = true ] && \
              [ "$protocol" = true ] && [ "$tls" = true ] && [ -n "$output" ] || exit 64
            /bin/cp "$FAKE_DOWNLOAD_SOURCE" "$output"
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
                'FAKE_DOWNLOAD_SOURCE': str(fixture),
            }
        )
        return environment, host, lock, curl_log

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
        environment, host, _, _ = self.make_environment(b'approved\n')
        staged = self.staged_path(host, 'runc.amd64')
        staged.parent.mkdir(parents=True, mode=0o700)
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
                [('bridge', b'bridge\n'), ('host-local', b'host-local\n'), ('loopback', b'loopback\n')],
            ),
            (
                'helm',
                '3.21.0',
                'https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz',
                '/usr/local/bin/helm',
                [('linux-amd64/helm', b'helm\n')],
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
        artifact = b'approved\n'
        environment, host, _, curl_log = self.make_environment(artifact)
        staged = self.staged_path(host, 'runc.amd64')
        staged.parent.mkdir(parents=True, mode=0o700)
        staged.write_bytes(artifact)
        staged.chmod(0o600)

        result = self.run_stage(environment, '--check')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', result.stdout)
        self.assertFalse(curl_log.exists())

    def test_apply_reports_already_compliant_only_when_all_locked_artifacts_match(self) -> None:
        records = [
            ('containerd', '2.3.1', 'https://github.com/containerd/containerd/releases/download/v2.3.1/containerd-2.3.1-linux-amd64.tar.gz', b'containerd\n', '/usr/local/bin'),
            ('runc', '1.3.6', 'https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64', b'runc\n', '/usr/local/sbin/runc'),
            ('cni-plugins', '1.9.1', 'https://github.com/containernetworking/plugins/releases/download/v1.9.1/cni-plugins-linux-amd64-v1.9.1.tgz', b'cni\n', '/opt/cni/bin'),
            ('helm', '3.21.0', 'https://get.helm.sh/helm-v3.21.0-linux-amd64.tar.gz', b'helm\n', '/usr/local/bin/helm'),
            ('gateway-api', '1.6.1', 'https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml', b'gateway\n', 'kubernetes://gateway-api/standard'),
            ('cilium-chart', '1.20.0', 'https://helm.cilium.io/cilium-1.20.0.tgz', b'cilium\n', 'kubernetes://kube-system/cilium'),
        ]
        environment, host, _, curl_log = self.make_environment(
            b'ignored\n', records=records
        )
        for _, _, url, artifact, _ in records:
            staged = self.staged_path(host, Path(url).name)
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(artifact)
            staged.chmod(0o600)

        result = self.run_stage(environment, '--apply')

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('RESULT=ALREADY_COMPLIANT', result.stdout)
        self.assertFalse(curl_log.exists())


if __name__ == '__main__':
    unittest.main()
