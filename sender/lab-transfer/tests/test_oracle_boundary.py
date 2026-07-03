from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tempest_lora_lab.oracle_boundary import OracleRequest, load_and_validate_result, write_request
from tempest_lora_lab.profiles import PINNED_ORACLE_COMMIT, PINNED_ORACLE_TREE, normalize_dynamic_symbols
from tempest_lora_lab.protocol import ProtocolError


class OracleBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = OracleRequest.from_payload(b"ABC")
        self.symbols = [13, 9, 1, 13, 61, 109, 49, 97]
        envelope = normalize_dynamic_symbols(
            symbols_zero_based=self.symbols,
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        self.result = {
            "schema": "tempest-lora.oracle-result.v1",
            "request_id": self.request.request_id,
            "payload_sha256": self.request.payload_sha256,
            "parameters_sha256": self.request.parameters_sha256,
            "oracle_commit": PINNED_ORACLE_COMMIT,
            "oracle_tree": PINNED_ORACLE_TREE,
            "index_base": 0,
            "symbol_count": len(self.symbols),
            "symbols": self.symbols,
            "symbols_sha256_uint16be": envelope.symbols_sha256_uint16be,
        }

    def test_request_is_deterministic_and_exclusive_write(self) -> None:
        self.assertEqual(self.request, OracleRequest.from_payload(b"ABC"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            write_request(path, self.request)
            self.assertEqual(json.loads(path.read_text(encoding="ascii")), self.request.to_dict())
            with self.assertRaises(ProtocolError):
                write_request(path, self.request)

    def test_valid_result_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(self.result), encoding="ascii")
            envelope = load_and_validate_result(path, self.request)
            self.assertEqual(list(envelope.symbols), self.symbols)

    def test_wrong_provenance_hash_count_and_index_base_are_rejected(self) -> None:
        mutations = [
            {"oracle_tree": "0" * 40},
            {"payload_sha256": "0" * 64},
            {"symbol_count": len(self.symbols) + 1},
            {"index_base": 1},
            {"symbols_sha256_uint16be": "0" * 64},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                candidate = dict(self.result)
                candidate.update(mutation)
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "result.json"
                    path.write_text(json.dumps(candidate), encoding="ascii")
                    with self.assertRaises(ProtocolError):
                        load_and_validate_result(path, self.request)

    def test_symlink_result_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text(json.dumps(self.result), encoding="ascii")
            link = root / "result.json"
            link.symlink_to(target)
            with self.assertRaises(ProtocolError):
                load_and_validate_result(link, self.request)

    def test_partial_writes_are_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            real_write = os.write

            def partial_write(fd, data):
                return real_write(fd, bytes(data[:7]))

            with patch("tempest_lora_lab.oracle_boundary.os.write", side_effect=partial_write):
                write_request(path, self.request)
            self.assertEqual(json.loads(path.read_text(encoding="ascii")), self.request.to_dict())

    def test_zero_progress_write_is_rejected_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            with patch("tempest_lora_lab.oracle_boundary.os.write", return_value=0):
                with self.assertRaises(ProtocolError):
                    write_request(path, self.request)
            self.assertFalse(path.exists())

    def test_boolean_result_metadata_is_rejected(self) -> None:
        one_symbol = [13]
        envelope = normalize_dynamic_symbols(
            symbols_zero_based=one_symbol,
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        candidate = dict(self.result)
        candidate.update(
            {
                "index_base": False,
                "symbol_count": True,
                "symbols": one_symbol,
                "symbols_sha256_uint16be": envelope.symbols_sha256_uint16be,
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(candidate), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_result(path, self.request)

    def test_result_mutation_during_read_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(json.dumps(self.result), encoding="ascii")
            real_read = os.read
            touched = False

            def mutating_read(fd, size):
                nonlocal touched
                chunk = real_read(fd, size)
                if chunk and not touched:
                    touched = True
                    current = path.stat()
                    os.utime(
                        path,
                        ns=(current.st_atime_ns, current.st_mtime_ns + 1_000_000_000),
                    )
                return chunk

            with patch("tempest_lora_lab.oracle_boundary.os.read", side_effect=mutating_read):
                with self.assertRaises(ProtocolError):
                    load_and_validate_result(path, self.request)


if __name__ == "__main__":
    unittest.main()
