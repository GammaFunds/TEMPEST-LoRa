from __future__ import annotations
import hashlib, json, struct, unittest
from dataclasses import replace
from tempest_lora_lab.display_contract import (
    ExactDisplayMode, ExactKmsSnapshot, PGM_HEADER, R2E1_CONTRACT_SHA256, black_guard_xrgb8888,
    convert_visible_u8_to_xrgb8888, prepare_scanout_buffers,
    validate_dynamic_display_artifact, validate_r2e1_contract_bytes,
)
from tempest_lora_lab.pixel_renderer import CaptureReplayArtifact, DynamicRenderedPixelArtifact
from tempest_lora_lab.profiles import DynamicPhyParameters, DynamicPixelRendererProfile
from tempest_lora_lab.protocol import ProtocolError, canonical_json_bytes


# Shared deterministic offline fixtures for R2E.2 tests.
def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def make_artifact(frame_count: int = 1) -> DynamicRenderedPixelArtifact:
    profile = DynamicPixelRendererProfile()
    symbol_counts = {1: 1, 2: 57, 16: 1032}
    if frame_count not in symbol_counts:
        raise ValueError("test helper supports only 1, 2, or 16 frames")
    symbol_count = symbol_counts[frame_count]
    visible_pixels = profile.visible_width * profile.visible_height
    frame_pixels = profile.total_width * profile.total_height
    base = bytearray(visible_pixels)
    base[0] = 255
    base[-1] = 255
    frames = tuple(bytes(base) for _ in range(frame_count))
    pgms = tuple(PGM_HEADER + frame for frame in frames)
    timeline = bytearray(frame_count * frame_pixels)
    translation = bytes.maketrans(bytes((0,255)), bytes((1,2)))
    for fi, frame in enumerate(frames):
        fb = fi * frame_pixels
        for y in range(profile.visible_height):
            rs = y * profile.visible_width
            ts = fb + (profile.active_y_start + y) * profile.total_width + profile.active_x_start
            row = frame[rs:rs+profile.visible_width]
            timeline[ts:ts+profile.visible_width] = row.translate(translation)
    timeline_b = bytes(timeline)
    symbols = tuple(0 for _ in range(symbol_count))
    symbol_hash = sha(b''.join(struct.pack('>H', x) for x in symbols))
    envelope = {
        'schema':'tempest-lora.symbol-sequence-envelope.v1',
        'profile_id':2,
        'source_kind':'pinned-gr-lora-sdr-result',
        'spreading_factor':7,
        'index_base':0,
        'ingress_transform':'identity',
        'symbol_count':symbol_count,
        'symbols':list(symbols),
        'symbols_sha256_uint16be':symbol_hash,
        'provenance':{
            'payload_sha256':sha(b'test'),
            'oracle_commit':'862746dd1cf635c9c8a4bfbaa2c3a0ec3a5306c9',
            'oracle_tree':'97e9f429c68b4672ca412a3ee411311564286eb1',
            'parameters_sha256':DynamicPhyParameters().descriptor_sha256(),
        },
    }
    signal_pixels = (profile.preamble_symbols*4 + len(profile.sync_symbols_zero_based)*4 + profile.sfd_quarter_chirps + symbol_count*4) * (38016//4)
    occupied = profile.active_y_start*profile.total_width+profile.active_x_start+signal_pixels
    assert (occupied + frame_pixels - 1)//frame_pixels == frame_count
    final_index = occupied - 1
    off = final_index % frame_pixels
    fy, fx = divmod(off, profile.total_width)
    manifest = {
        'schema':'tempest-lora.dynamic-pixel-renderer-manifest.v1',
        'generation_mode':'documented-clear-source-renderer',
        'golden_byte_equality_required':False,
        'protected_renderer_equivalence_claimed':False,
        'capture_replay_fixture_used':False,
        'renderer_descriptor':profile.descriptor(),
        'renderer_descriptor_sha256':profile.descriptor_sha256(),
        'envelope':envelope,
        'envelope_sha256':sha(canonical_json_bytes(envelope)),
        'symbol_count':symbol_count,
        'symbols_sha256_uint16be':symbol_hash,
        'chirp_pixels':38016,
        'preamble_symbols':4,
        'sync_symbols_zero_based':[8,16],
        'sfd_quarter_chirps':9,
        'tail_modification':'forbidden',
        'prepad_pixels':profile.active_y_start*profile.total_width+profile.active_x_start,
        'signal_pixels':signal_pixels,
        'signal_sha256':sha(b'signal'),
        'occupied_total_pixels':occupied,
        'frame_count':frame_count,
        'timeline_bytes':len(timeline_b),
        'timeline_sha256':sha(timeline_b),
        'timeline_counts':{'0':timeline_b.count(0),'1':timeline_b.count(1),'2':timeline_b.count(2)},
        'raw_frame_sha256':[sha(f) for f in frames],
        'raw_frame_black_pixels':[visible_pixels-f.count(255) for f in frames],
        'raw_frame_white_pixels':[f.count(255) for f in frames],
        'pgm_frame_sha256':[sha(p) for p in pgms],
        'final_signal_frame_index':final_index//frame_pixels,
        'final_signal_total_index':final_index,
        'final_signal_x':fx,
        'final_signal_y':fy,
    }
    return DynamicRenderedPixelArtifact(
        timeline_u8=timeline_b,
        visible_frames_u8=frames,
        canonical_pgm_frames=pgms,
        manifest_json=canonical_json_bytes(manifest),
    )

def make_snapshot(**changes) -> ExactKmsSnapshot:
    base = ExactKmsSnapshot(
        device_path='/dev/dri/card0',
        device_identity='226:0',
        driver_name='fake-drm',
        atomic_capable=True,
        drm_master=True,
        exclusive_control=True,
        connector_id=31,
        connector_type='HDMI-A',
        connected=True,
        edid_sha256=sha(b'edid'),
        edid_valid=True,
        mode=ExactDisplayMode(),
        mode_advertised=True,
        crtc_id=41,
        plane_id=51,
        plane_type='Primary',
        supported_formats=('DRM_FORMAT_XRGB8888',),
        supported_modifiers=('DRM_FORMAT_MOD_LINEAR',),
        src_rect_16_16=(0,0,1920<<16,1080<<16),
        dst_rect=(0,0,1920,1080),
        rotation='rotate-0',
        reflection=False,
        overlays_disabled=True,
        cursor_disabled=True,
        vrr_enabled=False,
        degamma_lut_enabled=False,
        ctm_enabled=False,
        gamma_lut_enabled=False,
        hdr_metadata_enabled=False,
        colorspace='Default',
        broadcast_rgb='Full',
        bits_per_component=8,
        scaling_mode='None',
        unknown_affecting_properties=(),
        topology_token='topology-v1',
    )
    return replace(base, **changes)


class DisplayContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = make_artifact(1)

    def test_exact_mode_is_vic16_60_over_1(self):
        mode = ExactDisplayMode()
        self.assertEqual((mode.frame_rate.numerator, mode.frame_rate.denominator), (60,1))
        self.assertEqual(mode.descriptor()['hsync_start'], 2008)
        self.assertEqual(mode.descriptor()['vsync_end'], 1089)

    def test_exact_mode_rejects_5994_clock(self):
        with self.assertRaises(ProtocolError):
            replace(ExactDisplayMode(), clock_khz=148352).validate()

    def test_contract_hash_constant_is_pinned(self):
        self.assertEqual(R2E1_CONTRACT_SHA256, 'd6b06815ea9e4e077170067c742a87d347766bd484d63fcb1996564524a739c4')

    def test_external_contract_rejects_changed_byte(self):
        with self.assertRaises(ProtocolError):
            validate_r2e1_contract_bytes(b'{}\n')

    def test_valid_dynamic_artifact(self):
        validated = validate_dynamic_display_artifact(self.artifact)
        self.assertEqual(validated.frame_count, 1)
        self.assertEqual(len(validated.raw_frame_sha256), 1)

    def test_valid_two_frame_artifact(self):
        self.assertEqual(validate_dynamic_display_artifact(make_artifact(2)).frame_count, 2)

    def test_valid_sixteen_frame_artifact(self):
        self.assertEqual(validate_dynamic_display_artifact(make_artifact(16)).frame_count, 16)

    def test_capture_artifact_is_rejected(self):
        capture = CaptureReplayArtifact('0'*64, b'', b'', b'{}')
        with self.assertRaises(ProtocolError):
            validate_dynamic_display_artifact(capture)  # type: ignore[arg-type]

    def test_duck_typed_artifact_is_rejected(self):
        class Duck: pass
        with self.assertRaises(ProtocolError):
            validate_dynamic_display_artifact(Duck())  # type: ignore[arg-type]

    def test_noncanonical_manifest_is_rejected(self):
        parsed = json.loads(self.artifact.manifest_json)
        altered = replace(self.artifact, manifest_json=json.dumps(parsed).encode())
        with self.assertRaises(ProtocolError):
            validate_dynamic_display_artifact(altered)

    def test_timeline_hash_mismatch_is_rejected(self):
        broken = bytearray(self.artifact.timeline_u8); broken[0] = 1
        with self.assertRaises(ProtocolError):
            validate_dynamic_display_artifact(replace(self.artifact, timeline_u8=bytes(broken)))

    def test_pgm_body_mismatch_is_rejected(self):
        pgm = bytearray(self.artifact.canonical_pgm_frames[0]); pgm[-1] ^= 0xff
        with self.assertRaises(ProtocolError):
            validate_dynamic_display_artifact(replace(self.artifact, canonical_pgm_frames=(bytes(pgm),)))

    def test_seventeen_frames_are_rejected_before_manifest_trust(self):
        frame = self.artifact.visible_frames_u8[0]
        pgm = self.artifact.canonical_pgm_frames[0]
        altered = DynamicRenderedPixelArtifact(
            timeline_u8=self.artifact.timeline_u8,
            visible_frames_u8=(frame,)*17,
            canonical_pgm_frames=(pgm,)*17,
            manifest_json=self.artifact.manifest_json,
        )
        with self.assertRaisesRegex(ProtocolError, '1..16'):
            validate_dynamic_display_artifact(altered)

    def test_xrgb_conversion_is_deterministic_and_exact(self):
        frame = bytearray(1920*1080); frame[0]=255; frame[-1]=255
        first = convert_visible_u8_to_xrgb8888(bytes(frame))
        second = convert_visible_u8_to_xrgb8888(bytes(frame))
        self.assertEqual(first, second)
        self.assertEqual(first[:8], b'\xff\xff\xff\xff\x00\x00\x00\xff')
        self.assertEqual(first[-4:], b'\xff\xff\xff\xff')

    def test_xrgb_conversion_rejects_gray_pixel(self):
        frame = bytearray(1920*1080); frame[10]=1
        with self.assertRaises(ProtocolError):
            convert_visible_u8_to_xrgb8888(bytes(frame))

    def test_guard_black_is_exact_xrgb(self):
        guard = black_guard_xrgb8888()
        self.assertEqual(len(guard), 1920*1080*4)
        self.assertEqual(guard[:4], b'\x00\x00\x00\xff')
        self.assertEqual(set(guard[3::4]), {255})

    def test_prepare_scanout_buffers_hashes_all_data(self):
        prepared = prepare_scanout_buffers(self.artifact)
        self.assertEqual(len(prepared.data_xrgb8888), 1)
        self.assertEqual(hashlib.sha256(prepared.data_xrgb8888[0]).hexdigest(), prepared.data_xrgb8888_sha256[0])

    def test_valid_snapshot(self):
        snapshot = make_snapshot(); snapshot.validate()
        self.assertEqual(snapshot.mode.frame_rate, 60)

    def test_snapshot_rejects_scaling(self):
        with self.assertRaises(ProtocolError):
            make_snapshot(dst_rect=(0,0,1919,1080)).validate()

    def test_snapshot_rejects_vrr_and_color_mutation(self):
        with self.assertRaises(ProtocolError): make_snapshot(vrr_enabled=True).validate()
        with self.assertRaises(ProtocolError): make_snapshot(ctm_enabled=True).validate()

    def test_snapshot_rejects_unknown_affecting_property(self):
        with self.assertRaises(ProtocolError):
            make_snapshot(unknown_affecting_properties=('DITHER',)).validate()

    def test_snapshot_rejects_non_string_format_or_duplicate_modifier(self):
        with self.assertRaises(ProtocolError):
            make_snapshot(supported_formats=('DRM_FORMAT_XRGB8888', 7)).validate()
        with self.assertRaises(ProtocolError):
            make_snapshot(supported_modifiers=('DRM_FORMAT_MOD_LINEAR', 'DRM_FORMAT_MOD_LINEAR')).validate()

if __name__ == '__main__': unittest.main()
