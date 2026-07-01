# Known Upstream Anomalies and Unresolved Questions

This document records observations without modifying the upstream-derived
files.

## A-001: Missing `boards.h`

### Observation

`SX1262_Receive_Interrupt.ino` includes:

```cpp
#include "boards.h"
```

No `boards.h` file is tracked at baseline commit
`0a9f87c8907ceb2b5bca404556ab31f05c666c2a`.

The sketch also depends on board-layer symbols such as:

- `RADIO_CS_PIN`;
- `RADIO_DIO1_PIN`;
- `RADIO_RST_PIN`;
- `RADIO_BUSY_PIN`;
- `LoRa_frequency`;
- optional display objects and feature macros.

### Consequence

The sketch is not a self-contained build target from this repository alone.

### Laboratory disposition

Do not reconstruct or guess the missing board header for the AIO V1.
Use the sketch only as a PHY and receive-flow reference. Implement a bounded
Linux-native SX1262 receiver against the verified AIO V1 SPI/GPIO mapping.

## A-002: CRC mode is not explicit

### Observation

The receiver contains only a commented CRC call:

```cpp
//radio.setCRC(1);
```

### Consequence

The intended CRC mode cannot be established solely from the visible receiver
source. Library defaults may also depend on the RadioLib version.

### Laboratory disposition

Treat CRC mode as unresolved. Determine it from upstream documentation,
compatible reference packets, and controlled receiver tests before fixing
the Linux receiver contract.

## A-003: Protected MATLAB P-code

### Observation

The following functions are supplied only as protected MATLAB P-code:

```text
EMR Tx/CalculateChirpPoints.p
EMR Tx/CalculateSFD.p
```

### Consequence

The two central transformations cannot be statically reviewed from the
repository. Compatibility with the laboratory MATLAB version has not yet
been established.

### Laboratory disposition

Preserve the files byte-for-byte. Record MATLAB version and execution
results when they are tested. Do not attempt to replace the protected
functions without a separate design and evidence review.

## A-004: Frequency labels disagree in eight sample filenames

### Observation

The directory:

```text
AttackSamples/SF7_125kHz_915MHz/
```

contains a correctly named zero-offset file:

```text
SF7_125kHz_ABC_915MHz_0HzOffset.avi
```

but the eight non-zero-offset files identify `433MHz` in their filenames:

```text
SF7_125kHz_ABC_433MHz_+50kHzOffset.avi
SF7_125kHz_ABC_433MHz_+100kHzOffset.avi
SF7_125kHz_ABC_433MHz_+150kHzOffset.avi
SF7_125kHz_ABC_433MHz_+200kHzOffset.avi
SF7_125kHz_ABC_433MHz_-50kHzOffset.avi
SF7_125kHz_ABC_433MHz_-100kHzOffset.avi
SF7_125kHz_ABC_433MHz_-150kHzOffset.avi
SF7_125kHz_ABC_433MHz_-200kHzOffset.avi
```

A repository-wide directory/filename comparison found exactly eight such
frequency-label mismatches among 140 comparable paths.

### Consequence

The filename alone cannot establish whether these eight files are 433 MHz
samples placed in the wrong directory or 915 MHz samples named incorrectly.

### Laboratory disposition

- Do not rename the files.
- Do not treat them as verified 915 MHz references.
- Preserve their hashes and paths.
- Determine their actual relationship only through metadata inspection,
  controlled playback, and RF observation.

## A-005: Stale receiver header comments

### Observation

The receiver file begins with comments describing an SX1276 transmit
example, while the implementation constructs an SX1262 and receives
packets.

### Consequence

The introductory comments are not reliable evidence of the implemented
radio or operation.

### Laboratory disposition

Use executable statements, repository documentation, and controlled tests
as evidence. Do not infer receiver behavior from the stale header block.

## A-006: Initialization frequency comes from an unavailable symbol

### Observation

The sketch first calls:

```cpp
radio.begin(LoRa_frequency);
```

and subsequently calls:

```cpp
radio.setFrequency(915);
```

`LoRa_frequency` is expected to come from the missing board layer.

### Consequence

The frequency passed to initial RadioLib setup is not knowable from the
tracked source, even though the later explicit call requests 915 MHz.

### Laboratory disposition

The Linux receiver must set all relevant parameters explicitly and verify
every return code. It must not depend on board-library defaults.

## Resolved observation: payload parsing

A previous visual reading could have been mistaken for a payload value
`4615`. Machine parsing established:

```text
payload values:             61
valid SF7 range:            0..127
out-of-range payload count: 0
```

The source contains separate values `46` and `15`. No payload correction is
required on this evidence.

## General anomaly policy

- Record observations before changing source or sample files.
- Distinguish verified facts from hypotheses.
- Do not silently repair upstream files.
- Preserve original paths and hashes.
- Use controlled experiments to resolve ambiguous RF or display behavior.
- Any corrective patch requires its own bounded review and explicit
  approval.
