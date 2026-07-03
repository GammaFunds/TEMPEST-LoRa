from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tempest_lora_lab.oracle_boundary import (
    OracleRequest,
    load_and_validate_request,
    load_and_validate_result,
    write_request,
    write_result,
)
from tempest_lora_lab.profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    normalize_dynamic_symbols,
)
from tempest_lora_lab.protocol import ProfileId, ProtocolError


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


class LoadRequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload_bytes = b"ABC"
        self.params = DynamicPhyParameters()
        self.request = OracleRequest.from_payload(self.payload_bytes, self.params)
        self.valid_json = json.dumps(self.request.to_dict(), sort_keys=True, indent=2, ensure_ascii=True) + "\n"

    def test_load_and_validate_request_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(self.valid_json, encoding="ascii")
            loaded = load_and_validate_request(path)
            self.assertEqual(loaded, self.request)

    def test_load_and_validate_request_extra_field_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["extra"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_missing_field_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        del doc["payload_hex"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_malformed_json_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text("{invalid}", encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_non_ascii_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text('{"a": "\u00e9"}', encoding="utf-8")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_relative_path_rejected(self) -> None:
        relative = Path("relative.json")
        with self.assertRaises(ProtocolError):
            load_and_validate_request(relative)

    def test_fake_posixpath_class_rejected(self) -> None:
        FakePosixPath = type(
            "PosixPath",
            (),
            {
                "is_absolute": lambda self: True,
                "resolve": lambda self, strict=True: self,
            },
        )
        with self.assertRaises(ProtocolError):
            load_and_validate_request(FakePosixPath())

    def test_load_and_validate_request_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text(self.valid_json, encoding="ascii")
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaises(ProtocolError):
                load_and_validate_request(link)

    def test_load_and_validate_request_uppercase_hex_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["payload_hex"] = "ABCDEF"  # uppercase hex values containing a-f
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_odd_hex_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["payload_hex"] = "414"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_empty_hex_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["payload_hex"] = ""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_excessive_payload_rejected(self) -> None:
        big = bytes(256)
        doc = dict(self.request.to_dict())
        doc["payload_hex"] = big.hex()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_boolean_parameter_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        params = dict(doc["parameters"])
        params["spreading_factor"] = True
        doc["parameters"] = params
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_wrong_request_id_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["request_id"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_duplicate_top_level_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            doc = self.request.to_dict()
            items = []
            for key, value in doc.items():
                items.append(f"{json.dumps(key)}:{json.dumps(value)}")
                if key == "request_id":
                    items.append(f"{json.dumps(key)}:{json.dumps(value)}")
            path.write_text("{" + ",".join(items) + "}", encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_duplicate_nested_parameter_key_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            text = self.valid_json
            needle = '"frequency_hz": 915000000'
            replacement = needle + ',\n    ' + needle
            path.write_text(text.replace(needle, replacement, 1), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_whitespace_hex_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["payload_hex"] = "41 42 43"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_nonhex_characters_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["payload_hex"] = "4142gz"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_missing_parameter_field_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        params = dict(doc["parameters"])
        del params["ldro"]
        doc["parameters"] = params
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_extra_parameter_field_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        params = dict(doc["parameters"])
        params["extra_param"] = 0
        doc["parameters"] = params
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_wrong_parameters_sha256_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        doc["parameters_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_wrong_requested_output_value_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        ro = dict(doc["requested_output"])
        ro["kind"] = "wrong-value"
        doc["requested_output"] = ro
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_index_base_false_rejected(self) -> None:
        doc = dict(self.request.to_dict())
        ro = dict(doc["requested_output"])
        ro["index_base"] = False
        doc["requested_output"] = ro
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(json.dumps(doc), encoding="ascii")
            with self.assertRaises(ProtocolError):
                load_and_validate_request(path)

    def test_load_and_validate_request_mutation_during_read_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            path.write_text(self.valid_json, encoding="ascii")
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
                    load_and_validate_request(path)


class WriteResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = OracleRequest.from_payload(b"ABC")
        self.symbols = [13, 9, 1, 13, 61, 109, 49, 97]
        self.envelope = normalize_dynamic_symbols(
            symbols_zero_based=self.symbols,
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )

    def test_write_result_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_result(path, self.request, self.envelope)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual(loaded["request_id"], self.request.request_id)
            self.assertEqual(loaded["symbol_count"], len(self.symbols))

    def test_write_result_existing_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text("{}", encoding="ascii")
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, self.envelope)

    def test_write_result_wrong_profile_rejected(self) -> None:
        from tempest_lora_lab.profiles import SymbolEnvelope as SE
        good = normalize_dynamic_symbols(
            symbols_zero_based=[0],
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        bad = SE(
            profile_id=ProfileId.CAPTURE_REPLAY,
            source_kind=good.source_kind,
            spreading_factor=good.spreading_factor,
            index_base=good.index_base,
            ingress_transform=good.ingress_transform,
            symbols=good.symbols,
            symbols_sha256_uint16be=good.symbols_sha256_uint16be,
            provenance=good.provenance,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, bad)

    def test_write_result_wrong_payload_hash_rejected(self) -> None:
        bad = normalize_dynamic_symbols(
            symbols_zero_based=[0],
            parameters=self.request.parameters,
            payload_sha256="0" * 64,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, bad)

    def test_write_result_zero_progress_write_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with patch("tempest_lora_lab.oracle_boundary.os.write", return_value=0):
                with self.assertRaises(ProtocolError):
                    write_result(path, self.request, self.envelope)
            self.assertFalse(path.exists())

    def test_write_result_partial_writes_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            real_write = os.write

            def partial_write(fd, data):
                return real_write(fd, bytes(data[:5]))

            with patch("tempest_lora_lab.oracle_boundary.os.write", side_effect=partial_write):
                write_result(path, self.request, self.envelope)
            loaded = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual(loaded["request_id"], self.request.request_id)

    def test_write_result_preserves_existing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text('{"existing": true}', encoding="ascii")
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, self.envelope)
            self.assertEqual(json.loads(path.read_text(encoding="ascii")), {"existing": True})

    def test_write_result_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a.json"
            second = Path(directory) / "b.json"
            write_result(first, self.request, self.envelope)
            write_result(second, self.request, self.envelope)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_write_result_mode_0600(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_result(path, self.request, self.envelope)
            st_mode = path.stat(follow_symlinks=False).st_mode
            self.assertEqual(st_mode & 0o777, 0o600)

    def test_write_result_symlink_destination_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            link = root / "link.json"
            link.symlink_to(target)
            with self.assertRaises(ProtocolError):
                write_result(link, self.request, self.envelope)

    def test_write_result_path_identity_mutation_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            real_link = os.link

            def replacing_link(src, dst, *args, **kwargs):
                real_link(src, dst, *args, **kwargs)
                Path(dst).unlink()
                Path(dst).write_text("replacement", encoding="ascii")

            with patch(
                "tempest_lora_lab.oracle_boundary.os.link",
                side_effect=replacing_link,
            ):
                with self.assertRaises(ProtocolError):
                    write_result(path, self.request, self.envelope)
            self.assertEqual(path.read_text(encoding="ascii"), "replacement")

    def test_write_result_wrong_source_kind_rejected(self) -> None:
        from tempest_lora_lab.profiles import SymbolEnvelope as SE
        bad = normalize_dynamic_symbols(
            symbols_zero_based=[0],
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        bad_with_source = SE(
            profile_id=bad.profile_id,
            source_kind="wrong-source",
            spreading_factor=bad.spreading_factor,
            index_base=bad.index_base,
            ingress_transform=bad.ingress_transform,
            symbols=bad.symbols,
            symbols_sha256_uint16be=bad.symbols_sha256_uint16be,
            provenance=bad.provenance,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, bad_with_source)

    def test_write_result_wrong_spreading_factor_rejected(self) -> None:
        from tempest_lora_lab.profiles import SymbolEnvelope as SE
        bad = normalize_dynamic_symbols(
            symbols_zero_based=[0],
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        bad_with_sf = SE(
            profile_id=bad.profile_id,
            source_kind=bad.source_kind,
            spreading_factor=8,
            index_base=bad.index_base,
            ingress_transform=bad.ingress_transform,
            symbols=bad.symbols,
            symbols_sha256_uint16be=bad.symbols_sha256_uint16be,
            provenance=bad.provenance,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, bad_with_sf)

    def test_write_result_wrong_index_base_rejected(self) -> None:
        from tempest_lora_lab.profiles import SymbolEnvelope as SE
        bad = normalize_dynamic_symbols(
            symbols_zero_based=[0],
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        bad_with_ib = SE(
            profile_id=bad.profile_id,
            source_kind=bad.source_kind,
            spreading_factor=bad.spreading_factor,
            index_base=1,
            ingress_transform=bad.ingress_transform,
            symbols=bad.symbols,
            symbols_sha256_uint16be=bad.symbols_sha256_uint16be,
            provenance=bad.provenance,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, bad_with_ib)

    def test_write_result_wrong_ingress_transform_rejected(self) -> None:
        from tempest_lora_lab.profiles import SymbolEnvelope as SE
        bad = normalize_dynamic_symbols(
            symbols_zero_based=[0],
            parameters=self.request.parameters,
            payload_sha256=self.request.payload_sha256,
            oracle_commit=PINNED_ORACLE_COMMIT,
            oracle_tree=PINNED_ORACLE_TREE,
        )
        bad_with_it = SE(
            profile_id=bad.profile_id,
            source_kind=bad.source_kind,
            spreading_factor=bad.spreading_factor,
            index_base=bad.index_base,
            ingress_transform="stored_Index - 1",
            symbols=bad.symbols,
            symbols_sha256_uint16be=bad.symbols_sha256_uint16be,
            provenance=bad.provenance,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with self.assertRaises(ProtocolError):
                write_result(path, self.request, bad_with_it)

    def test_write_result_replacement_path_preserved_on_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"

            def occupied_link(src, dst, *args, **kwargs):
                Path(dst).write_text("replacement", encoding="ascii")
                raise FileExistsError("occupied")

            with patch(
                "tempest_lora_lab.oracle_boundary.os.link",
                side_effect=occupied_link,
            ):
                with self.assertRaises(ProtocolError):
                    write_result(path, self.request, self.envelope)
            self.assertEqual(path.read_text(encoding="ascii"), "replacement")

    def test_write_result_float_spreading_factor_rejected(self) -> None:
        from tempest_lora_lab.profiles import SymbolEnvelope
        bad = SymbolEnvelope(
            profile_id=self.envelope.profile_id,
            source_kind=self.envelope.source_kind,
            spreading_factor=7.0,
            index_base=self.envelope.index_base,
            ingress_transform=self.envelope.ingress_transform,
            symbols=self.envelope.symbols,
            symbols_sha256_uint16be=self.envelope.symbols_sha256_uint16be,
            provenance=self.envelope.provenance,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ProtocolError):
                write_result(Path(directory) / "result.json", self.request, bad)

    def test_result_loader_rejects_noncanonical_request(self) -> None:
        from dataclasses import replace
        bad_request = replace(self.request, payload_sha256="0" * 64)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_result(path, self.request, self.envelope)
            with self.assertRaises(ProtocolError):
                load_and_validate_result(path, bad_request)

    def test_write_result_validates_via_load_and_validate_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            write_result(path, self.request, self.envelope)
            envelope = load_and_validate_result(path, self.request)
            self.assertEqual(envelope, self.envelope)


if __name__ == "__main__":
    unittest.main()
