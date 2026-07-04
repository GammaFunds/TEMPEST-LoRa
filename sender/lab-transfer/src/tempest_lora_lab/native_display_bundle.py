from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from typing import Any

from .display_contract import (
    R2E1_CONTRACT_SHA256,
    XRGB8888_FOURCC,
    LINEAR_MODIFIER,
    ExactDisplayMode,
    ExactKmsSnapshot,
    PreparedScanoutBuffers,
)
from .protocol import ProtocolError

NATIVE_BUNDLE_MAGIC = b"TLORABND"
NATIVE_BUNDLE_VERSION = 1
BYTE_ORDER_MARKER = 0x01020304
FRAME_BYTE_SIZE = 1920 * 1080 * 4  # 8294400
XRGB_FOURCC_BYTES = b"XRGB8888"
LINEAR_MODIFIER_BYTES = struct.pack(">Q", 0)

DESIGN_BASIS_COMMIT = "f05f7ded6c062852a08214523edf7c991b9493b1"
DESIGN_BASIS_TREE = "d6a6c1f0a9b495a51a2be0ca38c5c00fc9062c77"

DEVICE_ID_RE = re.compile(r"^[0-9]+:[0-9]+$")

RECORD_KIND_GUARD = 0
RECORD_KIND_DATA = 1


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_type(value: Any, expected_type: type, label: str) -> None:
    if type(value) is not expected_type:
        raise ProtocolError(f"{label} must be exact {expected_type.__name__}")


def _require_sha256(value: str, label: str) -> None:
    if type(value) is not str or len(value) != 64 or not all(c in "0123456789abcdef" for c in value):
        raise ProtocolError(f"{label} must be lowercase SHA-256 hex")


def _require_hex40(value: str, label: str) -> None:
    if type(value) is not str or len(value) != 40 or not all(c in "0123456789abcdef" for c in value):
        raise ProtocolError(f"{label} must be lowercase 40-char hex")


def _pack_str_fixed(value: str, size: int) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > size:
        raise ProtocolError(f"string too long for fixed field ({len(encoded)} > {size})")
    return encoded.ljust(size, b"\x00")


def _unpack_str_fixed(data: bytes, offset: int, size: int) -> str:
    raw = data[offset : offset + size]
    if len(raw) != size:
        raise ProtocolError("truncated fixed string field")
    null_pos = raw.find(b"\x00")
    if null_pos >= 0:
        trailing = raw[null_pos + 1:]
        if any(b != 0 for b in trailing):
            raise ProtocolError("nonzero bytes after NUL in fixed string")
        raw = raw[:null_pos]
    if not raw:
        raise ProtocolError("empty fixed string field")
    if any(b >= 128 for b in raw):
        raise ProtocolError("non-ASCII bytes in fixed string")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        raise ProtocolError("non-ASCII bytes in fixed string")


def _pack_sha256(value: str) -> bytes:
    _require_sha256(value, "sha256")
    return bytes.fromhex(value)


def _unpack_sha256(data: bytes, offset: int) -> str:
    raw = data[offset : offset + 32]
    if len(raw) != 32:
        raise ProtocolError("truncated SHA-256 field")
    return raw.hex()


def _pack_sha1(value: str) -> bytes:
    _require_hex40(value, "sha1")
    return bytes.fromhex(value)


def _unpack_sha1(data: bytes, offset: int) -> str:
    raw = data[offset : offset + 20]
    if len(raw) != 20:
        raise ProtocolError("truncated SHA-1 field")
    return raw.hex()


def _check_remaining(data: bytes, offset: int, needed: int, label: str) -> None:
    if offset + needed > len(data):
        raise ProtocolError(f"truncated bundle at {label}: need {needed} bytes at offset {offset}, have {len(data) - offset}")


def _read_u32_checked(data: bytes, offset: int, label: str) -> int:
    _check_remaining(data, offset, 4, label)
    return struct.unpack(">I", data[offset:offset+4])[0]


@dataclass(frozen=True)
class NativeDisplayBundleData:
    r2e1_contract_sha256: str
    design_basis_commit: str
    design_basis_tree: str
    current_checkout_commit: str
    current_checkout_tree: str
    mode: ExactDisplayMode
    fourcc: str
    modifier: str
    src_rect: tuple[int, int, int, int]
    dst_rect: tuple[int, int, int, int]
    device_identity: str
    connector_id: int
    crtc_id: int
    plane_id: int
    edid_sha256: str
    topology_token: str
    format_gate: str
    modifier_gate: str
    guard_before_sha256: str
    guard_before_payload: bytes
    data_frame_sha256: tuple[str, ...]
    data_payloads: tuple[bytes, ...]
    guard_after_sha256: str
    guard_after_payload: bytes


HEADER_SIZE = 128
MODE_SIZE = 40
FORMAT_SIZE = 16
GEOMETRY_SIZE = 32
IDENTITY_SIZE = 132
FIXED_METADATA = HEADER_SIZE + MODE_SIZE + FORMAT_SIZE + GEOMETRY_SIZE + IDENTITY_SIZE  # 348


def _make_frame_hash_records(
    guard_before_sha256: str,
    data_sha256s: tuple[str, ...],
    guard_after_sha256: str,
) -> bytes:
    parts: list[bytes] = []
    parts.append(struct.pack(">I", RECORD_KIND_GUARD))
    parts.append(struct.pack(">I", 0))
    parts.append(_pack_sha256(guard_before_sha256))
    parts.append(struct.pack(">I", len(data_sha256s)))
    for i, h in enumerate(data_sha256s):
        parts.append(struct.pack(">I", RECORD_KIND_DATA))
        parts.append(struct.pack(">I", i))
        parts.append(_pack_sha256(h))
    parts.append(struct.pack(">I", RECORD_KIND_GUARD))
    parts.append(struct.pack(">I", len(data_sha256s)))
    parts.append(_pack_sha256(guard_after_sha256))
    return b"".join(parts)


def _make_frame_size_records(frame_count: int) -> bytes:
    parts: list[bytes] = []
    parts.append(struct.pack(">I", RECORD_KIND_GUARD))
    parts.append(struct.pack(">I", 0))
    parts.append(struct.pack(">I", FRAME_BYTE_SIZE))
    for i in range(frame_count):
        parts.append(struct.pack(">I", RECORD_KIND_DATA))
        parts.append(struct.pack(">I", i))
        parts.append(struct.pack(">I", FRAME_BYTE_SIZE))
    parts.append(struct.pack(">I", RECORD_KIND_GUARD))
    parts.append(struct.pack(">I", frame_count))
    parts.append(struct.pack(">I", FRAME_BYTE_SIZE))
    return b"".join(parts)


def _parse_frame_hash_records(data: bytes, offset: int) -> tuple[int, str, list[str], str, list[int]]:
    guard_before_kind = _read_u32_checked(data, offset, "guard_before_hash.kind")
    offset += 4
    if guard_before_kind != RECORD_KIND_GUARD:
        raise ProtocolError("guard-before record must have GUARD kind")
    guard_before_ordinal = _read_u32_checked(data, offset, "guard_before_hash.ordinal")
    offset += 4
    if guard_before_ordinal != 0:
        raise ProtocolError("guard-before ordinal must be 0")
    guard_before_sha256 = _unpack_sha256(data, offset)
    offset += 32

    frame_count = _read_u32_checked(data, offset, "frame_count")
    offset += 4
    if not 1 <= frame_count <= 16:
        raise ProtocolError(f"frame_count {frame_count} outside 1..16")

    seen_ordinals: set[int] = set()
    data_sha256s: list[str] = []
    for i in range(frame_count):
        kind = _read_u32_checked(data, offset, f"data_hash_record[{i}].kind")
        offset += 4
        if kind != RECORD_KIND_DATA:
            raise ProtocolError(f"data record {i} must have DATA kind")
        ordinal = _read_u32_checked(data, offset, f"data_hash_record[{i}].ordinal")
        offset += 4
        if ordinal != i:
            raise ProtocolError(f"data record ordinal mismatch: expected {i}, got {ordinal}")
        if ordinal in seen_ordinals:
            raise ProtocolError(f"duplicate data ordinal {ordinal}")
        seen_ordinals.add(ordinal)
        h = _unpack_sha256(data, offset)
        offset += 32
        data_sha256s.append(h)

    guard_after_kind = _read_u32_checked(data, offset, "guard_after_hash.kind")
    offset += 4
    if guard_after_kind != RECORD_KIND_GUARD:
        raise ProtocolError("guard-after record must have GUARD kind")
    guard_after_ordinal = _read_u32_checked(data, offset, "guard_after_hash.ordinal")
    offset += 4
    if guard_after_ordinal != frame_count:
        raise ProtocolError(f"guard-after ordinal must be {frame_count}, got {guard_after_ordinal}")
    guard_after_sha256 = _unpack_sha256(data, offset)
    offset += 32

    return offset, guard_before_sha256, data_sha256s, guard_after_sha256, [frame_count]


def _parse_frame_size_records(data: bytes, offset: int, frame_count: int) -> int:
    kind = _read_u32_checked(data, offset, "guard_before_size.kind")
    offset += 4
    if kind != RECORD_KIND_GUARD:
        raise ProtocolError("guard-before size record must have GUARD kind")
    ordinal = _read_u32_checked(data, offset, "guard_before_size.ordinal")
    offset += 4
    if ordinal != 0:
        raise ProtocolError("guard-before size ordinal must be 0")
    guard_before_size = _read_u32_checked(data, offset, "guard_before_size.size")
    offset += 4
    if guard_before_size != FRAME_BYTE_SIZE:
        raise ProtocolError(f"guard_before_byte_size {guard_before_size} != {FRAME_BYTE_SIZE}")

    seen_ordinals: set[int] = set()
    for i in range(frame_count):
        kind = _read_u32_checked(data, offset, f"data_size_record[{i}].kind")
        offset += 4
        if kind != RECORD_KIND_DATA:
            raise ProtocolError(f"data size record {i} must have DATA kind")
        ordinal = _read_u32_checked(data, offset, f"data_size_record[{i}].ordinal")
        offset += 4
        if ordinal != i:
            raise ProtocolError(f"data size ordinal mismatch: expected {i}, got {ordinal}")
        if ordinal in seen_ordinals:
            raise ProtocolError(f"duplicate data size ordinal {ordinal}")
        seen_ordinals.add(ordinal)
        size = _read_u32_checked(data, offset, f"data_size_record[{i}].size")
        offset += 4
        if size != FRAME_BYTE_SIZE:
            raise ProtocolError(f"data_frame_byte_size[{i}] {size} != {FRAME_BYTE_SIZE}")

    kind = _read_u32_checked(data, offset, "guard_after_size.kind")
    offset += 4
    if kind != RECORD_KIND_GUARD:
        raise ProtocolError("guard-after size record must have GUARD kind")
    ordinal = _read_u32_checked(data, offset, "guard_after_size.ordinal")
    offset += 4
    if ordinal != frame_count:
        raise ProtocolError(f"guard-after size ordinal must be {frame_count}, got {ordinal}")
    guard_after_size = _read_u32_checked(data, offset, "guard_after_size.size")
    offset += 4
    if guard_after_size != FRAME_BYTE_SIZE:
        raise ProtocolError(f"guard_after_byte_size {guard_after_size} != {FRAME_BYTE_SIZE}")

    return offset


def build_native_display_bundle(
    buffers: PreparedScanoutBuffers,
    snapshot: ExactKmsSnapshot,
    *,
    checkout_commit: str,
    checkout_tree: str,
) -> bytes:
    _require_type(buffers, PreparedScanoutBuffers, "buffers")
    _require_type(snapshot, ExactKmsSnapshot, "snapshot")

    snapshot.validate()
    mode = snapshot.mode

    frame_count = len(buffers.data_xrgb8888)
    if not 1 <= frame_count <= 16:
        raise ProtocolError(f"frame_count {frame_count} outside 1..16")

    guard_before = buffers.guard_black_xrgb8888
    guard_after = buffers.guard_black_xrgb8888
    data_sha256s = buffers.data_xrgb8888_sha256
    if type(data_sha256s) is not tuple:
        raise ProtocolError("data_xrgb8888_sha256 must be exact tuple")
    if len(data_sha256s) != frame_count:
        raise ProtocolError(
            f"data_xrgb8888_sha256 length {len(data_sha256s)} != frame_count {frame_count}"
        )

    if type(guard_before) is not bytes or len(guard_before) != FRAME_BYTE_SIZE:
        raise ProtocolError("guard_before must be exact 8294400-byte XRGB8888 frame")
    guard_before_sha256 = _sha256(guard_before)
    if guard_before_sha256 != buffers.guard_black_sha256:
        raise ProtocolError("guard_before SHA-256 mismatch")

    for i, frame in enumerate(buffers.data_xrgb8888):
        if type(frame) is not bytes or len(frame) != FRAME_BYTE_SIZE:
            raise ProtocolError(f"data frame {i} must be exact 8294400-byte XRGB8888 frame")
        expected = data_sha256s[i]
        if _sha256(frame) != expected:
            raise ProtocolError(f"data frame {i} SHA-256 mismatch")

    guard_after_sha256 = buffers.guard_black_sha256
    if type(guard_after) is not bytes or len(guard_after) != FRAME_BYTE_SIZE:
        raise ProtocolError("guard_after must be exact 8294400-byte XRGB8888 frame")

    _require_hex40(checkout_commit, "checkout_commit")
    _require_hex40(checkout_tree, "checkout_tree")

    parts: list[bytes] = []

    # Header
    parts.append(NATIVE_BUNDLE_MAGIC)
    parts.append(struct.pack(">I", NATIVE_BUNDLE_VERSION))
    parts.append(struct.pack(">I", BYTE_ORDER_MARKER))
    parts.append(_pack_sha256(R2E1_CONTRACT_SHA256))
    parts.append(_pack_sha1(DESIGN_BASIS_COMMIT))
    parts.append(_pack_sha1(DESIGN_BASIS_TREE))
    parts.append(_pack_sha1(checkout_commit))
    parts.append(_pack_sha1(checkout_tree))

    # Mode
    parts.append(struct.pack(">IIIIIIIIII",
        mode.clock_khz,
        mode.hdisplay,
        mode.hsync_start,
        mode.hsync_end,
        mode.htotal,
        mode.vdisplay,
        mode.vsync_start,
        mode.vsync_end,
        mode.vtotal,
        (1 if mode.positive_hsync else 0) |
        (2 if mode.positive_vsync else 0) |
        (4 if mode.interlaced else 0) |
        (8 if mode.doublescan else 0),
    ))

    # Format
    parts.append(XRGB_FOURCC_BYTES)
    parts.append(LINEAR_MODIFIER_BYTES)

    # Geometry
    parts.append(struct.pack(">IIIIIIII",
        snapshot.src_rect_16_16[0],
        snapshot.src_rect_16_16[1],
        snapshot.src_rect_16_16[2],
        snapshot.src_rect_16_16[3],
        snapshot.dst_rect[0],
        snapshot.dst_rect[1],
        snapshot.dst_rect[2],
        snapshot.dst_rect[3],
    ))

    # Identity
    parts.append(_pack_str_fixed(snapshot.device_identity, 16))
    parts.append(struct.pack(">I", snapshot.connector_id))
    parts.append(struct.pack(">I", snapshot.crtc_id))
    parts.append(struct.pack(">I", snapshot.plane_id))
    parts.append(_pack_sha256(snapshot.edid_sha256))
    parts.append(_pack_str_fixed(snapshot.topology_token, 64))
    parts.append(struct.pack(">I", 1))  # format_gate: XRGB8888 present
    parts.append(struct.pack(">I", 1))  # modifier_gate: LINEAR present

    # Frame hash records (with kind and ordinal)
    parts.append(_make_frame_hash_records(
        buffers.guard_black_sha256,
        buffers.data_xrgb8888_sha256,
        guard_after_sha256,
    ))

    # Frame size records (with kind and ordinal)
    parts.append(_make_frame_size_records(frame_count))

    # Frame payloads
    parts.append(guard_before)
    for frame in buffers.data_xrgb8888:
        parts.append(frame)
    parts.append(guard_after)

    return b"".join(parts)


def parse_native_display_bundle(data: bytes) -> NativeDisplayBundleData:
    _require_type(data, bytes, "bundle data")

    offset = 0

    # Header
    _check_remaining(data, offset, 128, "header")
    magic = data[offset:offset+8]
    offset += 8
    if magic != NATIVE_BUNDLE_MAGIC:
        raise ProtocolError(
            f"bad magic: expected {NATIVE_BUNDLE_MAGIC!r}, got {magic!r}"
        )

    version = struct.unpack(">I", data[offset:offset+4])[0]
    offset += 4
    if version != NATIVE_BUNDLE_VERSION:
        raise ProtocolError(f"bad version: expected {NATIVE_BUNDLE_VERSION}, got {version}")

    bom = struct.unpack(">I", data[offset:offset+4])[0]
    offset += 4
    if bom != BYTE_ORDER_MARKER:
        raise ProtocolError(f"bad byte order marker: expected 0x{BYTE_ORDER_MARKER:08x}, got 0x{bom:08x}")

    r2e1_hash = _unpack_sha256(data, offset); offset += 32
    if r2e1_hash != R2E1_CONTRACT_SHA256:
        raise ProtocolError(f"R2E.1 contract SHA-256 mismatch: expected {R2E1_CONTRACT_SHA256}, got {r2e1_hash}")

    design_basis_commit = _unpack_sha1(data, offset); offset += 20
    design_basis_tree = _unpack_sha1(data, offset); offset += 20
    current_commit = _unpack_sha1(data, offset); offset += 20
    current_tree = _unpack_sha1(data, offset); offset += 20

    if design_basis_commit != DESIGN_BASIS_COMMIT:
        raise ProtocolError(f"design_basis_commit mismatch: expected {DESIGN_BASIS_COMMIT}, got {design_basis_commit}")
    if design_basis_tree != DESIGN_BASIS_TREE:
        raise ProtocolError(f"design_basis_tree mismatch: expected {DESIGN_BASIS_TREE}, got {design_basis_tree}")

    # Mode
    _check_remaining(data, offset, 40, "mode")
    mode_values = struct.unpack(">IIIIIIIIII", data[offset:offset+40])
    offset += 40
    clock_khz, hdisplay, hsync_start, hsync_end, htotal, vdisplay, vsync_start, vsync_end, vtotal, mode_flags = mode_values
    if mode_flags != 3:
        raise ProtocolError(f"mode flags must be exactly positive HSync | positive VSync, got {mode_flags}")
    mode = ExactDisplayMode(
        clock_khz=clock_khz,
        hdisplay=hdisplay,
        hsync_start=hsync_start,
        hsync_end=hsync_end,
        htotal=htotal,
        vdisplay=vdisplay,
        vsync_start=vsync_start,
        vsync_end=vsync_end,
        vtotal=vtotal,
        positive_hsync=bool(mode_flags & 1),
        positive_vsync=bool(mode_flags & 2),
        interlaced=bool(mode_flags & 4),
        doublescan=bool(mode_flags & 8),
    )
    mode.validate()

    # Format
    _check_remaining(data, offset, 16, "format")
    fourcc = data[offset:offset+8]; offset += 8
    if fourcc != XRGB_FOURCC_BYTES:
        fourcc_str = fourcc.rstrip(b"\x00").decode("ascii", errors="replace")
        raise ProtocolError(f"expected XRGB8888 fourcc, got {fourcc_str!r}")
    modifier_val = struct.unpack(">Q", data[offset:offset+8])[0]
    offset += 8
    if modifier_val != 0:
        raise ProtocolError(f"expected LINEAR modifier (0), got {modifier_val}")

    # Geometry
    _check_remaining(data, offset, 32, "geometry")
    gx, gy, gw, gh, dx, dy, dw, dh = struct.unpack(">IIIIIIII", data[offset:offset+32])
    offset += 32
    src_rect = (gx, gy, gw, gh)
    dst_rect = (dx, dy, dw, dh)
    if src_rect != (0, 0, 1920 << 16, 1080 << 16):
        raise ProtocolError(f"src_rect must be exact identity geometry, got {src_rect}")
    if dst_rect != (0, 0, 1920, 1080):
        raise ProtocolError(f"dst_rect must be exact identity geometry, got {dst_rect}")

    # Identity
    _check_remaining(data, offset, 132, "identity")
    device_identity = _unpack_str_fixed(data, offset, 16); offset += 16
    connector_id = struct.unpack(">I", data[offset:offset+4])[0]; offset += 4
    crtc_id = struct.unpack(">I", data[offset:offset+4])[0]; offset += 4
    plane_id = struct.unpack(">I", data[offset:offset+4])[0]; offset += 4
    edid_sha256 = _unpack_sha256(data, offset); offset += 32
    topology_token = _unpack_str_fixed(data, offset, 64); offset += 64
    fmt_gate = struct.unpack(">I", data[offset:offset+4])[0]; offset += 4
    mod_gate = struct.unpack(">I", data[offset:offset+4])[0]; offset += 4

    # Validate identity values
    if connector_id <= 0:
        raise ProtocolError(f"connector_id must be positive, got {connector_id}")
    if crtc_id <= 0:
        raise ProtocolError(f"crtc_id must be positive, got {crtc_id}")
    if plane_id <= 0:
        raise ProtocolError(f"plane_id must be positive, got {plane_id}")
    if not device_identity or not device_identity.isascii() or DEVICE_ID_RE.fullmatch(device_identity) is None:
        raise ProtocolError(f"device_identity must be numeric ID format, got {device_identity!r}")
    if fmt_gate != 1:
        raise ProtocolError(f"format_gate must be 1, got {fmt_gate}")
    if mod_gate != 1:
        raise ProtocolError(f"modifier_gate must be 1, got {mod_gate}")

    # Frame hash records
    offset, guard_before_sha256, data_frame_sha256, guard_after_sha256, _ = _parse_frame_hash_records(data, offset)
    frame_count = len(data_frame_sha256)

    # Frame size records
    offset = _parse_frame_size_records(data, offset, frame_count)

    # Frame payloads
    payloads_needed = (frame_count + 2) * FRAME_BYTE_SIZE
    _check_remaining(data, offset, payloads_needed, "frame_payloads")
    guard_before_payload = data[offset:offset+FRAME_BYTE_SIZE]; offset += FRAME_BYTE_SIZE
    if _sha256(guard_before_payload) != guard_before_sha256:
        raise ProtocolError("guard before payload SHA-256 mismatch")

    data_payloads: list[bytes] = []
    for i in range(frame_count):
        payload = data[offset:offset+FRAME_BYTE_SIZE]; offset += FRAME_BYTE_SIZE
        if _sha256(payload) != data_frame_sha256[i]:
            raise ProtocolError(f"data frame {i} payload SHA-256 mismatch")
        data_payloads.append(payload)

    guard_after_payload = data[offset:offset+FRAME_BYTE_SIZE]; offset += FRAME_BYTE_SIZE
    if _sha256(guard_after_payload) != guard_after_sha256:
        raise ProtocolError("guard after payload SHA-256 mismatch")

    # Check for trailing data
    if offset != len(data):
        raise ProtocolError(f"unexpected trailing data: {len(data) - offset} extra bytes")

    # Map gates to strings
    # Guard-after must match guard-before
    if guard_after_sha256 != guard_before_sha256:
        raise ProtocolError("guard after SHA-256 must match guard before")

    return NativeDisplayBundleData(
        r2e1_contract_sha256=r2e1_hash,
        design_basis_commit=design_basis_commit,
        design_basis_tree=design_basis_tree,
        current_checkout_commit=current_commit,
        current_checkout_tree=current_tree,
        mode=mode,
        fourcc=XRGB8888_FOURCC,
        modifier=LINEAR_MODIFIER,
        src_rect=src_rect,
        dst_rect=dst_rect,
        device_identity=device_identity,
        connector_id=connector_id,
        crtc_id=crtc_id,
        plane_id=plane_id,
        edid_sha256=edid_sha256,
        topology_token=topology_token,
        format_gate=XRGB8888_FOURCC,
        modifier_gate=LINEAR_MODIFIER,
        guard_before_sha256=guard_before_sha256,
        guard_before_payload=guard_before_payload,
        data_frame_sha256=tuple(data_frame_sha256),
        data_payloads=tuple(data_payloads),
        guard_after_sha256=guard_after_sha256,
        guard_after_payload=guard_after_payload,
    )
