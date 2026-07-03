from __future__ import annotations

import hashlib
import unittest

from tempest_lora_lab.profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    capture_profile_descriptor,
    dynamic_profile_descriptor,
    normalize_capture_symbols,
    normalize_dynamic_symbols,
)
from tempest_lora_lab.protocol import ProfileId, ProtocolError


class ProfileTests(unittest.TestCase):
    def test_profile_transport_boundary(self) -> None:
        self.assertFalse(capture_profile_descriptor()["transport_capable"])
        self.assertTrue(dynamic_profile_descriptor()["transport_capable"])
        self.assertEqual(dynamic_profile_descriptor()["symbol_output"]["index_base"], 0)

    def test_capture_and_dynamic_normalize_to_same_canonical_symbols(self) -> None:
        fixture_hash = hashlib.sha256(b"fixture").hexdigest()
        payload_hash = hashlib.sha256(b"payload").hexdigest()
        capture = normalize_capture_symbols(
            symbols_one_based=[1, 14, 128],
            spreading_factor=7,
            approved_fixture=True,
            fixture_sha256=fixture_hash,
        )
        dynamic = normalize_dynamic_symbols(
            symbols_zero_based=[0, 13, 127],
            parameters=DynamicPhyParameters(),
            payload_sha256=payload_hash,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        self.assertEqual(capture.profile_id, ProfileId.CAPTURE_REPLAY)
        self.assertEqual(dynamic.profile_id, ProfileId.DYNAMIC_SOFTWARE_PHY)
        self.assertEqual(capture.symbols, dynamic.symbols)
        self.assertEqual(capture.symbols_sha256_uint16be, dynamic.symbols_sha256_uint16be)

    def test_capture_rejects_unapproved_or_out_of_domain_source(self) -> None:
        digest = hashlib.sha256(b"fixture").hexdigest()
        with self.assertRaises(ProtocolError):
            normalize_capture_symbols(
                symbols_one_based=[1],
                spreading_factor=7,
                approved_fixture=False,
                fixture_sha256=digest,
            )
        with self.assertRaises(ProtocolError):
            normalize_capture_symbols(
                symbols_one_based=[0, 1],
                spreading_factor=7,
                approved_fixture=True,
                fixture_sha256=digest,
            )

    def test_dynamic_rejects_wrong_provenance_parameters_and_domain(self) -> None:
        digest = hashlib.sha256(b"payload").hexdigest()
        with self.assertRaises(ProtocolError):
            normalize_dynamic_symbols(
                symbols_zero_based=[0],
                parameters=DynamicPhyParameters(),
                payload_sha256=digest,
                oracle_commit="0" * 40,
                oracle_tree=PINNED_ORACLE_TREE,
            )
        with self.assertRaises(ProtocolError):
            normalize_dynamic_symbols(
                symbols_zero_based=[128],
                parameters=DynamicPhyParameters(),
                payload_sha256=digest,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
            )
        with self.assertRaises(ProtocolError):
            DynamicPhyParameters(payload_crc=False).validate()

    def test_boolean_symbols_are_rejected(self) -> None:
        fixture_hash = hashlib.sha256(b"fixture").hexdigest()
        payload_hash = hashlib.sha256(b"payload").hexdigest()
        with self.assertRaises(ProtocolError):
            normalize_capture_symbols(
                symbols_one_based=[True],
                spreading_factor=7,
                approved_fixture=True,
                fixture_sha256=fixture_hash,
            )
        with self.assertRaises(ProtocolError):
            normalize_dynamic_symbols(
                symbols_zero_based=[False],
                parameters=DynamicPhyParameters(),
                payload_sha256=payload_hash,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
            )

    def test_capture_approval_must_be_boolean_true(self) -> None:
        digest = hashlib.sha256(b"fixture").hexdigest()
        with self.assertRaises(ProtocolError):
            normalize_capture_symbols(
                symbols_one_based=[1],
                spreading_factor=7,
                approved_fixture=1,
                fixture_sha256=digest,
            )

    def test_dynamic_parameter_types_are_strict(self) -> None:
        with self.assertRaises(ProtocolError):
            DynamicPhyParameters(frequency_hz=915_000_000.0).validate()
        with self.assertRaises(ProtocolError):
            DynamicPhyParameters(coding_rate_value=True).validate()


if __name__ == "__main__":
    unittest.main()
