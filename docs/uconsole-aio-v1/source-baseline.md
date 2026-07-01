# Upstream Source Baseline

## Repository identity

- Upstream repository: `XieyangSun/TEMPEST-LoRa`
- Laboratory fork: `GammaFunds/TEMPEST-LoRa`
- Upstream default branch: `main`
- Laboratory branch: `lab/uconsole-aio-v1`
- Baseline commit:
  `0a9f87c8907ceb2b5bca404556ab31f05c666c2a`
- Baseline commit subject: `Update README.md`
- Baseline commit time: `2025-11-26T16:49:41+08:00`

At baseline creation, all of the following referenced the same commit:

- local `main`;
- `origin/main`;
- `upstream/main`;
- local `lab/uconsole-aio-v1`.

The laboratory branch had no source difference from `upstream/main`.

## Repository inventory

The baseline contains 179 tracked files.

| Type | Count |
| --- | ---: |
| `.avi` | 36 |
| `.mat` | 26 |
| `.png` | 105 |
| `.m` | 6 |
| `.p` | 2 |
| `.ino` | 1 |
| `.md` | 1 |
| `.gitattributes` | 1 |
| no extension | 1 |

There are no tracked `.iq` or `.bin` files.

Git LFS is not configured by `.gitattributes`; the baseline only contains:

```text
* text=auto
```

## Reference display parameters

The open MATLAB configuration specifies:

| Parameter | Value |
| --- | ---: |
| Active width | 1920 pixels |
| Active height | 1080 pixels |
| Total width | 2200 pixels |
| Total height | 1125 pixels |
| Refresh rate | 60 Hz |
| Derived pixel clock | 148.5 MHz |

The open-source release explicitly states support for the
`1080x1920@60Hz` configuration.

## Reference LoRa parameters

The MATLAB configuration and the receiver sketch agree on:

| Parameter | Value |
| --- | ---: |
| Center frequency | 915 MHz |
| Bandwidth | 500 kHz |
| Spreading factor | SF7 |
| Coding-rate call | `setCodingRate(5)` |
| Effective coding rate | 4/5 |
| Preamble | 4 symbols |
| Sync values | `[9, 17]` |

The parsed SF7 symbol range is `0..127`.

The parsed payload contains 61 values. All 61 values are within the valid
SF7 symbol range. There is no confirmed out-of-range payload value.

## Original receiver source

Tracked receiver source:

```text
SX1262_Receive_Interrupt.ino
```

SHA-256:

```text
0da65d4afa51cafd7ac6acdcfbf08735a15f58642ecacfc6cf22dbe18445e206
```

The source uses RadioLib and constructs an `SX1262` instance, but it also
includes:

```cpp
#include "boards.h"
```

No `boards.h` file is tracked in this repository. The symbols provided by
that external board layer include the radio pin definitions and the initial
`LoRa_frequency` value.

The sketch calls:

```cpp
radio.begin(LoRa_frequency);
radio.setFrequency(915);
radio.setBandwidth(500);
radio.setSpreadingFactor(7);
radio.setCodingRate(5);
radio.setPreambleLength(4);
```

The original Arduino sketch is therefore a reference implementation rather
than a directly buildable receiver for the Linux-attached AIO V1 SX1262.

The laboratory receiver must be implemented as a Linux-native program using
the verified SPI/GPIO resources.

## CRC state

The only visible CRC-setting call is commented out:

```cpp
//radio.setCRC(1);
```

The source does not explicitly establish the active CRC mode. The effective
CRC behavior must be determined before the laboratory receiver contract is
finalized.

## MATLAB source inventory

| Path | SHA-256 |
| --- | --- |
| `EMR Tx/BlackPic.m` | `4c6acb063572d2edc8a0d46cced4969a9abcf561d5b19a2ec29d446fb7a64cdc` |
| `EMR Tx/CrossConfigFile.m` | `40c7e0ac5c2baeb349c91c437df375fd1da740b5ddb0797717003147bfc8c57c` |
| `EMR Tx/GenerateAttackVideo.m` | `f0b9fdb70a689fb6c727ea8cfbbd3499ef9957c61d62a45d92eb0be67815e6ba` |
| `EMR Tx/GetLoRaPacketInfo.m` | `0b26eac370453f47b48dc8d4733b437ae96e953145814443508e523313d349ed` |
| `EMR Tx/ReverseLoRaPacket.m` | `7dfcf95d08c69ba914f6b71bc7ab4dc4dad10a514e59f08783c8acbfd53c4777` |
| `EMR Tx/showSpectrum.m` | `427eb4b1f1d9424a37a6c018af591477b70cf2a5f3a75530643946935da21d2c` |

Protected MATLAB artifacts:

| Path | Size | SHA-256 |
| --- | ---: | --- |
| `EMR Tx/CalculateChirpPoints.p` | 388 bytes | `f2dd934b265e10313850bd2577e15b149dc68598f2894568ef4a4378e9a0ee49` |
| `EMR Tx/CalculateSFD.p` | 318 bytes | `59e5b15f2b39519d20f5185730b3884b70082f8f435a164247367db89aa17a71` |

The protected P-code can be treated as an executable upstream artifact, but
its implementation cannot be statically reviewed from this repository.

## Baseline file hashes

```text
LICENSE
2de372accbf15cd16ce4f194d820e4a194c7891ba29b08014e4e43650ca23418

README.md
3b5e7c7a7e5b289f94485baabdbbf292384ea901ab21b8c2dff67f4fd243d0cd
```

## Change policy

- The upstream-derived `main` branch should remain unchanged where possible.
- Laboratory adaptations belong on bounded feature or lab branches.
- No upstream source correction is made merely because an anomaly is
  suspected.
- Every correction requires evidence, review, and explicit approval.
- Commit, merge, and push remain separate approval boundaries.
