# uConsole AIO V1 Hardware Baseline

## Status

- Baseline date: 2026-07-01
- Project: TEMPEST-LoRa Reproduction Lab
- Repository branch: `lab/uconsole-aio-v1`
- Initial work is receive-only and fail-closed.
- Transmission experiments require a separately reviewed laboratory procedure
  and compliance with the rules applicable at the experiment location.

## System roles

### Arch Linux development host

- Hostname: `archlinux`
- User: `miko`
- Primary development repository:
  `/home/miko/GitHub/TEMPEST-LoRa`
- Responsibilities:
  - source review and implementation;
  - repository and branch management;
  - documentation;
  - non-hardware tests;
  - preparation of the MATLAB sender workflow;
  - commits and pushes only after explicit approval.

### ClockworkPi uConsole laboratory receiver

- Hostname: `clockworkpi`
- User: `kali`
- Platform: ClockworkPi uConsole with Raspberry Pi CM5
- Operating system baseline: Debian GNU/Linux 13 (`trixie`) with selected
  Kali components
- Kernel baseline: `6.12.94-v8-16k+`
- Hardware expansion: HackerGadgets AIO Board V1
- Planned deployment checkout:
  `/home/kali/GitHub/TEMPEST-LoRa`
- The uConsole is the hardware-validation and receiver system, not the
  authoritative development working copy.

## SX1262 baseline

The HackerGadgets AIO Board V1 exposes an integrated SX1262 directly to Linux.

| Function | Linux resource |
| --- | --- |
| SPI device | `/dev/spidev1.0` |
| DIO1 / IRQ | GPIO 26 |
| BUSY | GPIO 24 |
| RESET | GPIO 25 |
| RF switch | DIO2 |
| TCXO control | DIO3 |

Verified boot configuration includes:

- `dtoverlay=spi1-1cs`;
- SPI enabled;
- DIO2 configured as the RF switch;
- DIO3 configured for TCXO control.

The installed Meshtastic configuration identifies the module as `sx1262` and
uses the same SPI and GPIO mapping.

### Verified SX1262 sanity result

The existing `meshtasticd` installation successfully initialized the SX1262:

- SX126x initialization result: `0`;
- radio frequency set successfully;
- SX1262 RX-improvement register patch applied;
- radio entered receive mode.

The RTC warning observed during this test is not an SX1262 initialization
failure.

`meshtasticd` normally owns the SPI/GPIO radio resources. A future native
receiver must therefore use a controlled stop-test-restore procedure. The
daemon and a custom receiver must never access the SX1262 concurrently.

## RTL-SDR baseline

Integrated receiver identity:

- USB device: HackerGadgets `UC AIO Ext`;
- chipset: RTL2832U;
- tuner: Rafael Micro R820T-compatible;
- serial: `12345678`.

Verified receive tests:

- asynchronous receive at 2.048 MS/s completed;
- observed loss: 188 bytes, approximately 4 parts per million;
- successful tuning and sampling at 869.525 MHz;
- successful tuning and sampling at 915 MHz;
- no transmission and no persistent configuration change occurred.

The recurring `[R82XX] PLL not locked!` message did not prevent either
successful capture. It remains a recorded observation and must be evaluated
against a known RF reference before scientific frequency measurements.

## Receiver responsibilities

### SX1262

Primary packet receiver for:

- LoRa packet reception;
- RSSI;
- SNR;
- CRC/result status;
- validation of the reproduced PHY parameters.

### RTL-SDR

Supporting instrument for:

- spectrum search;
- locating the actual leakage center frequency;
- measuring frequency offset;
- IQ recording;
- calibration before SX1262 packet tests.

## Laboratory isolation rules

- Only owned hardware and controlled laboratory signals are in scope.
- Initial receiver development is receive-only.
- No third-party systems, displays, cables, or communications are targets.
- Hardware state, software versions, frequencies, sample rates, and test
  results must be recorded for every experiment.
- `meshtasticd` must be restored after a bounded custom-radio test unless a
  separately approved persistent change is made.
