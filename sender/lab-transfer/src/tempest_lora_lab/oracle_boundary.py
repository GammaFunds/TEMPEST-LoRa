from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    normalize_dynamic_symbols,
)
from .protocol import ProtocolError, canonical_json_bytes

REQUEST_SCHEMA = "tempest-lora.oracle-request.v1"
RESULT_SCHEMA = "tempest-lora.oracle-result.v1"
REQUEST_DOMAIN = b"TEMPEST-LoRa-R2C2-Oracle-Request\x00"
MAX_RESULT_BYTES = 1_048_576


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


def _canonical_real_parent(path: Path) -> Path:
    if not isinstance(path, Path):
        raise ProtocolError("Oracle boundary path must be pathlib.Path")
    if not path.is_absolute():
        raise ProtocolError("Oracle boundary path must be absolute")
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError("Oracle boundary parent is unavailable") from exc
    if resolved_parent != path.parent or not resolved_parent.is_dir():
        raise ProtocolError("Oracle boundary parent must be canonical and symlink-free")
    return resolved_parent


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
    if type(request) is not OracleRequest:
        raise ProtocolError("request must be exact OracleRequest")
    _canonical_real_parent(path)
    if path.exists() or path.is_symlink():
        raise ProtocolError("request output already exists")

    payload = (
        json.dumps(request.to_dict(), sort_keys=True, indent=2, ensure_ascii=True)
        + "\n"
    ).encode("ascii")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ProtocolError("request output could not be created safely") from exc

    succeeded = False
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise ProtocolError("request output write made no progress")
            view = view[written:]
        os.fsync(fd)
        final_fd_stat = os.fstat(fd)
        if not stat.S_ISREG(final_fd_stat.st_mode) or final_fd_stat.st_size != len(payload):
            raise ProtocolError("request output size or type mismatch")
        try:
            final_path = path.resolve(strict=True)
            final_path_stat = path.stat(follow_symlinks=False)
        except (OSError, RuntimeError) as exc:
            raise ProtocolError("request output path changed during write") from exc
        if final_path != path:
            raise ProtocolError("request output path became non-canonical")
        if (
            final_path_stat.st_dev != final_fd_stat.st_dev
            or final_path_stat.st_ino != final_fd_stat.st_ino
            or stat.S_IFMT(final_path_stat.st_mode) != stat.S_IFMT(final_fd_stat.st_mode)
            or final_path_stat.st_size != final_fd_stat.st_size
        ):
            raise ProtocolError("request output path identity changed during write")
        succeeded = True
    finally:
        os.close(fd)
        if not succeeded:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _read_json_regular_file(path: Path) -> Mapping[str, Any]:
    _canonical_real_parent(path)
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
            chunk = os.read(fd, min(65_536, MAX_RESULT_BYTES + 1 - total))
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
        value = json.loads(raw.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Oracle result is not valid input JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Oracle result root must be an object")
    return value


def load_and_validate_result(path: Path, request: OracleRequest):
    if type(request) is not OracleRequest:
        raise ProtocolError("request must be exact OracleRequest")
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
    if not isinstance(symbols, list) or any(type(value) is not int for value in symbols):
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
