# Linux SX1262 Receiver

This directory contains the laboratory Linux receiver for the HackerGadgets
AIO V1 SX1262 attached to the ClockworkPi uConsole.

## Fixed RF and hardware contract

- frequency: 915 MHz
- bandwidth: 500 kHz
- spreading factor: 7
- coding rate: 4/5
- private RadioLib sync word API value: `0x12`
- preamble: 4 symbols
- explicit header
- two-byte CRC
- normal IQ polarity
- DIO2 RF switch enabled
- DIO3 TCXO: 1.8 V
- SPI: `/dev/spidev1.0`, 2 MHz
- DIO1: GPIO26
- RESET: GPIO25
- BUSY: GPIO24
- GPIO chip: `gpiochip0`

Runtime RF and hardware overrides are intentionally unavailable in v1.

## Arch Linux contract tests

These tests do not compile or access the hardware receiver:

```bash
cmake \
  -S receiver/linux-sx1262 \
  -B build/linux-sx1262-contract \
  -DTEMPEST_LORA_BUILD_HARDWARE_RECEIVER=OFF \
  -DTEMPEST_LORA_BUILD_CONTRACT_TESTS=ON

cmake --build build/linux-sx1262-contract
ctest --test-dir build/linux-sx1262-contract --output-on-failure
```

## uConsole hardware build

The hardware target requires:

- the exact `third_party/RadioLib` submodule;
- `liblgpio-dev`;
- a C++20-capable toolchain for the hardware receiver and RadioLib;
- `meshtasticd` stopped under a separately approved stop-test-restore procedure.

The hardware receiver executable and RadioLib compile as C++20 because
RadioLib 7.7.1 exposes C++20 syntax through public headers included by the
receiver. The hardware-independent serialization library and contract tests
remain C++17.

```bash
cmake \
  -S receiver/linux-sx1262 \
  -B build/linux-sx1262-hardware \
  -DTEMPEST_LORA_BUILD_HARDWARE_RECEIVER=ON \
  -DTEMPEST_LORA_BUILD_CONTRACT_TESTS=ON

cmake --build build/linux-sx1262-hardware
```

The receiver binary never starts, stops, disables, or reconfigures
`meshtasticd`.

## Output

Standard output is JSON Lines using schema `tempest-lora.rx.v1`.
Diagnostics are written to standard error.

Binary payload bytes are preserved in `payload_hex`. A separate
`payload_ascii` field maps bytes outside `0x20` through `0x7e` to `.`.
