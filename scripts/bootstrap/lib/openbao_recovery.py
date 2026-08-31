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


def _openpgp_length(data: bytes, offset: int) -> tuple[int, bool, int]:
    if offset >= len(data):
        _reject('malformed openpgp packet')
    first = data[offset]
    offset += 1
    if first < 192:
        return first, False, offset
    if first < 224:
        if offset >= len(data):
            _reject('malformed openpgp packet')
        length = ((first - 192) << 8) + data[offset] + 192
        return length, False, offset + 1
    if first < 255:
        return 1 << (first & 0x1F), True, offset
    if offset + 4 > len(data):
        _reject('malformed openpgp packet')
    return int.from_bytes(data[offset : offset + 4], 'big'), False, offset + 4


def _openpgp_packets(data: bytes) -> list[tuple[int, bytes]]:
    packets: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(data):
        header = data[offset]
        offset += 1
        if header & 0x80 == 0:
            _reject('malformed openpgp packet')
        if header & 0x40:
            tag = header & 0x3F
            length, partial, offset = _openpgp_length(data, offset)
            chunks: list[bytes] = []
            while True:
                if length > len(data) - offset:
                    _reject('malformed openpgp packet')
                chunks.append(data[offset : offset + length])
                offset += length
                if not partial:
                    break
                length, partial, offset = _openpgp_length(data, offset)
            body = b''.join(chunks)
        else:
            tag = (header & 0x3F) >> 2
            length_type = header & 0x03
            if length_type == 3:
                _reject('malformed openpgp packet')
            length_bytes = 1 << length_type
            if offset + length_bytes > len(data):
                _reject('malformed openpgp packet')
            length = int.from_bytes(
                data[offset : offset + length_bytes], 'big'
            )
            offset += length_bytes
            if length > len(data) - offset:
                _reject('malformed openpgp packet')
            body = data[offset : offset + length]
            offset += length
        packets.append((tag, body))
    if not packets:
        _reject('malformed openpgp packet')
    return packets


def _public_key_recipients(
    exported_key: bytes, expected_fingerprint: str
) -> tuple[set[bytes], set[bytes]]:
    key_ids: set[bytes] = set()
    fingerprints: set[bytes] = set()
    primary_fingerprint: bytes | None = None
    primary_count = 0
    for tag, body in _openpgp_packets(exported_key):
        if tag in (5, 7):
            _reject('private key packet forbidden')
        if tag not in (6, 14):
            continue
        if tag == 6:
            primary_count += 1
        if len(body) < 6:
            _reject('invalid public key packet')
        if body[0] == 4:
            if len(body) > 0xFFFF:
                _reject('invalid public key packet')
            fingerprint = hashlib.sha1(
                b'\x99' + len(body).to_bytes(2, 'big') + body
            ).digest()
            key_id = fingerprint[-8:]
        elif body[0] == 6:
            if len(body) < 10:
                _reject('invalid public key packet')
            material_length = int.from_bytes(body[6:10], 'big')
            if material_length != len(body) - 10:
                _reject('invalid public key packet')
            fingerprint = hashlib.sha256(
                b'\x9b' + len(body).to_bytes(4, 'big') + body
            ).digest()
            key_id = fingerprint[:8]
        else:
            _reject('unsupported public key version')
        fingerprints.add(fingerprint)
        key_ids.add(key_id)
        if tag == 6:
            primary_fingerprint = fingerprint
    if primary_count != 1 or primary_fingerprint is None:
        _reject('one public key required')
    try:
        expected = bytes.fromhex(expected_fingerprint)
    except ValueError as error:
        raise RecoveryValidationError('invalid public key fingerprint') from error
    if not hmac.compare_digest(primary_fingerprint, expected):
        _reject('public key packet fingerprint mismatch')
    return key_ids, fingerprints


def _consume_mpi(body: bytes, offset: int) -> int:
    if offset + 2 > len(body):
        _reject('malformed openpgp ciphertext')
    bit_length = int.from_bytes(body[offset : offset + 2], 'big')
    byte_length = (bit_length + 7) // 8
    if bit_length == 0 or offset + 2 + byte_length > len(body):
        _reject('malformed openpgp ciphertext')
    return offset + 2 + byte_length


def _validate_pkesk(
    body: bytes, key_ids: set[bytes], fingerprints: set[bytes]
) -> int:
    if not body:
        _reject('malformed openpgp ciphertext')
    if body[0] == 3:
        if len(body) < 13 or body[1:9] not in key_ids:
            _reject('openpgp recipient mismatch')
        algorithm = body[9]
        offset = 10
    elif body[0] == 6:
        if len(body) < 5:
            _reject('malformed openpgp ciphertext')
        recipient_size = body[1]
        if recipient_size not in (21, 33) or len(body) < 3 + recipient_size:
            _reject('openpgp recipient mismatch')
        key_version = body[2]
        recipient = body[3 : 2 + recipient_size]
        if (
            (key_version == 4 and len(recipient) != 20)
            or (key_version == 6 and len(recipient) != 32)
            or recipient not in fingerprints
        ):
            _reject('openpgp recipient mismatch')
        algorithm = body[2 + recipient_size]
        offset = 3 + recipient_size
    else:
        _reject('unsupported pkesk version')
    if algorithm in (1, 2):
        offset = _consume_mpi(body, offset)
    elif algorithm == 16:
        offset = _consume_mpi(body, offset)
        offset = _consume_mpi(body, offset)
    else:
        _reject('unsupported openpgp encryption algorithm')
    if offset != len(body):
        _reject('malformed openpgp ciphertext')
    return body[0]


def _validated_ciphertext(
    value: Any, key_ids: set[bytes], fingerprints: set[bytes]
) -> bytes:
    if not isinstance(value, str) or len(value) < 100:
        _reject('encrypted ciphertext required')
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, UnicodeError) as error:
        raise RecoveryValidationError('encrypted ciphertext required') from error
    if len(decoded) < 64:
        _reject('encrypted ciphertext required')
    packets = _openpgp_packets(decoded)
    if len(packets) != 2 or packets[0][0] != 1 or packets[1][0] != 18:
        _reject('openpgp encrypted message required')
    pkesk_version = _validate_pkesk(packets[0][1], key_ids, fingerprints)
    encrypted = packets[1][1]
    expected_seipd_version = 1 if pkesk_version == 3 else 2
    if len(encrypted) < 64 or encrypted[0] != expected_seipd_version:
        _reject('invalid integrity-protected ciphertext')
    return decoded


def _validate_init(
    document: dict[str, Any],
    raw: bytes,
    key_ids: set[bytes],
    fingerprints: set[bytes],
) -> None:
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
    decoded_keys = [
        _validated_ciphertext(value, key_ids, fingerprints) for value in keys
    ]
    if len(set(decoded_keys)) != 5:
        _reject('duplicate share ciphertext')
    _validated_ciphertext(document.get('root_token'), key_ids, fingerprints)

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
    key_ids, key_fingerprints = _public_key_recipients(
        decoded_key, public_key_fingerprint
    )
    _validate_init(
        init_document,
        files[f'{prefix}/init.json'],
        key_ids,
        key_fingerprints,
    )
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
