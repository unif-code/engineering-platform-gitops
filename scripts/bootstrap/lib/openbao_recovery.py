#!/usr/bin/env python3
"""Validate OpenBao recovery artifacts without exposing encrypted material."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import pathlib
import re
import sys
import tarfile
from typing import Any


V1_SCHEMA = 'engineering-platform/openbao-recovery/v1'
MAX_ARCHIVE_BYTES = 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024
SHA256 = re.compile(r'[0-9a-f]{64}')
GIT_SHA = re.compile(r'[0-9a-f]{40}')
PUBLIC_FINGERPRINT = re.compile(r'(?:[0-9A-F]{40}|[0-9A-F]{64})')
TOKEN_SHAPE = re.compile(rb'(?i)(?:hvs|hvb|hvr|s)\.[A-Za-z0-9_-]{8,}')


class RecoveryValidationError(Exception):
    """An artifact failed a fail-closed recovery validation rule."""


@dataclasses.dataclass(frozen=True)
class SourceBundleFacts:
    schema: str
    archive_sha256: str
    source_sha: str
    public_key_sha256: str
    public_key_fingerprint: str
    platform_secret_fingerprint: str


def _reject(message: str) -> None:
    raise RecoveryValidationError(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject('duplicate json field')
        result[key] = value
    return result


def _json_document(payload: bytes) -> dict[str, Any]:
    try:
        document = json.loads(
            payload.decode('utf-8'), object_pairs_hook=_unique_object
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RecoveryValidationError('invalid json') from error
    if not isinstance(document, dict):
        _reject('json object required')
    return document


def _single_archive_root(expected: set[str]) -> str:
    roots = {
        pathlib.PurePosixPath(name).parts[0]
        for name in expected
        if pathlib.PurePosixPath(name).parts
    }
    if len(roots) != 1:
        _reject('one archive root required')
    return next(iter(roots))


def read_exact_tar(
    archive: pathlib.Path, expected: set[str]
) -> dict[str, bytes]:
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        _reject('archive too large')
    root = _single_archive_root(expected)
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != expected | {root}:
            _reject('unsafe archive members')
        for member in members:
            path = pathlib.PurePosixPath(member.name)
            if (
                path.is_absolute()
                or '..' in path.parts
                or member.issym()
                or member.islnk()
                or member.isdev()
            ):
                _reject('unsafe archive members')
            if member.name == root:
                if not member.isdir():
                    _reject('unsafe archive members')
            elif member.name not in expected or not member.isfile():
                _reject('unsafe archive members')
            elif member.size < 0 or member.size > MAX_MEMBER_BYTES:
                _reject('unsafe archive member size')
        files: dict[str, bytes] = {}
        for member in members:
            if not member.isfile():
                continue
            extracted = stream.extractfile(member)
            if extracted is None:
                _reject('unreadable archive member')
            payload = extracted.read(MAX_MEMBER_BYTES + 1)
            if len(payload) != member.size or len(payload) > MAX_MEMBER_BYTES:
                _reject('unsafe archive member size')
            files[member.name] = payload
        return files


def _sidecar_digest(
    archive: pathlib.Path, sidecar: pathlib.Path, source_sha: str
) -> str:
    expected_name = f'openbao-recovery-{source_sha}.tar.gz'
    if archive.name != expected_name or sidecar.name != expected_name + '.sha256':
        _reject('source archive name mismatch')
    try:
        text = sidecar.read_text(encoding='ascii')
    except UnicodeError as error:
        raise RecoveryValidationError('invalid sidecar') from error
    match = re.fullmatch(
        rf'([0-9a-f]{{64}})  {re.escape(expected_name)}\n', text
    )
    if match is None:
        _reject('invalid sidecar')
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        _reject('archive too large')
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b''):
            digest.update(chunk)
    actual = digest.hexdigest()
    if not hmac.compare_digest(match.group(1), actual):
        _reject('archive digest mismatch')
    return actual


def _validated_ciphertext(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) < 100:
        _reject('encrypted ciphertext required')
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError) as error:
        raise RecoveryValidationError('encrypted ciphertext required') from error
    if len(decoded) < 64:
        _reject('encrypted ciphertext required')
    return decoded


def _validate_init(document: dict[str, Any], raw: bytes) -> None:
    allowed = {
        'unseal_shares',
        'unseal_threshold',
        'unseal_keys_b64',
        'unseal_keys_hex',
        'recovery_keys_b64',
        'recovery_keys_hex',
        'recovery_keys_shares',
        'recovery_keys_threshold',
        'root_token',
    }
    if not set(document) <= allowed:
        _reject('unexpected init field')
    if (
        type(document.get('unseal_shares')) is not int
        or document['unseal_shares'] != 5
        or type(document.get('unseal_threshold')) is not int
        or document['unseal_threshold'] != 3
    ):
        _reject('invalid share contract')
    keys = document.get('unseal_keys_b64')
    if not isinstance(keys, list) or len(keys) != 5:
        _reject('invalid share contract')
    decoded_keys = [_validated_ciphertext(value) for value in keys]
    if len(set(decoded_keys)) != 5:
        _reject('duplicate share ciphertext')
    _validated_ciphertext(document.get('root_token'))

    hex_keys = document.get('unseal_keys_hex')
    if hex_keys is not None:
        if not isinstance(hex_keys, list) or len(hex_keys) != 5:
            _reject('invalid share contract')
        try:
            decoded_hex = [bytes.fromhex(value) for value in hex_keys]
        except (TypeError, ValueError) as error:
            raise RecoveryValidationError('invalid share contract') from error
        if decoded_hex != decoded_keys:
            _reject('ciphertext representations differ')
    for field in ('recovery_keys_b64', 'recovery_keys_hex'):
        if field in document and document[field] != []:
            _reject('unexpected recovery keys')
    for field in ('recovery_keys_shares', 'recovery_keys_threshold'):
        if field in document and document[field] != 0:
            _reject('unexpected recovery key contract')
    if TOKEN_SHAPE.search(raw) or b'PRIVATE KEY' in raw.upper():
        _reject('plaintext secret shape detected')


def _validate_metadata(
    document: dict[str, Any],
    *,
    source_sha: str,
    docs_commit: str,
    docs_baseline: str,
    deviation: str,
    public_key_sha256: str,
    public_key_fingerprint: str,
    platform_secret_fingerprint: str,
) -> None:
    expected = {
        'schema': V1_SCHEMA,
        'git_commit': source_sha,
        'docs_commit': docs_commit,
        'docs_baseline': docs_baseline,
        'deviation': deviation,
        'public_key_sha256': public_key_sha256,
        'public_key_fingerprint': public_key_fingerprint,
        'platform_secret_fingerprint': platform_secret_fingerprint,
        'key_shares': 5,
        'key_threshold': 3,
        'plaintext_recovery_material': 'NOT_RECORDED',
    }
    if document != expected:
        _reject('source metadata mismatch')


def validate_source(
    archive: pathlib.Path,
    sidecar: pathlib.Path,
    *,
    source_sha: str,
    docs_commit: str,
    docs_baseline: str,
    deviation: str,
    public_key_sha256: str,
    public_key_fingerprint: str,
    platform_secret_fingerprint: str,
) -> SourceBundleFacts:
    if (
        GIT_SHA.fullmatch(source_sha) is None
        or GIT_SHA.fullmatch(docs_commit) is None
        or SHA256.fullmatch(public_key_sha256) is None
        or PUBLIC_FINGERPRINT.fullmatch(public_key_fingerprint) is None
        or SHA256.fullmatch(platform_secret_fingerprint) is None
        or not docs_baseline
        or not deviation
    ):
        _reject('invalid expected source facts')
    archive_sha256 = _sidecar_digest(archive, sidecar, source_sha)
    prefix = f'openbao-recovery-{source_sha}'
    names = {
        f'{prefix}/init.json',
        f'{prefix}/metadata.json',
        f'{prefix}/openbao-recovery-public-key.b64',
        f'{prefix}/openbao-recovery-public-key.fingerprint',
    }
    files = read_exact_tar(archive, names)
    metadata = _json_document(files[f'{prefix}/metadata.json'])
    init_document = _json_document(files[f'{prefix}/init.json'])
    public_key = files[f'{prefix}/openbao-recovery-public-key.b64']
    fingerprint_bytes = files[
        f'{prefix}/openbao-recovery-public-key.fingerprint'
    ]

    encoded_key = public_key.decode('ascii').strip()
    if not encoded_key or any(character.isspace() for character in encoded_key):
        _reject('invalid public key')
    try:
        decoded_key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, UnicodeError) as error:
        raise RecoveryValidationError('invalid public key') from error
    if not 128 <= len(decoded_key) <= 16384:
        _reject('invalid public key')
    actual_key_sha256 = hashlib.sha256(public_key).hexdigest()
    if not hmac.compare_digest(actual_key_sha256, public_key_sha256):
        _reject('public key digest mismatch')
    fingerprint = fingerprint_bytes.decode('ascii').strip()
    if (
        PUBLIC_FINGERPRINT.fullmatch(fingerprint) is None
        or not hmac.compare_digest(fingerprint, public_key_fingerprint)
    ):
        _reject('public key fingerprint mismatch')

    _validate_metadata(
        metadata,
        source_sha=source_sha,
        docs_commit=docs_commit,
        docs_baseline=docs_baseline,
        deviation=deviation,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=public_key_fingerprint,
        platform_secret_fingerprint=platform_secret_fingerprint,
    )
    _validate_init(init_document, files[f'{prefix}/init.json'])
    return SourceBundleFacts(
        schema=V1_SCHEMA,
        archive_sha256=archive_sha256,
        source_sha=source_sha,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=public_key_fingerprint,
        platform_secret_fingerprint=platform_secret_fingerprint,
    )


def main(arguments: list[str]) -> int:
    if len(arguments) != 10 or arguments[0] != 'validate-source':
        return 2
    try:
        validate_source(
            pathlib.Path(arguments[1]),
            pathlib.Path(arguments[2]),
            source_sha=arguments[3],
            docs_commit=arguments[4],
            docs_baseline=arguments[5],
            deviation=arguments[6],
            public_key_sha256=arguments[7],
            public_key_fingerprint=arguments[8],
            platform_secret_fingerprint=arguments[9],
        )
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
