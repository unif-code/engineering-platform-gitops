#!/usr/bin/env python3
"""Validate OpenBao recovery artifacts without exposing encrypted material."""

from __future__ import annotations

import argparse
import base64
import dataclasses
import datetime
import gzip
import hashlib
import hmac
import io
import json
import os
import pathlib
import re
import stat
import sys
import tarfile
import zlib
from typing import Any


V1_SCHEMA = 'engineering-platform/openbao-recovery/v1'
CANDIDATE_SCHEMA = (
    'engineering-platform/openbao-recovery-rotation-candidate/v1'
)
V2_SCHEMA = 'engineering-platform/openbao-recovery/v2'
MAX_ARCHIVE_BYTES = 1024 * 1024
MAX_UNCOMPRESSED_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024
MAX_SIDECAR_BYTES = 256
SHA256 = re.compile(r'[0-9a-f]{64}')
GIT_SHA = re.compile(r'[0-9a-f]{40}')
PUBLIC_FINGERPRINT = re.compile(r'(?:[0-9A-F]{40}|[0-9A-F]{64})')
TOKEN_SHAPE = re.compile(rb'(?i)(?:hvs|hvb|hvr|s)\.[A-Za-z0-9_-]{8,}')
SAFE_NONCE = re.compile(r'[A-Za-z0-9_-]{8,128}')
CLUSTER_ID = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-'
    r'[89ab][0-9a-f]{3}-[0-9a-f]{12}'
)
CLUSTER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')
UTC_TIMESTAMP = re.compile(
    r'(?:19|20)[0-9]{2}-(?:0[1-9]|1[0-2])-'
    r'(?:0[1-9]|[12][0-9]|3[01])T'
    r'(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z'
)
ROTATED_FILES = {
    'shares.json',
    'metadata.json',
    'openbao-recovery-public-key.b64',
    'openbao-recovery-public-key.fingerprint',
}


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


@dataclasses.dataclass(frozen=True)
class RotatedBundleFacts:
    schema: str
    archive_sha256: str
    current_sha: str
    source_sha: str
    source_bundle_sha256: str
    public_key_sha256: str
    public_key_fingerprint: str
    cluster_identity_sha256: str
    ciphertexts: tuple[str, ...]
    verification_nonce: str | None


@dataclasses.dataclass(frozen=True)
class _ArtifactSnapshot:
    archive_name: str
    archive_bytes: bytes
    sidecar_bytes: bytes
    archive_sha256: str


@dataclasses.dataclass(frozen=True)
class _SourceBundleValidation:
    facts: SourceBundleFacts
    ciphertexts: tuple[str, ...]
    root_token: str


@dataclasses.dataclass(frozen=True)
class _RotatedBundleValidation:
    facts: RotatedBundleFacts
    files: dict[str, bytes]


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


def _read_regular_file_once(
    path: pathlib.Path, maximum_bytes: int, *, require_mode: bool
) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, 'O_BINARY'):
        flags |= os.O_BINARY
    if hasattr(os, 'O_CLOEXEC'):
        flags |= os.O_CLOEXEC
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    elif path.is_symlink():
        _reject('unsafe artifact path')
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RecoveryValidationError('artifact missing') from error
    try:
        facts = os.fstat(descriptor)
        if (
            not stat.S_ISREG(facts.st_mode)
            or facts.st_size < 0
            or facts.st_size > maximum_bytes
        ):
            _reject('unsafe artifact path')
        if require_mode and stat.S_IMODE(facts.st_mode) != 0o600:
            _reject('artifact mode mismatch')
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(
                descriptor, min(64 * 1024, maximum_bytes + 1 - total)
            )
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                _reject('artifact too large')
        return b''.join(chunks)
    except OSError as error:
        raise RecoveryValidationError('artifact read failed') from error
    finally:
        os.close(descriptor)


def _artifact_snapshot(
    archive: pathlib.Path,
    sidecar: pathlib.Path,
    expected_name: str,
    *,
    require_mode: bool = False,
) -> _ArtifactSnapshot:
    if archive.name != expected_name or sidecar.name != expected_name + '.sha256':
        _reject('archive name mismatch')
    archive_bytes = _read_regular_file_once(
        archive, MAX_ARCHIVE_BYTES, require_mode=require_mode
    )
    sidecar_bytes = _read_regular_file_once(
        sidecar, MAX_SIDECAR_BYTES, require_mode=require_mode
    )
    try:
        sidecar_text = sidecar_bytes.decode('ascii')
    except UnicodeError as error:
        raise RecoveryValidationError('invalid sidecar') from error
    match = re.fullmatch(
        rf'([0-9a-f]{{64}})  {re.escape(expected_name)}\n', sidecar_text
    )
    if match is None:
        _reject('invalid sidecar')
    digest = hashlib.sha256(archive_bytes).hexdigest()
    if not hmac.compare_digest(match.group(1), digest):
        _reject('archive digest mismatch')
    return _ArtifactSnapshot(
        archive_name=expected_name,
        archive_bytes=archive_bytes,
        sidecar_bytes=sidecar_bytes,
        archive_sha256=digest,
    )


def _bounded_uncompressed_tar(archive_bytes: bytes) -> bytes:
    if (
        len(archive_bytes) < 18
        or archive_bytes[:3] != b'\x1f\x8b\x08'
        or archive_bytes[3] != 0
    ):
        _reject('noncanonical gzip header')
    gzip_mtime = int.from_bytes(archive_bytes[4:8], 'little')
    if gzip_mtime != 0 or (
        archive_bytes[8], archive_bytes[9]
    ) not in {(2, 255), (0, 3)}:
        _reject('noncanonical gzip metadata')
    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
    try:
        uncompressed = decompressor.decompress(
            archive_bytes[10:], MAX_UNCOMPRESSED_ARCHIVE_BYTES + 1
        )
    except zlib.error as error:
        raise RecoveryValidationError('invalid compressed archive') from error
    if (
        len(uncompressed) > MAX_UNCOMPRESSED_ARCHIVE_BYTES
        or not decompressor.eof
        or decompressor.unconsumed_tail
    ):
        _reject('uncompressed archive too large')
    trailer = decompressor.unused_data
    if len(trailer) != 8:
        _reject('multiple or trailing gzip data')
    expected_crc = int.from_bytes(trailer[:4], 'little')
    expected_size = int.from_bytes(trailer[4:], 'little')
    if (
        expected_crc != zlib.crc32(uncompressed) & 0xFFFFFFFF
        or expected_size != len(uncompressed) & 0xFFFFFFFF
    ):
        _reject('invalid gzip trailer')
    return uncompressed


def _canonical_member_header(member: tarfile.TarInfo) -> tuple[bytes, ...]:
    if (
        member.offset_data - member.offset != tarfile.BLOCKSIZE
        or member.pax_headers
        or member.linkname
        or member.devmajor != 0
        or member.devminor != 0
        or member.uname not in ('', 'root')
        or member.gname not in ('', 'root')
    ):
        _reject('noncanonical archive extension')
    canonical = tarfile.TarInfo(member.name)
    canonical.mode = member.mode
    canonical.uid = member.uid
    canonical.gid = member.gid
    canonical.size = member.size
    canonical.mtime = member.mtime
    canonical.type = member.type
    canonical.uname = member.uname
    canonical.gname = member.gname
    headers: list[bytes] = []
    for archive_format in (tarfile.USTAR_FORMAT, tarfile.GNU_FORMAT):
        try:
            header = canonical.tobuf(format=archive_format)
        except ValueError:
            continue
        if len(header) == tarfile.BLOCKSIZE:
            headers.append(header)
    return tuple(headers)


def _validate_raw_tar_member(
    uncompressed: bytes, member: tarfile.TarInfo
) -> None:
    header = uncompressed[
        member.offset:member.offset + tarfile.BLOCKSIZE
    ]
    if header not in _canonical_member_header(member):
        _reject('noncanonical archive header')
    data_end = member.offset_data + member.size
    padding_end = (
        member.offset_data
        + (member.size + tarfile.BLOCKSIZE - 1)
        // tarfile.BLOCKSIZE
        * tarfile.BLOCKSIZE
    )
    if any(uncompressed[data_end:padding_end]):
        _reject('noncanonical archive member padding')


def _validate_tar_termination(
    uncompressed: bytes, members: list[tarfile.TarInfo]
) -> None:
    content_end = max(
        member.offset_data
        + (
            (member.size + tarfile.BLOCKSIZE - 1)
            // tarfile.BLOCKSIZE
            * tarfile.BLOCKSIZE
        )
        for member in members
    )
    padding = uncompressed[content_end:]
    if len(padding) < 2 * tarfile.BLOCKSIZE or any(padding):
        _reject('noncanonical archive termination')


def read_exact_tar(
    archive_bytes: bytes, expected: set[str]
) -> dict[str, bytes]:
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        _reject('archive too large')
    root = _single_archive_root(expected)
    uncompressed = _bounded_uncompressed_tar(archive_bytes)
    try:
        stream = tarfile.open(fileobj=io.BytesIO(uncompressed), mode='r:')
    except tarfile.TarError as error:
        raise RecoveryValidationError('invalid tar archive') from error
    with stream:
        members = stream.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != expected | {root}:
            _reject('unsafe archive members')
        for member in members:
            _validate_raw_tar_member(uncompressed, member)
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
                if (
                    not member.isdir()
                    or member.size != 0
                    or member.mode != 0o700
                    or member.uid != 0
                    or member.gid != 0
                ):
                    _reject('unsafe archive members')
            elif (
                member.name not in expected
                or not member.isfile()
                or member.mode != 0o600
                or member.uid != 0
                or member.gid != 0
            ):
                _reject('unsafe archive members')
            elif member.size < 0 or member.size > MAX_MEMBER_BYTES:
                _reject('unsafe archive member size')
        _validate_tar_termination(uncompressed, members)
        outside_files = bytearray(uncompressed)
        for member in members:
            if member.isfile():
                outside_files[
                    member.offset_data:member.offset_data + member.size
                ] = b'\0' * member.size
        outside_upper = bytes(outside_files).upper()
        if (
            TOKEN_SHAPE.search(outside_files)
            or b'PRIVATE KEY' in outside_upper
            or b'ROOT_TOKEN' in outside_upper
            or b'ROOT-TOKEN' in outside_upper
        ):
            _reject('secret marker outside archive files')
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


def _validate_source_snapshot(
    snapshot: _ArtifactSnapshot,
    *,
    source_sha: str,
    docs_commit: str,
    docs_baseline: str,
    deviation: str,
    public_key_sha256: str,
    public_key_fingerprint: str,
    platform_secret_fingerprint: str,
) -> _SourceBundleValidation:
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
    prefix = f'openbao-recovery-{source_sha}'
    if snapshot.archive_name != prefix + '.tar.gz':
        _reject('source archive name mismatch')
    names = {
        f'{prefix}/init.json',
        f'{prefix}/metadata.json',
        f'{prefix}/openbao-recovery-public-key.b64',
        f'{prefix}/openbao-recovery-public-key.fingerprint',
    }
    files = read_exact_tar(snapshot.archive_bytes, names)
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
    return _SourceBundleValidation(
        facts=SourceBundleFacts(
            schema=V1_SCHEMA,
            archive_sha256=snapshot.archive_sha256,
            source_sha=source_sha,
            public_key_sha256=public_key_sha256,
            public_key_fingerprint=public_key_fingerprint,
            platform_secret_fingerprint=platform_secret_fingerprint,
        ),
        ciphertexts=tuple(init_document['unseal_keys_b64']),
        root_token=init_document['root_token'],
    )


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
    snapshot = _artifact_snapshot(
        archive, sidecar, f'openbao-recovery-{source_sha}.tar.gz'
    )
    return _validate_source_snapshot(
        snapshot,
        source_sha=source_sha,
        docs_commit=docs_commit,
        docs_baseline=docs_baseline,
        deviation=deviation,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=public_key_fingerprint,
        platform_secret_fingerprint=platform_secret_fingerprint,
    ).facts


def _public_key_material(
    public_key: bytes,
    fingerprint_bytes: bytes,
    *,
    expected_sha256: str | None = None,
    expected_fingerprint: str | None = None,
) -> tuple[str, str, set[bytes], set[bytes]]:
    try:
        encoded_key = public_key.decode('ascii').strip()
        fingerprint = fingerprint_bytes.decode('ascii').strip()
    except UnicodeError as error:
        raise RecoveryValidationError('invalid public key') from error
    if not encoded_key or any(character.isspace() for character in encoded_key):
        _reject('invalid public key')
    try:
        decoded_key = base64.b64decode(encoded_key, validate=True)
    except (ValueError, UnicodeError) as error:
        raise RecoveryValidationError('invalid public key') from error
    if not 128 <= len(decoded_key) <= 16384:
        _reject('invalid public key')
    public_key_sha256 = hashlib.sha256(public_key).hexdigest()
    if (
        expected_sha256 is not None
        and not hmac.compare_digest(public_key_sha256, expected_sha256)
    ):
        _reject('public key digest mismatch')
    if PUBLIC_FINGERPRINT.fullmatch(fingerprint) is None:
        _reject('public key fingerprint mismatch')
    if (
        expected_fingerprint is not None
        and not hmac.compare_digest(fingerprint, expected_fingerprint)
    ):
        _reject('public key fingerprint mismatch')
    key_ids, fingerprints = _public_key_recipients(decoded_key, fingerprint)
    return public_key_sha256, fingerprint, key_ids, fingerprints


def _safe_nonce(value: Any) -> str:
    if not isinstance(value, str) or SAFE_NONCE.fullmatch(value) is None:
        _reject('unsafe rotation nonce')
    return value


def cluster_identity_sha256(cluster_id: str, cluster_name: str) -> str:
    if (
        CLUSTER_ID.fullmatch(cluster_id) is None
        or CLUSTER_NAME.fullmatch(cluster_name) is None
    ):
        _reject('invalid cluster identity')
    canonical = json.dumps(
        {'cluster_id': cluster_id, 'cluster_name': cluster_name},
        ensure_ascii=True,
        separators=(',', ':'),
        sort_keys=True,
    ).encode('ascii')
    return hashlib.sha256(canonical).hexdigest()


def _rotation_ciphertexts(
    keys: Any,
    keys_base64: Any,
    key_ids: set[bytes],
    fingerprints: set[bytes],
) -> tuple[str, ...]:
    if (
        not isinstance(keys, list)
        or not isinstance(keys_base64, list)
        or len(keys) != 5
        or len(keys_base64) != 5
    ):
        _reject('rotation key count mismatch')
    decoded = tuple(
        _validated_ciphertext(value, key_ids, fingerprints)
        for value in keys_base64
    )
    if len(set(decoded)) != 5:
        _reject('duplicate share ciphertext')
    if any(not isinstance(value, str) for value in keys):
        _reject('ciphertext representations differ')
    try:
        decoded_hex = tuple(bytes.fromhex(value) for value in keys)
    except ValueError as error:
        raise RecoveryValidationError('ciphertext representations differ') from error
    if decoded_hex != decoded:
        _reject('ciphertext representations differ')
    return tuple(keys_base64)


def normalize_rotation_response(
    payload: bytes,
    *,
    response_kind: str,
    public_key: bytes,
    fingerprint_bytes: bytes,
    verification_nonce: str | None,
    key_shares: int,
    key_threshold: int,
) -> tuple[tuple[str, ...], str]:
    if key_shares != 5 or key_threshold != 3:
        _reject('invalid share contract')
    document = _json_document(payload)
    _, expected_fingerprint, key_ids, fingerprints = _public_key_material(
        public_key, fingerprint_bytes
    )
    if response_kind == 'direct':
        expected_fields = {
            'nonce',
            'complete',
            'keys',
            'keys_base64',
            'pgp_fingerprints',
            'backup',
            'verification_required',
            'verification_nonce',
        }
        if set(document) != expected_fields:
            _reject('unexpected rotation response field')
        if verification_nonce is not None:
            _reject('direct response nonce must not be supplied separately')
        _safe_nonce(document['nonce'])
        if (
            document['complete'] is not True
            or document['backup'] is not True
            or document['verification_required'] is not True
        ):
            _reject('rotation response incomplete')
        expected_fingerprints = document['pgp_fingerprints']
        if (
            not isinstance(expected_fingerprints, list)
            or len(expected_fingerprints) != 5
            or any(
                not isinstance(value, str)
                or not hmac.compare_digest(value, expected_fingerprint)
                for value in expected_fingerprints
            )
        ):
            _reject('PGP fingerprint mismatch')
        candidate_nonce = _safe_nonce(document['verification_nonce'])
        ciphertexts = _rotation_ciphertexts(
            document['keys'], document['keys_base64'], key_ids, fingerprints
        )
    elif response_kind == 'backup':
        expected_outer = {
            'request_id',
            'lease_id',
            'lease_duration',
            'renewable',
            'data',
            'warnings',
        }
        if set(document) != expected_outer:
            _reject('unexpected backup response field')
        if (
            document['request_id'] != ''
            or document['lease_id'] != ''
            or type(document['lease_duration']) is not int
            or document['lease_duration'] != 0
            or document['renewable'] is not False
            or document['warnings'] is not None
        ):
            _reject('unsafe backup response envelope')
        data = document['data']
        if not isinstance(data, dict) or set(data) != {
            'nonce', 'keys', 'keys_base64'
        }:
            _reject('unexpected backup response data')
        _safe_nonce(data['nonce'])
        keys = data['keys']
        keys_base64 = data['keys_base64']
        if (
            not isinstance(keys, dict)
            or not isinstance(keys_base64, dict)
            or set(keys) != {expected_fingerprint}
            or set(keys_base64) != {expected_fingerprint}
        ):
            _reject('PGP fingerprint mismatch')
        candidate_nonce = _safe_nonce(verification_nonce)
        ciphertexts = _rotation_ciphertexts(
            keys[expected_fingerprint],
            keys_base64[expected_fingerprint],
            key_ids,
            fingerprints,
        )
    else:
        _reject('unknown rotation response kind')
    if TOKEN_SHAPE.search(payload) or b'PRIVATE KEY' in payload.upper():
        _reject('plaintext secret shape detected')
    return ciphertexts, candidate_nonce


def _share_document(
    ciphertexts: tuple[str, ...],
    key_ids: set[bytes],
    fingerprints: set[bytes],
) -> tuple[dict[str, Any], dict[str, str]]:
    if len(ciphertexts) != 5:
        _reject('invalid share contract')
    decoded = tuple(
        _validated_ciphertext(value, key_ids, fingerprints)
        for value in ciphertexts
    )
    if len(set(decoded)) != 5:
        _reject('duplicate share ciphertext')
    return (
        {
            'unseal_keys_b64': list(ciphertexts),
            'unseal_shares': 5,
            'unseal_threshold': 3,
        },
        {
            f'share{index}': hashlib.sha256(value).hexdigest()
            for index, value in enumerate(decoded, start=1)
        },
    )


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=True,
            separators=(',', ':'),
            sort_keys=True,
        ).encode('ascii')
        + b'\n'
    )


def _exclusive_file(path: pathlib.Path, payload: bytes, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except OSError as error:
        raise RecoveryValidationError('artifact path already exists') from error
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise
    os.chmod(path, mode, follow_symlinks=False)


def _write_bundle(
    archive: pathlib.Path,
    sidecar: pathlib.Path,
    *,
    root: str,
    files: dict[str, bytes],
) -> None:
    if set(files) != ROTATED_FILES:
        _reject('unexpected artifact files')
    if archive.parent != sidecar.parent:
        _reject('artifact parents differ')
    directory = archive.parent / root
    for path in (directory, archive, sidecar):
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RecoveryValidationError('unsafe artifact path') from error
        _reject('artifact path already exists')
    try:
        os.mkdir(directory, 0o700)
    except OSError as error:
        raise RecoveryValidationError('artifact directory create failed') from error
    os.chmod(directory, 0o700)
    for name in (
        'shares.json',
        'metadata.json',
        'openbao-recovery-public-key.b64',
        'openbao-recovery-public-key.fingerprint',
    ):
        _exclusive_file(directory / name, files[name])
    raw_tar = io.BytesIO()
    with tarfile.open(
        fileobj=raw_tar, mode='w:', format=tarfile.USTAR_FORMAT
    ) as stream:
        root_member = tarfile.TarInfo(root)
        root_member.type = tarfile.DIRTYPE
        root_member.mode = 0o700
        root_member.uid = root_member.gid = 0
        root_member.mtime = 0
        stream.addfile(root_member)
        for name in (
            'shares.json',
            'metadata.json',
            'openbao-recovery-public-key.b64',
            'openbao-recovery-public-key.fingerprint',
        ):
            payload = files[name]
            member = tarfile.TarInfo(f'{root}/{name}')
            member.mode = 0o600
            member.uid = member.gid = 0
            member.mtime = 0
            member.size = len(payload)
            stream.addfile(member, io.BytesIO(payload))
    compressed = io.BytesIO()
    with gzip.GzipFile(
        filename='', mode='wb', fileobj=compressed, mtime=0
    ) as stream:
        stream.write(raw_tar.getvalue())
    archive_bytes = compressed.getvalue()
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        _reject('archive too large')
    _exclusive_file(archive, archive_bytes)
    digest = hashlib.sha256(archive_bytes).hexdigest()
    _exclusive_file(
        sidecar, f'{digest}  {archive.name}\n'.encode('ascii')
    )


def _rotated_bundle_files(
    archive_bytes: bytes, root: str
) -> dict[str, bytes]:
    names = {f'{root}/{name}' for name in ROTATED_FILES}
    members = read_exact_tar(archive_bytes, names)
    return {
        name: members[f'{root}/{name}']
        for name in ROTATED_FILES
    }


def _validate_utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        _reject('invalid verification timestamp')
    try:
        datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError as error:
        raise RecoveryValidationError('invalid verification timestamp') from error
    return value


def _validate_rotated_snapshot(
    snapshot: _ArtifactSnapshot,
    *,
    expected_schema: str,
    current_sha: str,
    source_sha: str,
    source_bundle_sha256: str,
    public_key_sha256: str,
    public_key_fingerprint: str,
    cluster_identity_digest: str,
) -> _RotatedBundleValidation:
    if (
        GIT_SHA.fullmatch(current_sha or '') is None
        or GIT_SHA.fullmatch(source_sha or '') is None
        or SHA256.fullmatch(source_bundle_sha256 or '') is None
        or SHA256.fullmatch(public_key_sha256 or '') is None
        or PUBLIC_FINGERPRINT.fullmatch(public_key_fingerprint or '') is None
        or SHA256.fullmatch(cluster_identity_digest or '') is None
    ):
        _reject('invalid rotated bundle expectations')
    if expected_schema == CANDIDATE_SCHEMA:
        root = f'openbao-recovery-rotation-candidate-{current_sha}'
    elif expected_schema == V2_SCHEMA:
        root = f'openbao-recovery-{current_sha}'
    else:
        _reject('unsupported rotated schema')
    expected_archive_name = root + '.tar.gz'
    if snapshot.archive_name != expected_archive_name:
        _reject('archive name mismatch')
    files = _rotated_bundle_files(snapshot.archive_bytes, root)
    actual_key_sha, actual_fingerprint, key_ids, fingerprints = (
        _public_key_material(
            files['openbao-recovery-public-key.b64'],
            files['openbao-recovery-public-key.fingerprint'],
            expected_sha256=public_key_sha256,
            expected_fingerprint=public_key_fingerprint,
        )
    )
    shares = _json_document(files['shares.json'])
    if set(shares) != {
        'unseal_keys_b64', 'unseal_shares', 'unseal_threshold'
    }:
        _reject('unexpected shares field')
    if (
        type(shares['unseal_shares']) is not int
        or shares['unseal_shares'] != 5
        or type(shares['unseal_threshold']) is not int
        or shares['unseal_threshold'] != 3
        or not isinstance(shares['unseal_keys_b64'], list)
    ):
        _reject('invalid share contract')
    share_document, share_digests = _share_document(
        tuple(shares['unseal_keys_b64']), key_ids, fingerprints
    )
    if shares != share_document:
        _reject('invalid shares document')
    metadata = _json_document(files['metadata.json'])
    common = {
        'git_commit': current_sha,
        'source_recovery_sha': source_sha,
        'source_bundle_sha256': source_bundle_sha256,
        'public_key_sha256': actual_key_sha,
        'public_key_fingerprint': actual_fingerprint,
        'cluster_identity_sha256': cluster_identity_digest,
        'key_shares': 5,
        'key_threshold': 3,
        'share_ciphertext_sha256': share_digests,
    }
    verification_nonce: str | None
    if expected_schema == CANDIDATE_SCHEMA:
        verification_nonce = _safe_nonce(metadata.get('verification_nonce'))
        expected_metadata = {
            **common,
            'schema': CANDIDATE_SCHEMA,
            'rotation_state': 'pending_verification',
            'verification_nonce': verification_nonce,
        }
    else:
        verification_nonce = None
        verified_at = _validate_utc_timestamp(
            metadata.get('rotation_verified_at_utc')
        )
        expected_metadata = {
            **common,
            'schema': V2_SCHEMA,
            'rotation_state': 'verified',
            'rotation_verified_at_utc': verified_at,
            'initial_root_token': 'revoked',
        }
    if metadata != expected_metadata:
        _reject('rotated metadata mismatch')
    combined = files['shares.json'] + files['metadata.json']
    if TOKEN_SHAPE.search(combined) or b'PRIVATE KEY' in combined.upper():
        _reject('plaintext secret shape detected')
    return _RotatedBundleValidation(
        facts=RotatedBundleFacts(
            schema=expected_schema,
            archive_sha256=snapshot.archive_sha256,
            current_sha=current_sha,
            source_sha=source_sha,
            source_bundle_sha256=source_bundle_sha256,
            public_key_sha256=actual_key_sha,
            public_key_fingerprint=actual_fingerprint,
            cluster_identity_sha256=cluster_identity_digest,
            ciphertexts=tuple(shares['unseal_keys_b64']),
            verification_nonce=verification_nonce,
        ),
        files=files,
    )


def validate_rotated_bundle(
    archive: pathlib.Path,
    sidecar: pathlib.Path,
    *,
    expected_schema: str,
    current_sha: str,
    source_sha: str,
    source_bundle_sha256: str,
    public_key_sha256: str,
    public_key_fingerprint: str,
    cluster_identity_digest: str,
    require_file_mode: bool = False,
) -> RotatedBundleFacts:
    if expected_schema == CANDIDATE_SCHEMA:
        root = f'openbao-recovery-rotation-candidate-{current_sha}'
    elif expected_schema == V2_SCHEMA:
        root = f'openbao-recovery-{current_sha}'
    else:
        _reject('unsupported rotated schema')
    snapshot = _artifact_snapshot(
        archive,
        sidecar,
        root + '.tar.gz',
        require_mode=require_file_mode,
    )
    return _validate_rotated_snapshot(
        snapshot,
        expected_schema=expected_schema,
        current_sha=current_sha,
        source_sha=source_sha,
        source_bundle_sha256=source_bundle_sha256,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=public_key_fingerprint,
        cluster_identity_digest=cluster_identity_digest,
    ).facts


def build_candidate(
    *,
    response: pathlib.Path,
    response_kind: str,
    verification_nonce: str | None,
    archive: pathlib.Path,
    sidecar: pathlib.Path,
    current_sha: str,
    source_sha: str,
    source_bundle_sha256: str,
    public_key_path: pathlib.Path,
    fingerprint_path: pathlib.Path,
    cluster_id: str,
    cluster_name: str,
    key_shares: int,
    key_threshold: int,
) -> RotatedBundleFacts:
    if (
        GIT_SHA.fullmatch(current_sha) is None
        or GIT_SHA.fullmatch(source_sha) is None
        or SHA256.fullmatch(source_bundle_sha256) is None
    ):
        _reject('invalid recovery provenance')
    public_key = public_key_path.read_bytes()
    fingerprint_bytes = fingerprint_path.read_bytes()
    public_key_sha256, fingerprint, key_ids, key_fingerprints = (
        _public_key_material(public_key, fingerprint_bytes)
    )
    payload = response.read_bytes()
    if len(payload) > MAX_MEMBER_BYTES:
        _reject('rotation response too large')
    ciphertexts, candidate_nonce = normalize_rotation_response(
        payload,
        response_kind=response_kind,
        public_key=public_key,
        fingerprint_bytes=fingerprint_bytes,
        verification_nonce=verification_nonce,
        key_shares=key_shares,
        key_threshold=key_threshold,
    )
    shares, share_digests = _share_document(
        ciphertexts, key_ids, key_fingerprints
    )
    cluster_digest = cluster_identity_sha256(cluster_id, cluster_name)
    metadata = {
        'schema': CANDIDATE_SCHEMA,
        'git_commit': current_sha,
        'source_recovery_sha': source_sha,
        'source_bundle_sha256': source_bundle_sha256,
        'public_key_sha256': public_key_sha256,
        'public_key_fingerprint': fingerprint,
        'cluster_identity_sha256': cluster_digest,
        'key_shares': 5,
        'key_threshold': 3,
        'rotation_state': 'pending_verification',
        'verification_nonce': candidate_nonce,
        'share_ciphertext_sha256': share_digests,
    }
    root = f'openbao-recovery-rotation-candidate-{current_sha}'
    if archive.name != root + '.tar.gz' or sidecar.name != archive.name + '.sha256':
        _reject('candidate output path mismatch')
    _write_bundle(
        archive,
        sidecar,
        root=root,
        files={
            'shares.json': _json_bytes(shares),
            'metadata.json': _json_bytes(metadata),
            'openbao-recovery-public-key.b64': public_key,
            'openbao-recovery-public-key.fingerprint': fingerprint_bytes,
        },
    )
    return validate_rotated_bundle(
        archive,
        sidecar,
        expected_schema=CANDIDATE_SCHEMA,
        current_sha=current_sha,
        source_sha=source_sha,
        source_bundle_sha256=source_bundle_sha256,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=fingerprint,
        cluster_identity_digest=cluster_digest,
        require_file_mode=True,
    )


def build_final(
    *,
    candidate_archive: pathlib.Path,
    candidate_sidecar: pathlib.Path,
    archive: pathlib.Path,
    sidecar: pathlib.Path,
    current_sha: str,
    source_sha: str,
    source_bundle_sha256: str,
    public_key_sha256: str,
    public_key_fingerprint: str,
    cluster_identity_digest: str,
    verified_at_utc: str,
) -> RotatedBundleFacts:
    candidate_root = f'openbao-recovery-rotation-candidate-{current_sha}'
    candidate_snapshot = _artifact_snapshot(
        candidate_archive,
        candidate_sidecar,
        candidate_root + '.tar.gz',
        require_mode=True,
    )
    candidate_validation = _validate_rotated_snapshot(
        candidate_snapshot,
        expected_schema=CANDIDATE_SCHEMA,
        current_sha=current_sha,
        source_sha=source_sha,
        source_bundle_sha256=source_bundle_sha256,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=public_key_fingerprint,
        cluster_identity_digest=cluster_identity_digest,
    )
    candidate = candidate_validation.facts
    verified_at = _validate_utc_timestamp(verified_at_utc)
    files = candidate_validation.files
    shares = _json_document(files['shares.json'])
    share_digests = _json_document(files['metadata.json'])[
        'share_ciphertext_sha256'
    ]
    metadata = {
        'schema': V2_SCHEMA,
        'git_commit': current_sha,
        'source_recovery_sha': source_sha,
        'source_bundle_sha256': source_bundle_sha256,
        'public_key_sha256': candidate.public_key_sha256,
        'public_key_fingerprint': candidate.public_key_fingerprint,
        'cluster_identity_sha256': cluster_identity_digest,
        'key_shares': 5,
        'key_threshold': 3,
        'rotation_state': 'verified',
        'rotation_verified_at_utc': verified_at,
        'initial_root_token': 'revoked',
        'share_ciphertext_sha256': share_digests,
    }
    root = f'openbao-recovery-{current_sha}'
    if archive.name != root + '.tar.gz' or sidecar.name != archive.name + '.sha256':
        _reject('final output path mismatch')
    _write_bundle(
        archive,
        sidecar,
        root=root,
        files={
            'shares.json': _json_bytes(shares),
            'metadata.json': _json_bytes(metadata),
            'openbao-recovery-public-key.b64': files[
                'openbao-recovery-public-key.b64'
            ],
            'openbao-recovery-public-key.fingerprint': files[
                'openbao-recovery-public-key.fingerprint'
            ],
        },
    )
    return validate_rotated_bundle(
        archive,
        sidecar,
        expected_schema=V2_SCHEMA,
        current_sha=current_sha,
        source_sha=source_sha,
        source_bundle_sha256=source_bundle_sha256,
        public_key_sha256=public_key_sha256,
        public_key_fingerprint=public_key_fingerprint,
        cluster_identity_digest=cluster_identity_digest,
        require_file_mode=True,
    )


def _emit_item(
    archive: pathlib.Path, sidecar: pathlib.Path, item: str
) -> str:
    candidate_match = re.fullmatch(
        r'openbao-recovery-rotation-candidate-([0-9a-f]{40})\.tar\.gz',
        archive.name,
    )
    recovery_match = re.fullmatch(
        r'openbao-recovery-([0-9a-f]{40})\.tar\.gz', archive.name
    )
    if candidate_match is None and recovery_match is None:
        _reject('unsupported archive name')
    snapshot = _artifact_snapshot(archive, sidecar, archive.name)
    if candidate_match is not None:
        current_sha = candidate_match.group(1)
        root = f'openbao-recovery-rotation-candidate-{current_sha}'
        files = _rotated_bundle_files(snapshot.archive_bytes, root)
        metadata = _json_document(files['metadata.json'])
        validation = _validate_rotated_snapshot(
            snapshot,
            expected_schema=CANDIDATE_SCHEMA,
            current_sha=current_sha,
            source_sha=metadata.get('source_recovery_sha'),
            source_bundle_sha256=metadata.get('source_bundle_sha256'),
            public_key_sha256=metadata.get('public_key_sha256'),
            public_key_fingerprint=metadata.get('public_key_fingerprint'),
            cluster_identity_digest=metadata.get('cluster_identity_sha256'),
        )
        if item == 'root':
            _reject('root item forbidden for rotated bundle')
        ciphertexts = validation.facts.ciphertexts
    elif recovery_match is not None:
        current_sha = recovery_match.group(1)
        root = f'openbao-recovery-{current_sha}'
        v1_names = {
            f'{root}/init.json',
            f'{root}/metadata.json',
            f'{root}/openbao-recovery-public-key.b64',
            f'{root}/openbao-recovery-public-key.fingerprint',
        }
        v2_names = {f'{root}/{name}' for name in ROTATED_FILES}
        try:
            files = read_exact_tar(snapshot.archive_bytes, v1_names)
            metadata = _json_document(files[f'{root}/metadata.json'])
            validation_v1 = _validate_source_snapshot(
                snapshot,
                source_sha=current_sha,
                docs_commit=metadata.get('docs_commit'),
                docs_baseline=metadata.get('docs_baseline'),
                deviation=metadata.get('deviation'),
                public_key_sha256=metadata.get('public_key_sha256'),
                public_key_fingerprint=metadata.get('public_key_fingerprint'),
                platform_secret_fingerprint=metadata.get(
                    'platform_secret_fingerprint'
                ),
            )
            if item == 'root':
                return validation_v1.root_token
            ciphertexts = validation_v1.ciphertexts
        except RecoveryValidationError as v1_error:
            try:
                files = read_exact_tar(snapshot.archive_bytes, v2_names)
                metadata = _json_document(files[f'{root}/metadata.json'])
                validation_v2 = _validate_rotated_snapshot(
                    snapshot,
                    expected_schema=V2_SCHEMA,
                    current_sha=current_sha,
                    source_sha=metadata.get('source_recovery_sha'),
                    source_bundle_sha256=metadata.get('source_bundle_sha256'),
                    public_key_sha256=metadata.get('public_key_sha256'),
                    public_key_fingerprint=metadata.get(
                        'public_key_fingerprint'
                    ),
                    cluster_identity_digest=metadata.get(
                        'cluster_identity_sha256'
                    ),
                )
            except RecoveryValidationError:
                raise v1_error
            if item == 'root':
                _reject('root item forbidden for rotated bundle')
            ciphertexts = validation_v2.facts.ciphertexts
    match = re.fullmatch(r'share([1-5])', item)
    if match is None:
        _reject('unsupported recovery item')
    return ciphertexts[int(match.group(1)) - 1]


def _add_validation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--current-sha', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--source-bundle-sha256', required=True)
    parser.add_argument('--public-key-sha256', required=True)
    parser.add_argument('--public-key-fingerprint', required=True)
    parser.add_argument('--cluster-identity-sha256', required=True)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    commands = parser.add_subparsers(dest='operation', required=True)

    candidate = commands.add_parser('build-candidate', add_help=False)
    candidate.add_argument('--response', required=True)
    candidate.add_argument('--response-kind', required=True)
    candidate.add_argument('--verification-nonce')
    candidate.add_argument('--archive', required=True)
    candidate.add_argument('--sidecar', required=True)
    candidate.add_argument('--current-sha', required=True)
    candidate.add_argument('--source-sha', required=True)
    candidate.add_argument('--source-bundle-sha256', required=True)
    candidate.add_argument('--public-key', required=True)
    candidate.add_argument('--public-key-fingerprint-file', required=True)
    candidate.add_argument('--cluster-id', required=True)
    candidate.add_argument('--cluster-name', required=True)
    candidate.add_argument('--key-shares', required=True, type=int)
    candidate.add_argument('--key-threshold', required=True, type=int)

    for operation in ('validate-candidate', 'validate-final'):
        validate = commands.add_parser(operation, add_help=False)
        validate.add_argument('--archive', required=True)
        validate.add_argument('--sidecar', required=True)
        _add_validation_arguments(validate)

    final = commands.add_parser('build-final', add_help=False)
    final.add_argument('--candidate-archive', required=True)
    final.add_argument('--candidate-sidecar', required=True)
    final.add_argument('--archive', required=True)
    final.add_argument('--sidecar', required=True)
    _add_validation_arguments(final)
    final.add_argument('--verified-at-utc', required=True)

    emit = commands.add_parser('emit-item', add_help=False)
    emit.add_argument('--archive', required=True)
    emit.add_argument('--sidecar', required=True)
    emit.add_argument('--item', required=True)

    cluster = commands.add_parser('cluster-identity-sha256', add_help=False)
    cluster.add_argument('--cluster-id', required=True)
    cluster.add_argument('--cluster-name', required=True)
    return parser


def main(arguments: list[str]) -> int:
    if arguments and arguments[0] == 'validate-source':
        if len(arguments) != 10:
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
    try:
        try:
            parsed = _argument_parser().parse_args(arguments)
        except SystemExit:
            return 2
        operation = parsed.operation
        if operation == 'build-candidate':
            build_candidate(
                response=pathlib.Path(parsed.response),
                response_kind=parsed.response_kind,
                verification_nonce=parsed.verification_nonce,
                archive=pathlib.Path(parsed.archive),
                sidecar=pathlib.Path(parsed.sidecar),
                current_sha=parsed.current_sha,
                source_sha=parsed.source_sha,
                source_bundle_sha256=parsed.source_bundle_sha256,
                public_key_path=pathlib.Path(parsed.public_key),
                fingerprint_path=pathlib.Path(
                    parsed.public_key_fingerprint_file
                ),
                cluster_id=parsed.cluster_id,
                cluster_name=parsed.cluster_name,
                key_shares=parsed.key_shares,
                key_threshold=parsed.key_threshold,
            )
        elif operation in ('validate-candidate', 'validate-final'):
            validate_rotated_bundle(
                pathlib.Path(parsed.archive),
                pathlib.Path(parsed.sidecar),
                expected_schema=(
                    CANDIDATE_SCHEMA
                    if operation == 'validate-candidate'
                    else V2_SCHEMA
                ),
                current_sha=parsed.current_sha,
                source_sha=parsed.source_sha,
                source_bundle_sha256=parsed.source_bundle_sha256,
                public_key_sha256=parsed.public_key_sha256,
                public_key_fingerprint=parsed.public_key_fingerprint,
                cluster_identity_digest=parsed.cluster_identity_sha256,
                require_file_mode=True,
            )
        elif operation == 'build-final':
            build_final(
                candidate_archive=pathlib.Path(parsed.candidate_archive),
                candidate_sidecar=pathlib.Path(parsed.candidate_sidecar),
                archive=pathlib.Path(parsed.archive),
                sidecar=pathlib.Path(parsed.sidecar),
                current_sha=parsed.current_sha,
                source_sha=parsed.source_sha,
                source_bundle_sha256=parsed.source_bundle_sha256,
                public_key_sha256=parsed.public_key_sha256,
                public_key_fingerprint=parsed.public_key_fingerprint,
                cluster_identity_digest=parsed.cluster_identity_sha256,
                verified_at_utc=parsed.verified_at_utc,
            )
        elif operation == 'emit-item':
            sys.stdout.write(
                _emit_item(
                    pathlib.Path(parsed.archive),
                    pathlib.Path(parsed.sidecar),
                    parsed.item,
                )
            )
        elif operation == 'cluster-identity-sha256':
            sys.stdout.write(
                cluster_identity_sha256(
                    parsed.cluster_id, parsed.cluster_name
                )
                + '\n'
            )
        else:
            return 2
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
