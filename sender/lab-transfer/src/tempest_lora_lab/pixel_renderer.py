from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import Any

from .profiles import (
    CAPTURE_GOLDEN_SYMBOLS_ZERO_BASED,
    CaptureReplayRendererProfile,
    DynamicPhyParameters,
    DynamicPixelRendererProfile,
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    SHA256_PATTERN,
    SymbolEnvelope,
)
from .protocol import ProfileId, ProtocolError, canonical_json_bytes


@dataclass(frozen=True)
class CaptureReplayArtifact:
    source_png_sha256: str
    visible_frame_u8: bytes
    canonical_pgm: bytes
    manifest_json: bytes


@dataclass(frozen=True)
class DynamicRenderedPixelArtifact:
    timeline_u8: bytes
    visible_frames_u8: tuple[bytes, ...]
    canonical_pgm_frames: tuple[bytes, ...]
    manifest_json: bytes


def _sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _symbol_hash(symbols: tuple[int, ...]) -> str:
    return _sha256_hex(b"".join(struct.pack(">H", value) for value in symbols))


def _require_lower_sha256(value: Any, label: str) -> None:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise ProtocolError(f"{label} must be lowercase SHA-256 hex")


def _validate_capture_envelope(
    envelope: SymbolEnvelope,
    profile: CaptureReplayRendererProfile,
) -> None:
    if type(envelope) is not SymbolEnvelope:
        raise ProtocolError("capture envelope must be exact SymbolEnvelope")
    if type(envelope.profile_id) is not ProfileId or envelope.profile_id is not ProfileId.CAPTURE_REPLAY:
        raise ProtocolError("capture renderer requires CAPTURE_REPLAY envelope")
    if type(envelope.source_kind) is not str or envelope.source_kind != "published-verified-payloadsymbols-mat":
        raise ProtocolError("capture source_kind mismatch")
    if type(envelope.spreading_factor) is not int or envelope.spreading_factor != 7:
        raise ProtocolError("capture spreading_factor mismatch")
    if type(envelope.index_base) is not int or envelope.index_base != 0:
        raise ProtocolError("capture index_base mismatch")
    if type(envelope.ingress_transform) is not str or envelope.ingress_transform != "stored_Index - 1":
        raise ProtocolError("capture ingress_transform mismatch")
    if type(envelope.symbols) is not tuple or envelope.symbols != CAPTURE_GOLDEN_SYMBOLS_ZERO_BASED:
        raise ProtocolError("capture symbols differ from pinned Golden fixture")
    if any(type(value) is not int for value in envelope.symbols):
        raise ProtocolError("capture symbols must be plain integers")
    if type(envelope.symbols_sha256_uint16be) is not str:
        raise ProtocolError("capture symbol hash must be a string")
    expected_symbol_hash = _symbol_hash(envelope.symbols)
    if envelope.symbols_sha256_uint16be != expected_symbol_hash:
        raise ProtocolError("capture symbol hash mismatch")
    if expected_symbol_hash != profile.symbols_sha256_uint16be:
        raise ProtocolError("capture symbol hash differs from renderer profile")
    if type(envelope.provenance) is not dict:
        raise ProtocolError("capture provenance must be an object")
    if set(envelope.provenance) != {"fixture_sha256", "approved_fixture"}:
        raise ProtocolError("capture provenance keys mismatch")
    if envelope.provenance["approved_fixture"] is not True:
        raise ProtocolError("capture fixture approval must be exact boolean true")
    if type(envelope.provenance["fixture_sha256"]) is not str:
        raise ProtocolError("capture fixture SHA-256 must be a string")
    if envelope.provenance["fixture_sha256"] != profile.symbol_fixture_sha256:
        raise ProtocolError("capture MAT fixture SHA-256 mismatch")


def _validate_dynamic_envelope(
    envelope: SymbolEnvelope,
    profile: DynamicPixelRendererProfile,
) -> None:
    if type(envelope) is not SymbolEnvelope:
        raise ProtocolError("dynamic envelope must be exact SymbolEnvelope")
    if type(envelope.profile_id) is not ProfileId or envelope.profile_id is not ProfileId.DYNAMIC_SOFTWARE_PHY:
        raise ProtocolError("dynamic renderer requires DYNAMIC_SOFTWARE_PHY envelope")
    if type(envelope.source_kind) is not str or envelope.source_kind != "pinned-gr-lora-sdr-result":
        raise ProtocolError("dynamic source_kind mismatch")
    if type(envelope.spreading_factor) is not int or envelope.spreading_factor != profile.supported_spreading_factor:
        raise ProtocolError("dynamic spreading_factor mismatch")
    if type(envelope.index_base) is not int or envelope.index_base != 0:
        raise ProtocolError("dynamic index_base mismatch")
    if type(envelope.ingress_transform) is not str or envelope.ingress_transform != "identity":
        raise ProtocolError("dynamic ingress_transform mismatch")
    if type(envelope.symbols) is not tuple or not envelope.symbols:
        raise ProtocolError("dynamic symbols must be a nonempty exact tuple")
    maximum = (1 << profile.supported_spreading_factor) - 1
    if any(type(value) is not int or not 0 <= value <= maximum for value in envelope.symbols):
        raise ProtocolError("dynamic symbol outside zero-based SF7 domain")
    if type(envelope.symbols_sha256_uint16be) is not str:
        raise ProtocolError("dynamic symbol hash must be a string")
    expected_symbol_hash = _symbol_hash(envelope.symbols)
    if envelope.symbols_sha256_uint16be != expected_symbol_hash:
        raise ProtocolError("dynamic symbol hash mismatch")
    if type(envelope.provenance) is not dict:
        raise ProtocolError("dynamic provenance must be an object")
    expected_keys = {
        "payload_sha256",
        "oracle_commit",
        "oracle_tree",
        "parameters_sha256",
    }
    if set(envelope.provenance) != expected_keys:
        raise ProtocolError("dynamic provenance keys mismatch")
    for key in expected_keys:
        if type(envelope.provenance[key]) is not str:
            raise ProtocolError("dynamic provenance values must be strings")
    _require_lower_sha256(envelope.provenance["payload_sha256"], "payload_sha256")
    _require_lower_sha256(envelope.provenance["parameters_sha256"], "parameters_sha256")
    if envelope.provenance["oracle_commit"] != PINNED_ORACLE_COMMIT:
        raise ProtocolError("dynamic Oracle commit mismatch")
    if envelope.provenance["oracle_tree"] != PINNED_ORACLE_TREE:
        raise ProtocolError("dynamic Oracle tree mismatch")
    if envelope.provenance["parameters_sha256"] != DynamicPhyParameters().descriptor_sha256():
        raise ProtocolError("dynamic PHY parameter hash mismatch")


def _paeth(left: int, above: int, upper_left: int) -> int:
    estimate = left + above - upper_left
    left_distance = abs(estimate - left)
    above_distance = abs(estimate - above)
    upper_left_distance = abs(estimate - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def _decode_png_grayscale8(encoded: bytes) -> bytes:
    if type(encoded) is not bytes:
        raise ProtocolError("PNG fixture must be exact bytes")
    signature = b"\x89PNG\r\n\x1a\n"
    if not encoded.startswith(signature):
        raise ProtocolError("invalid PNG signature")

    offset = len(signature)
    ihdr: tuple[int, int, int, int, int, int, int] | None = None
    idat_parts: list[bytes] = []
    seen_iend = False
    idat_started = False
    idat_finished = False

    while offset < len(encoded):
        if offset + 12 > len(encoded):
            raise ProtocolError("truncated PNG chunk header")
        length = struct.unpack(">I", encoded[offset:offset + 4])[0]
        chunk_type = encoded[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(encoded):
            raise ProtocolError("truncated PNG chunk")
        if len(chunk_type) != 4 or any(
            not (65 <= value <= 90 or 97 <= value <= 122)
            for value in chunk_type
        ):
            raise ProtocolError("invalid PNG chunk type")
        chunk_data = encoded[data_start:data_end]
        stored_crc = struct.unpack(">I", encoded[data_end:crc_end])[0]
        calculated_crc = zlib.crc32(chunk_type)
        calculated_crc = zlib.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            raise ProtocolError("PNG chunk CRC mismatch")

        if chunk_type == b"IHDR":
            if ihdr is not None or offset != len(signature) or length != 13:
                raise ProtocolError("invalid PNG IHDR")
            ihdr = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            if ihdr is None or idat_finished:
                raise ProtocolError("invalid PNG IDAT ordering")
            idat_started = True
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0 or seen_iend:
                raise ProtocolError("invalid PNG IEND")
            seen_iend = True
            offset = crc_end
            break
        else:
            if idat_started:
                idat_finished = True
            if 65 <= chunk_type[0] <= 90:
                raise ProtocolError("unsupported critical PNG chunk")

        offset = crc_end

    if not seen_iend or offset != len(encoded):
        raise ProtocolError("PNG IEND missing or trailing bytes present")
    if ihdr is None or not idat_parts:
        raise ProtocolError("PNG IHDR or IDAT missing")

    (
        width,
        height,
        bit_depth,
        color_type,
        compression_method,
        filter_method,
        interlace_method,
    ) = ihdr
    if (width, height) != (1920, 1080):
        raise ProtocolError("PNG dimensions mismatch")
    if bit_depth != 8 or color_type != 0:
        raise ProtocolError("PNG must be 8-bit grayscale")
    if compression_method != 0 or filter_method != 0 or interlace_method != 0:
        raise ProtocolError("unsupported PNG coding mode")

    inflater = zlib.decompressobj()
    filtered = inflater.decompress(b"".join(idat_parts))
    filtered += inflater.flush()
    if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ProtocolError("invalid PNG zlib stream")

    stride = width
    expected_filtered = height * (stride + 1)
    if len(filtered) != expected_filtered:
        raise ProtocolError("PNG decompressed length mismatch")

    output = bytearray()
    previous = bytearray(stride)
    cursor = 0

    for _ in range(height):
        filter_type = filtered[cursor]
        cursor += 1
        encoded_row = filtered[cursor:cursor + stride]
        cursor += stride
        if filter_type not in {0, 1, 2, 3, 4}:
            raise ProtocolError("unsupported PNG row filter")
        row = bytearray(stride)
        for x, encoded_byte in enumerate(encoded_row):
            left = row[x - 1] if x else 0
            above = previous[x]
            upper_left = previous[x - 1] if x else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            else:
                predictor = _paeth(left, above, upper_left)
            row[x] = (encoded_byte + predictor) & 0xFF
        output.extend(row)
        previous = row

    raw = bytes(output)
    if len(raw) != 1920 * 1080:
        raise ProtocolError("decoded PNG frame length mismatch")
    if set(raw) != {0, 255}:
        raise ProtocolError("decoded PNG is not binary grayscale")
    return raw


def replay_capture_fixture(
    *,
    envelope: SymbolEnvelope,
    fixture_png: bytes,
    profile: CaptureReplayRendererProfile | None = None,
) -> CaptureReplayArtifact:
    if profile is None:
        profile = CaptureReplayRendererProfile()
    if type(profile) is not CaptureReplayRendererProfile:
        raise ProtocolError("profile must be exact CaptureReplayRendererProfile")
    profile.validate()
    _validate_capture_envelope(envelope, profile)
    if type(fixture_png) is not bytes:
        raise ProtocolError("fixture_png must be exact bytes")
    if len(fixture_png) != 21_884:
        raise ProtocolError("capture PNG byte length mismatch")

    source_hash = _sha256_hex(fixture_png)
    if source_hash != profile.image_fixture_sha256:
        raise ProtocolError("capture PNG SHA-256 mismatch")
    raw = _decode_png_grayscale8(fixture_png)
    raw_hash = _sha256_hex(raw)
    if raw_hash != profile.decoded_raw_sha256:
        raise ProtocolError("capture raw frame SHA-256 mismatch")

    black_pixels = raw.count(profile.black_pixel)
    white_pixels = raw.count(profile.white_pixel)
    if black_pixels != 1_704_784 or white_pixels != 368_816:
        raise ProtocolError("capture pixel counts mismatch")

    first_white_index = raw.find(bytes((profile.white_pixel,)))
    last_white_index = raw.rfind(bytes((profile.white_pixel,)))
    if first_white_index < 0 or last_white_index < 0:
        raise ProtocolError("capture fixture contains no white pixels")
    first_white_y, first_white_x = divmod(first_white_index, profile.visible_width)
    last_white_y, last_white_x = divmod(last_white_index, profile.visible_width)
    if (first_white_x, first_white_y) != (1, 0):
        raise ProtocolError("capture first white pixel mismatch")
    if (last_white_x, last_white_y) != (1051, 384):
        raise ProtocolError("capture last white pixel mismatch")

    min_x = profile.visible_width
    max_x = -1
    min_y = profile.visible_height
    max_y = -1
    white_byte = bytes((profile.white_pixel,))
    for y in range(profile.visible_height):
        row = raw[y * profile.visible_width:(y + 1) * profile.visible_width]
        left = row.find(white_byte)
        if left < 0:
            continue
        right = row.rfind(white_byte)
        min_x = min(min_x, left)
        max_x = max(max_x, right)
        min_y = min(min_y, y)
        max_y = max(max_y, y)
    if (min_x, max_x, min_y, max_y) != (0, 1919, 0, 384):
        raise ProtocolError("capture white-pixel bounding box mismatch")

    canonical_pgm = b"P5\n1920 1080\n255\n" + raw
    pgm_hash = _sha256_hex(canonical_pgm)
    if pgm_hash != profile.canonical_pgm_sha256:
        raise ProtocolError("capture canonical PGM SHA-256 mismatch")

    descriptor = profile.descriptor()
    envelope_dict = envelope.to_dict()
    manifest = {
        "schema": "tempest-lora.capture-replay-artifact-manifest.v1",
        "generation_mode": "verified-fixture-replay",
        "algorithmic_reconstruction_claimed": False,
        "transport_capable": False,
        "hidden_raster_reconstructed": False,
        "renderer_descriptor": descriptor,
        "renderer_descriptor_sha256": profile.descriptor_sha256(),
        "envelope": envelope_dict,
        "envelope_sha256": _sha256_hex(canonical_json_bytes(envelope_dict)),
        "mat_fixture_sha256": profile.symbol_fixture_sha256,
        "png_fixture_sha256": source_hash,
        "visible_width": profile.visible_width,
        "visible_height": profile.visible_height,
        "encoded_png_bytes": len(fixture_png),
        "decoded_frame_bytes": len(raw),
        "black_pixels": black_pixels,
        "white_pixels": white_pixels,
        "first_white": [first_white_x, first_white_y],
        "last_white": [last_white_x, last_white_y],
        "white_bounding_box": {
            "min_x": min_x,
            "max_x": max_x,
            "min_y": min_y,
            "max_y": max_y,
        },
        "raw_frame_sha256": raw_hash,
        "canonical_pgm_sha256": pgm_hash,
    }
    return CaptureReplayArtifact(
        source_png_sha256=source_hash,
        visible_frame_u8=raw,
        canonical_pgm=canonical_pgm,
        manifest_json=canonical_json_bytes(manifest),
    )


def _render_chirp(
    *,
    symbol: int,
    down: bool,
    profile: DynamicPixelRendererProfile,
) -> bytes:
    if type(profile) is not DynamicPixelRendererProfile:
        raise ProtocolError("profile must be exact DynamicPixelRendererProfile")
    profile.validate()
    if type(symbol) is not int:
        raise ProtocolError("symbol must be a plain integer")
    if type(down) is not bool:
        raise ProtocolError("down must be an exact boolean")

    chip_count = 1 << profile.supported_spreading_factor
    if not 0 <= symbol < chip_count:
        raise ProtocolError("symbol outside renderer SF domain")

    chirp_numerator = profile.pixel_clock_hz * chip_count
    if chirp_numerator % profile.bandwidth_hz != 0:
        raise ProtocolError("non-integral chirp pixel count")
    chirp_pixels = chirp_numerator // profile.bandwidth_hz
    shift_numerator = chirp_pixels * symbol
    if shift_numerator % chip_count != 0:
        raise ProtocolError("non-integral symbol shift")
    shift = shift_numerator // chip_count

    if profile.bandwidth_hz % 2 != 0:
        raise ProtocolError("bandwidth must permit integral half-band edges")
    low_hz = profile.center_frequency_hz - profile.bandwidth_hz // 2
    high_hz = profile.center_frequency_hz + profile.bandwidth_hz // 2
    if down:
        low_hz, high_hz = high_hz, low_hz

    low_mod = low_hz % profile.pixel_clock_hz
    high_mod = high_hz % profile.pixel_clock_hz
    denominator = profile.pixel_clock_hz * chirp_pixels
    base = low_mod * chirp_pixels
    delta = high_mod - low_mod
    output = bytearray(chirp_pixels)

    for timer in range(chirp_pixels):
        shifted_position = (shift + timer) % chirp_pixels
        numerator = timer * (base + delta * shifted_position)
        phase = numerator % denominator
        if 0 < 2 * phase < denominator:
            output[timer] = profile.white_pixel

    return bytes(output)


def _dynamic_geometry(
    symbol_count: int,
    profile: DynamicPixelRendererProfile,
) -> tuple[int, int, int, int]:
    if type(symbol_count) is not int or symbol_count < 1:
        raise ProtocolError("symbol_count must be a positive plain integer")

    chip_count = 1 << profile.supported_spreading_factor
    chirp_numerator = profile.pixel_clock_hz * chip_count
    if chirp_numerator % profile.bandwidth_hz != 0:
        raise ProtocolError("non-integral chirp pixel count")
    chirp_pixels = chirp_numerator // profile.bandwidth_hz
    if chirp_pixels % 4 != 0:
        raise ProtocolError("chirp pixel count is not divisible by four")

    quarter_chirps = (
        profile.preamble_symbols * 4
        + len(profile.sync_symbols_zero_based) * 4
        + profile.sfd_quarter_chirps
        + symbol_count * 4
    )
    signal_pixels = quarter_chirps * (chirp_pixels // 4)
    prepad_pixels = (
        profile.active_y_start * profile.total_width
        + profile.active_x_start
    )
    occupied_total_pixels = prepad_pixels + signal_pixels
    frame_pixels = profile.total_width * profile.total_height
    frame_count = (
        occupied_total_pixels + frame_pixels - 1
    ) // frame_pixels
    return chirp_pixels, signal_pixels, occupied_total_pixels, frame_count


def render_dynamic_envelope(
    *,
    envelope: SymbolEnvelope,
    profile: DynamicPixelRendererProfile | None = None,
) -> DynamicRenderedPixelArtifact:
    if profile is None:
        profile = DynamicPixelRendererProfile()
    if type(profile) is not DynamicPixelRendererProfile:
        raise ProtocolError("profile must be exact DynamicPixelRendererProfile")
    profile.validate()
    _validate_dynamic_envelope(envelope, profile)

    (
        chirp_pixels,
        expected_signal_pixels,
        occupied_total_pixels,
        frame_count,
    ) = _dynamic_geometry(envelope.symbol_count, profile)
    if frame_count > profile.maximum_frame_count:
        raise ProtocolError("dynamic render exceeds maximum_frame_count")

    cache: dict[tuple[bool, int], bytes] = {}

    def chirp(symbol: int, *, down: bool) -> bytes:
        key = (down, symbol)
        if key not in cache:
            cache[key] = _render_chirp(
                symbol=symbol,
                down=down,
                profile=profile,
            )
        return cache[key]

    up_zero = chirp(0, down=False)
    down_zero = chirp(0, down=True)
    parts: list[bytes] = [up_zero] * profile.preamble_symbols
    parts.extend(chirp(symbol, down=False) for symbol in profile.sync_symbols_zero_based)
    parts.extend((down_zero, down_zero, down_zero[:chirp_pixels // 4]))
    parts.extend(chirp(symbol, down=False) for symbol in envelope.symbols)
    signal = b"".join(parts)
    if len(signal) != expected_signal_pixels:
        raise ProtocolError("dynamic signal length mismatch")

    signal_hash = _sha256_hex(signal)
    frame_pixels = profile.total_width * profile.total_height
    visible_pixels = profile.visible_width * profile.visible_height
    prepad_pixels = (
        profile.active_y_start * profile.total_width
        + profile.active_x_start
    )
    signal_start = prepad_pixels
    signal_end = signal_start + len(signal)

    mutable_frames = [
        bytearray(visible_pixels)
        for _ in range(frame_count)
    ]

    for frame_index, frame in enumerate(mutable_frames):
        frame_base = frame_index * frame_pixels
        for visible_y in range(profile.visible_height):
            visible_total_start = (
                frame_base
                + (profile.active_y_start + visible_y) * profile.total_width
                + profile.active_x_start
            )
            visible_total_end = visible_total_start + profile.visible_width
            intersection_start = max(visible_total_start, signal_start)
            intersection_end = min(visible_total_end, signal_end)
            if intersection_start >= intersection_end:
                continue
            source_start = intersection_start - signal_start
            destination_start = (
                visible_y * profile.visible_width
                + intersection_start
                - visible_total_start
            )
            count = intersection_end - intersection_start
            frame[destination_start:destination_start + count] = (
                signal[source_start:source_start + count]
            )

    raw_frames = tuple(bytes(frame) for frame in mutable_frames)
    for frame in raw_frames:
        if set(frame).difference({profile.black_pixel, profile.white_pixel}):
            raise ProtocolError("dynamic visible frame contains invalid pixel values")

    timeline = bytearray(frame_count * frame_pixels)
    translation = bytearray(256)
    translation[profile.black_pixel] = 1
    translation[profile.white_pixel] = 2
    translation_table = bytes(translation)

    for frame_index, frame in enumerate(raw_frames):
        frame_base = frame_index * frame_pixels
        for visible_y in range(profile.visible_height):
            raw_start = visible_y * profile.visible_width
            timeline_start = (
                frame_base
                + (profile.active_y_start + visible_y) * profile.total_width
                + profile.active_x_start
            )
            timeline[timeline_start:timeline_start + profile.visible_width] = (
                frame[raw_start:raw_start + profile.visible_width].translate(
                    translation_table
                )
            )

    timeline_bytes = bytes(timeline)
    pgm_header = b"P5\n1920 1080\n255\n"
    pgm_frames = tuple(pgm_header + frame for frame in raw_frames)

    raw_hashes = [_sha256_hex(frame) for frame in raw_frames]
    pgm_hashes = [_sha256_hex(frame) for frame in pgm_frames]
    raw_white_counts = [frame.count(profile.white_pixel) for frame in raw_frames]
    raw_black_counts = [visible_pixels - count for count in raw_white_counts]
    hidden_count = frame_count * (frame_pixels - visible_pixels)
    visible_white_count = sum(raw_white_counts)
    visible_black_count = frame_count * visible_pixels - visible_white_count

    final_signal_total_index = occupied_total_pixels - 1
    final_signal_frame_index = final_signal_total_index // frame_pixels
    final_signal_frame_offset = final_signal_total_index % frame_pixels
    final_signal_y, final_signal_x = divmod(
        final_signal_frame_offset,
        profile.total_width,
    )

    descriptor = profile.descriptor()
    envelope_dict = envelope.to_dict()
    manifest = {
        "schema": "tempest-lora.dynamic-pixel-renderer-manifest.v1",
        "generation_mode": "documented-clear-source-renderer",
        "golden_byte_equality_required": False,
        "protected_renderer_equivalence_claimed": False,
        "capture_replay_fixture_used": False,
        "renderer_descriptor": descriptor,
        "renderer_descriptor_sha256": profile.descriptor_sha256(),
        "envelope": envelope_dict,
        "envelope_sha256": _sha256_hex(canonical_json_bytes(envelope_dict)),
        "symbol_count": envelope.symbol_count,
        "symbols_sha256_uint16be": envelope.symbols_sha256_uint16be,
        "chirp_pixels": chirp_pixels,
        "preamble_symbols": profile.preamble_symbols,
        "sync_symbols_zero_based": list(profile.sync_symbols_zero_based),
        "sfd_quarter_chirps": profile.sfd_quarter_chirps,
        "tail_modification": "forbidden",
        "prepad_pixels": prepad_pixels,
        "signal_pixels": len(signal),
        "signal_sha256": signal_hash,
        "occupied_total_pixels": occupied_total_pixels,
        "frame_count": frame_count,
        "timeline_bytes": len(timeline_bytes),
        "timeline_sha256": _sha256_hex(timeline_bytes),
        "timeline_counts": {
            "0": hidden_count,
            "1": visible_black_count,
            "2": visible_white_count,
        },
        "raw_frame_sha256": raw_hashes,
        "raw_frame_black_pixels": raw_black_counts,
        "raw_frame_white_pixels": raw_white_counts,
        "pgm_frame_sha256": pgm_hashes,
        "final_signal_frame_index": final_signal_frame_index,
        "final_signal_total_index": final_signal_total_index,
        "final_signal_x": final_signal_x,
        "final_signal_y": final_signal_y,
    }

    return DynamicRenderedPixelArtifact(
        timeline_u8=timeline_bytes,
        visible_frames_u8=raw_frames,
        canonical_pgm_frames=pgm_frames,
        manifest_json=canonical_json_bytes(manifest),
    )
