from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .pixel_renderer import DynamicRenderedPixelArtifact
from .profiles import (
    PINNED_ORACLE_COMMIT,
    PINNED_ORACLE_TREE,
    DynamicPhyParameters,
    DynamicPixelRendererProfile,
)
from .protocol import ProtocolError, canonical_json_bytes

R2E1_CONTRACT_SHA256 = "d6b06815ea9e4e077170067c742a87d347766bd484d63fcb1996564524a739c4"
DISPLAY_SESSION_SCHEMA = "tempest-lora.exact-timing-display-session-manifest.v1"
XRGB8888_FOURCC = "DRM_FORMAT_XRGB8888"
LINEAR_MODIFIER = "DRM_FORMAT_MOD_LINEAR"
PGM_HEADER = b"P5\n1920 1080\n255\n"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CARD_PATH_RE = re.compile(r"^/dev/dri/card[0-9]+$")
DEVICE_ID_RE = re.compile(r"^[0-9]+:[0-9]+$")


@dataclass(frozen=True)
class ExactDisplayMode:
    clock_khz: int = 148_500
    hdisplay: int = 1920
    hsync_start: int = 2008
    hsync_end: int = 2052
    htotal: int = 2200
    vdisplay: int = 1080
    vsync_start: int = 1084
    vsync_end: int = 1089
    vtotal: int = 1125
    positive_hsync: bool = True
    positive_vsync: bool = True
    interlaced: bool = False
    doublescan: bool = False

    def validate(self) -> None:
        expected = ExactDisplayMode()
        if type(self) is not ExactDisplayMode:
            raise ProtocolError("mode must be exact ExactDisplayMode")
        if self != expected:
            raise ProtocolError("display mode differs from exact R2E.1 VIC-16 contract")

    @property
    def frame_rate(self) -> Fraction:
        self.validate()
        return Fraction(self.clock_khz * 1000, self.htotal * self.vtotal)

    def descriptor(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "tempest-lora.exact-display-mode.v1",
            "standard": "CTA-861-VIC-16",
            "clock_khz": self.clock_khz,
            "hdisplay": self.hdisplay,
            "hsync_start": self.hsync_start,
            "hsync_end": self.hsync_end,
            "htotal": self.htotal,
            "vdisplay": self.vdisplay,
            "vsync_start": self.vsync_start,
            "vsync_end": self.vsync_end,
            "vtotal": self.vtotal,
            "positive_hsync": self.positive_hsync,
            "positive_vsync": self.positive_vsync,
            "interlaced": self.interlaced,
            "doublescan": self.doublescan,
            "frame_rate_numerator": self.frame_rate.numerator,
            "frame_rate_denominator": self.frame_rate.denominator,
        }


@dataclass(frozen=True)
class ExactKmsSnapshot:
    device_path: str
    device_identity: str
    driver_name: str
    atomic_capable: bool
    drm_master: bool
    exclusive_control: bool
    connector_id: int
    connector_type: str
    connected: bool
    edid_sha256: str
    edid_valid: bool
    mode: ExactDisplayMode
    mode_advertised: bool
    crtc_id: int
    plane_id: int
    plane_type: str
    supported_formats: tuple[str, ...]
    supported_modifiers: tuple[str, ...]
    src_rect_16_16: tuple[int, int, int, int]
    dst_rect: tuple[int, int, int, int]
    rotation: str
    reflection: bool
    overlays_disabled: bool
    cursor_disabled: bool
    vrr_enabled: bool
    degamma_lut_enabled: bool
    ctm_enabled: bool
    gamma_lut_enabled: bool
    hdr_metadata_enabled: bool
    colorspace: str
    broadcast_rgb: str
    bits_per_component: int
    scaling_mode: str
    unknown_affecting_properties: tuple[str, ...]
    topology_token: str

    def validate(self) -> None:
        if type(self) is not ExactKmsSnapshot:
            raise ProtocolError("snapshot must be exact ExactKmsSnapshot")
        if type(self.device_path) is not str or CARD_PATH_RE.fullmatch(self.device_path) is None:
            raise ProtocolError("device_path must be exact canonical /dev/dri/cardN form")
        if type(self.device_identity) is not str or DEVICE_ID_RE.fullmatch(self.device_identity) is None:
            raise ProtocolError("device_identity must be major:minor")
        if type(self.driver_name) is not str or not self.driver_name or not self.driver_name.isascii():
            raise ProtocolError("driver_name must be nonempty ASCII")
        for name in ("atomic_capable", "drm_master", "exclusive_control", "connected", "edid_valid", "mode_advertised"):
            if getattr(self, name) is not True:
                raise ProtocolError(f"{name} must be exact true")
        for name in ("connector_id", "crtc_id", "plane_id"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ProtocolError(f"{name} must be a positive plain integer")
        if type(self.connector_type) is not str or not self.connector_type:
            raise ProtocolError("connector_type must be nonempty")
        _require_sha256(self.edid_sha256, "edid_sha256")
        if type(self.mode) is not ExactDisplayMode:
            raise ProtocolError("mode must be exact ExactDisplayMode")
        self.mode.validate()
        if self.plane_type != "Primary":
            raise ProtocolError("only a primary plane is permitted")
        if (
            type(self.supported_formats) is not tuple
            or not self.supported_formats
            or any(type(value) is not str or not value or not value.isascii() for value in self.supported_formats)
            or len(set(self.supported_formats)) != len(self.supported_formats)
        ):
            raise ProtocolError("supported_formats must be a unique nonempty ASCII string tuple")
        if XRGB8888_FOURCC not in self.supported_formats:
            raise ProtocolError("primary plane lacks XRGB8888")
        if (
            type(self.supported_modifiers) is not tuple
            or not self.supported_modifiers
            or any(type(value) is not str or not value or not value.isascii() for value in self.supported_modifiers)
            or len(set(self.supported_modifiers)) != len(self.supported_modifiers)
        ):
            raise ProtocolError("supported_modifiers must be a unique nonempty ASCII string tuple")
        if LINEAR_MODIFIER not in self.supported_modifiers:
            raise ProtocolError("primary plane lacks LINEAR modifier")
        if self.src_rect_16_16 != (0, 0, 1920 << 16, 1080 << 16):
            raise ProtocolError("source rectangle is not exact identity geometry")
        if self.dst_rect != (0, 0, 1920, 1080):
            raise ProtocolError("destination rectangle is not exact identity geometry")
        if self.rotation != "rotate-0" or self.reflection is not False:
            raise ProtocolError("rotation or reflection is forbidden")
        if self.overlays_disabled is not True or self.cursor_disabled is not True:
            raise ProtocolError("all non-primary planes must be disabled")
        for name in (
            "vrr_enabled",
            "degamma_lut_enabled",
            "ctm_enabled",
            "gamma_lut_enabled",
            "hdr_metadata_enabled",
        ):
            if getattr(self, name) is not False:
                raise ProtocolError(f"{name} must be exact false")
        if self.colorspace not in {"Default", "RGB"}:
            raise ProtocolError("colorspace must be default non-HDR RGB")
        if self.broadcast_rgb != "Full":
            raise ProtocolError("Broadcast RGB must be pinned Full")
        if type(self.bits_per_component) is not int or self.bits_per_component != 8:
            raise ProtocolError("bits_per_component must be exact 8")
        if self.scaling_mode != "None":
            raise ProtocolError("scaling mode must be None")
        if type(self.unknown_affecting_properties) is not tuple or self.unknown_affecting_properties:
            raise ProtocolError("unknown pixel- or timing-affecting properties are forbidden")
        if type(self.topology_token) is not str or not self.topology_token or not self.topology_token.isascii():
            raise ProtocolError("topology_token must be nonempty ASCII")

    def descriptor(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "tempest-lora.exact-kms-snapshot.v1",
            "device_path": self.device_path,
            "device_identity": self.device_identity,
            "driver_name": self.driver_name,
            "atomic_capable": self.atomic_capable,
            "drm_master": self.drm_master,
            "exclusive_control": self.exclusive_control,
            "connector_id": self.connector_id,
            "connector_type": self.connector_type,
            "connected": self.connected,
            "edid_sha256": self.edid_sha256,
            "edid_valid": self.edid_valid,
            "mode": self.mode.descriptor(),
            "mode_advertised": self.mode_advertised,
            "crtc_id": self.crtc_id,
            "plane_id": self.plane_id,
            "plane_type": self.plane_type,
            "supported_formats": list(self.supported_formats),
            "supported_modifiers": list(self.supported_modifiers),
            "src_rect_16_16": list(self.src_rect_16_16),
            "dst_rect": list(self.dst_rect),
            "rotation": self.rotation,
            "reflection": self.reflection,
            "overlays_disabled": self.overlays_disabled,
            "cursor_disabled": self.cursor_disabled,
            "vrr_enabled": self.vrr_enabled,
            "degamma_lut_enabled": self.degamma_lut_enabled,
            "ctm_enabled": self.ctm_enabled,
            "gamma_lut_enabled": self.gamma_lut_enabled,
            "hdr_metadata_enabled": self.hdr_metadata_enabled,
            "colorspace": self.colorspace,
            "broadcast_rgb": self.broadcast_rgb,
            "bits_per_component": self.bits_per_component,
            "scaling_mode": self.scaling_mode,
            "unknown_affecting_properties": list(self.unknown_affecting_properties),
            "topology_token": self.topology_token,
        }


@dataclass(frozen=True)
class ValidatedDynamicDisplayArtifact:
    manifest_sha256: str
    renderer_descriptor_sha256: str
    envelope_sha256: str
    timeline_sha256: str
    frame_count: int
    raw_frame_sha256: tuple[str, ...]
    pgm_frame_sha256: tuple[str, ...]


@dataclass(frozen=True)
class PreparedScanoutBuffers:
    validated: ValidatedDynamicDisplayArtifact
    guard_black_xrgb8888: bytes
    guard_black_sha256: str
    data_xrgb8888: tuple[bytes, ...]
    data_xrgb8888_sha256: tuple[str, ...]


def _require_sha256(value: Any, label: str) -> None:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ProtocolError(f"{label} must be lowercase SHA-256 hex")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_r2e1_contract_bytes(value: bytes) -> dict[str, Any]:
    if type(value) is not bytes:
        raise ProtocolError("R2E.1 contract must be exact bytes")
    if _sha256(value) != R2E1_CONTRACT_SHA256:
        raise ProtocolError("R2E.1 contract SHA-256 mismatch")
    try:
        decoded = value.decode("ascii")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("R2E.1 contract is not canonical ASCII JSON") from exc
    if canonical_json_bytes(parsed) + b"\n" != value:
        raise ProtocolError("R2E.1 contract bytes are not canonical")
    if parsed.get("schema") != "tempest-lora.r2e1-exact-timing-display-contract.v1":
        raise ProtocolError("R2E.1 contract schema mismatch")
    if parsed.get("status") != "read-only-design-complete":
        raise ProtocolError("R2E.1 contract status mismatch")
    basis = parsed.get("repository_basis")
    if type(basis) is not dict or basis.get("commit") != "8e326e2e4537e5afb2f3823f79bf1671e2a180aa":
        raise ProtocolError("R2E.1 repository basis mismatch")
    return parsed


def _parse_manifest(value: bytes) -> dict[str, Any]:
    if type(value) is not bytes:
        raise ProtocolError("manifest_json must be exact bytes")
    try:
        parsed = json.loads(value.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("manifest_json must be canonical ASCII JSON") from exc
    if type(parsed) is not dict or canonical_json_bytes(parsed) != value:
        raise ProtocolError("manifest_json is not canonical JSON")
    return parsed


def validate_dynamic_display_artifact(
    artifact: DynamicRenderedPixelArtifact,
    *,
    profile: DynamicPixelRendererProfile | None = None,
) -> ValidatedDynamicDisplayArtifact:
    if type(artifact) is not DynamicRenderedPixelArtifact:
        raise ProtocolError("display backend requires exact DynamicRenderedPixelArtifact")
    if profile is None:
        profile = DynamicPixelRendererProfile()
    if type(profile) is not DynamicPixelRendererProfile:
        raise ProtocolError("profile must be exact DynamicPixelRendererProfile")
    profile.validate()

    if type(artifact.visible_frames_u8) is not tuple:
        raise ProtocolError("visible_frames_u8 must be exact tuple")
    frame_count = len(artifact.visible_frames_u8)
    if not 1 <= frame_count <= profile.maximum_frame_count:
        raise ProtocolError("frame_count outside 1..16")
    if type(artifact.canonical_pgm_frames) is not tuple or len(artifact.canonical_pgm_frames) != frame_count:
        raise ProtocolError("canonical_pgm_frames count mismatch")
    if type(artifact.timeline_u8) is not bytes:
        raise ProtocolError("timeline_u8 must be exact bytes")

    manifest = _parse_manifest(artifact.manifest_json)
    expected_keys = {
        "schema", "generation_mode", "golden_byte_equality_required",
        "protected_renderer_equivalence_claimed", "capture_replay_fixture_used",
        "renderer_descriptor", "renderer_descriptor_sha256", "envelope",
        "envelope_sha256", "symbol_count", "symbols_sha256_uint16be",
        "chirp_pixels", "preamble_symbols", "sync_symbols_zero_based",
        "sfd_quarter_chirps", "tail_modification", "prepad_pixels",
        "signal_pixels", "signal_sha256", "occupied_total_pixels", "frame_count",
        "timeline_bytes", "timeline_sha256", "timeline_counts",
        "raw_frame_sha256", "raw_frame_black_pixels", "raw_frame_white_pixels",
        "pgm_frame_sha256", "final_signal_frame_index",
        "final_signal_total_index", "final_signal_x", "final_signal_y",
    }
    if set(manifest) != expected_keys:
        raise ProtocolError("dynamic renderer manifest key set mismatch")
    if manifest["schema"] != "tempest-lora.dynamic-pixel-renderer-manifest.v1":
        raise ProtocolError("dynamic renderer manifest schema mismatch")
    if manifest["generation_mode"] != "documented-clear-source-renderer":
        raise ProtocolError("dynamic generation_mode mismatch")
    if manifest["golden_byte_equality_required"] is not False:
        raise ProtocolError("golden byte equality flag mismatch")
    if manifest["protected_renderer_equivalence_claimed"] is not False:
        raise ProtocolError("protected renderer equivalence flag mismatch")
    if manifest["capture_replay_fixture_used"] is not False:
        raise ProtocolError("capture replay fixture must not be used")

    descriptor = profile.descriptor()
    descriptor_hash = profile.descriptor_sha256()
    if manifest["renderer_descriptor"] != descriptor:
        raise ProtocolError("renderer descriptor mismatch")
    if manifest["renderer_descriptor_sha256"] != descriptor_hash:
        raise ProtocolError("renderer descriptor hash mismatch")

    envelope = manifest["envelope"]
    if type(envelope) is not dict or envelope.get("schema") != "tempest-lora.symbol-sequence-envelope.v1":
        raise ProtocolError("dynamic envelope manifest mismatch")
    if envelope.get("profile_id") != 2 or envelope.get("source_kind") != "pinned-gr-lora-sdr-result":
        raise ProtocolError("dynamic envelope profile/source mismatch")
    if envelope.get("spreading_factor") != 7 or envelope.get("index_base") != 0 or envelope.get("ingress_transform") != "identity":
        raise ProtocolError("dynamic envelope domain mismatch")
    if type(envelope.get("symbol_count")) is not int or envelope["symbol_count"] < 1:
        raise ProtocolError("dynamic envelope symbol_count mismatch")
    symbols = envelope.get("symbols")
    if type(symbols) is not list or len(symbols) != envelope["symbol_count"]:
        raise ProtocolError("dynamic envelope symbols mismatch")
    if any(type(value) is not int or not 0 <= value <= 127 for value in symbols):
        raise ProtocolError("dynamic envelope symbol outside SF7 domain")
    expected_symbol_hash = _sha256(b"".join(struct.pack(">H", value) for value in symbols))
    if envelope.get("symbols_sha256_uint16be") != expected_symbol_hash:
        raise ProtocolError("dynamic envelope symbol hash mismatch")
    provenance = envelope.get("provenance")
    if type(provenance) is not dict or set(provenance) != {
        "payload_sha256", "oracle_commit", "oracle_tree", "parameters_sha256"
    }:
        raise ProtocolError("dynamic envelope provenance mismatch")
    _require_sha256(provenance.get("payload_sha256"), "payload_sha256")
    _require_sha256(provenance.get("parameters_sha256"), "parameters_sha256")
    if provenance.get("oracle_commit") != PINNED_ORACLE_COMMIT or provenance.get("oracle_tree") != PINNED_ORACLE_TREE:
        raise ProtocolError("dynamic envelope Oracle provenance mismatch")
    if provenance.get("parameters_sha256") != DynamicPhyParameters().descriptor_sha256():
        raise ProtocolError("dynamic envelope PHY parameter hash mismatch")
    envelope_hash = _sha256(canonical_json_bytes(envelope))
    if manifest["envelope_sha256"] != envelope_hash:
        raise ProtocolError("dynamic envelope hash mismatch")
    if manifest["symbol_count"] != envelope["symbol_count"]:
        raise ProtocolError("manifest/envelope symbol_count mismatch")
    _require_sha256(manifest["symbols_sha256_uint16be"], "symbols_sha256_uint16be")
    if manifest["symbols_sha256_uint16be"] != expected_symbol_hash:
        raise ProtocolError("manifest/envelope symbol hash mismatch")

    if manifest["chirp_pixels"] != 38_016:
        raise ProtocolError("chirp_pixels mismatch")
    if manifest["preamble_symbols"] != 4 or manifest["sync_symbols_zero_based"] != [8, 16]:
        raise ProtocolError("preamble or sync mismatch")
    if manifest["sfd_quarter_chirps"] != 9 or manifest["tail_modification"] != "forbidden":
        raise ProtocolError("SFD or tail contract mismatch")
    prepad = profile.active_y_start * profile.total_width + profile.active_x_start
    if manifest["prepad_pixels"] != prepad:
        raise ProtocolError("prepad_pixels mismatch")
    for key in ("signal_pixels", "occupied_total_pixels", "final_signal_frame_index", "final_signal_total_index", "final_signal_x", "final_signal_y"):
        if type(manifest[key]) is not int or manifest[key] < 0:
            raise ProtocolError(f"{key} must be a nonnegative plain integer")
    expected_signal_pixels = (
        profile.preamble_symbols * 4
        + len(profile.sync_symbols_zero_based) * 4
        + profile.sfd_quarter_chirps
        + envelope["symbol_count"] * 4
    ) * (38_016 // 4)
    if manifest["signal_pixels"] != expected_signal_pixels:
        raise ProtocolError("signal_pixels mismatch")
    if manifest["occupied_total_pixels"] != prepad + expected_signal_pixels:
        raise ProtocolError("occupied_total_pixels mismatch")
    _require_sha256(manifest["signal_sha256"], "signal_sha256")

    visible_pixels = profile.visible_width * profile.visible_height
    frame_pixels = profile.total_width * profile.total_height
    expected_timeline_bytes = frame_count * frame_pixels
    expected_frame_count = (manifest["occupied_total_pixels"] + frame_pixels - 1) // frame_pixels
    if expected_frame_count != frame_count or manifest["frame_count"] != frame_count:
        raise ProtocolError("frame_count mismatch")
    if manifest["timeline_bytes"] != expected_timeline_bytes or len(artifact.timeline_u8) != expected_timeline_bytes:
        raise ProtocolError("timeline byte length mismatch")
    timeline_hash = _sha256(artifact.timeline_u8)
    if manifest["timeline_sha256"] != timeline_hash:
        raise ProtocolError("timeline SHA-256 mismatch")

    raw_hashes: list[str] = []
    pgm_hashes: list[str] = []
    black_counts: list[int] = []
    white_counts: list[int] = []
    expected_timeline = bytearray(expected_timeline_bytes)
    translation = bytes.maketrans(bytes((0, 255)), bytes((1, 2)))

    for frame_index, frame in enumerate(artifact.visible_frames_u8):
        if type(frame) is not bytes or len(frame) != visible_pixels:
            raise ProtocolError("visible frame byte length mismatch")
        invalid = set(frame).difference({profile.black_pixel, profile.white_pixel})
        if invalid:
            raise ProtocolError("visible frame contains a non-binary pixel")
        raw_hashes.append(_sha256(frame))
        white = frame.count(profile.white_pixel)
        white_counts.append(white)
        black_counts.append(visible_pixels - white)

        pgm = artifact.canonical_pgm_frames[frame_index]
        if type(pgm) is not bytes or pgm != PGM_HEADER + frame:
            raise ProtocolError("canonical PGM frame mismatch")
        pgm_hashes.append(_sha256(pgm))

        frame_base = frame_index * frame_pixels
        for y in range(profile.visible_height):
            raw_start = y * profile.visible_width
            timeline_start = frame_base + (profile.active_y_start + y) * profile.total_width + profile.active_x_start
            expected_timeline[timeline_start:timeline_start + profile.visible_width] = frame[
                raw_start:raw_start + profile.visible_width
            ].translate(translation)

    if bytes(expected_timeline) != artifact.timeline_u8:
        raise ProtocolError("timeline geometry or values mismatch")
    counts = {
        "0": artifact.timeline_u8.count(0),
        "1": artifact.timeline_u8.count(1),
        "2": artifact.timeline_u8.count(2),
    }
    if set(artifact.timeline_u8).difference({0, 1, 2}) or manifest["timeline_counts"] != counts:
        raise ProtocolError("timeline value domain or counts mismatch")
    if manifest["raw_frame_sha256"] != raw_hashes:
        raise ProtocolError("raw frame hash list mismatch")
    if manifest["raw_frame_black_pixels"] != black_counts or manifest["raw_frame_white_pixels"] != white_counts:
        raise ProtocolError("raw frame pixel counts mismatch")
    if manifest["pgm_frame_sha256"] != pgm_hashes:
        raise ProtocolError("PGM frame hash list mismatch")

    occupied = manifest["occupied_total_pixels"]
    if occupied < 1 or occupied > expected_timeline_bytes:
        raise ProtocolError("occupied_total_pixels outside timeline")
    final_index = occupied - 1
    if manifest["final_signal_total_index"] != final_index:
        raise ProtocolError("final signal total index mismatch")
    final_frame = final_index // frame_pixels
    final_offset = final_index % frame_pixels
    final_y, final_x = divmod(final_offset, profile.total_width)
    if (
        manifest["final_signal_frame_index"] != final_frame
        or manifest["final_signal_x"] != final_x
        or manifest["final_signal_y"] != final_y
    ):
        raise ProtocolError("final signal coordinate mismatch")

    return ValidatedDynamicDisplayArtifact(
        manifest_sha256=_sha256(artifact.manifest_json),
        renderer_descriptor_sha256=descriptor_hash,
        envelope_sha256=envelope_hash,
        timeline_sha256=timeline_hash,
        frame_count=frame_count,
        raw_frame_sha256=tuple(raw_hashes),
        pgm_frame_sha256=tuple(pgm_hashes),
    )


def convert_visible_u8_to_xrgb8888(frame_u8: bytes) -> bytes:
    if type(frame_u8) is not bytes or len(frame_u8) != 1920 * 1080:
        raise ProtocolError("visible frame must be exact 1920x1080 bytes")
    if set(frame_u8).difference({0, 255}):
        raise ProtocolError("visible frame must contain only 0 and 255")
    count = len(frame_u8)
    output = bytearray(count * 4)
    output[0::4] = frame_u8
    output[1::4] = frame_u8
    output[2::4] = frame_u8
    output[3::4] = b"\xff" * count
    return bytes(output)


def black_guard_xrgb8888() -> bytes:
    return b"\x00\x00\x00\xff" * (1920 * 1080)


def prepare_scanout_buffers(artifact: DynamicRenderedPixelArtifact) -> PreparedScanoutBuffers:
    validated = validate_dynamic_display_artifact(artifact)
    guard = black_guard_xrgb8888()
    data = tuple(convert_visible_u8_to_xrgb8888(frame) for frame in artifact.visible_frames_u8)
    return PreparedScanoutBuffers(
        validated=validated,
        guard_black_xrgb8888=guard,
        guard_black_sha256=_sha256(guard),
        data_xrgb8888=data,
        data_xrgb8888_sha256=tuple(_sha256(frame) for frame in data),
    )
