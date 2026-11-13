# AGENTS.md

Guide for AI agents working on the Satellite1-XMOS codebase.

## What This Project Is

XMOS XS3-A firmware for the "Satellite1" voice assistant satellite. It runs a
real-time audio DSP pipeline (AEC → IC → VNR → NS → AGC) on a 2-tile, 14-core
XMOS chip, streaming processed 16 kHz audio to an ESP32-S3 (ESPHome) over I2S.
Also handles: USB DFU, SPI device control (LED ring, GPIO), PDM mic capture.

**This repo does NOT contain the ESP32/ESPHome firmware.** That is a separate
project: [FutureProofHomes/Satellite1-ESPHome](https://github.com/FutureProofHomes/Satellite1-ESPHome).
The ESP32 is the "brain" (Wi-Fi, wake-word, cloud); this firmware is
the "ears" (audio front-end DSP).

You can build the firmware here once the tools and dependencies are installed.

## Build Commands

Prerequisites: XMOS XTC-Tools 15.3.1 installed and `XMOS_XTC_ROOT` set in
`~/.env` (sourced by `tools/env/xmos_env.sh`). Repo already cloned.

```bash
# One-time setup
git submodule update --init --recursive
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build firmware
source tools/env/xmos_env.sh
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cmake --build build --target create_flash_img_satellite1_firmware_fixed_delay -j$(nproc)

# Unit tests (no hardware required)
pip install -r requirements_tests.txt
pytest tests/test_versioning/ tests/test_package_firmware_deb.py -v
```

## Directory Structure

```
Satellite1-XMOS/
├── CMakeLists.txt              # Top-level CMake (project root)
├── xmos_macros.cmake           # Custom CMake macros (flash, DFU, merge, run)
├── firmware_version.txt        # Current version string (e.g. "dev", "v1.2.0")
├── requirements.txt            # Python deps for build (xmos-ai-tools)
├── requirements_tests.txt      # Python deps for tests (pytest)
├── LICENSE.md                  # XMOS Public Licence v1
├── README.md                   # Build + flash instructions
│
├── satellite-xmos-firmware/    # THE FIRMWARE (project-local source)
│   ├── firmware.cmake          # Entry point: sources, flags, pipeline options
│   ├── satellite1.cmake        # Per-variant build targets (tile0/tile1, merge)
│   ├── versioning.py           # Version management tool
│   ├── src/                    # Application source
│   │   ├── main.c              # Entry point: tile dispatch, pipeline I/O, servicers
│   │   ├── app_conf.h          # Pipeline/I2S/core config (compile-time)
│   │   ├── app_conf_check.h    # Static asserts on config consistency
│   │   ├── ff_appconf.h        # FFVA app configuration
│   │   ├── FreeRTOSConfig.h    # FreeRTOS tuning
│   │   ├── config.xscope       # xscope debugger config
│   │   ├── fractions_1000ppm.h # Clock fraction constants
│   │   ├── register_setup_1000ppm.h  # Clock register pre-computed values
│   │   ├── control/            # SPI device-control servicer
│   │   │   ├── servicer.c/h    #   Command dispatch
│   │   │   └── cmd_map.h       #   Command ID mapping
│   │   ├── dfu_int/            # USB DFU servicer
│   │   │   ├── dfu_servicer.c/h
│   │   │   ├── dfu_state_machine.c/h
│   │   │   ├── dfu_cmds.c/h
│   │   │   └── dfu_common.c/h
│   │   ├── gpio/               # GPIO servicer
│   │   │   └── gpio_servicer.c/h
│   │   └── led_ring/           # WS2812 LED ring servicer
│   │       └── (led_ring sources)
│   ├── audio_pipelines/        # DSP pipeline variants
│   │   ├── CMakeLists.txt
│   │   ├── reference/          # Pipelines with echo reference (AEC-capable)
│   │   │   ├── audio_pipeline.h
│   │   │   ├── CMakeLists.txt
│   │   │   ├── fixed_delay/    #   PRODUCTION: AEC (0ms delay) + IC + NS + AGC
│   │   │   ├── adec/           #   AEC with adaptive delay estimation
│   │   │   ├── adec_alt_arch/  #   Alternative ADEC architecture
│   │   │   └── empty/          #   Empty pipeline (testing)
│   │   ├── referenceless/      # Pipelines without echo reference
│   │   └── speaker/            # Speaker (output) pipeline
│   ├── bsp_config/             # Board Support Package
│   │   ├── bsp_config.cmake    #   Selects board via -DBOARD=
│   │   └── SATELLITE1/         #   Satellite1 board definition
│   │       ├── SATELLITE1.cmake    #   CMake: pins, clocks, mic config
│   │       ├── SATELLITE1.xn       #   XMOS network: pin assignments
│   │       └── platform/         #   Platform init, PLL, driver instances
│   └── filesystem_support/     # FAT filesystem content (data partition)
│
├── modules/                    # XMOS framework + libraries
│   ├── CMakeLists.txt          #   Guards: voice/inferencing only for XCORE
│   ├── core/                   # [SUBMODULE] xmos/fwk_core
│   ├── io/                     # [SUBMODULE] xmos/fwk_io
│   ├── rtos/                   # [SUBMODULE] xmos/fwk_rtos (FreeRTOS, drivers)
│   ├── voice/                  # [SUBMODULE] xmos/fwk_voice (AEC/IC/NS/AGC/VNR)
│   ├── sw_pll/                 # [SUBMODULE] xmos/lib_sw_pll
│   ├── xua/                    # [SUBMODULE] xmos/lib_xua (USB Audio)
│   ├── inferencing/            # [SUBMODULE] TFLite Micro, lib_nn
│   ├── sample_rate_conversion/ # [SUBMODULE] lib_src
│   ├── lib_qspi_fast_read/     # [SUBMODULE] QSPI fast read
│   ├── xscope_fileio/          # [SUBMODULE] xscope file I/O
│   └── fph/                    # PROJECT-LOCAL custom libraries (not a submodule)
│       ├── CMakeLists.txt
│       ├── rtos_device_control/  # SPI device-control protocol stack
│       ├── rtos_mic_array/       # PDM mic array driver
│       ├── i2s_sync/             # I2S sync/transport
│       ├── rtos_ws2812/          # WS2812 (Neopixel) driver
│       └── qspi_flash_ext/       # QSPI flash extensions
│
├── xmos_cmake_toolchain/       # [SUBMODULE] CMake toolchain for XS3A
│
├── tests/                      # Test suite
│   ├── conftest.py             # Shared fixtures (HW_TESTS env gate)
│   ├── test_versioning/        # Unit tests for versioning.py
│   ├── test_package_firmware_deb.py  # Debian packaging test
│   └── test_hw_sat1_firmware/  # Hardware tests (require physical device)
│       └── test_usb_dfu.py     #   USB DFU round-trip test
│
├── tools/                      # Build and CI scripts
│   ├── ci/
│   │   ├── build_firmware.sh   #   CI firmware build script
│   │   ├── build_host_apps.sh  #   CI host-app build script
│   │   ├── package_firmware_deb.sh  # Debian .deb packaging
│   │   ├── helper_functions.sh #   Shared CI helpers
│   │   ├── log_metadata.sh     #   GitHub Actions metadata
│   │   └── firmwares.txt       #   Build manifest (name, target, board, toolchain)
│   └── env/
│       └── xmos_env.sh         # Sources XMOS XTC SetEnv.sh + .env
│
├── debian/                     # Debian package template
│   └── control.in
│
├── .github/workflows/          # CI/CD
│   ├── apps.yml                # PR build: firmware + host apps + .deb
│   └── release.yml             # Release: tag, build, GitHub Release, docs update
│
└── docs/                       # Developer documentation
    ├── architecture.md         # System architecture overview
    ├── audio-pipeline.md       # DSP pipeline documentation
    ├── device-control-spi-protocol.md  # SPI protocol spec
    └── versioning.md           # Versioning scheme
```

## CMake Build Hierarchy

```
CMakeLists.txt
    ├── include(xmos_macros.cmake)       # Custom macros
    ├── add_subdirectory(modules/)       # All framework libs
    │     ├── core, io, rtos, voice, ... # Upstream XMOS submodules
    │     └── fph/                       # Project-local libs
    └── include(satellite-xmos-firmware/firmware.cmake)  # The app
          ├── bsp_config/bsp_config.cmake  # Board selection
          ├── audio_pipelines/             # Pipeline targets
          └── satellite1.cmake             # Tile targets, merge, flash
```

## Submodules vs Local Code

| Directory | Type | Upstream |
|-----------|------|----------|
| `modules/core/` | Submodule | `xmos/fwk_core` |
| `modules/io/` | Submodule | `xmos/fwk_io` |
| `modules/rtos/` | Submodule | `xmos/fwk_rtos` |
| `modules/voice/` | Submodule | `xmos/fwk_voice` |
| `modules/sw_pll/` | Submodule | `xmos/lib_sw_pll` |
| `modules/xua/` | Submodule | `xmos/lib_xua` |
| `modules/inferencing/` | Submodule | `xmos/lib_tflite_micro`, `xmos/lib_nn` |
| `modules/sample_rate_conversion/` | Submodule | `xmos/lib_src` |
| `modules/lib_qspi_fast_read/` | Submodule | `xmos/lib_qspi_fast_read` |
| `modules/xscope_fileio/` | Submodule | `xmos/xscope_fileio` |
| `xmos_cmake_toolchain/` | Submodule | `xmos/xmos_cmake_toolchain` |
| `modules/fph/` | **Local** | — (project-specific, committed directly) |
| `satellite-xmos-firmware/` | **Local** | — (the actual firmware application) |

## Critical File Map

| What | Where |
|------|-------|
| Entry point (tile dispatch) | `satellite-xmos-firmware/src/main.c` |
| App config (sample rate, bypass flags) | `satellite-xmos-firmware/src/app_conf.h` |
| Pipeline config (channels, AEC phases, frame size) | `satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/audio_pipeline_dsp.h` |
| Tile 0 pipeline (IC+VNR, NS, AGC) | `satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/audio_pipeline_t0.c` |
| Tile 1 pipeline (delay, AEC) | `satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/audio_pipeline_t1.c` |
| AEC frame processor | `satellite-xmos-firmware/audio_pipelines/reference/fixed_delay/aec/aec_process_frame_1thread.c` |
| Board config (pins, clocks, mic array) | `satellite-xmos-firmware/bsp_config/SATELLITE1/SATELLITE1.cmake` |
| Pin assignments | `satellite-xmos-firmware/bsp_config/SATELLITE1/SATELLITE1.xn` |
| Build targets (per-variant) | `satellite-xmos-firmware/satellite1.cmake` |
| Source gathering + flags | `satellite-xmos-firmware/firmware.cmake` |
| Version management | `satellite-xmos-firmware/versioning.py` |
| CMake macros (flash, DFU, merge) | `xmos_macros.cmake` |
| SPI device-control protocol | `modules/fph/rtos_device_control/` |
| PDM mic driver | `modules/fph/rtos_mic_array/` |
| I2S transport | `modules/fph/i2s_sync/` |
| LED ring driver | `modules/fph/rtos_ws2812/` |
| USB DFU servicer | `satellite-xmos-firmware/src/dfu_int/` |
| GPIO servicer | `satellite-xmos-firmware/src/gpio/` |
| LED ring servicer | `satellite-xmos-firmware/src/led_ring/` |
| CI build script | `tools/ci/build_firmware.sh` |
| CI manifest (what to build) | `tools/ci/firmwares.txt` |
| GitHub Actions workflows | `.github/workflows/apps.yml`, `release.yml` |
| DSP library (AEC/IC/NS/AGC/VNR) | `modules/voice/` (submodule — READ ONLY) |
| FreeRTOS + drivers | `modules/rtos/` (submodule — READ ONLY) |

## Architecture in 30 Seconds

```
PDM mics → [Tile 1: gain → delay → AEC] → intertile port 7 → [Tile 0: IC+VNR → NS → AGC] → I2S → ESP32
                                                                                        → SPI ← ESP32 (control)
                                                                                        → USB (DFU)
                                                                                        → WS2812 (LEDs)
```

- Frame size: 240 samples (15 ms) at 16 kHz
- 2 mic channels, 2 reference channels
- AEC: 10 main + 5 shadow filter phases
- AGC: `AGC_PROFILE_ASR` profile
- VNR: TFLite Micro model (13 KB), runs on Tile 0

## Conventions

- **C code:** 4-space indent, `snake_case` functions, `SCREAMING_SNAKE_CASE`
  macros, `/* */` comments. No C++ in firmware. No heap allocation in
  pipeline stages (use static `DWORD_ALIGNED` state).
- **CMake:** Follow existing patterns in `satellite1.cmake` and `firmware.cmake`.
  Use `target_compile_definitions` for config, not `#define` in source.
- **Python:** PEP 8. Only used for build tools and tests.
- **Naming:** Pipeline variants use `satellite1_firmware_<name>`.
  Pipeline stages use `stage_<name>` function names.

## Rules

### DO
- Modify code in `satellite-xmos-firmware/` (the application)
- Modify code in `modules/fph/` (project-local libraries)
- Modify CMake files in `satellite-xmos-firmware/`
- Add new pipeline variants under `audio_pipelines/reference/`
- Add new servicers under `satellite-xmos-firmware/src/`
- Write tests under `tests/`
- Update docs in `docs/`

### DO NOT
- Modify anything inside `modules/` submodules (core, io, rtos, voice,
  sw_pll, xua, inferencing, sample_rate_conversion, lib_qspi_fast_read,
  xscope_fileio). These are upstream XMOS libraries pinned by git SHA.
  If you need a change, note it — do not edit the submodule.
- Modify `xmos_cmake_toolchain/` (submodule).
- Change `AP_FRAME_ADVANCE` from 240 without updating ALL dependent code
  (AEC, NS, AGC all assert on this value).
- Change clock frequencies in `SATELLITE1.cmake` without also updating
  `fractions_1000ppm.h` and `register_setup_1000ppm.h`.
- Add heap allocation (`pvPortMalloc`/`malloc`) in pipeline stage functions.
  Use static state.
- Commit build artifacts, `.env` files, or secrets.
- Use `#include <bits/...>` or other GCC-internal headers.

## Verifying Changes

Verify changes by building the firmware (once tools are installed) or, if
the toolchain is unavailable, by:

1. **Reading the code carefully** — check that function signatures match
   declarations in headers, that includes are correct, that preprocessor
   guards are consistent.
2. **Running Python tests** for versioning/packaging changes:
   ```bash
   pytest tests/test_versioning/ -v
   ```
3. **Checking CMake consistency** — if you add a source file, verify it will
   be picked up by the `file(GLOB_RECURSE ...)` in `firmware.cmake` or that
   you added it to the correct `target_sources()`.
4. **Cross-referencing config** — if you change a value in `app_conf.h`,
   check that `app_conf_check.h` static asserts still hold.

## Common Tasks

### Add a new pipeline stage (e.g., on Tile 0)
1. Add `static void stage_my_stage(frame_data_t *frame_data) { ... }` in
   `audio_pipeline_t0.c`.
2. Add `static my_state_t DWORD_ALIGNED my_stage_state = {};` near the top.
3. Initialize it in `initialize_pipeline_stages()`.
4. Add to `stages[]` array in `audio_pipeline_init()` (in the correct order).
5. Add stack size to `stage_stack_sizes[]`.
6. Increment `stage_count`.
7. If it needs a config value, add it to `audio_pipeline_dsp.h`.

### Add a new firmware variant
1. Create directory: `audio_pipelines/reference/<name>/`
2. Copy `fixed_delay/` as a starting point, modify as needed.
3. Add CMake target in `audio_pipelines/reference/CMakeLists.txt`.
4. Add to `FFVA_PIPELINES_INT` list in `firmware.cmake`.
5. Add to `tools/ci/firmwares.txt` if it should be built in CI.

### Change the mic count or sample rate
1. Update `MIC_ARRAY_CONFIG_MIC_COUNT` / `MIC_ARRAY_CONFIG_PDM_FREQ` in
   `SATELLITE1.cmake`.
2. Update `appconfAUDIO_PIPELINE_SAMPLE_RATE` in `app_conf.h` if needed.
3. Verify `AP_FRAME_ADVANCE` still divides evenly into the sample rate
   for the desired frame period.
4. Check RAM: each channel × frame_advance × 4 bytes × number_of_stages.

### Debug a DSP issue
1. The `mic_samples_passthrough` field in `frame_data_t` preserves the raw
   mic signal pre-AEC for comparison.
2. `aec_reference_audio_samples[0]` stores IC output (when
   `appconfAUDIO_PIPELINE_STORE_IC_AUDIO=1`).
3. `aec_reference_audio_samples[1]` stores NS output (when
   `appconfAUDIO_PIPELINE_STORE_NS_AUDIO=1`).
4. For xscope debugging: build the `.xe` target, run
   `xrun --xscope satellite1_firmware_fixed_delay.xe` on an xTAG.

## Documentation

| Doc | Content |
|-----|---------|
| `docs/architecture.md` | System overview, data flow, tile split, clocks |
| `docs/audio-pipeline.md` | DSP stages, frame format, config, how to add stages |
| `docs/device-control-spi-protocol.md` | SPI protocol spec (v0x11) |
| `docs/versioning.md` | Version scheme, ESPHome integration |
| `CONTRIBUTING.md` | Build instructions, branching model, PR guidelines |
