from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import asdict, dataclass, fields
from typing import Any, Iterable, Sequence

from .protocol import ProfileId, ProtocolError, canonical_json_bytes

PINNED_ORACLE_COMMIT = "862746dd1cf635c9c8a4bfbaa2c3a0ec3a5306c9"
PINNED_ORACLE_TREE = "97e9f429c68b4672ca412a3ee411311564286eb1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DynamicPhyParameters:
    frequency_hz: int = 915_000_000
    bandwidth_hz: int = 500_000
    spreading_factor: int = 7
    coding_rate: str = "4/5"
    coding_rate_value: int = 1
    preamble_symbols: int = 4
    sync_word_api: str = "0x12"
    header_mode: str = "explicit"
    payload_crc: bool = True
    iq_inverted: bool = False
    ldro: int = 0

    def validate(self) -> None:
        expected = DynamicPhyParameters()
        for field in fields(self):
            actual_value = getattr(self, field.name)
            expected_value = getattr(expected, field.name)
            if type(actual_value) is not type(expected_value) or actual_value != expected_value:
                raise ProtocolError("dynamic PHY parameters differ from R2C.1 v1 profile")

    def descriptor(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    def descriptor_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.descriptor())).hexdigest()


@dataclass(frozen=True)
class SymbolEnvelope:
    profile_id: ProfileId
    source_kind: str
    spreading_factor: int
    index_base: int
    ingress_transform: str
    symbols: tuple[int, ...]
    symbols_sha256_uint16be: str
    provenance: dict[str, Any]

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "tempest-lora.symbol-sequence-envelope.v1",
            "profile_id": int(self.profile_id),
            "source_kind": self.source_kind,
            "spreading_factor": self.spreading_factor,
            "index_base": self.index_base,
            "ingress_transform": self.ingress_transform,
            "symbol_count": self.symbol_count,
            "symbols": list(self.symbols),
            "symbols_sha256_uint16be": self.symbols_sha256_uint16be,
            "provenance": self.provenance,
        }


def dynamic_profile_descriptor(parameters: DynamicPhyParameters | None = None) -> dict[str, Any]:
    parameters = parameters or DynamicPhyParameters()
    parameters.validate()
    return {
        "schema": "tempest-lora.dynamic-software-phy-profile.v1",
        "profile_id": int(ProfileId.DYNAMIC_SOFTWARE_PHY),
        "name": "dynamic-software-phy-v1",
        "transport_capable": True,
        "oracle_boundary": {
            "type": "external-process-file-v1",
            "commit": PINNED_ORACLE_COMMIT,
            "tree": PINNED_ORACLE_TREE,
            "source_integration": False,
            "library_linkage": False,
        },
        "phy": parameters.descriptor(),
        "symbol_output": {
            "index_base": 0,
            "includes_preamble": False,
            "includes_sync": False,
            "includes_sfd": False,
            "tail_modification": "forbidden",
        },
    }


def capture_profile_descriptor() -> dict[str, Any]:
    return {
        "schema": "tempest-lora.capture-replay-profile.v1",
        "profile_id": int(ProfileId.CAPTURE_REPLAY),
        "name": "capture-replay-v1",
        "transport_capable": False,
        "accepted_source_kind": "published-verified-payloadsymbols-mat",
        "raw_index_base": 1,
        "canonical_ingress_operation": "stored_Index - 1",
        "tail_modification": "forbidden",
    }


def _validate_sha256_hex(value: str, label: str) -> None:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise ProtocolError(f"{label} must be lowercase SHA-256 hex")


def _validate_sf(spreading_factor: int) -> None:
    if type(spreading_factor) is not int or not 6 <= spreading_factor <= 12:
        raise ProtocolError("spreading_factor must be an integer in 6..12")


def _strict_symbols(values: Iterable[int], label: str) -> tuple[int, ...]:
    try:
        symbols = tuple(values)
    except TypeError as exc:
        raise ProtocolError(f"{label} must be an integer sequence") from exc
    if not symbols:
        raise ProtocolError(f"{label} is empty")
    if any(type(value) is not int for value in symbols):
        raise ProtocolError(f"{label} must contain plain integers")
    return symbols


def _symbol_hash(symbols: Sequence[int]) -> str:
    payload = b"".join(struct.pack(">H", value) for value in symbols)
    return hashlib.sha256(payload).hexdigest()


def normalize_capture_symbols(
    *,
    symbols_one_based: Sequence[int],
    spreading_factor: int,
    approved_fixture: bool,
    fixture_sha256: str,
) -> SymbolEnvelope:
    _validate_sf(spreading_factor)
    _validate_sha256_hex(fixture_sha256, "fixture_sha256")
    if approved_fixture is not True:
        raise ProtocolError("capture fixture approval must be explicit boolean true")
    source = _strict_symbols(symbols_one_based, "capture symbol sequence")
    maximum = 1 << spreading_factor
    if any(not 1 <= value <= maximum for value in source):
        raise ProtocolError("capture symbol outside one-based SF domain")
    canonical = tuple(value - 1 for value in source)
    return SymbolEnvelope(
        profile_id=ProfileId.CAPTURE_REPLAY,
        source_kind="published-verified-payloadsymbols-mat",
        spreading_factor=spreading_factor,
        index_base=0,
        ingress_transform="stored_Index - 1",
        symbols=canonical,
        symbols_sha256_uint16be=_symbol_hash(canonical),
        provenance={"fixture_sha256": fixture_sha256, "approved_fixture": True},
    )


def normalize_dynamic_symbols(
    *,
    symbols_zero_based: Sequence[int],
    parameters: DynamicPhyParameters,
    payload_sha256: str,
    oracle_commit: str,
    oracle_tree: str,
) -> SymbolEnvelope:
    if type(parameters) is not DynamicPhyParameters:
        raise ProtocolError("parameters must be exact DynamicPhyParameters")
    parameters.validate()
    _validate_sha256_hex(payload_sha256, "payload_sha256")
    if type(oracle_commit) is not str or type(oracle_tree) is not str:
        raise ProtocolError("Oracle provenance must be strings")
    if oracle_commit != PINNED_ORACLE_COMMIT or oracle_tree != PINNED_ORACLE_TREE:
        raise ProtocolError("Oracle provenance differs from pinned R2C.1 boundary")
    source = _strict_symbols(symbols_zero_based, "dynamic symbol sequence")
    maximum = (1 << parameters.spreading_factor) - 1
    if any(not 0 <= value <= maximum for value in source):
        raise ProtocolError("dynamic symbol outside zero-based SF domain")
    return SymbolEnvelope(
        profile_id=ProfileId.DYNAMIC_SOFTWARE_PHY,
        source_kind="pinned-gr-lora-sdr-result",
        spreading_factor=parameters.spreading_factor,
        index_base=0,
        ingress_transform="identity",
        symbols=source,
        symbols_sha256_uint16be=_symbol_hash(source),
        provenance={
            "payload_sha256": payload_sha256,
            "oracle_commit": oracle_commit,
            "oracle_tree": oracle_tree,
            "parameters_sha256": parameters.descriptor_sha256(),
        },
    )
