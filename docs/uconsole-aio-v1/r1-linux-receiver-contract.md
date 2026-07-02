# R1 Linux SX1262 Receiver Contract

## Scope

This contract defines the first Linux-native SX1262 packet receiver for the
HackerGadgets AIO V1 in the ClockworkPi uConsole laboratory environment.

It does not modify the original Arduino receiver, MATLAB sender sources,
attack samples, Meshtastic configuration, system services, or RTL-SDR tools.

## Source baseline

- TEMPEST-LoRa base commit: `46d8340ff7b877dc9c111d67e82193b23ab6a213`
- implementation branch: `feature/linux-sx1262-receiver-v1`
- RadioLib release: `7.7.1`
- RadioLib commit: `034126ef3b5305394d1e4e14a5049482ec10c1c4`
- RadioLib tree: `6c6fb4d440c8527ea9bc01f2ea0a3a03dcb0d226`

## RF contract

| Parameter | Value |
| --- | --- |
| Frequency | 915 MHz |
| Bandwidth | 500 kHz |
| Spreading factor | 7 |
| Coding rate | 4/5 |
| Sync word API value | `0x12` |
| Sync-word class | private |
| Preamble | 4 symbols |
| Header | explicit |
| CRC | enabled, 2 bytes |
| IQ inversion | disabled |
| DIO2 RF switch | enabled |
| DIO3 TCXO | 1.8 V |
| Regulator mode | DC-DC, not forced LDO |

## Hardware contract

| Resource | Value |
| --- | --- |
| SPI device | `/dev/spidev1.0` |
| SPI device index | 1 |
| SPI channel / CS | 0 |
| SPI clock | 2 MHz |
| Module NSS | `RADIOLIB_NC` |
| GPIO chip | 0 |
| DIO1 / IRQ | GPIO26 |
| RESET | GPIO25 |
| BUSY | GPIO24 |

Kernel spidev owns CS0. The RadioLib module therefore receives
`RADIOLIB_NC` for its NSS GPIO argument.

## Failure model

Every RadioLib return value is checked. Because the RadioLib HAL interface
uses several `void` methods, the project-local `LabPiHal` stores the first
negative lgpio error together with the operation name.

A RadioLib call is successful only when:

1. its RadioLib state is `RADIOLIB_ERR_NONE`; and
2. the HAL remains ready with no sticky error.

Cleanup is idempotent and preserves the first failure.

## Receive model

The callback only sets an atomic flag. Packet processing occurs in the main
thread.

The receiver:

1. obtains the packet length;
2. rejects lengths above 255;
3. reads into a byte vector;
4. preserves null and non-printable bytes;
5. emits lowercase hexadecimal payload data;
6. records RSSI, SNR, CRC result and RadioLib state;
7. checks every receive restart.

## Output schema

Standard output contains JSON Lines with schema
`tempest-lora.rx.v1`. Standard error is reserved for diagnostics.

Required packet-event fields:

- `schema`
- `type`
- `sequence`
- `time_utc`
- `monotonic_ns`
- `length`
- `payload_hex`
- `payload_ascii`
- `rssi_dbm`
- `snr_db`
- `crc`
- `radiolib_state`

## Service boundary

The receiver contains no service-management code. Parallel use with
`meshtasticd` is forbidden. Stopping and restoring that service requires a
separate, explicitly approved laboratory procedure.

## Build boundary

Arch Linux runs only hardware-independent contract and serialization tests.

The uConsole hardware build additionally requires:

- the exact RadioLib submodule;
- `liblgpio-dev`;
- a C++20-capable compiler for the hardware receiver and RadioLib targets.

The hardware receiver translation units compile as C++20 because they include
RadioLib 7.7.1 public headers containing C++20 syntax. The
hardware-independent serialization library and both contract-test targets
remain C++17.

Package installation, uConsole deployment, hardware compilation and radio
execution remain separate approval boundaries.
