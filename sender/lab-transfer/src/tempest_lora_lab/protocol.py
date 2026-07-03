from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Iterable, Sequence

PROTOCOL_MAGIC = b"TLR1"
MANIFEST_MAGIC = b"TLM1"
COMMIT_MAGIC = b"TLC1"
PROTOCOL_VERSION = 1
MAX_LORA_PAYLOAD_BYTES = 255
MAX_FIXTURE_BYTES = 65_535
SESSION_DOMAIN = b"TEMPEST-LoRa-R2C1\x00"

HEADER_STRUCT = struct.Struct(">4sBBBB16sHHIIHHII")
MANIFEST_STRUCT = struct.Struct(">4s32s32s32sHHII")
COMMIT_STRUCT = struct.Struct(">4s32s32sHIIH")

HEADER_BYTES = HEADER_STRUCT.size
MAX_FRAGMENT_PAYLOAD_BYTES = MAX_LORA_PAYLOAD_BYTES - HEADER_BYTES
MAX_FRAGMENT_COUNT = math.ceil(MAX_FIXTURE_BYTES / MAX_FRAGMENT_PAYLOAD_BYTES)


class ProtocolError(RuntimeError):
    """Raised when a frame or transfer violates the v1 fail-closed contract."""


class FrameType(IntEnum):
    MANIFEST = 1
    DATA = 2
    COMMIT = 3


class ProfileId(IntEnum):
    CAPTURE_REPLAY = 1
    DYNAMIC_SOFTWARE_PHY = 2


@dataclass(frozen=True)
class Frame:
    frame_type: FrameType
    profile_id: ProfileId
    session_id: bytes
    sequence: int
    fragment_count: int
    total_size: int
    fragment_offset: int
    payload: bytes


@dataclass(frozen=True)
class ManifestPayload:
    fixture_id: str
    input_sha256: bytes
    profile_descriptor_sha256: bytes
    fragment_count: int
    total_size: int


@dataclass(frozen=True)
class CommitPayload:
    input_sha256: bytes
    manifest_sha256: bytes
    fragment_count: int
    total_size: int
    reassembled_size: int


@dataclass(frozen=True)
class ReassembledTransfer:
    fixture_id: str
    session_id_hex: str
    content: bytes
    sha256: str


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ProtocolError("value is not canonical JSON data") from exc


def sha256_bytes(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def crc32_ieee(value: bytes) -> int:
    return zlib.crc32(value) & 0xFFFFFFFF


def _validate_sha256(value: bytes, label: str) -> None:
    if type(value) is not bytes or len(value) != 32:
        raise ProtocolError(f"{label} must be 32 bytes")


def _validate_plain_int(value: int, label: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError(f"{label} outside permitted integer range")


def _validated_dynamic_profile_bytes(value: dict[str, Any]) -> bytes:
    if type(value) is not dict:
        raise ProtocolError("dynamic profile descriptor must be an object")
    from .profiles import dynamic_profile_descriptor as expected_descriptor

    candidate = canonical_json_bytes(value)
    expected = canonical_json_bytes(expected_descriptor())
    if candidate != expected:
        raise ProtocolError("dynamic profile descriptor differs from R2C.1 v1")
    return candidate


def _encode_fixture_id(fixture_id: str) -> bytes:
    if type(fixture_id) is not str or not 1 <= len(fixture_id) <= 32:
        raise ProtocolError("fixture_id length must be 1..32")
    try:
        encoded = fixture_id.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProtocolError("fixture_id must be ASCII") from exc
    if any(not (byte in b"._-" or 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122) for byte in encoded):
        raise ProtocolError("fixture_id contains a forbidden character")
    return encoded.ljust(32, b"\x00")


def _decode_fixture_id(value: bytes) -> str:
    raw = value.rstrip(b"\x00")
    try:
        decoded = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError("fixture_id is not ASCII") from exc
    if _encode_fixture_id(decoded).rstrip(b"\x00") != raw:
        raise ProtocolError("fixture_id is not canonical")
    return decoded


def build_frame(
    *,
    frame_type: FrameType,
    profile_id: ProfileId,
    session_id: bytes,
    sequence: int,
    fragment_count: int,
    total_size: int,
    fragment_offset: int,
    payload: bytes,
) -> bytes:
    if isinstance(frame_type, bool) or isinstance(profile_id, bool):
        raise ProtocolError("frame type and profile must not be boolean")
    try:
        frame_type = FrameType(frame_type)
        profile_id = ProfileId(profile_id)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("unknown frame type or profile") from exc
    if type(session_id) is not bytes or len(session_id) != 16:
        raise ProtocolError("session_id must be 16 bytes")
    _validate_plain_int(sequence, "sequence", 0, 0xFFFF)
    _validate_plain_int(fragment_count, "fragment_count", 1, MAX_FRAGMENT_COUNT)
    _validate_plain_int(total_size, "total_size", 1, MAX_FIXTURE_BYTES)
    _validate_plain_int(fragment_offset, "fragment_offset", 0, total_size)
    if type(payload) is not bytes:
        raise ProtocolError("payload must be bytes")
    if len(payload) > MAX_FRAGMENT_PAYLOAD_BYTES:
        raise ProtocolError("payload exceeds v1 frame capacity")

    payload_crc = crc32_ieee(payload)
    zero_crc_header = HEADER_STRUCT.pack(
        PROTOCOL_MAGIC,
        PROTOCOL_VERSION,
        int(frame_type),
        int(profile_id),
        0,
        session_id,
        sequence,
        fragment_count,
        total_size,
        fragment_offset,
        len(payload),
        0,
        payload_crc,
        0,
    )
    header_crc = crc32_ieee(zero_crc_header)
    header = HEADER_STRUCT.pack(
        PROTOCOL_MAGIC,
        PROTOCOL_VERSION,
        int(frame_type),
        int(profile_id),
        0,
        session_id,
        sequence,
        fragment_count,
        total_size,
        fragment_offset,
        len(payload),
        0,
        payload_crc,
        header_crc,
    )
    frame = header + payload
    if len(frame) > MAX_LORA_PAYLOAD_BYTES:
        raise ProtocolError("constructed frame exceeds LoRa payload limit")
    return frame


def parse_frame(frame: bytes) -> Frame:
    if type(frame) is not bytes:
        raise ProtocolError("frame must be bytes")
    if len(frame) < HEADER_BYTES:
        raise ProtocolError("truncated frame header")
    (
        magic,
        version,
        raw_frame_type,
        raw_profile_id,
        flags,
        session_id,
        sequence,
        fragment_count,
        total_size,
        fragment_offset,
        payload_length,
        reserved,
        payload_crc,
        header_crc,
    ) = HEADER_STRUCT.unpack(frame[:HEADER_BYTES])

    if magic != PROTOCOL_MAGIC:
        raise ProtocolError("invalid protocol magic")
    if version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    try:
        frame_type = FrameType(raw_frame_type)
        profile_id = ProfileId(raw_profile_id)
    except ValueError as exc:
        raise ProtocolError("unknown frame type or profile") from exc
    if flags != 0 or reserved != 0:
        raise ProtocolError("nonzero flags or reserved field")
    _validate_plain_int(fragment_count, "fragment_count", 1, MAX_FRAGMENT_COUNT)
    _validate_plain_int(total_size, "total_size", 1, MAX_FIXTURE_BYTES)
    if not 0 <= fragment_offset <= total_size:
        raise ProtocolError("fragment_offset outside transfer")
    if payload_length > MAX_FRAGMENT_PAYLOAD_BYTES:
        raise ProtocolError("payload length exceeds v1 capacity")
    if len(frame) != HEADER_BYTES + payload_length:
        raise ProtocolError("frame length mismatch")

    payload = frame[HEADER_BYTES:]
    if crc32_ieee(payload) != payload_crc:
        raise ProtocolError("payload CRC32 mismatch")
    zero_crc_header = HEADER_STRUCT.pack(
        magic,
        version,
        raw_frame_type,
        raw_profile_id,
        flags,
        session_id,
        sequence,
        fragment_count,
        total_size,
        fragment_offset,
        payload_length,
        reserved,
        payload_crc,
        0,
    )
    if crc32_ieee(zero_crc_header) != header_crc:
        raise ProtocolError("header CRC32 mismatch")

    return Frame(
        frame_type=frame_type,
        profile_id=profile_id,
        session_id=session_id,
        sequence=sequence,
        fragment_count=fragment_count,
        total_size=total_size,
        fragment_offset=fragment_offset,
        payload=payload,
    )


def build_manifest_payload(
    *,
    fixture_id: str,
    input_sha256: bytes,
    profile_descriptor_sha256: bytes,
    fragment_count: int,
    total_size: int,
) -> bytes:
    _validate_sha256(input_sha256, "input_sha256")
    _validate_sha256(profile_descriptor_sha256, "profile_descriptor_sha256")
    _validate_plain_int(fragment_count, "fragment_count", 1, MAX_FRAGMENT_COUNT)
    _validate_plain_int(total_size, "total_size", 1, MAX_FIXTURE_BYTES)
    return MANIFEST_STRUCT.pack(
        MANIFEST_MAGIC,
        _encode_fixture_id(fixture_id),
        input_sha256,
        profile_descriptor_sha256,
        MAX_FRAGMENT_PAYLOAD_BYTES,
        fragment_count,
        total_size,
        0,
    )


def parse_manifest_payload(payload: bytes) -> ManifestPayload:
    if type(payload) is not bytes:
        raise ProtocolError("manifest payload must be bytes")
    if len(payload) != MANIFEST_STRUCT.size:
        raise ProtocolError("manifest payload size mismatch")
    (
        magic,
        fixture_id,
        input_sha256,
        profile_hash,
        fragment_payload_size,
        fragment_count,
        total_size,
        flags,
    ) = MANIFEST_STRUCT.unpack(payload)
    if magic != MANIFEST_MAGIC:
        raise ProtocolError("manifest magic mismatch")
    if flags != 0:
        raise ProtocolError("manifest flags must be zero")
    if fragment_payload_size != MAX_FRAGMENT_PAYLOAD_BYTES:
        raise ProtocolError("fragment payload size mismatch")
    if not 1 <= fragment_count <= MAX_FRAGMENT_COUNT:
        raise ProtocolError("manifest fragment_count outside v1 range")
    if not 1 <= total_size <= MAX_FIXTURE_BYTES:
        raise ProtocolError("manifest total_size outside v1 range")
    return ManifestPayload(
        fixture_id=_decode_fixture_id(fixture_id),
        input_sha256=input_sha256,
        profile_descriptor_sha256=profile_hash,
        fragment_count=fragment_count,
        total_size=total_size,
    )


def build_commit_payload(
    *,
    input_sha256: bytes,
    manifest_sha256: bytes,
    fragment_count: int,
    total_size: int,
) -> bytes:
    _validate_sha256(input_sha256, "input_sha256")
    _validate_sha256(manifest_sha256, "manifest_sha256")
    _validate_plain_int(fragment_count, "fragment_count", 1, MAX_FRAGMENT_COUNT)
    _validate_plain_int(total_size, "total_size", 1, MAX_FIXTURE_BYTES)
    return COMMIT_STRUCT.pack(
        COMMIT_MAGIC,
        input_sha256,
        manifest_sha256,
        fragment_count,
        total_size,
        total_size,
        0,
    )


def parse_commit_payload(payload: bytes) -> CommitPayload:
    if type(payload) is not bytes:
        raise ProtocolError("commit payload must be bytes")
    if len(payload) != COMMIT_STRUCT.size:
        raise ProtocolError("commit payload size mismatch")
    (
        magic,
        input_sha256,
        manifest_sha256,
        fragment_count,
        total_size,
        reassembled_size,
        reserved,
    ) = COMMIT_STRUCT.unpack(payload)
    if magic != COMMIT_MAGIC:
        raise ProtocolError("commit magic mismatch")
    if reserved != 0:
        raise ProtocolError("commit reserved field must be zero")
    if not 1 <= fragment_count <= MAX_FRAGMENT_COUNT:
        raise ProtocolError("commit fragment_count outside v1 range")
    if not 1 <= total_size <= MAX_FIXTURE_BYTES:
        raise ProtocolError("commit total_size outside v1 range")
    return CommitPayload(
        input_sha256=input_sha256,
        manifest_sha256=manifest_sha256,
        fragment_count=fragment_count,
        total_size=total_size,
        reassembled_size=reassembled_size,
    )


def build_transfer_frames(
    *,
    fixture_id: str,
    content: bytes,
    dynamic_profile_descriptor: dict[str, Any],
) -> tuple[bytes, ...]:
    if type(content) is not bytes:
        raise ProtocolError("fixture content must be bytes")
    if not 1 <= len(content) <= MAX_FIXTURE_BYTES:
        raise ProtocolError("fixture size outside v1 bounds")
    profile_descriptor_bytes = _validated_dynamic_profile_bytes(
        dynamic_profile_descriptor
    )
    fragment_count = math.ceil(len(content) / MAX_FRAGMENT_PAYLOAD_BYTES)
    input_hash = sha256_bytes(content)
    profile_hash = sha256_bytes(profile_descriptor_bytes)
    manifest_payload = build_manifest_payload(
        fixture_id=fixture_id,
        input_sha256=input_hash,
        profile_descriptor_sha256=profile_hash,
        fragment_count=fragment_count,
        total_size=len(content),
    )
    session_id = sha256_bytes(SESSION_DOMAIN + manifest_payload)[:16]
    frames: list[bytes] = [
        build_frame(
            frame_type=FrameType.MANIFEST,
            profile_id=ProfileId.DYNAMIC_SOFTWARE_PHY,
            session_id=session_id,
            sequence=0,
            fragment_count=fragment_count,
            total_size=len(content),
            fragment_offset=0,
            payload=manifest_payload,
        )
    ]
    for index in range(fragment_count):
        offset = index * MAX_FRAGMENT_PAYLOAD_BYTES
        fragment = content[offset:offset + MAX_FRAGMENT_PAYLOAD_BYTES]
        frames.append(
            build_frame(
                frame_type=FrameType.DATA,
                profile_id=ProfileId.DYNAMIC_SOFTWARE_PHY,
                session_id=session_id,
                sequence=index + 1,
                fragment_count=fragment_count,
                total_size=len(content),
                fragment_offset=offset,
                payload=fragment,
            )
        )
    commit_payload = build_commit_payload(
        input_sha256=input_hash,
        manifest_sha256=sha256_bytes(manifest_payload),
        fragment_count=fragment_count,
        total_size=len(content),
    )
    frames.append(
        build_frame(
            frame_type=FrameType.COMMIT,
            profile_id=ProfileId.DYNAMIC_SOFTWARE_PHY,
            session_id=session_id,
            sequence=fragment_count + 1,
            fragment_count=fragment_count,
            total_size=len(content),
            fragment_offset=len(content),
            payload=commit_payload,
        )
    )
    return tuple(frames)


def reassemble_transfer(
    frames: Iterable[bytes],
    dynamic_profile_descriptor: dict[str, Any],
) -> ReassembledTransfer:
    profile_descriptor_bytes = _validated_dynamic_profile_bytes(
        dynamic_profile_descriptor
    )
    try:
        parsed = [parse_frame(frame) for frame in frames]
    except TypeError as exc:
        raise ProtocolError("frames must be an iterable of bytes") from exc
    if not parsed:
        raise ProtocolError("empty session")
    by_sequence: dict[int, Frame] = {}
    for frame in parsed:
        if frame.sequence in by_sequence:
            raise ProtocolError("duplicate sequence")
        by_sequence[frame.sequence] = frame
    manifest_frame = by_sequence.get(0)
    if manifest_frame is None or manifest_frame.frame_type is not FrameType.MANIFEST:
        raise ProtocolError("manifest frame missing or misplaced")
    if manifest_frame.profile_id is not ProfileId.DYNAMIC_SOFTWARE_PHY:
        raise ProtocolError("capture profile is not transport capable")
    manifest = parse_manifest_payload(manifest_frame.payload)
    if manifest_frame.fragment_count != manifest.fragment_count:
        raise ProtocolError("manifest frame fragment_count mismatch")
    if manifest_frame.total_size != manifest.total_size:
        raise ProtocolError("manifest frame total_size mismatch")
    if manifest_frame.fragment_offset != 0:
        raise ProtocolError("manifest frame offset must be zero")
    expected_sequences = set(range(manifest.fragment_count + 2))
    if set(by_sequence) != expected_sequences:
        raise ProtocolError("missing or unexpected sequence")
    expected_profile_hash = sha256_bytes(profile_descriptor_bytes)
    if manifest.profile_descriptor_sha256 != expected_profile_hash:
        raise ProtocolError("profile descriptor hash mismatch")
    expected_session = sha256_bytes(SESSION_DOMAIN + manifest_frame.payload)[:16]
    if manifest_frame.session_id != expected_session:
        raise ProtocolError("session ID derivation mismatch")

    fragments: list[bytes] = []
    for index in range(manifest.fragment_count):
        frame = by_sequence[index + 1]
        if frame.frame_type is not FrameType.DATA:
            raise ProtocolError("non-data frame in data sequence")
        if frame.profile_id is not ProfileId.DYNAMIC_SOFTWARE_PHY:
            raise ProtocolError("profile mismatch")
        if frame.session_id != expected_session:
            raise ProtocolError("session mismatch")
        if frame.fragment_count != manifest.fragment_count or frame.total_size != manifest.total_size:
            raise ProtocolError("transfer metadata mismatch")
        expected_offset = index * MAX_FRAGMENT_PAYLOAD_BYTES
        if frame.fragment_offset != expected_offset:
            raise ProtocolError("fragment offset mismatch")
        expected_length = min(MAX_FRAGMENT_PAYLOAD_BYTES, manifest.total_size - expected_offset)
        if len(frame.payload) != expected_length:
            raise ProtocolError("fragment length mismatch")
        fragments.append(frame.payload)

    content = b"".join(fragments)
    if len(content) != manifest.total_size:
        raise ProtocolError("reassembled size mismatch")
    content_hash = sha256_bytes(content)
    if content_hash != manifest.input_sha256:
        raise ProtocolError("final SHA-256 differs from manifest")

    commit_frame = by_sequence[manifest.fragment_count + 1]
    if commit_frame.frame_type is not FrameType.COMMIT:
        raise ProtocolError("final sequence is not commit")
    if commit_frame.profile_id is not ProfileId.DYNAMIC_SOFTWARE_PHY:
        raise ProtocolError("commit profile mismatch")
    if commit_frame.session_id != expected_session:
        raise ProtocolError("commit session mismatch")
    if commit_frame.fragment_offset != manifest.total_size:
        raise ProtocolError("commit offset mismatch")
    if commit_frame.fragment_count != manifest.fragment_count or commit_frame.total_size != manifest.total_size:
        raise ProtocolError("commit frame metadata mismatch")
    commit = parse_commit_payload(commit_frame.payload)
    if commit.input_sha256 != content_hash:
        raise ProtocolError("commit input SHA-256 mismatch")
    if commit.manifest_sha256 != sha256_bytes(manifest_frame.payload):
        raise ProtocolError("commit manifest SHA-256 mismatch")
    if commit.fragment_count != manifest.fragment_count:
        raise ProtocolError("commit fragment_count mismatch")
    if commit.total_size != manifest.total_size or commit.reassembled_size != manifest.total_size:
        raise ProtocolError("commit size mismatch")

    return ReassembledTransfer(
        fixture_id=manifest.fixture_id,
        session_id_hex=expected_session.hex(),
        content=content,
        sha256=content_hash.hex(),
    )
