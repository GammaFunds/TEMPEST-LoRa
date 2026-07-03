from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tempest_lora_lab.input_policy import read_synthetic_fixture
from tempest_lora_lab.protocol import MAX_FIXTURE_BYTES, ProtocolError


class InputPolicyTests(unittest.TestCase):
    def test_explicit_regular_fixture_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "fixture.bin"
            path.write_bytes(b"synthetic")
            fixture = read_synthetic_fixture(path, fixture_id="fixture-1", required_root=root)
            self.assertEqual(fixture.content, b"synthetic")
            self.assertEqual(fixture.size, 9)

    def test_outside_root_symlink_empty_and_oversized_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside_directory:
            root = Path(directory).resolve()
            outside = Path(outside_directory).resolve() / "outside.bin"
            outside.write_bytes(b"x")
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(outside, fixture_id="outside", required_root=root)

            link = root / "link.bin"
            link.symlink_to(outside)
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(link, fixture_id="link", required_root=root)

            empty = root / "empty.bin"
            empty.write_bytes(b"")
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(empty, fixture_id="empty", required_root=root)

            oversized = root / "oversized.bin"
            oversized.write_bytes(b"x" * (MAX_FIXTURE_BYTES + 1))
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(oversized, fixture_id="oversized", required_root=root)

    def test_lexical_parent_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "input"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            target = outside / "fixture.bin"
            target.write_bytes(b"outside")
            escaped = root / ".." / "outside" / "fixture.bin"
            self.assertTrue(escaped.exists())
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(escaped, fixture_id="escape", required_root=root)

    def test_file_replacement_between_stat_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "fixture.bin"
            path.write_bytes(b"first123")
            real_open = os.open
            replaced = False

            def replacing_open(target, flags, *args):
                nonlocal replaced
                if Path(target) == path and not replaced:
                    replaced = True
                    path.unlink()
                    path.write_bytes(b"second12")
                return real_open(target, flags, *args)

            with patch("tempest_lora_lab.input_policy.os.open", side_effect=replacing_open):
                with self.assertRaises(ProtocolError):
                    read_synthetic_fixture(path, fixture_id="race", required_root=root)

    def test_symlinked_required_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            real_root = base / "real"
            real_root.mkdir()
            path = real_root / "fixture.bin"
            path.write_bytes(b"fixture")
            linked_root = base / "linked"
            linked_root.symlink_to(real_root, target_is_directory=True)
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(
                    linked_root / "fixture.bin",
                    fixture_id="linked-root",
                    required_root=linked_root,
                )

    def test_same_inode_content_change_between_stat_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "fixture.bin"
            path.write_bytes(b"first123")
            real_open = os.open
            changed = False

            def changing_open(target, flags, *args):
                nonlocal changed
                if Path(target) == path and not changed:
                    changed = True
                    path.write_bytes(b"second12")
                return real_open(target, flags, *args)

            with patch("tempest_lora_lab.input_policy.os.open", side_effect=changing_open):
                with self.assertRaises(ProtocolError):
                    read_synthetic_fixture(path, fixture_id="same-inode", required_root=root)

    def test_invalid_fixture_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "fixture.bin"
            path.write_bytes(b"fixture")
            with self.assertRaises(ProtocolError):
                read_synthetic_fixture(path, fixture_id="bad/id", required_root=root)


if __name__ == "__main__":
    unittest.main()
