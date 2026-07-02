# RadioLib provenance

The Linux SX1262 receiver uses RadioLib as an exact Git submodule.

| Field | Value |
| --- | --- |
| Repository | `https://github.com/jgromes/RadioLib.git` |
| Release tag | `7.7.1` |
| Commit | `034126ef3b5305394d1e4e14a5049482ec10c1c4` |
| Tree | `6c6fb4d440c8527ea9bc01f2ea0a3a03dcb0d226` |
| Git archive SHA-256 | `c4548bbb146f1727ff1a8ef6c95ec97f3badb2f42802ac59c3c5041d0a4fd6ca` |
| License file SHA-256 | `025378110a5679f82e8a59c19cf91b8ed760dc8752e5504596ef0c0592b8a3e8` |
| Local path | `third_party/RadioLib` |

The submodule must remain detached at the exact commit. Local changes inside
the submodule are not permitted.

The project-local `LabPiHal` is derived from the design of
`src/hal/RPi/PiHal.h`, but adds sticky error propagation, explicit resource
ownership, guarded cleanup, and an idempotent close path. The upstream
submodule itself remains unmodified.
