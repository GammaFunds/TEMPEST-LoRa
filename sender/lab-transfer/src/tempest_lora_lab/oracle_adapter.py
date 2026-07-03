from __future__ import annotations

import math
import platform
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .oracle_boundary import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    OracleRequest,
    load_and_validate_request,
    _canonical_request,
    _validate_new_output_path,
    write_result,
)
from .profiles import normalize_dynamic_symbols, SymbolEnvelope
from .protocol import ProtocolError


PINNED_PYTHON_VERSION = "3.12.13"
PINNED_GNRADIO_VERSION = "3.10.11.0"


@dataclass(frozen=True)
class PinnedOracleRuntime:
    python_executable: Path
    stage_site_packages: Path
    lora_sdr_package: Path
    lora_sdr_init: Path
    lora_sdr_binding: Path
    native_library: Path
    python_version: str
    gnuradio_version: str
    oracle_commit: str
    oracle_tree: str

    def __post_init__(self) -> None:
        _validate_runtime(self)


def _validate_runtime(runtime: PinnedOracleRuntime) -> None:
    if type(runtime) is not PinnedOracleRuntime:
        raise ProtocolError("runtime must be exact PinnedOracleRuntime")

    concrete_path_type = type(Path())
    path_fields = (
        "python_executable",
        "stage_site_packages",
        "lora_sdr_package",
        "lora_sdr_init",
        "lora_sdr_binding",
        "native_library",
    )
    for field_name in path_fields:
        value = getattr(runtime, field_name)
        if type(value) is not concrete_path_type:
            raise ProtocolError(f"{field_name} must be an exact concrete pathlib path")
        if not value.is_absolute():
            raise ProtocolError(f"{field_name} must be absolute")
        try:
            resolved = value.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProtocolError(f"{field_name} is unavailable") from exc
        if resolved != value:
            raise ProtocolError(f"{field_name} must be canonical and symlink-free")

    for field_name in (
        "python_version",
        "gnuradio_version",
        "oracle_commit",
        "oracle_tree",
    ):
        if type(getattr(runtime, field_name)) is not str:
            raise ProtocolError(f"{field_name} must be a plain string")

    python_stat = runtime.python_executable.stat(follow_symlinks=False)
    stage_stat = runtime.stage_site_packages.stat(follow_symlinks=False)
    package_stat = runtime.lora_sdr_package.stat(follow_symlinks=False)
    init_stat = runtime.lora_sdr_init.stat(follow_symlinks=False)
    binding_stat = runtime.lora_sdr_binding.stat(follow_symlinks=False)
    native_stat = runtime.native_library.stat(follow_symlinks=False)
    if not stat.S_ISREG(python_stat.st_mode):
        raise ProtocolError("python_executable must be a regular file")
    if not python_stat.st_mode & 0o111:
        raise ProtocolError("python_executable must be executable")
    if not stat.S_ISDIR(stage_stat.st_mode):
        raise ProtocolError("stage_site_packages must be a directory")
    if not stat.S_ISDIR(package_stat.st_mode):
        raise ProtocolError("lora_sdr_package must be a directory")
    try:
        runtime.lora_sdr_package.relative_to(runtime.stage_site_packages)
    except ValueError as exc:
        raise ProtocolError(
            "lora_sdr_package must be contained under stage_site_packages"
        ) from exc
    if not stat.S_ISREG(init_stat.st_mode):
        raise ProtocolError("lora_sdr_init must be a regular file")
    if runtime.lora_sdr_init.name != "__init__.py":
        raise ProtocolError("lora_sdr_init basename must be __init__.py")
    if runtime.lora_sdr_init.parent != runtime.lora_sdr_package:
        raise ProtocolError(
            "lora_sdr_init must be contained directly within lora_sdr_package"
        )
    if not stat.S_ISREG(binding_stat.st_mode):
        raise ProtocolError("lora_sdr_binding must be a regular file")
    try:
        runtime.lora_sdr_binding.relative_to(runtime.lora_sdr_package)
    except ValueError as exc:
        raise ProtocolError(
            "lora_sdr_binding must be contained within lora_sdr_package"
        ) from exc
    if not stat.S_ISREG(native_stat.st_mode):
        raise ProtocolError("native_library must be a regular file")

    if runtime.python_version != PINNED_PYTHON_VERSION:
        raise ProtocolError("python_version must equal pinned value")
    if runtime.gnuradio_version != PINNED_GNRADIO_VERSION:
        raise ProtocolError("gnuradio_version must equal pinned value")
    if runtime.oracle_commit != PINNED_ORACLE_COMMIT:
        raise ProtocolError("oracle_commit must equal pinned value")
    if runtime.oracle_tree != PINNED_ORACLE_TREE:
        raise ProtocolError("oracle_tree must equal pinned value")

def _load_runtime(runtime: PinnedOracleRuntime) -> dict[str, Any]:
    import importlib

    _validate_runtime(runtime)
    if platform.python_version() != runtime.python_version:
        raise ProtocolError("Python version mismatch")
    try:
        resolved_executable = Path(sys.executable).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError("Python executable could not be resolved") from exc
    if resolved_executable != runtime.python_executable:
        raise ProtocolError("Python executable mismatch")

    gr = importlib.import_module("gnuradio.gr")
    blocks = importlib.import_module("gnuradio.blocks")
    pmt_mod = importlib.import_module("pmt")
    lora_sdr = importlib.import_module("gnuradio.lora_sdr")

    required_callables = {
        "gr.top_block": getattr(gr, "top_block", None),
        "gr.version": getattr(gr, "version", None),
        "blocks.vector_sink_i": getattr(blocks, "vector_sink_i", None),
        "lora_sdr.whitening": getattr(lora_sdr, "whitening", None),
        "lora_sdr.header": getattr(lora_sdr, "header", None),
        "lora_sdr.add_crc": getattr(lora_sdr, "add_crc", None),
        "lora_sdr.hamming_enc": getattr(lora_sdr, "hamming_enc", None),
        "lora_sdr.interleaver": getattr(lora_sdr, "interleaver", None),
        "lora_sdr.gray_demap": getattr(lora_sdr, "gray_demap", None),
        "pmt.intern": getattr(pmt_mod, "intern", None),
        "pmt.to_long": getattr(pmt_mod, "to_long", None),
        "pmt.symbol_to_string": getattr(pmt_mod, "symbol_to_string", None),
    }
    for name, value in required_callables.items():
        if not callable(value):
            raise ProtocolError(f"{name} is not callable")

    if gr.version() != runtime.gnuradio_version:
        raise ProtocolError("GNU Radio version mismatch")

    package_file = getattr(lora_sdr, "__file__", None)
    binding_module = getattr(lora_sdr, "lora_sdr_python", None)
    binding_file = getattr(binding_module, "__file__", None)
    if type(package_file) is not str:
        raise ProtocolError("lora_sdr package origin is unavailable")
    if type(binding_file) is not str:
        raise ProtocolError("lora_sdr binding origin is unavailable")
    try:
        package_origin = Path(package_file).resolve(strict=True)
        binding_origin = Path(binding_file).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError("lora_sdr origin could not be resolved") from exc
    if package_origin != runtime.lora_sdr_init:
        raise ProtocolError("lora_sdr package path mismatch")
    if binding_origin != runtime.lora_sdr_binding:
        raise ProtocolError("lora_sdr binding path mismatch")

    return {
        "gr": gr,
        "blocks": blocks,
        "pmt": pmt_mod,
        "lora_sdr": lora_sdr,
    }

def _stop_and_wait(top_block: Any) -> None:
    active_error = sys.exc_info()[1]
    stop_error: BaseException | None = None
    wait_error: BaseException | None = None
    try:
        top_block.stop()
    except BaseException as exc:  # cleanup must still attempt wait
        stop_error = exc
    try:
        top_block.wait()
    except BaseException as exc:
        wait_error = exc
    if active_error is not None:
        if stop_error is not None:
            active_error.add_note(f"stop() also failed: {stop_error!r}")
        if wait_error is not None:
            active_error.add_note(f"wait() also failed: {wait_error!r}")
        return
    if stop_error is not None:
        if wait_error is not None:
            stop_error.add_note(f"wait() also failed: {wait_error!r}")
        raise stop_error
    if wait_error is not None:
        raise wait_error


def _execute_with_injected(
    request: OracleRequest,
    runtime: PinnedOracleRuntime,
    modules: dict[str, Any],
    timeout_seconds: float,
    max_symbol_count: int,
) -> SymbolEnvelope:
    request = _canonical_request(request)
    _validate_runtime(runtime)
    if type(modules) is not dict:
        raise ProtocolError("modules must be an exact dict")
    gr = modules["gr"]
    blocks = modules["blocks"]
    pmt_mod = modules["pmt"]
    lora_sdr = modules["lora_sdr"]

    if type(timeout_seconds) is bool:
        raise ProtocolError("timeout_seconds must not be bool")
    if type(timeout_seconds) not in (int, float):
        raise ProtocolError("timeout_seconds must be int or float")
    timeout_seconds = float(timeout_seconds)
    if not math.isfinite(timeout_seconds):
        raise ProtocolError("timeout_seconds must be finite")
    if timeout_seconds <= 0:
        raise ProtocolError("timeout_seconds must be positive")

    if type(max_symbol_count) is not int or max_symbol_count <= 0:
        raise ProtocolError("max_symbol_count must be a positive integer")

    tb = gr.top_block()

    whitening = lora_sdr.whitening(True, False, ",", "packet_len")
    header_block = lora_sdr.header(False, True, 1)
    crc_block = lora_sdr.add_crc(True)
    hamming = lora_sdr.hamming_enc(1, 7)
    interleaver = lora_sdr.interleaver(1, 7, 0, 500_000)
    gray_demap = lora_sdr.gray_demap(7)
    sink = blocks.vector_sink_i()

    tb.connect(whitening, header_block)
    tb.connect(header_block, crc_block)
    tb.connect(crc_block, hamming)
    tb.connect(hamming, interleaver)
    tb.connect(interleaver, gray_demap)
    tb.connect(gray_demap, sink)

    start_succeeded = False
    tb.start()
    start_succeeded = True
    try:
        whitening.to_basic_block()._post(
            pmt_mod.intern("msg"),
            pmt_mod.intern(request.payload_hex),
        )

        deadline = time.monotonic() + timeout_seconds
        stable_frame_len: int | None = None
        stable_symbols: tuple[int, ...] | None = None
        stable_tag_count: int | None = None
        stable_tag_offset: int | None = None
        stable_tag_key: str | None = None
        stable_tag_value: Any = None

        while True:
            time.sleep(0.01)

            if time.monotonic() >= deadline:
                raise ProtocolError("Oracle execution timed out")

            tags = sink.tags()
            frame_len_tags = [
                t
                for t in tags
                if pmt_mod.symbol_to_string(t.key) == "frame_len"
            ]
            if not frame_len_tags:
                continue
            if len(frame_len_tags) > 1:
                raise ProtocolError("duplicate frame_len tag")
            fl_tag = frame_len_tags[0]
            if fl_tag.offset != 0:
                raise ProtocolError("frame_len tag offset must be zero")
            fl = pmt_mod.to_long(fl_tag.value)
            if type(fl) is not int or fl is True or fl is False:
                raise ProtocolError("frame_len must be a plain integer")
            if fl <= 0:
                raise ProtocolError("frame_len must be positive")
            if fl > max_symbol_count:
                raise ProtocolError("frame_len exceeds max_symbol_count")

            data = tuple(sink.data())
            data_len = len(data)

            for s in data:
                if type(s) is not int or s is True or s is False:
                    raise ProtocolError("output symbols must be plain integers")
            if any(s < 0 or s > 127 for s in data):
                raise ProtocolError("output symbol outside 0..127 range")

            if data_len > fl:
                raise ProtocolError("output symbol count exceeds frame_len")

            if data_len < fl:
                continue

            if stable_frame_len is None:
                stable_frame_len = fl
                stable_symbols = data
                stable_tag_count = len(frame_len_tags)
                stable_tag_offset = fl_tag.offset
                stable_tag_key = pmt_mod.symbol_to_string(fl_tag.key)
                stable_tag_value = fl
                continue

            if (
                data == stable_symbols
                and len(frame_len_tags) == stable_tag_count
                and fl_tag.offset == stable_tag_offset
                and fl == stable_tag_value
            ):
                break

            raise ProtocolError("changed data or frame_len metadata after initial completion")

    finally:
        if start_succeeded:
            _stop_and_wait(tb)

    final_tags = sink.tags()
    final_data = tuple(sink.data())
    final_data_len = len(final_data)

    if final_data_len != stable_frame_len:
        raise ProtocolError("final symbol count differs after stop/wait")

    final_frame_len_tags = [
        t
        for t in final_tags
        if pmt_mod.symbol_to_string(t.key) == "frame_len"
    ]
    if len(final_frame_len_tags) != stable_tag_count:
        raise ProtocolError("final frame_len tag count mismatch")
    if pmt_mod.symbol_to_string(final_frame_len_tags[0].key) != stable_tag_key:
        raise ProtocolError("final frame_len tag key mismatch")
    if final_frame_len_tags[0].offset != stable_tag_offset:
        raise ProtocolError("final frame_len tag offset mismatch")
    final_frame_len = pmt_mod.to_long(final_frame_len_tags[0].value)
    if type(final_frame_len) is not int:
        raise ProtocolError("final frame_len value must be a plain integer")
    if final_frame_len != stable_tag_value:
        raise ProtocolError("final frame_len value mismatch")

    if final_data != stable_symbols:
        raise ProtocolError("final symbol tuple differs from stable snapshot")
    if any(type(s) is not int or s is True or s is False for s in final_data):
        raise ProtocolError("output symbols must be plain integers")
    if any(s < 0 or s > 127 for s in final_data):
        raise ProtocolError("output symbol outside 0..127 range")

    envelope = normalize_dynamic_symbols(
        symbols_zero_based=list(final_data),
        parameters=request.parameters,
        payload_sha256=request.payload_sha256,
        oracle_commit=runtime.oracle_commit,
        oracle_tree=runtime.oracle_tree,
    )

    return envelope


def execute_pinned_oracle(
    *,
    request_path: Path,
    result_path: Path,
    runtime: PinnedOracleRuntime,
    timeout_seconds: float,
    max_symbol_count: int,
) -> SymbolEnvelope:
    concrete_path_type = type(Path())
    if type(request_path) is not concrete_path_type:
        raise ProtocolError("request_path must be an exact concrete pathlib path")
    if type(result_path) is not concrete_path_type:
        raise ProtocolError("result_path must be an exact concrete pathlib path")
    _validate_runtime(runtime)
    if type(timeout_seconds) is bool or type(timeout_seconds) not in (int, float):
        raise ProtocolError("timeout_seconds must be a plain int or float")
    timeout = float(timeout_seconds)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ProtocolError("timeout_seconds must be finite and positive")
    if type(max_symbol_count) is not int or max_symbol_count <= 0:
        raise ProtocolError("max_symbol_count must be a positive integer")

    # Reject an invalid or occupied destination before loading runtime modules or
    # constructing a flowgraph. write_result() repeats this check before publish.
    _validate_new_output_path(result_path, "Oracle result")
    request = load_and_validate_request(request_path)
    modules = _load_runtime(runtime)
    envelope = _execute_with_injected(
        request, runtime, modules, timeout, max_symbol_count
    )
    write_result(result_path, request, envelope)
    return envelope
