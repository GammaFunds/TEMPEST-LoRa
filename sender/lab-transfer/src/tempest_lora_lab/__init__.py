"""Offline TEMPEST-LoRa laboratory transfer protocol and profile contracts."""

from .input_policy import DEFAULT_INPUT_ROOT, SyntheticFixture, read_synthetic_fixture
from .oracle_adapter import PinnedOracleRuntime, execute_pinned_oracle
from .oracle_boundary import (
    OracleRequest,
    load_and_validate_request,
    load_and_validate_result,
    write_request,
    write_result,
)
from .profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    SymbolEnvelope,
    capture_profile_descriptor,
    dynamic_profile_descriptor,
    normalize_capture_symbols,
    normalize_dynamic_symbols,
)
from .protocol import (
    HEADER_BYTES,
    MAX_FIXTURE_BYTES,
    MAX_FRAGMENT_COUNT,
    MAX_FRAGMENT_PAYLOAD_BYTES,
    MAX_LORA_PAYLOAD_BYTES,
    FrameType,
    ProfileId,
    ProtocolError,
    build_transfer_frames,
    parse_frame,
    reassemble_transfer,
)

__all__ = [
    "DEFAULT_INPUT_ROOT",
    "DynamicPhyParameters",
    "FrameType",
    "HEADER_BYTES",
    "MAX_FIXTURE_BYTES",
    "MAX_FRAGMENT_COUNT",
    "MAX_FRAGMENT_PAYLOAD_BYTES",
    "MAX_LORA_PAYLOAD_BYTES",
    "OracleRequest",
    "PINNED_ORACLE_COMMIT",
    "PINNED_ORACLE_TREE",
    "PinnedOracleRuntime",
    "ProfileId",
    "ProtocolError",
    "SymbolEnvelope",
    "SyntheticFixture",
    "build_transfer_frames",
    "capture_profile_descriptor",
    "dynamic_profile_descriptor",
    "execute_pinned_oracle",
    "load_and_validate_request",
    "load_and_validate_result",
    "normalize_capture_symbols",
    "normalize_dynamic_symbols",
    "parse_frame",
    "read_synthetic_fixture",
    "reassemble_transfer",
    "write_request",
    "write_result",
]
