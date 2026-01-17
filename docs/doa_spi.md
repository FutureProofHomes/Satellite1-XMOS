# DoA SPI Interface (Path B)

## Overview
The XMOS firmware computes DoA (azimuth + confidence) from the 4‑mic array and exposes results over the device control SPI interface.

## Resource + Commands
- Resource ID: `230` (DOA servicer)
- Commands (read only):
  - `0x80` (GET_RESULT): returns 2 floats (8 bytes)
    - `float azimuth_deg` (0–360)
    - `float confidence` (0–1)
  - `0x81` (GET_CAPS): returns 2 bytes
    - `0xA5` signature
    - `0x02` capability/version (offsets supported)
  - `0x02` (SET_OFFSETS): writes 4 floats (16 bytes)
    - `float delay_offsets_samples[4]` (relative to mic 0)

## Mic Mapping + Geometry
The firmware uses a 4‑mic mapping that keeps legacy E/W channels first:
- Mapping order: `E, W, N, S` (indices `4, 5, 0, 1` on the PDM pins)

Default XY positions (meters) used by the DoA estimator:
- Mic 0: `[ 0.035,  0.000]`
- Mic 1: `[ 0.000,  0.035]`
- Mic 2: `[-0.035,  0.000]`
- Mic 3: `[ 0.000, -0.035]`

If hardware geometry differs, update `doa_default_positions` in `satellite-xmos-firmware/src/doa/doa.c`.

## Quick Synthetic Validation
You can run a host-side synthetic check to verify the estimator math:
```
cc -Isatellite-xmos-firmware/src -o /tmp/doa_sim tools/doa/doa_sim.c satellite-xmos-firmware/src/doa/doa.c -lm
/tmp/doa_sim
```
