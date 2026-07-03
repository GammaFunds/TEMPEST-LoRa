from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    SymbolEnvelope,
    normalize_dynamic_symbols,
)
from .protocol import ProfileId, ProtocolError, canonical_json_bytes

REQUEST_SCHEMA = "tempest-lora.oracle-request.v1"
RESULT_SCHEMA = "tempest-lora.oracle-result.v1"
REQUEST_DOMAIN = b"TEMPEST-LoRa-R2C2-Oracle-Request\x00"
MAX_RESULT_BYTES = 1_048_576
MAX_REQUEST_BYTES = 16_384
PAYLOAD_HEX_PATTERN = re.compile(r"[0-9a-f]+")
CONCRETE_PATH_TYPE = type(Path())


def _no_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for key, value in pairs:
        if key in seen:
            raise ProtocolError("Oracle JSON contains duplicate key")
        seen.add(key)
    return dict(pairs)


_STRICT_JSON_DECODER = json.JSONDecoder(
    object_pairs_hook=_no_duplicate_json_keys
)


@dataclass(frozen=True)
class OracleRequest:
    request_id: str
    payload_hex: str
    payload_sha256: str
    parameters: DynamicPhyParameters
    parameters_sha256: str
    oracle_commit: str = PINNED_ORACLE_COMMIT
    oracle_tree: str = PINNED_ORACLE_TREE

    @classmethod
    def from_payload(
        cls,
        payload: bytes,
        parameters: DynamicPhyParameters | None = None,
    ) -> "OracleRequest":
        if type(payload) is not bytes:
            raise ProtocolError("Oracle payload must be bytes")
        if not payload:
            raise ProtocolError("Oracle payload is empty")
        if len(payload) > 255:
            raise ProtocolError("Oracle payload exceeds LoRa payload limit")
        parameters = parameters or DynamicPhyParameters()
        if type(parameters) is not DynamicPhyParameters:
            raise ProtocolError("Oracle parameters must be exact DynamicPhyParameters")
        parameters.validate()
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        parameters_sha256 = parameters.descriptor_sha256()
        identity_document = {
            "schema": REQUEST_SCHEMA,
            "payload_sha256": payload_sha256,
            "parameters_sha256": parameters_sha256,
            "oracle_commit": PINNED_ORACLE_COMMIT,
            "oracle_tree": PINNED_ORACLE_TREE,
        }
        request_id = hashlib.sha256(
            REQUEST_DOMAIN + canonical_json_bytes(identity_document)
        ).hexdigest()
        return cls(
            request_id=request_id,
            payload_hex=payload.hex(),
            payload_sha256=payload_sha256,
            parameters=parameters,
            parameters_sha256=parameters_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REQUEST_SCHEMA,
            "request_id": self.request_id,
            "payload_hex": self.payload_hex,
            "payload_sha256": self.payload_sha256,
            "parameters": self.parameters.descriptor(),
            "parameters_sha256": self.parameters_sha256,
            "oracle_commit": self.oracle_commit,
            "oracle_tree": self.oracle_tree,
            "requested_output": {
                "kind": "physical-symbols",
                "index_base": 0,
                "serialization": "json-uint-array",
                "tail_modification": "forbidden",
            },
        }


def _require_exact_path(path: Path, label: str) -> None:
    if type(path) is not CONCRETE_PATH_TYPE:
        raise ProtocolError(f"{label} must be an exact concrete pathlib path")


def _canonical_real_parent(path: Path, label: str = "Oracle boundary path") -> Path:
    _require_exact_path(path, label)
    if not path.is_absolute():
        raise ProtocolError(f"{label} must be absolute")
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError(f"{label} parent is unavailable") from exc
    if resolved_parent != path.parent or not resolved_parent.is_dir():
        raise ProtocolError(f"{label} parent must be canonical and symlink-free")
    return resolved_parent


def _canonical_request(request: OracleRequest) -> OracleRequest:
    if type(request) is not OracleRequest:
        raise ProtocolError("request must be exact OracleRequest")
    if type(request.payload_hex) is not str:
        raise ProtocolError("request payload_hex must be a string")
    if PAYLOAD_HEX_PATTERN.fullmatch(request.payload_hex) is None:
        raise ProtocolError("request payload_hex must match [0-9a-f]+")
    if len(request.payload_hex) % 2 != 0:
        raise ProtocolError("request payload_hex must be even-length")
    try:
        payload = bytes.fromhex(request.payload_hex)
    except ValueError as exc:
        raise ProtocolError("request payload_hex is invalid") from exc
    if type(request.parameters) is not DynamicPhyParameters:
        raise ProtocolError("request parameters must be exact DynamicPhyParameters")
    reconstructed = OracleRequest.from_payload(payload, request.parameters)
    if reconstructed != request or reconstructed.to_dict() != request.to_dict():
        raise ProtocolError("request is not internally canonical")
    return reconstructed


def _validate_new_output_path(path: Path, label: str) -> Path:
    parent = _canonical_real_parent(path, label)
    try:
        path.lstat()
    except FileNotFoundError:
        return parent
    except OSError as exc:
        raise ProtocolError(f"{label} could not be checked safely") from exc
    raise ProtocolError(f"{label} already exists")


def _write_new_file(path: Path, payload: bytes, label: str) -> None:
    if type(payload) is not bytes:
        raise ProtocolError(f"{label} payload must be bytes")
    parent = _validate_new_output_path(path, label)
    stage_dir = Path(tempfile.mkdtemp(prefix=".tempest-lora-write-", dir=parent))
    stage_path = stage_dir / "payload"
    fd: int | None = None
    linked = False
    published_identity: tuple[int, int] | None = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(stage_path, flags, 0o600)
        os.fchmod(fd, 0o600)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise ProtocolError(f"{label} staging descriptor is not regular")
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ProtocolError(f"{label} write made no progress")
            view = view[written:]
        os.fsync(fd)
        final_fd_stat = os.fstat(fd)
        if not stat.S_ISREG(final_fd_stat.st_mode):
            raise ProtocolError(f"{label} staging descriptor is not regular")
        if final_fd_stat.st_size != len(payload):
            raise ProtocolError(f"{label} size mismatch")
        if stat.S_IMODE(final_fd_stat.st_mode) != 0o600:
            raise ProtocolError(f"{label} mode is not 0600")
        os.close(fd)
        fd = None

        try:
            os.link(stage_path, path, follow_symlinks=False)
        except OSError as exc:
            raise ProtocolError(f"{label} could not be published exclusively") from exc
        linked = True

        stage_stat = stage_path.stat(follow_symlinks=False)
        final_path = path.resolve(strict=True)
        final_stat = path.stat(follow_symlinks=False)
        if final_path != path:
            raise ProtocolError(f"{label} path became non-canonical")
        if (
            final_stat.st_dev != stage_stat.st_dev
            or final_stat.st_ino != stage_stat.st_ino
            or not stat.S_ISREG(final_stat.st_mode)
            or final_stat.st_size != len(payload)
            or stat.S_IMODE(final_stat.st_mode) != 0o600
        ):
            raise ProtocolError(f"{label} published identity mismatch")
        published_identity = (final_stat.st_dev, final_stat.st_ino)
    finally:
        if fd is not None:
            os.close(fd)
        # Cleanup is limited to the private random staging directory. The
        # caller-controlled destination is never unlinked on failure.
        try:
            stage_path.unlink()
        except FileNotFoundError:
            pass
        try:
            stage_dir.rmdir()
        except OSError:
            pass
        if linked and published_identity is not None:
            try:
                current = path.stat(follow_symlinks=False)
            except FileNotFoundError as exc:
                raise ProtocolError(f"{label} disappeared after publication") from exc
            if (
                current.st_dev != published_identity[0]
                or current.st_ino != published_identity[1]
                or not stat.S_ISREG(current.st_mode)
            ):
                raise ProtocolError(f"{label} was replaced after publication")


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def write_request(path: Path, request: OracleRequest) -> None:
    canonical = _canonical_request(request)
    payload = (
        json.dumps(
            canonical.to_dict(),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    _write_new_file(path, payload, "Oracle request output")


def _read_json_regular_file(path: Path) -> Mapping[str, Any]:
    _require_exact_path(path, "Oracle result path")
    _canonical_real_parent(path, "Oracle result path")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError("Oracle result is unavailable") from exc
    if resolved != path:
        raise ProtocolError("Oracle result path must be canonical and symlink-free")

    initial_stat = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ProtocolError("Oracle result must be a regular file")
    if initial_stat.st_size > MAX_RESULT_BYTES:
        raise ProtocolError("Oracle result exceeds the size limit")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ProtocolError("Oracle result could not be opened safely") from exc

    try:
        opened_stat = os.fstat(fd)
        if not _same_file_snapshot(initial_stat, opened_stat):
            raise ProtocolError("Oracle result changed before open")
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = MAX_RESULT_BYTES + 1 - total
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_RESULT_BYTES:
                raise ProtocolError("Oracle result exceeds the size limit")
        final_fd_stat = os.fstat(fd)
        if not _same_file_snapshot(opened_stat, final_fd_stat):
            raise ProtocolError("Oracle result changed during read")
        try:
            final_path = path.resolve(strict=True)
            final_path_stat = path.stat(follow_symlinks=False)
        except (OSError, RuntimeError) as exc:
            raise ProtocolError("Oracle result path changed during read") from exc
        if final_path != path or not _same_file_snapshot(opened_stat, final_path_stat):
            raise ProtocolError("Oracle result path identity changed during read")
        raw = b"".join(chunks)
    finally:
        os.close(fd)

    try:
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise ProtocolError("Oracle result is not ASCII JSON") from exc
    try:
        value = _STRICT_JSON_DECODER.decode(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Oracle result is not valid JSON") from exc
    if type(value) is not dict:
        raise ProtocolError("Oracle result root must be an exact dict")
    return value

def load_and_validate_result(path: Path, request: OracleRequest) -> SymbolEnvelope:
    request = _canonical_request(request)
    data = _read_json_regular_file(path)
    required = {
        "schema",
        "request_id",
        "payload_sha256",
        "parameters_sha256",
        "oracle_commit",
        "oracle_tree",
        "index_base",
        "symbol_count",
        "symbols",
        "symbols_sha256_uint16be",
    }
    if set(data) != required:
        raise ProtocolError("Oracle result field set mismatch")
    if data["schema"] != RESULT_SCHEMA:
        raise ProtocolError("Oracle result schema mismatch")
    if data["request_id"] != request.request_id:
        raise ProtocolError("Oracle request_id mismatch")
    if data["payload_sha256"] != request.payload_sha256:
        raise ProtocolError("Oracle payload hash mismatch")
    if data["parameters_sha256"] != request.parameters_sha256:
        raise ProtocolError("Oracle parameters hash mismatch")
    if (
        data["oracle_commit"] != PINNED_ORACLE_COMMIT
        or data["oracle_tree"] != PINNED_ORACLE_TREE
    ):
        raise ProtocolError("Oracle provenance mismatch")
    if type(data["index_base"]) is not int or data["index_base"] != 0:
        raise ProtocolError("Oracle result must declare integer zero index_base")
    if type(data["symbol_count"]) is not int or data["symbol_count"] < 1:
        raise ProtocolError("Oracle symbol_count must be a positive integer")
    symbols = data["symbols"]
    if type(symbols) is not list or any(type(value) is not int for value in symbols):
        raise ProtocolError("Oracle symbols must be an integer array")
    if data["symbol_count"] != len(symbols):
        raise ProtocolError("Oracle symbol_count mismatch")
    envelope = normalize_dynamic_symbols(
        symbols_zero_based=symbols,
        parameters=request.parameters,
        payload_sha256=request.payload_sha256,
        oracle_commit=data["oracle_commit"],
        oracle_tree=data["oracle_tree"],
    )
    if data["symbols_sha256_uint16be"] != envelope.symbols_sha256_uint16be:
        raise ProtocolError("Oracle symbol hash mismatch")
    return envelope


def load_and_validate_request(path: Path) -> OracleRequest:
    _require_exact_path(path, "Oracle request path")
    if not path.is_absolute():
        raise ProtocolError("Oracle request path must be absolute")
    _canonical_real_parent(path)
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError("Oracle request is unavailable") from exc
    if resolved != path:
        raise ProtocolError("Oracle request path must be canonical and symlink-free")
    initial_stat = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ProtocolError("Oracle request must be a regular file")
    if initial_stat.st_size > MAX_REQUEST_BYTES:
        raise ProtocolError("Oracle request exceeds the size limit")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ProtocolError("Oracle request could not be opened safely") from exc
    try:
        opened_stat = os.fstat(fd)
        if not _same_file_snapshot(initial_stat, opened_stat):
            raise ProtocolError("Oracle request changed before open")
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = MAX_REQUEST_BYTES + 1 - total
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_REQUEST_BYTES:
                raise ProtocolError("Oracle request exceeds the size limit")
        final_fd_stat = os.fstat(fd)
        if not _same_file_snapshot(opened_stat, final_fd_stat):
            raise ProtocolError("Oracle request changed during read")
        try:
            final_path = path.resolve(strict=True)
            final_path_stat = path.stat(follow_symlinks=False)
        except (OSError, RuntimeError) as exc:
            raise ProtocolError("Oracle request path changed during read") from exc
        if final_path != path or not _same_file_snapshot(opened_stat, final_path_stat):
            raise ProtocolError("Oracle request path identity changed during read")
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        text = raw.decode("ascii")
    except UnicodeError as exc:
        raise ProtocolError("Oracle request is not valid ASCII JSON") from exc
    try:
        data = _STRICT_JSON_DECODER.decode(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("Oracle request is not valid JSON") from exc
    if type(data) is not dict:
        raise ProtocolError("Oracle request root must be an exact dict")
    required = {
        "schema", "request_id", "payload_hex", "payload_sha256",
        "parameters", "parameters_sha256", "oracle_commit",
        "oracle_tree", "requested_output",
    }
    if set(data) != required:
        raise ProtocolError("Oracle request field set mismatch")
    if data["schema"] != REQUEST_SCHEMA:
        raise ProtocolError("Oracle request schema mismatch")
    ro = data["requested_output"]
    expected_ro = {
        "kind": "physical-symbols",
        "index_base": 0,
        "serialization": "json-uint-array",
        "tail_modification": "forbidden",
    }
    if type(ro) is not dict or set(ro) != set(expected_ro):
        raise ProtocolError("Oracle request requested_output mismatch")
    if type(ro["index_base"]) is not int:
        raise ProtocolError("Oracle request requested_output index_base must be int")
    if any(ro[k] != expected_ro[k] for k in expected_ro):
        raise ProtocolError("Oracle request requested_output mismatch")
    payload_hex = data["payload_hex"]
    if type(payload_hex) is not str:
        raise ProtocolError("Oracle request payload_hex must be a string")
    if payload_hex != payload_hex.lower():
        raise ProtocolError("Oracle request payload_hex must be lowercase")
    if PAYLOAD_HEX_PATTERN.fullmatch(payload_hex) is None:
        raise ProtocolError("Oracle request payload_hex must match [0-9a-f]+")
    if len(payload_hex) % 2 != 0:
        raise ProtocolError("Oracle request payload_hex must be even-length")
    try:
        payload_bytes = bytes.fromhex(payload_hex)
    except ValueError as exc:
        raise ProtocolError("Oracle request payload_hex is not valid hexadecimal") from exc
    if not 1 <= len(payload_bytes) <= 255:
        raise ProtocolError("Oracle request payload_hex must represent 1..255 bytes")
    params_data = data["parameters"]
    if type(params_data) is not dict:
        raise ProtocolError("Oracle request parameters must be an object")
    expected_param_types = {
        "frequency_hz": int,
        "bandwidth_hz": int,
        "spreading_factor": int,
        "coding_rate": str,
        "coding_rate_value": int,
        "preamble_symbols": int,
        "sync_word_api": str,
        "header_mode": str,
        "payload_crc": bool,
        "iq_inverted": bool,
        "ldro": int,
    }
    if set(params_data) != set(expected_param_types):
        raise ProtocolError("Oracle request parameters field set mismatch")
    for name, expected_type in expected_param_types.items():
        if type(params_data[name]) is not expected_type:
            raise ProtocolError(f"Oracle request parameter {name} must be {expected_type.__name__}")
    parameters = DynamicPhyParameters(
        frequency_hz=params_data["frequency_hz"],
        bandwidth_hz=params_data["bandwidth_hz"],
        spreading_factor=params_data["spreading_factor"],
        coding_rate=params_data["coding_rate"],
        coding_rate_value=params_data["coding_rate_value"],
        preamble_symbols=params_data["preamble_symbols"],
        sync_word_api=params_data["sync_word_api"],
        header_mode=params_data["header_mode"],
        payload_crc=params_data["payload_crc"],
        iq_inverted=params_data["iq_inverted"],
        ldro=params_data["ldro"],
    )
    request = OracleRequest.from_payload(payload_bytes, parameters)
    if request.to_dict() != data:
        raise ProtocolError("Oracle request reconstruction mismatch")
    return request


def write_result(path: Path, request: OracleRequest, envelope: SymbolEnvelope) -> None:
    request = _canonical_request(request)
    if type(envelope) is not SymbolEnvelope:
        raise ProtocolError("envelope must be exact SymbolEnvelope")
    if envelope.profile_id is not ProfileId.DYNAMIC_SOFTWARE_PHY:
        raise ProtocolError("result envelope must be dynamic software PHY profile")
    if type(envelope.source_kind) is not str or envelope.source_kind != "pinned-gr-lora-sdr-result":
        raise ProtocolError("result envelope source_kind mismatch")
    if type(envelope.spreading_factor) is not int or envelope.spreading_factor != 7:
        raise ProtocolError("result envelope must have integer spreading_factor 7")
    if type(envelope.index_base) is not int or envelope.index_base != 0:
        raise ProtocolError("result envelope must have integer zero-based index")
    if type(envelope.ingress_transform) is not str or envelope.ingress_transform != "identity":
        raise ProtocolError("result envelope must have identity ingress transform")
    if type(envelope.symbols) is not tuple or not envelope.symbols:
        raise ProtocolError("result envelope symbols must be a nonempty tuple")
    if any(type(symbol) is not int for symbol in envelope.symbols):
        raise ProtocolError("result envelope symbols must be plain integers")
    if any(symbol < 0 or symbol > 127 for symbol in envelope.symbols):
        raise ProtocolError("result envelope symbols must be within 0..127")
    if type(envelope.provenance) is not dict:
        raise ProtocolError("result envelope provenance must be an exact dict")
    expected_provenance = {
        "payload_sha256",
        "parameters_sha256",
        "oracle_commit",
        "oracle_tree",
    }
    if set(envelope.provenance) != expected_provenance:
        raise ProtocolError("result envelope provenance field set mismatch")
    if any(type(envelope.provenance[name]) is not str for name in expected_provenance):
        raise ProtocolError("result envelope provenance values must be plain strings")
    if envelope.provenance["payload_sha256"] != request.payload_sha256:
        raise ProtocolError("result envelope payload hash mismatch")
    if envelope.provenance["parameters_sha256"] != request.parameters_sha256:
        raise ProtocolError("result envelope parameters hash mismatch")
    if envelope.provenance["oracle_commit"] != PINNED_ORACLE_COMMIT:
        raise ProtocolError("result envelope oracle commit mismatch")
    if envelope.provenance["oracle_tree"] != PINNED_ORACLE_TREE:
        raise ProtocolError("result envelope oracle tree mismatch")

    canonical_envelope = normalize_dynamic_symbols(
        symbols_zero_based=envelope.symbols,
        parameters=request.parameters,
        payload_sha256=request.payload_sha256,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
    )
    if envelope != canonical_envelope:
        raise ProtocolError("envelope is not canonical")

    result = {
        "schema": RESULT_SCHEMA,
        "request_id": request.request_id,
        "payload_sha256": request.payload_sha256,
        "parameters_sha256": request.parameters_sha256,
        "oracle_commit": PINNED_ORACLE_COMMIT,
        "oracle_tree": PINNED_ORACLE_TREE,
        "index_base": 0,
        "symbol_count": canonical_envelope.symbol_count,
        "symbols": list(canonical_envelope.symbols),
        "symbols_sha256_uint16be": canonical_envelope.symbols_sha256_uint16be,
    }
    payload = (
        json.dumps(
            result,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    _write_new_file(path, payload, "Oracle result")
