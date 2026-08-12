# SQ66 Dev-Mode Workflow

This guide describes the local development workflow for the XK-VOICE-SQ66
board. It builds the `sq66_firmware_fixed_delay` executable and loads it
temporarily through an xTAG adapter. It does not create or write a persistent
flash image.

## Prerequisites

- An XK-VOICE-SQ66 board connected through an XMOS xTAG adapter.
- XMOS XTC Tools 15.3.1 installed locally.
- Python 3.10 and the repository-local `.venv` with `xmos-ai-tools` installed.
- An initialized recursive submodule checkout.

Configure local paths and the preferred adapter in an ignored `.env` file at
the repository root:

```bash
XMOS_XTC_ROOT=$HOME/Projects/FutureProofHomes/XMOS_XTC_15.3.1
SQ66_XTAG_ID=7A3VAER2
```

`XMOS_ADAPTER_ID` is accepted as a fallback when `SQ66_XTAG_ID` is not set.

## Detect The Adapter

Source the environment before invoking XMOS tools:

```bash
source tools/env/xmos_env.sh
bash tools/e2e/run_sq66_dev.sh --detect-only
```

The command prints the selected adapter and the default build target:

```text
mode=run
build_dir=build_sq66_dev
target=sq66_firmware_fixed_delay
adapter_id=<xTAG-id>
```

If multiple adapters are connected, set `SQ66_XTAG_ID` or pass
`--adapter-id <xTAG-id>` explicitly.

## Build

Build the SQ66 fixed-delay firmware in dev mode:

```bash
bash tools/e2e/run_sq66_dev.sh --build
```

This configures `build_sq66_dev/` with `USE_DEV_MODE=ON` and produces:

```text
build_sq66_dev/sq66_firmware_fixed_delay.xe
```

Dev mode enables SQ66 diagnostic output and disables the firmware watchdog.
Builds from dirty source are rejected by default. For a local, non-shareable
bring-up build only, opt in explicitly:

```bash
SQ66_ALLOW_DIRTY_BUILD=1 bash tools/e2e/run_sq66_dev.sh --build
```

Do not use that override for release, shareable, or embedded firmware
artifacts.

## Run With xscope

Load the built executable temporarily through xTAG and capture xscope output:

```bash
bash tools/e2e/run_sq66_dev.sh --run --skip-build
```

The runner uses:

```text
xrun --adapter-id <xTAG-id> --xscope build_sq66_dev/sq66_firmware_fixed_delay.xe
```

`xrun` loads the executable for the active debug session only. It does not
flash the SQ66 QSPI device. Stop the session with `Ctrl-C`.

Before running or debugging, ensure no other `xrun`, `xgdb`, or `xgdbserver`
process owns the adapter. The runner refuses to start when it detects one.

Expected current board-support output includes GPIO and DFU device-control
servicer registration, for example:

```text
Calling device_control_servicer_register(), servicer ID 210, on tile 1, core ...
Calling device_control_servicer_register(), servicer ID 240, on tile 0, core ...
GPIO handler task on tile 1, core ...
```

These lines confirm the basic GPIO and DFU servicers registered. They do not
by themselves validate PDM capture, I2S audio, or host SPI transactions.

## Debug

Launch the executable through the XMOS debugger instead of `xrun`:

```bash
bash tools/e2e/run_sq66_dev.sh --debug --skip-build
```

Pass `--adapter-id <xTAG-id>`, `--build-dir <path>`, or `--target <name>` when
working with a non-default adapter, build directory, or SQ66 target.
