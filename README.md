# Satellite1 XMOS Firmware

This repository contains the XMOS firmware for Satellite1. It builds the
audio-pipeline firmware that runs on the Satellite1 XMOS HAT.

The XK-VOICE-SQ66 board is available for development and debugging when
xTAG/xscope visibility is needed. See [SQ66 Dev-Mode Workflow](docs/sq66-dev-mode.md).

## Prerequisites

- Git with access to the repository submodules.
- XMOS XTC Tools 15.3.1.
- Python 3.10.
- CMake 3.21 or newer.

Clone the repository and initialize its submodules:

```bash
git clone git@github.com:FutureProofHomes/Satellite1-XMOS.git
cd Satellite1-XMOS
git submodule update --init --recursive
```

Set the local XTC installation in an ignored `.env` file when it is not at the
default location used by `tools/env/xmos_env.sh`:

```bash
XMOS_XTC_ROOT=$HOME/Projects/FutureProofHomes/XMOS_XTC_15.3.1
```

Create the repository-local Python environment and install the required XMOS
Python tools:

```bash
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -c 'import xmos_ai_tools.runtime; print(xmos_ai_tools.runtime.__file__)'
```

Before configuring or building firmware, activate the Python environment and
load the XTC environment:

```bash
source .venv/bin/activate
source tools/env/xmos_env.sh
export PATH="$VIRTUAL_ENV/bin:$PATH"
```

## Satellite1 Targets

| Target | Purpose |
| --- | --- |
| `satellite1_firmware_fixed_delay` | Normal Satellite1 audio pipeline with fixed delay processing. |
| `satellite1_firmware_bypass` | Bypasses the microphone pipeline for raw microphone-path debugging. |
| `satellite1_firmware_adec` | Automatic delay-estimation and correction pipeline. |

Build the fixed-delay executable:

```bash
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cmake --build build --target satellite1_firmware_fixed_delay
```

Build Satellite1 factory and upgrade artifacts:

```bash
cmake --build build --target create_flash_img_satellite1_firmware_fixed_delay
cmake --build build --target create_upgrade_img_satellite1_firmware_fixed_delay
```

Replace `satellite1_firmware_fixed_delay` with another target from the table
when required. Generated artifacts are written to the selected build directory.

## Firmware Artifacts

For a firmware target named `<target>`, the build can produce:

| Artifact | Purpose |
| --- | --- |
| `<target>.xe` | XMOS executable used for xTAG/xscope development and debugging. |
| `<target>.factory.bin` | Factory flash image for initial/persistent installation. |
| `<target>.upgrade.bin` | DFU upgrade image for a device already running a compatible factory image. |
| `<target>.factory.md5`, `<target>.upgrade.md5` | MD5 sidecars used by current firmware-flashing workflows. |

Creating an artifact is separate from installing it on a device. Satellite1
factory installation is performed through the Satellite1 ESPHome/SPI flashing
workflow with the matching factory image and MD5 sidecar.

## Versioning And Reproducibility

Normal builds reject dirty source trees. Use a clean, committed checkout for
artifacts that will be shared, embedded in ESPHome, or used for comparison.

For a tracked development artifact, configure with:

```bash
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake \
  -DUSE_DEV_TRACKING=ON
```

This creates versioned artifact metadata under `dev_tracking/`. The firmware's
runtime version is a compatibility identifier; retain the generated metadata,
checksums, and Git commit for full artifact provenance.

`-DALLOW_DIRTY_VERSIONING=ON` is only for local throwaway builds of uncommitted
changes. Do not use those artifacts for release or ESPHome embedding.

## SQ66 Development And Debugging

When xTAG/xscope visibility is needed during Satellite1 firmware development,
use the [SQ66 Dev-Mode Workflow](docs/sq66-dev-mode.md). It provides adapter
detection, dev-mode builds, temporary xscope runs, and debugger invocation.
