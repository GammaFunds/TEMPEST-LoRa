# R2C.6C Offline Laboratory Transfer Core

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
`gnuradio.gr`, `gnuradio.blocks`, `pmt`, and `gnuradio.lora_sdr` (not plain
`lora_sdr`) and verifies their versions and origins.

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

## R2C.6C validation status

R2C.6B completed the adapter implementation and its fake/mock-based offline
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
`vector_sink_i`. It did not invoke `modulate`, a renderer, display access, SDR,
IQ recording, RF, or hardware. Those paths remain untested and prohibited
without separate approval. Ordinary imports and the offline test suite do not
execute the real Oracle or start a flowgraph.

## Offline tests

The accepted offline suite contains 156 tests. Run it from the repository root
without installing anything or loading the real Oracle runtime:

```bash
env -u LD_LIBRARY_PATH -u PYTHONHOME \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONHASHSEED=0 \
  PYTHONPATH=sender/lab-transfer/src \
  python3 -B -m unittest discover \
    -s sender/lab-transfer/tests \
    -q
```
