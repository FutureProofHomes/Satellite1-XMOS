# SQ66 Manual Dev-Mode Build and HIL/E2E Test Runbook

This document is for users who want to run the SQ66 dev-mode firmware build and
the full hardware-in-the-loop (HIL) SQ66 pytest suite.

## What this covers

- Build SQ66 firmware in dev mode (`sq66_firmware_fixed_delay.xe`)
- Run the full SQ66 HIL/e2e pytest selection (`tests/test_hil` + `tests/test_hw_sq66_firmware`)
- Explain what each test validates

## Prerequisites

- SQ66 hardware connected and reachable by xTAG
- A reachable Pi host with Satellite1 SDK command available
- SSH access to the Pi host without interactive prompts
- Repo cloned with submodules and local `.venv` available (or creatable)

## Environment variables

Required:

- `SQ66_RPI_HOST=<ssh-host>`

Common/optional:

- `XMOS_ADAPTER_ID=<xtag-id>` (recommended if multiple adapters are present)
- `SQ66_RPI_CLI_CMD=<remote sat1 command>` (defaults to `sat1`)
- `SQ66_HIL_BOOT_WAIT_S=<seconds>` (runner settle time; default from tests is 8)

Test-control variables used by this suite:

- `SQ66_HIL=1` (enables SQ66 HIL tests)
- `SQ66_HIL_RUN_FIRMWARE=1` (auto-starts local firmware runner fixture)
- `SQ66_HIL_REQUIRE_RUNNER=1` (skip if runner is not enabled)

Optional DoA playback variables (for the DoA playback test):

- `SQ66_HIL_DOA_PLAYBACK=1` to enable playback test
- `SQ66_HIL_XSCOPE_LOG=<path-to-live-xscope-log>`
- `SQ66_HIL_DOA_TEST_ANGLES_DEG` (default `45,135`)
- `SQ66_HIL_DOA_TOLERANCE_DEG` (default `50`)
- `SQ66_HIL_DOA_MIN_SEPARATION_DEG` (default `35`)
- `SQ66_HIL_DOA_REQUIRE_ABSOLUTE=1` to enforce absolute-angle error threshold

## Important ordering rule

Always source XMOS environment before validating SQ66 env vars in your shell:

```bash
source tools/env/xmos_env.sh
```

`tools/env/xmos_env.sh` loads repo `.env` and exports variables used by local
commands and pytest child processes.

## Manual command sequence

Run these in order from the repo root.

1) Source XMOS env

```bash
source tools/env/xmos_env.sh
```

2) Prepare and activate Python environment

```bash
tools/env/python_env.sh --setup --with-tests
source .venv/bin/activate
```

3) Optional Pi-side preflight checks

```bash
ssh "$SQ66_RPI_HOST" "${SQ66_RPI_CLI_CMD:-sat1} --help"
ssh "$SQ66_RPI_HOST" "${SQ66_RPI_CLI_CMD:-sat1} -c 'import satellite1; print(1)'"
```

4) Build SQ66 dev-mode firmware

```bash
tools/e2e/run_sq66_dev.sh --build
```

Expected firmware artifact:

- `build_sq66_dev/sq66_firmware_fixed_delay.xe`

5) Run the full SQ66 HIL/e2e suite (recommended wrapper)

```bash
tools/e2e/run_sq66_hil_e2e.sh --full
```

If firmware is already running and should not be started by pytest:

```bash
tools/e2e/run_sq66_hil_e2e.sh --full --no-run-firmware
```

If using `--no-run-firmware` without a live xscope log path, the wrapper
automatically disables the xscope-based DoA playback test to avoid skip/fail
noise under strict no-skip mode. To force that test in this mode, set
`SQ66_HIL_XSCOPE_LOG` and keep optional tests enabled.

To run only smoke checks:

```bash
tools/e2e/run_sq66_hil_e2e.sh --smoke
```

`run_sq66_hil_e2e.sh` defaults to fail on skipped tests. Use `--allow-skips`
for exploratory runs, or `--disable-optional` to turn off optional DoA playback
gates explicitly.

## Full test inventory and purpose

### `tests/test_hw_sq66_firmware/test_sq66_hil_smoke.py`

- `test_sq66_detect_only_reports_adapter`
  - Verifies runner detect-only path works and reports adapter/build metadata.
- `test_sq66_cli_reads_firmware_and_status`
  - Verifies Pi-side CLI can read firmware version and XMOS status on SQ66.
- `test_sq66_cli_enforces_lineout_only`
  - Verifies speaker DAC operations are rejected on SQ66 with expected message.
- `test_sq66_cli_lineout_setup_and_volume`
  - Verifies line-out DAC setup and set/get volume command path.
- `test_sq66_cli_plugged_in_reports_unsupported`
  - Verifies line-out jack detect command is rejected as unsupported on SQ66.

### `tests/test_hil/*`

- Shared SAT1/SQ66 HIL coverage for:
  - mic input gain behavior
  - mic input/output packaging and routing
  - mic output device-control API round-trips

### `tests/test_hw_sq66_firmware/test_sq66_hil_doa_spi.py`

- `test_sq66_mic_input_routing_roundtrip_spi`
  - Verifies SQ66 mic-input routing/source-mode roundtrip over SDK/SPI.
- `test_sq66_doa_seq_progresses_with_packaged_playback_spi`
  - Verifies DoA raw/smooth sequence counters advance during packaged playback.
- `test_sq66_doa_estimate_from_packaged_wav_playback_spi`
  - Verifies DoA estimate behavior from packaged playback using SPI reads.

### `tests/test_hw_sq66_firmware/test_sq66_hil_doa_playback.py`

- `test_sq66_doa_estimate_from_packaged_wav_playback`
  - Synthesizes angle-tagged multichannel audio, plays it on Pi, and validates
    DoA estimation behavior from xscope logs.
  - Skipped unless `SQ66_HIL_DOA_PLAYBACK=1` and `SQ66_HIL_XSCOPE_LOG` points to
    a valid running xscope log file.

## Typical failure and fix

If pytest fails with:

- `xrun: Cannot connect, device is in use by another process`

clear stale debugger/runner processes and rerun:

```bash
pkill -f xrun || true
pkill -f xgdbserver || true
pkill -f xgdb || true
```
