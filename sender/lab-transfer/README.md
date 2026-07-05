# R2D.2I Offline Laboratory Transfer and Renderer Core

This directory implements the offline-only R2C.1 transfer contracts and the
strictly separated R2D.2G renderer contracts for synthetic TEMPEST-LoRa
laboratory fixtures.

## Scope

- deterministic `TLR1` manifest/data/commit framing;
- 48-byte application header and at most 207 data bytes per LoRa payload;
- per-frame header and payload CRC32;
- final SHA-256 reassembly validation;
- explicit synthetic-fixture input policy;
- separate `capture-replay-v1` and `dynamic-software-phy-v1` transfer profiles;
- strict JSON request/result validation for the pinned external
  `gr-lora_sdr` process/file boundary;
- fixture-only Capture-Replay validation and canonical PGM reproduction;
- a separate deterministic Dynamic Clear-Source pixel renderer.

The module contains no automatic or implicit Oracle execution, display access,
SDR access, receiver control, service management, IQ recording, RF, or hardware
code. The explicit `execute_pinned_oracle` boundary remains caller-controlled;
ordinary imports and tests do not execute it or start a GNU Radio flowgraph.

The Oracle adapter captures only payload symbols after `gray_demap` and before
`modulate`. It does not add preamble, sync, SFD, padding, zero-fill, or tail
symbols. The Dynamic renderer adds its independently documented renderer
envelope only after a validated `SymbolEnvelope` has crossed that boundary.

## Transfer-profile boundary

`capture-replay-v1` accepts only approved published MAT-derived symbol
fixtures. It is not transport-capable. One-based MAT indices are converted to
the canonical zero-based domain with `stored_Index - 1`; order and length are
preserved.

`dynamic-software-phy-v1` is the only transfer-capable profile. It accepts only
validated zero-based results associated with the pinned Oracle commit and tree
and the exact R2C.1 PHY parameter descriptor. No Oracle payload symbols are
added, removed, reordered, borrowed, or substituted.

Renderer descriptors are separate from `dynamic_profile_descriptor()`. They do
not alter the byte-exact `TLR1` transport-profile hash.

## Renderer boundary

R2D.2G defines two deliberately separate APIs:

- `replay_capture_fixture(...)`
- `render_dynamic_envelope(...)`

There is no automatic cross-profile renderer dispatch.

### Capture-Replay renderer

`CaptureReplayRendererProfile` accepts only the pinned published SF7 Golden
fixture and its exact approved Capture envelope. It validates the PNG
structure, chunk CRCs, dimensions, grayscale coding, binary pixels, fixture
hashes, pixel counts, bounding box, raw-frame hash, and canonical PGM hash.

It does not infer a 2200x1125 hidden raster and does not claim to reconstruct
the protected MATLAB P-code algorithm. Its manifest states:

- `generation_mode = verified-fixture-replay`;
- `algorithmic_reconstruction_claimed = false`;
- `transport_capable = false`;
- `hidden_raster_reconstructed = false`.

### Dynamic Clear-Source renderer

`DynamicPixelRendererProfile` is fixed to the accepted laboratory profile:

- visible raster: 1920x1080;
- total raster: 2200x1125;
- active offset: x=132, y=9;
- pixel clock: 148.5 MHz;
- center frequency: 915 MHz;
- bandwidth: 500 kHz;
- SF7;
- four K=0 upchirps;
- zero-based sync chirps K=8 and K=16;
- 2.25 K=0 downchirps;
- payload upchirps in exact envelope order;
- no tail;
- at most 16 output frames.

The normative laboratory chirp is the R2D.2G integer formula. It contains no
floating-point tolerance, Golden-specific repair, runtime formula selection,
or protected-renderer equivalence claim.

The Dynamic renderer validates only `DYNAMIC_SOFTWARE_PHY` envelopes with the
pinned Oracle provenance. It never launches the Oracle. The Golden PNG is not a
Dynamic acceptance oracle.

Dynamic outputs are:

- a full-timing `timeline_u8` where 0 is hidden raster, 1 is visible black, and
  2 is visible white;
- binary 1920x1080 raw frames;
- canonical PGM frames;
- a canonical manifest with formula, raster, symbol, frame, and hash evidence.

The maximum-frame gate is evaluated before chirp rendering or large frame
allocation.

## Public API

- `load_and_validate_request(path: Path) -> OracleRequest` -- validates path
  identity, schema, fields, types, payload hex format, rejects duplicate JSON
  keys, reconstructs `DynamicPhyParameters` and `OracleRequest`, and verifies
  full reconstruction equality.

- `execute_pinned_oracle(*, request_path, result_path, runtime,
  timeout_seconds, max_symbol_count) -> SymbolEnvelope` -- public Oracle
  boundary entry point. Loads and validates the request, validates the lazy
  runtime, constructs exactly seven blocks, connects exactly six edges,
  submits the payload, polls for a stable `frame_len` tag and symbol snapshot,
  normalises with `normalize_dynamic_symbols`, writes the result, and returns
  the `SymbolEnvelope`.

- `write_result(path: Path, request: OracleRequest, envelope: SymbolEnvelope)
  -> None` -- verifies canonical request and envelope, validates all envelope
  fields and provenance, writes deterministic sorted-key ASCII JSON.

- `replay_capture_fixture(*, envelope, fixture_png, profile=None)
  -> CaptureReplayArtifact` -- validates and reproduces only the pinned Capture
  fixture entirely in memory.

- `render_dynamic_envelope(*, envelope, profile=None)
  -> DynamicRenderedPixelArtifact` -- renders a validated Dynamic envelope
  entirely in memory with the documented Clear-Source algorithm.

## Process/file boundary

The strict external process/file boundary validates paths as exact `Path`
objects, requiring absolute canonical symlink-free regular files opened with
`O_RDONLY | O_NOFOLLOW`. Stable path and descriptor identity is verified at
every stage. Requests are limited to 16 384 bytes, decode as ASCII only, and
reject duplicate JSON object keys at every level.

The renderer APIs accept in-memory objects and bytes. They perform no path
discovery, filesystem writes, environment mutation, process launch, network
access, device access, or service action.

## Runtime descriptor

`PinnedOracleRuntime` has ten required, explicit caller-supplied fields. The
dataclass defines no defaults:

- `python_executable: Path`
- `stage_site_packages: Path`
- `lora_sdr_package: Path`
- `lora_sdr_init: Path`
- `lora_sdr_binding: Path`
- `native_library: Path`
- `python_version: str` -- required exact value `"3.12.13"`
- `gnuradio_version: str` -- required exact value `"3.10.11.0"`
- `oracle_commit: str` -- required exact pinned commit
- `oracle_tree: str` -- required exact pinned tree

All paths must be exact concrete `Path` objects, absolute, canonical, and
symlink-free. Files and directories must have the required type and containment
relationships. The runtime descriptor performs no filesystem discovery and
mutates neither `sys.path` nor `os.environ`. The lazy loader imports exactly
`gnuradio.gr`, `gnuradio.blocks`, `pmt`, and `gnuradio.lora_sdr` and verifies
their versions and origins.

## Exact Oracle tap point

The adapter captures physical symbols **after `gray_demap` and before
`modulate`**. No preamble, sync word, SFD, tail, zero-fill, or other renderer
symbols are added at the Oracle boundary. The six stream edges are:

1. `whitening -> header`
2. `header -> add_crc`
3. `add_crc -> hamming_enc`
4. `hamming_enc -> interleaver`
5. `interleaver -> gray_demap`
6. `gray_demap -> vector_sink_i`

## R2C.6C validation status

R2C.6B completed the adapter implementation and fake/mock-based offline
validation. R2C.6C then completed one explicitly authorised real offline smoke
test against the pinned GNU Radio runtime:

- repository commit:
  `8d3102f8fe7879d3f6f3b44dfd05d6cbf10a7000`;
- Oracle commit:
  `862746dd1cf635c9c8a4bfbaa2c3a0ec3a5306c9`;
- Oracle tree:
  `97e9f429c68b4672ca412a3ee411311564286eb1`;
- Python `3.12.13` and GNU Radio `3.10.11.0`;
- synthetic payload `ABC` (`414243`);
- request ID:
  `3665c1a10f88cb6718b3fdf8227891e72fe106a9d7cc9d50d589a0d24c066aeb`;
- 18 zero-based SF7 symbols;
- symbol SHA-256 over unsigned 16-bit big-endian values:
  `6495c516e2f416393038ca3ea5a7e0331035ef4f31e93c072e5f493086931f1f`.

The external evidence set is identified as `R2C6C-B-ABC-8d3102f8`. Its
acceptance marker SHA-256 is
`5d63b69fd671be8db7756eb4bffccba3466a13ced901dd7ffcb592418eb81a20`;
its manifest SHA-256 is
`276d56eed3a0f9e66e1033c18bcb933fa5d4903ab7a56b98891f77ff3b4d33e1`.
The evidence remains outside this repository.

GNU Radio created one isolated runtime preference inside the evidence-specific
`XDG_CONFIG_HOME`: `gnuradio/prefs/vmcircbuf_default_factory`, containing
`gr::vmcircbuf_sysv_shm_factory`. A separate read-only audit classified this as
the expected GNU Radio circular-buffer factory preference. It did not modify
the repository, Oracle checkout, staged runtime, or system configuration.

The smoke test instantiated only the seven approved blocks through
`vector_sink_i`. It did not invoke `modulate`, either renderer, display access,
SDR, IQ recording, RF, or hardware.

## R2D.2H test-vector pin

The Dynamic renderer tests embed the canonical
`tempest-lora.r2d2h-clear-source-test-vectors.v1` bundle with SHA-256:

`f0e8d676a82afe72b47e2e7daea1e50e44c1af3ffe746c6aef8800af31361afe`

The bundle was derived without the Golden capture fixture and without an
Oracle run. It pins independent chirp, spot, packet, frame-boundary, raw-frame,
PGM, and timeline vectors. Capture tests use the Golden fixture only inside the
Capture-Replay path.

## Offline tests

Run from the repository root without installing anything or loading the real
Oracle runtime:

```bash
env -u LD_LIBRARY_PATH -u PYTHONHOME \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONHASHSEED=0 \
  PYTHONPATH=sender/lab-transfer/src \
  python3 -B -m unittest discover \
    -s sender/lab-transfer/tests \
    -q
```

## R2E.4 compile-only native display-bundle adapter

R2E.4 implements the deterministic native display-bundle format and a
compile-only libdrm-linked CLI validator.

It contains no live DRM/KMS operation, no `/dev/dri` device discovery,
no device discovery, no DRM master, framebuffer, TEST_ONLY call, atomic
commit, page flip, event wait, display output, service change, Oracle
execution, SDR, IQ, or RF use. Blocker B1 remains open.

### Deterministic bundle format and explicit frame identities

The native display bundle (`TLORABND`) encodes every frame record with
an explicit fixed-width record kind (GUARD=0, DATA=1) and ordinal.
The parser requires exactly:

    guard-before
    data ordinal 0
    data ordinal 1
    ...
    data ordinal N-1
    guard-after

It rejects duplicate ordinals, missing ordinals, reordered ordinals,
wrong record kind, guard records used as data, data records used as
guards, changed guard-after identity, truncation, and trailing bytes.
Identical payloads and SHA-256 values at distinct ordinals are allowed.

### Design basis

The bundle design basis is the completed R2E.2 contract commit and tree:

- design_basis_commit: `f05f7ded6c062852a08214523edf7c991b9493b1`
- design_basis_tree: `d6a6c1f0a9b495a51a2be0ca38c5c00fc9062c77`

Caller-supplied `checkout_commit` and `checkout_tree` are stored
separately as current-checkout evidence.

### Build and test

Native (compile-only, no hardware required):

```bash
cmake -S native/libdrm-backend -B /tmp/build-r2e4 -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/build-r2e4 --verbose
ctest --test-dir /tmp/build-r2e4 --output-on-failure
```

Python (from repository root):

```bash
env -u LD_LIBRARY_PATH -u PYTHONHOME \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONHASHSEED=0 \
  PYTHONPATH=sender/lab-transfer/src \
  python3 -B -m unittest discover \
    -s sender/lab-transfer/tests \
    -q
```

### Scope

- deterministic bundle format with explicit record kind and ordinal frame identities;
- Python `build_native_display_bundle` / `parse_native_display_bundle` API;
- C++ link-time libdrm dependency via `--no-as-needed` without importing any
  prohibited live function (`drmSetMaster`, `drmModeGetResources`, etc.);
- system libdrm and OpenSSL via pkg-config imported targets;
- C++20, `-Wall -Wextra -Wpedantic -Werror`;
- CTest.

### Nonclaims

- no live DRM/KMS access;
- no `/dev/dri` access or device discovery;
- no DRM master, framebuffer, TEST_ONLY call, atomic commit, page flip,
  event wait, or display output;
- no service control, Oracle execution, SDR, IQ, or RF use;
- no physical pixel-clock accuracy proof;
- no RF emission or LoRa decodability proof;
- no protected MATLAB/P-code equivalence claim;
- B1 remains open.

### R2E.2 offline exact-timing display contract

R2E.2 implements only the pure, offline parts of the accepted R2E.1 contract.
It does not open or discover `/dev/dri` devices and contains no live libdrm
adapter, modeset, hardware framebuffer write, page flip, display output,
service control, Oracle execution, SDR, IQ, or RF path.

The pinned external design contract is identified by SHA-256:

`d6b06815ea9e4e077170067c742a87d347766bd484d63fcb1996564524a739c4`

The offline implementation provides:

- `ExactDisplayMode` for the complete CTA-861 VIC-16 timing fields;
- `ExactKmsSnapshot` for strict caller-supplied KMS identity and property gates;
- `validate_r2e1_contract_bytes(...)`;
- `validate_dynamic_display_artifact(...)`;
- deterministic binary grayscale to linear XRGB8888 conversion;
- prebuilt black guard and data scanout buffers;
- strict guard/data/final-guard frame scheduling;
- `FakeAtomicKmsAdapter`, which has no operating-system or device access;
- a deterministic offline state machine and session manifest;
- negative tests for mode, EDID/property, scaling, color, test-only, commit,
  event, sequence, timeout, out-fence, and topology failures.

Only exact `DynamicRenderedPixelArtifact` values are accepted. Capture-Replay
artifacts, duck-typed objects, 59.94-Hz modes, scaling, crop, rotation,
reflection, VRR, HDR, non-linear modifiers, skipped frames, repeated frames,
async flips, automatic device selection, and unknown pixel- or
timing-affecting properties are rejected.

R2E.2 is not a live display implementation. A future native/libdrm adapter
requires a separate phase, a read-only toolchain and hardware gate, resolution
of display blocker B1, and explicit approval.

### Independent R2E.2 review corrections

The bounded independent review corrected three fail-closed details before commit:

- offline manifests label commit/tree values only as the pinned R2E.1 design basis, never as the current checkout identity;
- a detected KMS topology mutation suppresses the optional abort-black submission because the pipe is no longer verified stable;
- flip-event monotonic timestamps must be strictly increasing in addition to consecutive CRTC sequence numbers.

Snapshot format/modifier tuples are also required to contain unique nonempty ASCII strings.

## R2E.6A offline native atomic preflight contract

R2E.6A implements a deterministic and purely in-memory C++20 preflight layer
that converts an `AtomicDisplayPlan` plus a caller-supplied synthetic KMS
topology/property snapshot into a symbolic atomic-request template.

It is offline only. It must not open a device, discover hardware, create a
property blob, create a framebuffer, issue an ioctl, acquire DRM master, or
submit TEST_ONLY or live atomic commits.

### Validation invariants

The preflight rejects unless all conditions hold:

- plan connector, CRTC, and plane IDs are nonzero;
- plan mode is the exact VIC16 mode and plan format/modifier are XRGB8888/linear;
- snapshot object IDs exactly equal plan IDs;
- device identity exactly matches;
- EDID SHA-256 exactly matches;
- topology token exactly matches;
- connector is connected;
- connector supports selected CRTC;
- plane is a primary plane;
- plane supports selected CRTC;
- exact mode is 148500/1920/2008/2052/2200/1080/1084/1089/1125 with positive
  HSync, positive VSync, not interlaced, not doublescan;
- XRGB8888 plus linear modifier is explicitly supported;
- source and destination rectangles exactly match the existing plan;
- no scaling is present (src_w>>16 == dst_w, src_h>>16 == dst_h);
- rotation, scaling, and color-pipeline identity gates are true;
- every required property exists exactly once;
- required property names are exact and case-sensitive;
- all property IDs in each supplied DRM-object snapshot are nonzero;
- no duplicate property ID within one DRM object;
- no duplicate property name within one DRM object.

### Symbolic MODE_ID and FB_ID binding

The prepared request marks `MODE_ID` as `SymbolicValueSource::FutureModeBlobId`
and `FB_ID` as `SymbolicValueSource::FutureFramebufferId`. These are symbolic
placeholders to be resolved at a future live-commit stage. No blob or
framebuffer is created during preflight.

### Deterministic assignment order

The prepared request contains exactly 13 property assignments in this order:

1. connector CRTC_ID
2. CRTC MODE_ID
3. CRTC ACTIVE
4. plane FB_ID
5. plane CRTC_ID
6. plane SRC_X
7. plane SRC_Y
8. plane SRC_W
9. plane SRC_H
10. plane CRTC_X
11. plane CRTC_Y
12. plane CRTC_W
13. plane CRTC_H

### TEST_ONLY-before-live marker

The prepared result records `test_only_before_live_required=true` and
`allow_modeset_required=true`, `async_flip_forbidden=true`,
`max_outstanding_commits=1`. These are data markers only. No TEST_ONLY
call occurred.

### B1 remains open

Physical blocker B1 remains open. This preflight layer does not resolve B1,
perform physical timing validation, claim real TEST_ONLY readiness, or claim
RF decodability.

### Build and test

```bash
cmake -S native/libdrm-backend -B /tmp/build-r2e6a -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/build-r2e6a --verbose
ctest --test-dir /tmp/build-r2e6a --output-on-failure
```

### Nonclaims

- no TEST_ONLY call occurred;
- no live DRM/KMS, display, SDR, IQ, RF, Oracle, MATLAB, service, network,
  subprocess, or SX1262 action occurred;
- no `/dev/dri` access or device discovery;
- no libdrm function called (open, ioctl, drmModeGet*, drmModeAtomic*, etc.).
