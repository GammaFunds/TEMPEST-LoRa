# R2C.2 Offline Laboratory Transfer Core

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

## Profile boundary

`capture-replay-v1` accepts only approved published MAT-derived symbol
fixtures. It is not transport-capable. One-based MAT indices are converted to
the canonical zero-based domain with `stored_Index - 1`; order and length are
preserved.

`dynamic-software-phy-v1` is the only transfer-capable profile. It accepts only
validated zero-based results associated with the pinned Oracle commit and tree
and the exact R2C.1 PHY parameter descriptor. No symbols are added, removed,
reordered, borrowed, or substituted.

## Offline tests

Run from the repository root without installing anything:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=sender/lab-transfer/src \
python3 -m unittest discover \
  -s sender/lab-transfer/tests \
  -v
```
