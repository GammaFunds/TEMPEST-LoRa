from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .protocol import MAX_FIXTURE_BYTES, ProtocolError

DEFAULT_INPUT_ROOT = Path("/home/miko/lab/fixtures/TEMPEST-LoRa/input")
FIXTURE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


@dataclass(frozen=True)
class SyntheticFixture:
    fixture_id: str
    path: Path
    size: int
    sha256: str
    content: bytes


def _canonical_existing_path(path: Path, label: str) -> Path:
    if not isinstance(path, Path):
        raise ProtocolError(f"{label} must be a pathlib.Path")
    if not path.is_absolute():
        raise ProtocolError(f"{label} must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError(f"{label} is unavailable") from exc
    if resolved != path:
        raise ProtocolError(f"{label} must be canonical and symlink-free")
    return resolved


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and stat.S_IFMT(left.st_mode) == stat.S_IFMT(right.st_mode)
    )


def _same_file_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _same_file_identity(left, right)
        and left.st_size == right.st_size
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def read_synthetic_fixture(
    path: Path,
    *,
    fixture_id: str,
    required_root: Path = DEFAULT_INPUT_ROOT,
) -> SyntheticFixture:
    if type(fixture_id) is not str or FIXTURE_ID_PATTERN.fullmatch(fixture_id) is None:
        raise ProtocolError("fixture_id must match [A-Za-z0-9._-]{1,32}")

    root = _canonical_existing_path(required_root, "required input root")
    candidate = _canonical_existing_path(path, "input fixture")

    if not root.is_dir():
        raise ProtocolError("required input root is not a directory")

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProtocolError("input path is outside the required lab root") from exc

    initial_stat = candidate.stat(follow_symlinks=False)
    if not stat.S_ISREG(initial_stat.st_mode):
        raise ProtocolError("input fixture must be a regular file")
    if not 1 <= initial_stat.st_size <= MAX_FIXTURE_BYTES:
        raise ProtocolError("input fixture size outside v1 bounds")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        fd = os.open(candidate, flags)
    except OSError as exc:
        raise ProtocolError("input fixture could not be opened safely") from exc

    try:
        opened_stat = os.fstat(fd)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ProtocolError("opened input is not a regular file")
        if not _same_file_snapshot(initial_stat, opened_stat):
            raise ProtocolError("input fixture changed before open")

        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = MAX_FIXTURE_BYTES + 1 - total
            chunk = os.read(fd, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FIXTURE_BYTES:
                raise ProtocolError("input fixture exceeded the bounded read")

        final_fd_stat = os.fstat(fd)
        if not _same_file_snapshot(opened_stat, final_fd_stat):
            raise ProtocolError("input fixture changed during read")

        try:
            final_path = candidate.resolve(strict=True)
            final_path_stat = candidate.stat(follow_symlinks=False)
        except (OSError, RuntimeError) as exc:
            raise ProtocolError("input fixture path changed during read") from exc

        if final_path != candidate:
            raise ProtocolError("input fixture path became non-canonical")
        if not _same_file_snapshot(opened_stat, final_path_stat):
            raise ProtocolError("input fixture path identity changed during read")

        content = b"".join(chunks)
    finally:
        os.close(fd)

    if len(content) != opened_stat.st_size:
        raise ProtocolError("input fixture read length mismatch")

    return SyntheticFixture(
        fixture_id=fixture_id,
        path=candidate,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )
