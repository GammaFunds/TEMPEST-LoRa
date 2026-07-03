from __future__ import annotations

import importlib
import json
import math
import os
import platform
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, call, patch

from tempest_lora_lab.oracle_boundary import (
    OracleRequest,
    load_and_validate_result,
    write_result,
)
from tempest_lora_lab.profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    normalize_dynamic_symbols,
)
from tempest_lora_lab.protocol import ProtocolError


PINNED_PYTHON_VERSION = "3.12.13"
PINNED_GR_VERSION = "3.10.11.0"


def _make_fake_tag(key: str, offset: int, value: object) -> MagicMock:
    tag = MagicMock()
    tag.key = MagicMock()
    tag.key.__repr__ = MagicMock(return_value=key)
    tag.offset = offset
    tag.value = value
    return tag


def _make_fake_modules(
    frame_len_value: int | None = 7,
    sink_data: list[int] | None = None,
    frame_len_offset: int = 0,
    frame_len_key: str = "frame_len",
    callable_check: bool = True,
) -> dict:
    if sink_data is None:
        sink_data = [13, 9, 1, 13, 61, 109, 49]
    if frame_len_value is None:
        tags: list[MagicMock] = []
    else:
        tags = [_make_fake_tag(frame_len_key, frame_len_offset, frame_len_value)]

    fake_sink = MagicMock()
    fake_sink.tags.return_value = tags
    fake_sink.data.return_value = list(sink_data)

    fake_whitening = MagicMock()
    fake_header = MagicMock()
    fake_crc = MagicMock()
    fake_hamming = MagicMock()
    fake_interleaver = MagicMock()
    fake_gray_demap = MagicMock()
    fake_vector_sink = MagicMock(return_value=fake_sink)

    fake_tb = MagicMock()
    fake_tb.start = MagicMock()
    fake_tb.stop = MagicMock()
    fake_tb.wait = MagicMock()
    fake_tb.connect = MagicMock()

    fake_gr = MagicMock()
    fake_gr.top_block = MagicMock(return_value=fake_tb)
    fake_gr.version = MagicMock(return_value=PINNED_GR_VERSION)

    fake_blocks = MagicMock()
    fake_blocks.vector_sink_i = fake_vector_sink

    fake_pmt = MagicMock()
    fake_pmt.intern = MagicMock(side_effect=lambda x: f"interned-{x}")
    fake_pmt.to_long = MagicMock(side_effect=lambda x: x)
    fake_pmt.symbol_to_string = MagicMock(side_effect=lambda x: str(x))

    fake_lora_sdr = MagicMock()
    fake_lora_sdr.whitening = MagicMock(return_value=fake_whitening)
    fake_lora_sdr.header = MagicMock(return_value=fake_header)
    fake_lora_sdr.add_crc = MagicMock(return_value=fake_crc)
    fake_lora_sdr.hamming_enc = MagicMock(return_value=fake_hamming)
    fake_lora_sdr.interleaver = MagicMock(return_value=fake_interleaver)
    fake_lora_sdr.gray_demap = MagicMock(return_value=fake_gray_demap)
    fake_lora_sdr.__file__ = "/fake/lora_sdr/__init__.py"
    fake_lora_sdr.lora_sdr_python = MagicMock()
    fake_lora_sdr.lora_sdr_python.__file__ = "/fake/lora_sdr/lora_sdr_python.so"

    return {
        "gr": fake_gr,
        "blocks": fake_blocks,
        "pmt": fake_pmt,
        "lora_sdr": fake_lora_sdr,
        "_whitening": fake_whitening,
        "_header": fake_header,
        "_crc": fake_crc,
        "_hamming": fake_hamming,
        "_interleaver": fake_interleaver,
        "_gray_demap": fake_gray_demap,
        "_sink": fake_sink,
        "_tb": fake_tb,
    }


def _make_valid_runtime(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    pyexe = tmp_path / "python3"
    pyexe.write_text("#!/bin/false")
    pyexe.chmod(0o755)

    stage = tmp_path / "site-packages"
    stage.mkdir()

    pkg = stage / "lora_sdr"
    pkg.mkdir()

    init = pkg / "__init__.py"
    init.write_text("")

    binding = pkg / "lora_sdr_python.so"
    binding.write_text("")

    native = tmp_path / "libgnuradio-lora_sdr.so"
    native.write_text("")

    return pyexe, stage, pkg, init, binding, native


def _runtime_from_paths(
    pyexe: Path, stage: Path, pkg: Path, init: Path, binding: Path, native: Path
) -> object:
    from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
    return PinnedOracleRuntime(
        python_executable=pyexe,
        stage_site_packages=stage,
        lora_sdr_package=pkg,
        lora_sdr_init=init,
        lora_sdr_binding=binding,
        native_library=native,
        python_version=PINNED_PYTHON_VERSION,
        gnuradio_version=PINNED_GR_VERSION,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
    )


class ImportIsolationTests(unittest.TestCase):
    def test_tempest_lora_lab_import_isolation(self) -> None:
        with patch.dict("sys.modules"):
            for mod in ("gnuradio", "pmt", "lora_sdr", "uhd", "osmosdr"):
                sys.modules.pop(mod, None)
                sys.modules.pop(mod + ".gr", None)
                sys.modules.pop(mod + ".blocks", None)
                sys.modules.pop(mod + ".lora_sdr", None)
            import tempest_lora_lab
            self.assertIsNotNone(tempest_lora_lab)

    def test_oracle_adapter_import_isolation(self) -> None:
        with patch.dict("sys.modules"):
            for mod in ("gnuradio", "pmt", "lora_sdr", "uhd", "osmosdr"):
                sys.modules.pop(mod, None)
                sys.modules.pop(mod + ".gr", None)
                sys.modules.pop(mod + ".blocks", None)
                sys.modules.pop(mod + ".lora_sdr", None)
            from tempest_lora_lab import oracle_adapter
            self.assertIsNotNone(oracle_adapter)


class PublicApiTests(unittest.TestCase):
    def test_correct_public_api_names(self) -> None:
        import tempest_lora_lab
        self.assertTrue(hasattr(tempest_lora_lab, "load_and_validate_request"))
        self.assertTrue(hasattr(tempest_lora_lab, "write_result"))
        self.assertTrue(hasattr(tempest_lora_lab, "PinnedOracleRuntime"))
        self.assertTrue(hasattr(tempest_lora_lab, "execute_pinned_oracle"))
        self.assertFalse(hasattr(tempest_lora_lab, "load_request"))
        self.assertFalse(hasattr(tempest_lora_lab, "execute_oracle"))


class PinnedOracleRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _paths(self):
        return _make_valid_runtime(self.tmp)

    def test_immutability(self) -> None:
        r = _runtime_from_paths(*self._paths())
        with self.assertRaises(AttributeError):
            r.python_executable = Path("/other")

    def test_all_runtime_fields_are_required(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(TypeError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
            )

    def test_fake_posixpath_class_rejected(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        FakePosixPath = type(
            "PosixPath",
            (),
            {
                "is_absolute": lambda self: True,
                "resolve": lambda self, strict=True: self,
            },
        )
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=FakePosixPath(),
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
            )

    def test_exact_path_required(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable="/wrong-type",
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_relative_path_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=Path("relative"),
                stage_site_packages=Path("relative"),
                lora_sdr_package=Path("relative"),
                lora_sdr_init=Path("relative"),
                lora_sdr_binding=Path("relative"),
                native_library=Path("relative"),
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_symlink_rejected(self) -> None:
        target = self.tmp / "target"
        target.write_text("")
        link = self.tmp / "link"
        link.symlink_to(target)
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=link,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_wrong_file_type_rejected(self) -> None:
        d = self.tmp / "adir"
        d.mkdir()
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=d,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_python_executable_mode_bits(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        pyexe.chmod(0o644)
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_stage_site_packages_validation(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        import shutil
        shutil.rmtree(stage)
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_package_containment(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        outside = self.tmp / "outside_pkg"
        outside.mkdir()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=outside,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_init_basename(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        wrong_init = self.tmp / "wrong_name.py"
        wrong_init.write_text("")
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=wrong_init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_init_containment(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        outside = self.tmp / "outside_init.py"
        outside.write_text("")
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=outside,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_binding_containment(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        outside = self.tmp / "outside.so"
        outside.write_text("")
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=outside,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_native_library_validation(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        native.unlink()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                            python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
)

    def test_wrong_python_version(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
                python_version="9.9.9",
            )

    def test_wrong_gnuradio_version(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                python_version=PINNED_PYTHON_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree=PINNED_ORACLE_TREE,
                gnuradio_version="9.9.9",
            )

    def test_wrong_commit(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_tree=PINNED_ORACLE_TREE,
                oracle_commit="0" * 40,
            )

    def test_wrong_tree(self) -> None:
        pyexe, stage, pkg, init, binding, native = self._paths()
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        with self.assertRaises(ProtocolError):
            PinnedOracleRuntime(
                python_executable=pyexe,
                stage_site_packages=stage,
                lora_sdr_package=pkg,
                lora_sdr_init=init,
                lora_sdr_binding=binding,
                native_library=native,
                python_version=PINNED_PYTHON_VERSION,
                gnuradio_version=PINNED_GR_VERSION,
                oracle_commit=PINNED_ORACLE_COMMIT,
                oracle_tree="0" * 40,
            )


class LoaderConstructorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _runtime(self) -> object:
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        return _runtime_from_paths(pyexe, stage, pkg, init, binding, native)

    def test_missing_top_block(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["gr"].top_block = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_vector_sink_i(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["blocks"].vector_sink_i = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_whitening(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["lora_sdr"].whitening = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_header(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["lora_sdr"].header = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_add_crc(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["lora_sdr"].add_crc = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_hamming_enc(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["lora_sdr"].hamming_enc = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_interleaver(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["lora_sdr"].interleaver = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_gray_demap(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["lora_sdr"].gray_demap = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_pmt_intern(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["pmt"].intern = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_pmt_to_long(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["pmt"].to_long = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_missing_pmt_symbol_to_string(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules()
        mods["pmt"].symbol_to_string = None
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(TypeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_seven_blocks_constructed(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        mods["lora_sdr"].whitening.assert_called_once_with(True, False, ",", "packet_len")
        mods["lora_sdr"].header.assert_called_once_with(False, True, 1)
        mods["lora_sdr"].add_crc.assert_called_once_with(True)
        mods["lora_sdr"].hamming_enc.assert_called_once_with(1, 7)
        mods["lora_sdr"].interleaver.assert_called_once_with(1, 7, 0, 500_000)
        mods["lora_sdr"].gray_demap.assert_called_once_with(7)
        mods["blocks"].vector_sink_i.assert_called_once_with()

    def test_six_stream_connections(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        expected_connects = [
            call(mods["_whitening"], mods["_header"]),
            call(mods["_header"], mods["_crc"]),
            call(mods["_crc"], mods["_hamming"]),
            call(mods["_hamming"], mods["_interleaver"]),
            call(mods["_interleaver"], mods["_gray_demap"]),
            call(mods["_gray_demap"], mods["_sink"]),
        ]
        mods["_tb"].connect.assert_has_calls(expected_connects, any_order=False)

    def test_exact_pmt_msg_port(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        mods["pmt"].intern.assert_any_call("msg")

    def test_exact_payload_hex_message(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        mods["pmt"].intern.assert_any_call(request.payload_hex)

    def test_modulate_not_accessed(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        attrs = [name for name in dir(mods["lora_sdr"]) if "modulate" in name.lower()]
        self.assertFalse(attrs)

    def test_lora_sdr_lora_tx_not_accessed(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        attrs = [name for name in dir(mods["lora_sdr"]) if "lora_tx" in name.lower()]
        self.assertFalse(attrs)

    def test_prohibited_modules_not_accessed(self) -> None:
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)
        import re as _re
        gr_repr = repr(mods["gr"])
        blocks_repr = repr(mods["blocks"])
        lora_repr = repr(mods["lora_sdr"])
        for attr in ("uhd", "osmosdr", "modulate"):
            pattern = _re.escape(attr)
            self.assertFalse(_re.search(pattern, gr_repr, _re.IGNORECASE))
            self.assertFalse(_re.search(pattern, blocks_repr, _re.IGNORECASE))
            self.assertFalse(_re.search(pattern, lora_repr, _re.IGNORECASE))

    def test_exact_import_module_names(self) -> None:
        _real_import_module = importlib.import_module
        runtime = self._runtime()
        mods = _make_fake_modules(frame_len_value=7)
        mods["lora_sdr"].__file__ = str(runtime.lora_sdr_init)
        mods["lora_sdr"].lora_sdr_python.__file__ = str(runtime.lora_sdr_binding)
        import_names = []

        def _capture_import(name, *args, **kw):
            import_names.append(name)
            if name == "gnuradio.gr":
                return mods["gr"]
            if name == "gnuradio.blocks":
                return mods["blocks"]
            if name == "pmt":
                return mods["pmt"]
            if name == "gnuradio.lora_sdr":
                return mods["lora_sdr"]
            return _real_import_module(name)

        with patch("importlib.import_module", side_effect=_capture_import):
            with patch("platform.python_version", return_value=PINNED_PYTHON_VERSION):
                with patch.object(sys, "executable", str(runtime.python_executable)):
                    from tempest_lora_lab.oracle_adapter import _load_runtime
                    _load_runtime(runtime)

        self.assertIn("gnuradio.lora_sdr", import_names)
        self.assertNotIn("lora_sdr", import_names)


class ExecuteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self._sleep_patch = patch("tempest_lora_lab.oracle_adapter.time.sleep")
        self._sleep_patch.start()

    def tearDown(self) -> None:
        self._sleep_patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _runtime(self) -> object:
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        return _runtime_from_paths(pyexe, stage, pkg, init, binding, native)

    def _execute(self, mods: dict | None = None, **kw) -> object:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        if mods is None:
            mods = _make_fake_modules(frame_len_value=7)
        request = OracleRequest.from_payload(b"ABC")
        timeout = kw.pop("timeout_seconds", 1.0)
        max_sym = kw.pop("max_symbol_count", 100)
        return _execute_with_injected(request, self._runtime(), mods, timeout, max_sym)

    def _execute_with_tags(
        self,
        frame_len_value: int | None = 7,
        sink_data: list[int] | None = None,
        frame_len_offset: int = 0,
    ) -> object:
        mods = _make_fake_modules(
            frame_len_value=frame_len_value,
            sink_data=sink_data,
            frame_len_offset=frame_len_offset,
        )
        return self._execute(mods)

    def test_valid_fake_execution(self) -> None:
        env = self._execute_with_tags(frame_len_value=7)
        self.assertIsNotNone(env)
        self.assertEqual(env.profile_id, 2)

    def test_timeout(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=None)
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 0.01, 100)

    def test_timeout_false_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, False, 100)

    def test_timeout_true_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, True, 100)

    def test_timeout_nan_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, float("nan"), 100)

    def test_timeout_infinity_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, float("inf"), 100)

    def test_timeout_neg_infinity_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, float("-inf"), 100)

    def test_timeout_zero_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 0, 100)

    def test_timeout_negative_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, -1.0, 100)

    def test_max_symbol_count_bool_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, True)

    def test_max_symbol_count_zero_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules()
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 0)

    def test_no_frame_len_tag_times_out(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=None)
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 0.01, 100)

    def test_duplicate_frame_len_offset_zero_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=None)
        tag_a = _make_fake_tag("frame_len", 0, 7)
        tag_b = _make_fake_tag("frame_len", 0, 7)
        mods["_sink"].tags.return_value = [tag_a, tag_b]
        mods["_sink"].data.return_value = [13, 9, 1, 13, 61, 109, 49]
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_duplicate_frame_len_different_offsets_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=None)
        tag_a = _make_fake_tag("frame_len", 0, 7)
        tag_b = _make_fake_tag("frame_len", 5, 7)
        mods["_sink"].tags.return_value = [tag_a, tag_b]
        mods["_sink"].data.return_value = [13, 9, 1, 13, 61, 109, 49]
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_wrong_offset_frame_len_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=7, frame_len_offset=5)
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_noninteger_frame_len_rejected(self) -> None:
        mods = _make_fake_modules(frame_len_value="seven")
        request = OracleRequest.from_payload(b"ABC")
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_boolean_frame_len_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=True)
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_zero_frame_len_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=0)
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_negative_frame_len_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=-1)
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_excessive_frame_len_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=200, sink_data=list(range(200)))
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_too_few_symbols_until_timeout(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=10, sink_data=[1, 2, 3])
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 0.01, 100)

    def test_too_many_symbols_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3, sink_data=[1, 2, 3, 4])
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_same_length_changed_symbols_causes_failure(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3)

        class _ChangingSink:
            def __init__(self):
                self.call_count = 0

            def tags(self):
                return [_make_fake_tag("frame_len", 0, 3)]

            def data(self):
                self.call_count += 1
                if self.call_count <= 2:
                    return [1, 2, 3]
                return [4, 5, 6]

        custom_sink = _ChangingSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_changed_tags_between_observations_causes_failure(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3)

        class _ChangingTagsSink:
            def __init__(self):
                self.call_count = 0

            def tags(self):
                self.call_count += 1
                if self.call_count <= 2:
                    return [_make_fake_tag("frame_len", 0, 3)]
                return [_make_fake_tag("frame_len", 0, 4)]

            def data(self):
                return [1, 2, 3]

        custom_sink = _ChangingTagsSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_boolean_symbol_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=7, sink_data=[True, 2, 3, 4, 5, 6, 7])
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_noninteger_symbol_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=7, sink_data=["x", 2, 3, 4, 5, 6, 7])
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_negative_symbol_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=7, sink_data=[-1, 2, 3, 4, 5, 6, 7])
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_symbol_over_127_rejected(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=7, sink_data=[128, 2, 3, 4, 5, 6, 7])
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_stop_and_wait_called_after_success(self) -> None:
        mods = _make_fake_modules(frame_len_value=7)
        self._execute(mods)
        mods["_tb"].stop.assert_called_once()
        mods["_tb"].wait.assert_called_once()

    def test_wait_is_attempted_when_stop_fails(self) -> None:
        mods = _make_fake_modules(frame_len_value=7)
        mods["_tb"].stop.side_effect = RuntimeError("stop failed")
        with self.assertRaises(RuntimeError):
            self._execute(mods)
        mods["_tb"].wait.assert_called_once()

    def test_stop_and_wait_not_called_when_start_fails(self) -> None:
        mods = _make_fake_modules(frame_len_value=7)
        mods["_tb"].start = MagicMock(side_effect=RuntimeError("start failed"))
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(RuntimeError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)
        mods["_tb"].stop.assert_not_called()
        mods["_tb"].wait.assert_not_called()

    def test_final_tag_count_mismatch_after_stop(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3)

        class _MismatchSink:
            def __init__(self):
                self.phase = "run"

            def tags(self):
                if self.phase == "run":
                    return [_make_fake_tag("frame_len", 0, 3)]
                return []

            def data(self):
                if self.phase == "run":
                    self.phase = "stop"
                    return [1, 2, 3]
                return [1, 2, 3]

        custom_sink = _MismatchSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_final_offset_mismatch_after_stop(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3)

        class _OffsetMismatchSink:
            def __init__(self):
                self.phase = "run"

            def tags(self):
                if self.phase == "run":
                    return [_make_fake_tag("frame_len", 0, 3)]
                return [_make_fake_tag("frame_len", 5, 3)]

            def data(self):
                if self.phase == "run":
                    self.phase = "stop"
                    return [1, 2, 3]
                return [1, 2, 3]

        custom_sink = _OffsetMismatchSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_final_frame_len_value_mismatch(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3)

        class _ValueMismatchSink:
            def __init__(self):
                self.phase = "run"

            def tags(self):
                if self.phase == "run":
                    return [_make_fake_tag("frame_len", 0, 3)]
                return [_make_fake_tag("frame_len", 0, 5)]

            def data(self):
                if self.phase == "run":
                    self.phase = "stop"
                    return [1, 2, 3]
                return [1, 2, 3]

        custom_sink = _ValueMismatchSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_final_symbol_tuple_mismatch(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=3)

        class _SymbolMismatchSink:
            def __init__(self):
                self.phase = "run"

            def tags(self):
                return [_make_fake_tag("frame_len", 0, 3)]

            def data(self):
                if self.phase == "run":
                    self.phase = "stop"
                    return [1, 2, 3]
                return [4, 5, 6]

        custom_sink = _SymbolMismatchSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 1.0, 100)

    def test_result_remains_absent_after_execution_failure(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=None)
        request = OracleRequest.from_payload(b"ABC")
        result_path = self.tmp / "result.json"
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, self._runtime(), mods, 0.01, 100)
        self.assertFalse(result_path.exists())


class PublicExecutionPreflightTests(unittest.TestCase):
    def test_existing_result_rejected_before_runtime_load(self) -> None:
        from tempest_lora_lab.oracle_adapter import execute_pinned_oracle
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            result_path = root / "result.json"
            result_path.write_text("existing", encoding="ascii")
            with patch(
                "tempest_lora_lab.oracle_adapter._load_runtime"
            ) as load_runtime:
                with self.assertRaises(ProtocolError):
                    execute_pinned_oracle(
                        request_path=request_path,
                        result_path=result_path,
                        runtime=object(),
                        timeout_seconds=1.0,
                        max_symbol_count=100,
                    )
            load_runtime.assert_not_called()


class IntegrationExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execution_returns_symbol_envelope(self) -> None:
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected, PinnedOracleRuntime
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        runtime = PinnedOracleRuntime(
            python_executable=pyexe,
            stage_site_packages=stage,
            lora_sdr_package=pkg,
            lora_sdr_init=init,
            lora_sdr_binding=binding,
            native_library=native,
                python_version=PINNED_PYTHON_VERSION,
        gnuradio_version=PINNED_GR_VERSION,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
)
        request = OracleRequest.from_payload(b"ABC")
        envelope = _execute_with_injected(request, runtime, mods, 1.0, 100)
        from tempest_lora_lab.profiles import SymbolEnvelope
        self.assertIsInstance(envelope, SymbolEnvelope)

    def test_result_validates_through_load_and_validate_result(self) -> None:
        mods = _make_fake_modules(frame_len_value=7)
        from tempest_lora_lab.oracle_adapter import _execute_with_injected, PinnedOracleRuntime
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        runtime = PinnedOracleRuntime(
            python_executable=pyexe,
            stage_site_packages=stage,
            lora_sdr_package=pkg,
            lora_sdr_init=init,
            lora_sdr_binding=binding,
            native_library=native,
                python_version=PINNED_PYTHON_VERSION,
        gnuradio_version=PINNED_GR_VERSION,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
)
        request = OracleRequest.from_payload(b"ABC")
        envelope = _execute_with_injected(request, runtime, mods, 1.0, 100)
        result_path = self.tmp / "result.json"
        write_result(result_path, request, envelope)
        loaded = load_and_validate_result(result_path, request)
        self.assertEqual(loaded, envelope)

    def test_no_sys_path_mutation(self) -> None:
        original = list(sys.path)
        mods = _make_fake_modules(frame_len_value=7)
        self._test_no_mutation(mods)
        self.assertEqual(sys.path, original)

    def test_no_os_environ_mutation(self) -> None:
        original = dict(os.environ)
        mods = _make_fake_modules(frame_len_value=7)
        self._test_no_mutation(mods)
        self.assertEqual(os.environ, original)

    def _test_no_mutation(self, mods: dict) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        runtime = PinnedOracleRuntime(
            python_executable=pyexe,
            stage_site_packages=stage,
            lora_sdr_package=pkg,
            lora_sdr_init=init,
            lora_sdr_binding=binding,
            native_library=native,
                python_version=PINNED_PYTHON_VERSION,
        gnuradio_version=PINNED_GR_VERSION,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
)
        request = OracleRequest.from_payload(b"ABC")
        _execute_with_injected(request, runtime, mods, 1.0, 100)

    def test_stop_and_wait_after_post_start_failure(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected
        mods = _make_fake_modules(frame_len_value=7)
        mods["_whitening"].to_basic_block = MagicMock(side_effect=RuntimeError("post fail"))
        request = OracleRequest.from_payload(b"ABC")
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        from tempest_lora_lab.oracle_adapter import PinnedOracleRuntime
        runtime = PinnedOracleRuntime(
            python_executable=pyexe,
            stage_site_packages=stage,
            lora_sdr_package=pkg,
            lora_sdr_init=init,
            lora_sdr_binding=binding,
            native_library=native,
                python_version=PINNED_PYTHON_VERSION,
        gnuradio_version=PINNED_GR_VERSION,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
)
        with self.assertRaises(RuntimeError):
            _execute_with_injected(request, runtime, mods, 1.0, 100)
        mods["_tb"].stop.assert_called_once()
        mods["_tb"].wait.assert_called_once()

    def test_trailing_symbols_after_stable_observation(self) -> None:
        from tempest_lora_lab.oracle_adapter import _execute_with_injected, PinnedOracleRuntime
        pyexe, stage, pkg, init, binding, native = _make_valid_runtime(self.tmp)
        runtime = PinnedOracleRuntime(
            python_executable=pyexe,
            stage_site_packages=stage,
            lora_sdr_package=pkg,
            lora_sdr_init=init,
            lora_sdr_binding=binding,
            native_library=native,
                python_version=PINNED_PYTHON_VERSION,
        gnuradio_version=PINNED_GR_VERSION,
        oracle_commit=PINNED_ORACLE_COMMIT,
        oracle_tree=PINNED_ORACLE_TREE,
)
        mods = _make_fake_modules(frame_len_value=3)

        class _TrailingSink:
            def __init__(self):
                self.call_count = 0

            def tags(self):
                return [_make_fake_tag("frame_len", 0, 3)]

            def data(self):
                self.call_count += 1
                if self.call_count <= 2:
                    return [1, 2, 3]
                if self.call_count <= 2:
                    return [1, 2, 3]
                return [1, 2, 3, 4]

        custom_sink = _TrailingSink()
        mods["_sink"] = custom_sink
        mods["blocks"].vector_sink_i.return_value = custom_sink
        request = OracleRequest.from_payload(b"ABC")
        with self.assertRaises(ProtocolError):
            _execute_with_injected(request, runtime, mods, 5.0, 100)


if __name__ == "__main__":
    unittest.main()
