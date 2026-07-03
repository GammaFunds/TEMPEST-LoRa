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

CAPTURE_GOLDEN_SYMBOL_FIXTURE_SHA256 = (
    "bbac8ea1e0cd5c3c204505d553c982f711d7b13c3a7542309f91adf0d41c572f"
)
CAPTURE_GOLDEN_IMAGE_FIXTURE_SHA256 = (
    "b35b03f5485f98206dbd3858bdd9d902343a9237273e0b0989f6e5646fabe7f6"
)
CAPTURE_GOLDEN_DECODED_RAW_SHA256 = (
    "641de69d5bf70cd643a12fdec73c401f512ad1b288cdf8c2210f715c020e12c4"
)
CAPTURE_GOLDEN_CANONICAL_PGM_SHA256 = (
    "47357bca7297b24aafe2b642edb0677f88639243b0b149d932830ee29f8915df"
)
CAPTURE_GOLDEN_SYMBOLS_SHA256_UINT16BE = (
    "30a781f30ea358336a09ffbaac517c97d95f1ac3e4e79d21c881e14e3ac2962e"
)
CAPTURE_GOLDEN_SYMBOLS_ZERO_BASED = (
    13,
    9,
    1,
    13,
    61,
    109,
    49,
    97,
    84,
    106,
    39,
    91,
    109,
    109,
)


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
class CaptureReplayRendererProfile:
    profile_id: ProfileId = ProfileId.CAPTURE_REPLAY
    visible_width: int = 1920
    visible_height: int = 1080
    pixel_encoding: str = "grayscale-u8"
    black_pixel: int = 0
    white_pixel: int = 255
    source_format: str = "png-grayscale8-noninterlaced"
    symbol_spreading_factor: int = 7
    symbol_index_base: int = 0
    symbol_count: int = 14
    symbol_fixture_sha256: str = CAPTURE_GOLDEN_SYMBOL_FIXTURE_SHA256
    image_fixture_sha256: str = CAPTURE_GOLDEN_IMAGE_FIXTURE_SHA256
    decoded_raw_sha256: str = CAPTURE_GOLDEN_DECODED_RAW_SHA256
    canonical_pgm_sha256: str = CAPTURE_GOLDEN_CANONICAL_PGM_SHA256
    symbols_sha256_uint16be: str = CAPTURE_GOLDEN_SYMBOLS_SHA256_UINT16BE

    def validate(self) -> None:
        expected = CaptureReplayRendererProfile()
        for field in fields(self):
            actual = getattr(self, field.name)
            wanted = getattr(expected, field.name)
            if type(actual) is not type(wanted) or actual != wanted:
                raise ProtocolError("capture renderer profile differs from R2D.2G v1")

    def descriptor(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "tempest-lora.capture-replay-renderer-profile.v1",
            "name": "capture-replay-published-golden-sf7-v1",
            "profile_id": int(self.profile_id),
            "visible_width": self.visible_width,
            "visible_height": self.visible_height,
            "pixel_encoding": self.pixel_encoding,
            "black_pixel": self.black_pixel,
            "white_pixel": self.white_pixel,
            "source_format": self.source_format,
            "symbol_spreading_factor": self.symbol_spreading_factor,
            "symbol_index_base": self.symbol_index_base,
            "symbol_count": self.symbol_count,
            "symbol_fixture_sha256": self.symbol_fixture_sha256,
            "image_fixture_sha256": self.image_fixture_sha256,
            "decoded_raw_sha256": self.decoded_raw_sha256,
            "canonical_pgm_sha256": self.canonical_pgm_sha256,
            "symbols_sha256_uint16be": self.symbols_sha256_uint16be,
        }

    def descriptor_sha256(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.descriptor())).hexdigest()


@dataclass(frozen=True)
class DynamicPixelRendererProfile:
    profile_id: ProfileId = ProfileId.DYNAMIC_SOFTWARE_PHY
    visible_width: int = 1920
    visible_height: int = 1080
    total_width: int = 2200
    total_height: int = 1125
    active_x_start: int = 132
    active_y_start: int = 9
    frame_rate_numerator: int = 60
    frame_rate_denominator: int = 1
    pixel_clock_hz: int = 148_500_000
    center_frequency_hz: int = 915_000_000
    bandwidth_hz: int = 500_000
    supported_spreading_factor: int = 7
    preamble_symbols: int = 4
    sync_symbols_zero_based: tuple[int, int] = (8, 16)
    sfd_quarter_chirps: int = 9
    black_pixel: int = 0
    white_pixel: int = 255
    maximum_frame_count: int = 16

    def validate(self) -> None:
        expected = DynamicPixelRendererProfile()
        for field in fields(self):
            actual = getattr(self, field.name)
            wanted = getattr(expected, field.name)
            if type(actual) is not type(wanted) or actual != wanted:
                raise ProtocolError("dynamic renderer profile differs from R2D.2G v1")

    def descriptor(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "tempest-lora.dynamic-pixel-renderer-profile.v1",
            "name": "dynamic-clear-source-linear-phase-1080p60-sf7-v1",
            "profile_id": int(self.profile_id),
            "visible_width": self.visible_width,
            "visible_height": self.visible_height,
            "total_width": self.total_width,
            "total_height": self.total_height,
            "active_x_start": self.active_x_start,
            "active_y_start": self.active_y_start,
            "frame_rate_numerator": self.frame_rate_numerator,
            "frame_rate_denominator": self.frame_rate_denominator,
            "pixel_clock_hz": self.pixel_clock_hz,
            "center_frequency_hz": self.center_frequency_hz,
            "bandwidth_hz": self.bandwidth_hz,
            "supported_spreading_factor": self.supported_spreading_factor,
            "preamble_symbols": self.preamble_symbols,
            "sync_symbols_zero_based": list(self.sync_symbols_zero_based),
            "sfd_quarter_chirps": self.sfd_quarter_chirps,
            "black_pixel": self.black_pixel,
            "white_pixel": self.white_pixel,
            "maximum_frame_count": self.maximum_frame_count,
        }

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
