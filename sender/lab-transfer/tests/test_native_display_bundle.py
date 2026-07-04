from __future__ import annotations

import hashlib
import struct
import unittest

from tempest_lora_lab.display_contract import (
    ExactDisplayMode,
    ExactKmsSnapshot,
    PreparedScanoutBuffers,
    ValidatedDynamicDisplayArtifact,
    black_guard_xrgb8888,
    prepare_scanout_buffers,
)
from tempest_lora_lab.native_display_bundle import (
    DESIGN_BASIS_COMMIT,
    DESIGN_BASIS_TREE,
    FRAME_BYTE_SIZE,
    NATIVE_BUNDLE_MAGIC,
    NATIVE_BUNDLE_VERSION,
    BYTE_ORDER_MARKER,
    XRGB_FOURCC_BYTES,
    LINEAR_MODIFIER_BYTES,
    RECORD_KIND_GUARD,
    RECORD_KIND_DATA,
    R2E1_CONTRACT_SHA256,
    NativeDisplayBundleData,
    build_native_display_bundle,
    parse_native_display_bundle,
)
from tempest_lora_lab.pixel_renderer import DynamicRenderedPixelArtifact
from tempest_lora_lab.protocol import ProtocolError
from test_display_contract import make_artifact, make_snapshot


CHECKOUT_COMMIT = "f05f7ded6c062852a08214523edf7c991b9493b1"
CHECKOUT_TREE = "d6a6c1f0a9b495a51a2be0ca38c5c00fc9062c77"

FIXED_METADATA_SIZE = 128 + 40 + 16 + 32 + 132  # 348


def _hash_records_size(frame_count: int) -> int:
    return 40 + 4 + frame_count * 40 + 40  # 84 + frame_count * 40


def _size_records_size(frame_count: int) -> int:
    return 12 + frame_count * 12 + 12  # 24 + frame_count * 12


def _payloads_offset(frame_count: int) -> int:
    return FIXED_METADATA_SIZE + _hash_records_size(frame_count) + _size_records_size(frame_count)


def _data0_sha256_offset(frame_count: int) -> int:
    return FIXED_METADATA_SIZE + 40 + 4  # 392


def _data_i_sha256_offset(frame_count: int, i: int) -> int:
    return _data0_sha256_offset(frame_count) + i * 40 + 8  # kind(4)+ordinal(4) before sha256


def _data_i_ordinal_offset(frame_count: int, i: int) -> int:
    return _data0_sha256_offset(frame_count) + i * 40 + 4  # kind(4) before ordinal


def _data_i_kind_offset(frame_count: int, i: int) -> int:
    return _data0_sha256_offset(frame_count) + i * 40


def _guard_after_sha256_offset(frame_count: int) -> int:
    return FIXED_METADATA_SIZE + 40 + 4 + frame_count * 40 + 8  # kind(4)+ordinal(4) before sha256


def _guard_after_ordinal_offset(frame_count: int) -> int:
    return FIXED_METADATA_SIZE + 40 + 4 + frame_count * 40 + 4


def _data_i_payload_offset(frame_count: int, i: int) -> int:
    return _payloads_offset(frame_count) + FRAME_BYTE_SIZE + i * FRAME_BYTE_SIZE


def _build_bundle(frame_count: int = 1):
    artifact = make_artifact(frame_count)
    buffers = prepare_scanout_buffers(artifact)
    snapshot = make_snapshot()
    data = build_native_display_bundle(
        buffers, snapshot,
        checkout_commit=CHECKOUT_COMMIT,
        checkout_tree=CHECKOUT_TREE,
    )
    return data, buffers, snapshot


class NativeDisplayBundleTests(unittest.TestCase):
    def test_deterministic_byte_equality(self):
        data1, _, _ = _build_bundle(1)
        data2, _, _ = _build_bundle(1)
        self.assertEqual(data1, data2)

    def test_deterministic_byte_equality_sixteen_frames(self):
        data1, _, _ = _build_bundle(16)
        data2, _, _ = _build_bundle(16)
        self.assertEqual(data1, data2)

    def test_python_round_trip_one_frame(self):
        data, buffers, snapshot = _build_bundle(1)
        parsed = parse_native_display_bundle(data)
        self.assertEqual(parsed.mode, snapshot.mode)
        self.assertEqual(parsed.connector_id, snapshot.connector_id)
        self.assertEqual(parsed.crtc_id, snapshot.crtc_id)
        self.assertEqual(parsed.plane_id, snapshot.plane_id)
        self.assertEqual(parsed.guard_before_sha256, buffers.guard_black_sha256)
        self.assertEqual(parsed.guard_before_payload, buffers.guard_black_xrgb8888)
        self.assertEqual(parsed.guard_after_sha256, buffers.guard_black_sha256)
        self.assertEqual(parsed.data_frame_sha256, buffers.data_xrgb8888_sha256)
        self.assertEqual(parsed.data_payloads, buffers.data_xrgb8888)

    def test_exact_object_type_enforcement_buffers(self):
        class FakeBuffers:
            pass
        snapshot = make_snapshot()
        with self.assertRaises(ProtocolError):
            build_native_display_bundle(
                FakeBuffers(), snapshot,  # type: ignore[arg-type]
                checkout_commit=CHECKOUT_COMMIT,
                checkout_tree=CHECKOUT_TREE,
            )

    def test_exact_object_type_enforcement_snapshot(self):
        artifact = make_artifact(1)
        buffers = prepare_scanout_buffers(artifact)
        class FakeSnapshot:
            pass
        with self.assertRaises(ProtocolError):
            build_native_display_bundle(
                buffers, FakeSnapshot(),  # type: ignore[arg-type]
                checkout_commit=CHECKOUT_COMMIT,
                checkout_tree=CHECKOUT_TREE,
            )

    def test_wrong_magic(self):
        data, _, _ = _build_bundle(1)
        bad = b"BADMAGIC" + data[8:]
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bad)

    def test_wrong_version(self):
        data, _, _ = _build_bundle(1)
        bad = data[:8] + struct.pack(">I", 999) + data[12:]
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bad)

    def test_wrong_byte_order(self):
        data, _, _ = _build_bundle(1)
        bad = data[:12] + struct.pack(">I", 0x04030201) + data[16:]
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bad)

    def test_wrong_r2e1_hash(self):
        data, _, _ = _build_bundle(1)
        fake_hash = b"\x00" * 32
        bad = data[:16] + fake_hash + data[48:]
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bad)

    def test_wrong_mode_field(self):
        data, _, _ = _build_bundle(1)
        off = 128
        bad = bytearray(data)
        struct.pack_into(">I", bad, off, 148_000)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_wrong_format(self):
        data, _, _ = _build_bundle(1)
        off = 128 + 40
        bad = bytearray(data)
        bad[off:off+8] = b"XRGB0000"
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_wrong_modifier(self):
        data, _, _ = _build_bundle(1)
        off = 128 + 40 + 8
        bad = bytearray(data)
        struct.pack_into(">Q", bad, off, 1)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_invalid_format_gate_rejected(self):
        data, _, _ = _build_bundle(1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, 340, 0)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_invalid_modifier_gate_rejected(self):
        data, _, _ = _build_bundle(1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, 344, 2)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_unknown_mode_flag_bits_rejected(self):
        data, _, _ = _build_bundle(1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, 128 + 36, 3 | 0x10)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_invalid_source_geometry_rejected(self):
        data, _, _ = _build_bundle(1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, 184, 1)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_invalid_destination_geometry_rejected(self):
        data, _, _ = _build_bundle(1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, 200, 1)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_frame_count_boundaries(self):
        artifact = make_artifact(1)
        buffers = prepare_scanout_buffers(artifact)
        snapshot = make_snapshot()
        empty_data: tuple[bytes, ...] = ()
        empty_hashes: tuple[str, ...] = ()
        empty_buffers = PreparedScanoutBuffers(
            validated=buffers.validated,
            guard_black_xrgb8888=buffers.guard_black_xrgb8888,
            guard_black_sha256=buffers.guard_black_sha256,
            data_xrgb8888=empty_data,
            data_xrgb8888_sha256=empty_hashes,
        )
        with self.assertRaises(ProtocolError):
            build_native_display_bundle(
                empty_buffers, snapshot,
                checkout_commit=CHECKOUT_COMMIT,
                checkout_tree=CHECKOUT_TREE,
            )

    def test_builder_rejects_shorter_data_hash_tuple(self):
        artifact = make_artifact(2)
        buffers = prepare_scanout_buffers(artifact)
        snapshot = make_snapshot()
        short_buffers = PreparedScanoutBuffers(
            validated=buffers.validated,
            guard_black_xrgb8888=buffers.guard_black_xrgb8888,
            guard_black_sha256=buffers.guard_black_sha256,
            data_xrgb8888=buffers.data_xrgb8888,
            data_xrgb8888_sha256=(buffers.data_xrgb8888_sha256[0],),
        )
        with self.assertRaises(ProtocolError):
            build_native_display_bundle(
                short_buffers, snapshot,
                checkout_commit=CHECKOUT_COMMIT,
                checkout_tree=CHECKOUT_TREE,
            )

    def test_builder_rejects_longer_data_hash_tuple(self):
        artifact = make_artifact(2)
        buffers = prepare_scanout_buffers(artifact)
        snapshot = make_snapshot()
        hash0, hash1 = buffers.data_xrgb8888_sha256
        long_buffers = PreparedScanoutBuffers(
            validated=buffers.validated,
            guard_black_xrgb8888=buffers.guard_black_xrgb8888,
            guard_black_sha256=buffers.guard_black_sha256,
            data_xrgb8888=buffers.data_xrgb8888,
            data_xrgb8888_sha256=(hash0, hash1, hash0),
        )
        with self.assertRaises(ProtocolError):
            build_native_display_bundle(
                long_buffers, snapshot,
                checkout_commit=CHECKOUT_COMMIT,
                checkout_tree=CHECKOUT_TREE,
            )

    def test_builder_rejects_non_tuple_data_hashes(self):
        artifact = make_artifact(2)
        buffers = prepare_scanout_buffers(artifact)
        snapshot = make_snapshot()
        list_buffers = PreparedScanoutBuffers(
            validated=buffers.validated,
            guard_black_xrgb8888=buffers.guard_black_xrgb8888,
            guard_black_sha256=buffers.guard_black_sha256,
            data_xrgb8888=buffers.data_xrgb8888,
            data_xrgb8888_sha256=list(buffers.data_xrgb8888_sha256),
        )
        with self.assertRaises(ProtocolError):
            build_native_display_bundle(
                list_buffers, snapshot,
                checkout_commit=CHECKOUT_COMMIT,
                checkout_tree=CHECKOUT_TREE,
            )

    def _make_nonidentical_2frame_bundle(self):
        artifact = make_artifact(2)
        buffers = prepare_scanout_buffers(artifact)
        snapshot = make_snapshot()
        guard = buffers.guard_black_xrgb8888
        data0 = buffers.data_xrgb8888[0]
        data1 = bytearray(data0)
        data1[0:4] = b"\x01\x02\x03\xff"
        data1_b = bytes(data1)
        hash0 = buffers.data_xrgb8888_sha256[0]
        hash1 = hashlib.sha256(data1_b).hexdigest()
        diff_buffers = PreparedScanoutBuffers(
            validated=buffers.validated,
            guard_black_xrgb8888=guard,
            guard_black_sha256=buffers.guard_black_sha256,
            data_xrgb8888=(data0, data1_b),
            data_xrgb8888_sha256=(hash0, hash1),
        )
        data = build_native_display_bundle(
            diff_buffers, snapshot,
            checkout_commit=CHECKOUT_COMMIT,
            checkout_tree=CHECKOUT_TREE,
        )
        return data, diff_buffers, snapshot

    def test_two_frame_bundle(self):
        data, buffers, snapshot = _build_bundle(2)
        parsed = parse_native_display_bundle(data)
        self.assertEqual(len(parsed.data_frame_sha256), 2)
        self.assertEqual(len(parsed.data_payloads), 2)
        self.assertEqual(parsed.data_frame_sha256, buffers.data_xrgb8888_sha256)
        self.assertEqual(parsed.data_payloads, buffers.data_xrgb8888)

    def test_sixteen_frame_bundle(self):
        data, buffers, snapshot = _build_bundle(16)
        parsed = parse_native_display_bundle(data)
        self.assertEqual(len(parsed.data_frame_sha256), 16)
        self.assertEqual(len(parsed.data_payloads), 16)

    def test_checkout_identity_encoded(self):
        data, _, _ = _build_bundle(1)
        parsed = parse_native_display_bundle(data)
        self.assertEqual(parsed.current_checkout_commit, CHECKOUT_COMMIT)
        self.assertEqual(parsed.current_checkout_tree, CHECKOUT_TREE)
        self.assertEqual(parsed.design_basis_commit, DESIGN_BASIS_COMMIT)
        self.assertEqual(parsed.design_basis_tree, DESIGN_BASIS_TREE)

    def test_guard_identity_preserved(self):
        data, buffers, _ = _build_bundle(1)
        parsed = parse_native_display_bundle(data)
        self.assertEqual(parsed.guard_before_sha256, parsed.guard_after_sha256)
        self.assertEqual(parsed.guard_before_payload, parsed.guard_after_payload)

    def test_guard_after_mismatch_rejected(self):
        data, _, _ = _build_bundle(1)
        off = _guard_after_sha256_offset(1)
        bad = bytearray(data)
        bad[off:off+32] = b"\xff" * 32
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_truncated_bundle_rejected(self):
        data, _, _ = _build_bundle(1)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(data[:len(data)-1])

    def test_extended_bundle_rejected(self):
        data, _, _ = _build_bundle(1)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(data + b"EXTRA")

    def test_frame_payload_hash_mismatch(self):
        data, _, _ = _build_bundle(1)
        off = _data_i_sha256_offset(1, 0)
        bad = bytearray(data)
        bad[off:off+32] = b"\x00" * 32
        off_payload = _data_i_payload_offset(1, 0)
        bad[off_payload:off_payload+FRAME_BYTE_SIZE] = b"\x01" * FRAME_BYTE_SIZE
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_truncated_frame_hash_section_rejected(self):
        data, _, _ = _build_bundle(1)
        cut = FIXED_METADATA_SIZE + 40 + 4 + 12
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(data[:cut])

    def test_truncated_frame_size_section_rejected(self):
        data, _, _ = _build_bundle(1)
        cut = FIXED_METADATA_SIZE + _hash_records_size(1) + 8
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(data[:cut])

    def test_wrong_device_identity(self):
        snapshot = make_snapshot()
        artifact = make_artifact(1)
        buffers = prepare_scanout_buffers(artifact)
        data = build_native_display_bundle(
            buffers, snapshot,
            checkout_commit=CHECKOUT_COMMIT,
            checkout_tree=CHECKOUT_TREE,
        )
        off = 128 + 40 + 16 + 32  # 216
        bad = bytearray(data)
        bad[off:off+16] = b"invalid_id_ident"
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_identical_payloads_with_distinct_ordinals_accepted(self):
        artifact = make_artifact(2)
        buffers = prepare_scanout_buffers(artifact)
        snapshot = make_snapshot()
        guard = buffers.guard_black_xrgb8888
        data0 = buffers.data_xrgb8888[0]
        hash0 = buffers.data_xrgb8888_sha256[0]
        same_buffers = PreparedScanoutBuffers(
            validated=buffers.validated,
            guard_black_xrgb8888=guard,
            guard_black_sha256=buffers.guard_black_sha256,
            data_xrgb8888=(data0, data0),
            data_xrgb8888_sha256=(hash0, hash0),
        )
        data = build_native_display_bundle(
            same_buffers, snapshot,
            checkout_commit=CHECKOUT_COMMIT,
            checkout_tree=CHECKOUT_TREE,
        )
        parsed = parse_native_display_bundle(data)
        self.assertEqual(len(parsed.data_frame_sha256), 2)
        self.assertEqual(parsed.data_frame_sha256[0], parsed.data_frame_sha256[1])
        self.assertEqual(parsed.data_payloads[0], parsed.data_payloads[1])

    def test_duplicate_frame_ordinal_rejected(self):
        data, _, _ = self._make_nonidentical_2frame_bundle()
        fc = 2
        off = _data_i_ordinal_offset(fc, 1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, off, 0)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_reordered_frame_ordinals_rejected(self):
        data, _, _ = self._make_nonidentical_2frame_bundle()
        fc = 2
        off0 = _data_i_ordinal_offset(fc, 0)
        off1 = _data_i_ordinal_offset(fc, 1)
        bad = bytearray(data)
        ord0 = struct.unpack(">I", bad[off0:off0+4])[0]
        ord1 = struct.unpack(">I", bad[off1:off1+4])[0]
        struct.pack_into(">I", bad, off0, ord1)
        struct.pack_into(">I", bad, off1, ord0)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_wrong_guard_after_ordinal_rejected(self):
        data, _, _ = _build_bundle(1)
        off = _guard_after_ordinal_offset(1)
        bad = bytearray(data)
        struct.pack_into(">I", bad, off, 0)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_data_record_wrong_kind_rejected(self):
        data, _, _ = _build_bundle(1)
        off = _data_i_kind_offset(1, 0)
        bad = bytearray(data)
        struct.pack_into(">I", bad, off, RECORD_KIND_GUARD)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_guard_record_wrong_kind_rejected(self):
        data, _, _ = _build_bundle(1)
        fc = 1
        guard_before_kind_off = FIXED_METADATA_SIZE
        bad = bytearray(data)
        struct.pack_into(">I", bad, guard_before_kind_off, RECORD_KIND_DATA)
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_non_ascii_device_identity_rejected_as_protocol_error(self):
        snapshot = make_snapshot()
        artifact = make_artifact(1)
        buffers = prepare_scanout_buffers(artifact)
        data = build_native_display_bundle(
            buffers, snapshot,
            checkout_commit=CHECKOUT_COMMIT,
            checkout_tree=CHECKOUT_TREE,
        )
        off = 128 + 40 + 16 + 32
        bad = bytearray(data)
        bad[off:off+16] = b"226:0\x00\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_noncanonical_string_padding_rejected(self):
        data, _, _ = _build_bundle(1)
        off = 128 + 40 + 16 + 32
        bad = bytearray(data)
        bad[off+5:off+6] = b"\x01"
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_design_basis_commit_mismatch_rejected(self):
        data, _, _ = _build_bundle(1)
        off = 48
        bad = bytearray(data)
        bad[off] ^= 1
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_design_basis_tree_mismatch_rejected(self):
        data, _, _ = _build_bundle(1)
        off = 68
        bad = bytearray(data)
        bad[off] ^= 1
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_linear_modifier_big_endian(self):
        data, _, _ = _build_bundle(1)
        off = 128 + 40 + 8
        self.assertEqual(data[off:off+8], b"\x00\x00\x00\x00\x00\x00\x00\x00")

    def test_topology_token_rejects_non_ascii(self):
        data, _, _ = _build_bundle(1)
        off = 276
        bad = bytearray(data)
        bad[off+1] = 0xE9
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))

    def test_topology_token_rejects_nonzero_after_nul(self):
        data, _, _ = _build_bundle(1)
        off = 276
        bad = bytearray(data)
        bad[off+20] = 0x01
        with self.assertRaises(ProtocolError):
            parse_native_display_bundle(bytes(bad))


if __name__ == "__main__":
    unittest.main()
