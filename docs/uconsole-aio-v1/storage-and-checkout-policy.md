# Storage and Checkout Policy

## Measured baseline

Measured on the Arch Linux development checkout:

| Component | Disk usage | Apparent size |
| --- | ---: | ---: |
| `.git` | 6.3 MB | 6.1 MB |
| `AttackSamples` | 3.4 GB | 3.4 GB |
| `EMR Tx` | 160 KB | 22 KB |
| Complete checkout | 3.4 GB | 3.4 GB |

Git object database:

```text
packed objects: 234
pack count:     1
pack size:      6.00 MiB
loose objects:  0
garbage:        0
```

The large AVI files compress very strongly inside the Git pack but expand to
approximately 3.4 GB in the materialized working tree.

Git LFS is not used by the upstream baseline.

## Arch Linux policy

The Arch Linux host keeps a complete checkout at:

```text
/home/miko/GitHub/TEMPEST-LoRa
```

Reasons:

- MATLAB sender review requires the full source and sample inventory;
- sample-file anomalies can be examined locally;
- documentation and code development occur on this host;
- the Arch checkout is the authoritative development working copy.

## uConsole policy

The planned uConsole checkout is:

```text
/home/kali/GitHub/TEMPEST-LoRa
```

It should use a sparse working tree and should not materialize
`AttackSamples/` by default.

Required paths initially include:

```text
README.md
LICENSE
SX1262_Receive_Interrupt.ino
EMR Tx/
docs/
```

Future Linux receiver and hardware-test paths will be added explicitly after
they exist.

## Rationale

The uConsole is responsible for:

- SX1262 access through `/dev/spidev1.0`;
- GPIO interrupt, BUSY, RESET, RF-switch, and TCXO handling;
- RTL-SDR spectrum and IQ work;
- ARM64 compilation and hardware validation.

The 3.4 GB attack-video collection is not needed for these receiver tasks.
Avoiding its materialization reduces:

- storage use;
- clone and checkout time;
- backup volume;
- accidental interaction with large sample files;
- unrelated working-tree noise on the laboratory receiver.

## Checkout integrity requirements

A uConsole deployment must record:

- exact Git commit;
- exact branch or detached commit;
- sparse-checkout specification;
- clean or intentionally modified working-tree state;
- build command and toolchain versions;
- hardware configuration used for the test.

Hardware tests should normally consume an exact published or otherwise
recorded commit, rather than uncommitted development state copied manually
from another host.

## Data placement

Generated experiment data must not be placed casually inside tracked source
directories.

Expected generated artifacts include:

- RTL-SDR IQ captures;
- spectrum screenshots;
- receiver logs;
- packet result logs;
- generated attack videos;
- temporary MATLAB images.

Before such data is produced, the project must define:

- a dedicated data root;
- naming conventions;
- metadata sidecars;
- retention and backup rules;
- Git-ignore rules where appropriate;
- maximum expected sizes.

No generated-data directory or ignore rule is introduced by this baseline
documentation step.

## Repository expansion controls

Before adding binary captures or generated videos to Git:

1. determine the expected size;
2. determine whether the artifact is reproducible;
3. decide whether Git, Git LFS, release assets, or external laboratory
   storage is appropriate;
4. obtain explicit approval;
5. record hashes and provenance.

The existing upstream sample files remain untouched.

## R1 Linux SX1262 receiver deployment paths

The Linux receiver introduced in R1 adds these uConsole sparse-checkout paths:

```text
receiver/linux-sx1262/
third_party/RadioLib.PROVENANCE.md
third_party/RadioLib/
```

`third_party/RadioLib/` is an exact Git submodule and must be initialized
explicitly at the commit recorded in the provenance file. It must not track an
unpinned branch and must remain free of local modifications.

The receiver source and RadioLib submodule do not change the policy excluding
`AttackSamples/` from the default uConsole checkout.

Deployment, submodule initialization, `liblgpio-dev` installation, hardware
compilation, and the meshtasticd stop-test-restore procedure remain separate
approval boundaries.
