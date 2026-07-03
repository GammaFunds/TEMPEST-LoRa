# R2C.6B Offline Laboratory Transfer Core

This directory implements the offline-only R2C.1 contracts for synthetic
TEMPEST-LoRa laboratory fixtures.

## Scope

- deterministic `TLR1` manifest/data/commit framing;
- 48-byte application header and at most 207 data bytes per LoRa payload;
- per-frame header and payload CRC32;
- final SHA-256 reassembly validation;
- explicit synthetic-fixture input policy;
- separate `capture-replay-v1` and `dynamic-software-phy-v1` profiles;
- strict JSON request/result validation for the pinned external
  `gr-lora_sdr` process/file boundary.

The module deliberately contains no Oracle launcher, modulator, renderer,
display access, SDR access, receiver control, service management, or RF code.

The module contains no preamble, sync, SFD, padding, zero-fill, or tail output.
Symbols are captured after `gray_demap` and before `modulate`.

## Profile boundary

`capture-replay-v1` accepts only approved published MAT-derived symbol
fixtures. It is not transport-capable. One-based MAT indices are converted to
the canonical zero-based domain with `stored_Index - 1`; order and length are
preserved.

`dynamic-software-phy-v1` is the only transfer-capable profile. It accepts only
validated zero-based results associated with the pinned Oracle commit and tree
and the exact R2C.1 PHY parameter descriptor. No symbols are added, removed,
reordered, borrowed, or substituted.

## Public API

- `load_and_validate_request(path: Path) -> OracleRequest` -- validates path
  identity, schema, fields, types, payload hex format, rejects duplicate JSON
  keys, reconstructs `DynamicPhyParameters` and `OracleRequest`, and verifies
  full reconstruction equality.

- `execute_pinned_oracle(*, request_path, result_path, runtime,
  timeout_seconds, max_symbol_count) -> SymbolEnvelope` -- public production
  entry point. Loads and validates the request, validates the lazy runtime,
  constructs exactly seven blocks, connects exactly six edges, submits the
  payload, polls for a stable `frame_len` tag and symbol snapshot, normalises
  with `normalize_dynamic_symbols`, writes the result, and returns the
  `SymbolEnvelope`.

- `write_result(path: Path, request: OracleRequest, envelope: SymbolEnvelope)
  -> None` -- verifies canonical request and envelope, validates all envelope
  fields and provenance, writes deterministic sorted-key ASCII JSON.

## Process/file boundary

The strict external process/file boundary validates paths as exact `Path`
objects, requiring absolute canonical symlink-free regular files opened with
`O_RDONLY | O_NOFOLLOW`. Stable path and descriptor identity is verified at
every stage (before open, after open, after read, after resolve). Requests are
limited to 16 384 bytes, decode as ASCII only, and reject duplicate JSON
object keys at every level.

## Runtime descriptor

`PinnedOracleRuntime` holds only explicit caller-supplied fields:

- `python_executable: Path`
- `stage_site_packages: Path`
- `lora_sdr_package: Path`
- `lora_sdr_init: Path`
- `lora_sdr_binding: Path`
- `native_library: Path`
- `python_version: str` = `"3.12.13"`
- `gnuradio_version: str` = `"3.10.11.0"`
- `oracle_commit: str` = pinned commit
- `oracle_tree: str` = pinned tree

All paths must be exact `Path` objects, absolute, canonical, and symlink-free.
The runtime descriptor performs no filesystem discovery and mutates neither
`sys.path` nor `os.environ`. The lazy loader imports exactly `gnuradio.gr`,
`gnuradio.blocks`, `pmt`, and `gnuradio.lora_sdr` (not plain `lora_sdr`).

## Exact tap point

The adapter captures physical symbols **after `gray_demap` and before
`modulate`**. No preamble, sync word, SFD, tail, zero-fill, or any other
symbols are added. The six stream edges are:

1. `whitening -> header`
2. `header -> add_crc`
3. `add_crc -> hamming_enc`
4. `hamming_enc -> interleaver`
5. `interleaver -> gray_demap`
6. `gray_demap -> vector_sink_i`

## R2C.6B status

All code in this directory (including `oracle_adapter.py`) is **code/mock-only
for R2C.6B**. The adapter constructs flowgraph blocks, connects edges, and
processes tags only through fakes/mocks in tests. Separate approval is required
before any real execution against the staged GNU Radio runtime.

The module prohibits display, SDR, device, IQ and RF behavior. No real Oracle,
flowgraph, symbol generation, display, SDR, device, network, service,
installation, commit, push, or staging action occurs within the test or import
path.

## Offline tests

Run from the repository root without installing anything:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=sender/lab-transfer/src \
python3 -m unittest discover \
  -s sender/lab-transfer/tests \
  -v
```
