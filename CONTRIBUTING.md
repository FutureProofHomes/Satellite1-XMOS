# Contributing

## Prerequisites

- **XMOS XTC-Tools 15.3.1** — download from [xmos.com/software-tools](https://www.xmos.com/software-tools/)
- **CMake >= 3.21**
- **Python 3.10+** with `xmos-ai-tools==1.3.1` (for TFLite model conversion)
- **dfu-util** (for flashing via USB)
- **Git** with submodule support

## Building

```bash
# 1. Clone with submodules
git clone https://github.com/FutureProofHomes/Satellite1-XMOS.git
cd Satellite1-XMOS
git submodule update --init --recursive

# 2. Source the XMOS toolchain
source tools/env/xmos_env.sh
# (or manually: source /path/to/XMOS_XTC_15.3.1/SetEnv.sh)

# 3. Set up Python (for xmos-ai-tools / TFLite conversion)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 4. Build
cmake -B build --toolchain xmos_cmake_toolchain/xs3a.cmake
cd build
make create_flash_img_satellite1_firmware_fixed_delay -j$(nproc)
make create_upgrade_img_satellite1_firmware_fixed_delay -j$(nproc)
```

### Build Targets

| Target | Output |
|--------|--------|
| `satellite1_firmware_fixed_delay` | `.xe` executable |
| `create_flash_img_satellite1_firmware_fixed_delay` | `.factory.bin` + `.factory.md5` |
| `create_upgrade_img_satellite1_firmware_fixed_delay` | `.upgrade.bin` + `.upgrade.md5` |
| `make_data_partition_satellite1_firmware_fixed_delay` | `_data_partition.bin` |
| `debug_satellite1_firmware_fixed_delay` | Run under xgdb |

Replace `fixed_delay` with `adec` or `bypass` for other variants.

## Code Style

- **C:** XMOS/XC convention. 4-space indent, `snake_case` functions,
  `SCREAMING_SNAKE_CASE` macros. No C++ in firmware code.
- **CMake:** `snake_case` variables for local, `UPPER_CASE` for interface.
- **Python:** PEP 8. Used only for build tools (`versioning.py`) and tests.

## Branching Model

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases. Only receives merges from `staging`. |
| `staging` | Integration branch. PRs merge here for release candidates. |
| `develop` | Day-to-day development. Feature branches merge here. |
| `feature/*` | Individual features/fixes. Short-lived. |

### Release Process

1. Merge feature branches into `staging`.
2. Push to `staging` triggers `release.yml`:
   - Auto-bumps semver tag (e.g. `v1.2.0-beta`)
   - Builds all firmware variants in Docker
   - Packages `.deb`
   - Creates a GitHub Release with binary assets
   - Dispatches a workflow in `FutureProofHomes/Documentation` to host binaries
3. After validation, merge `staging` → `main` for a stable release
   (tag becomes `v1.2.0` without pre-release suffix).

## Pull Request Guidelines

- Branch from `develop`.
- Keep PRs focused. One logical change per PR.
- Include a description of what changed and why.
- For DSP changes: note which pipeline variant(s) are affected and whether
  the change affects audio output (may require baseline updates).
- For hardware/BSP changes: note pin mappings or clock changes.
- CI must pass before merge (firmware build in Docker).

## Versioning

- Do NOT manually edit `firmware_version.txt` for feature branches.
  Leave it as `dev` — the release workflow handles version bumps.
- For local testing builds, use the dev-tracking workflow:
  ```bash
  python satellite-xmos-firmware/versioning.py build satellite1_firmware_fixed_delay --track
  ```
  This generates a version like `v0.0.0-dev.42` with git metadata.

## Testing

```bash
# Unit tests (no hardware needed)
source .venv/bin/activate
pip install -r requirements_tests.txt
pytest tests/test_versioning/ tests/test_package_firmware_deb.py -v

# Hardware tests (require Satellite1 connected via USB)
HW_TESTS=1 pytest tests/test_hw_sat1_firmware/ -v
```

## Flashing

See `README.md` for flashing instructions (ESPHome, dfu-util, xTAG).

## Things NOT to Do

- Do not modify code in `modules/` submodules (core, io, rtos, voice, etc.).
  These are upstream XMOS libraries. Pin changes only.
- Do not commit build artifacts (`build/`, `dist/`, `*.xe`, `*.bin`).
- Do not commit `.env` files (they contain local paths).
- Do not change the I2S or PDM clock frequencies without updating
  `SATELLITE1.cmake`, `fractions_1000ppm.h`, AND `register_setup_1000ppm.h`
  together.
- Do not increase `AP_FRAME_ADVANCE` without checking RAM budget
  (each channel adds 240 × 4 bytes per frame per stage).
