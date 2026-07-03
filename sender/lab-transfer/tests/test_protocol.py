from __future__ import annotations

import hashlib
import unittest

from tempest_lora_lab.profiles import dynamic_profile_descriptor
from tempest_lora_lab.protocol import (
    HEADER_BYTES,
    MAX_FIXTURE_BYTES,
    MAX_FRAGMENT_COUNT,
    MAX_FRAGMENT_PAYLOAD_BYTES,
    MAX_LORA_PAYLOAD_BYTES,
    ProtocolError,
    build_transfer_frames,
    parse_frame,
    reassemble_transfer,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = dynamic_profile_descriptor()
        self.fixture = bytes(index % 256 for index in range(4096))
        self.frames = build_transfer_frames(
            fixture_id="synthetic-pattern-4096",
            content=self.fixture,
            dynamic_profile_descriptor=self.profile,
        )

    def test_contract_sizes(self) -> None:
        self.assertEqual(HEADER_BYTES, 48)
        self.assertEqual(MAX_FRAGMENT_PAYLOAD_BYTES, 207)
        self.assertEqual(MAX_LORA_PAYLOAD_BYTES, 255)
        self.assertEqual(MAX_FIXTURE_BYTES, 65_535)
        self.assertEqual(MAX_FRAGMENT_COUNT, 317)
        self.assertEqual(len(self.frames), 22)

    def test_deterministic_ordered_and_reordered_reassembly(self) -> None:
        repeated = build_transfer_frames(
            fixture_id="synthetic-pattern-4096",
            content=self.fixture,
            dynamic_profile_descriptor=self.profile,
        )
        self.assertEqual(self.frames, repeated)
        ordered = reassemble_transfer(self.frames, self.profile)
        reordered = reassemble_transfer(reversed(self.frames), self.profile)
        self.assertEqual(ordered.content, self.fixture)
        self.assertEqual(reordered.content, self.fixture)
        self.assertEqual(ordered.sha256, hashlib.sha256(self.fixture).hexdigest())

    def test_maximum_fixture_uses_317_fragments(self) -> None:
        content = bytes(index % 251 for index in range(MAX_FIXTURE_BYTES))
        frames = build_transfer_frames(
            fixture_id="maximum-fixture",
            content=content,
            dynamic_profile_descriptor=self.profile,
        )
        self.assertEqual(len(frames), MAX_FRAGMENT_COUNT + 2)
        self.assertTrue(all(len(frame) <= MAX_LORA_PAYLOAD_BYTES for frame in frames))
        self.assertEqual(reassemble_transfer(frames, self.profile).content, content)

    def test_corruptions_duplicates_and_gaps_are_rejected(self) -> None:
        header_corrupt = bytearray(self.frames[1])
        header_corrupt[8] ^= 1
        with self.assertRaises(ProtocolError):
            parse_frame(bytes(header_corrupt))

        payload_corrupt = bytearray(self.frames[1])
        payload_corrupt[-1] ^= 1
        with self.assertRaises(ProtocolError):
            parse_frame(bytes(payload_corrupt))

        with self.assertRaises(ProtocolError):
            reassemble_transfer(self.frames + (self.frames[1],), self.profile)
        with self.assertRaises(ProtocolError):
            reassemble_transfer(self.frames[:2] + self.frames[3:], self.profile)

    def test_profile_descriptor_mismatch_is_rejected(self) -> None:
        changed = dict(self.profile)
        changed["name"] = "changed"
        with self.assertRaises(ProtocolError):
            reassemble_transfer(self.frames, changed)

    def test_empty_and_oversized_fixture_are_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            build_transfer_frames(
                fixture_id="empty",
                content=b"",
                dynamic_profile_descriptor=self.profile,
            )
        with self.assertRaises(ProtocolError):
            build_transfer_frames(
                fixture_id="oversized",
                content=b"x" * (MAX_FIXTURE_BYTES + 1),
                dynamic_profile_descriptor=self.profile,
            )

    def test_noncanonical_profile_descriptor_is_rejected_during_build(self) -> None:
        changed = dict(self.profile)
        changed["name"] = "changed"
        with self.assertRaises(ProtocolError):
            build_transfer_frames(
                fixture_id="changed-profile",
                content=b"synthetic",
                dynamic_profile_descriptor=changed,
            )

    def test_fixture_content_must_be_bytes(self) -> None:
        with self.assertRaises(ProtocolError):
            build_transfer_frames(
                fixture_id="bytearray",
                content=bytearray(b"synthetic"),
                dynamic_profile_descriptor=self.profile,
            )


if __name__ == "__main__":
    unittest.main()
