# SQ66 Manual Dev-Mode Build and HIL/E2E Test Runbook

This document is for users who want to run the SQ66 dev-mode firmware build and
the full hardware-in-the-loop (HIL) SQ66 pytest suite manually.

## What this covers

- Build SQ66 firmware in dev mode (`sq66_firmware_fixed_delay.xe`)
- Run the full SQ66 HIL/e2e pytest selection in `tests/test_hw_sq66_firmware`
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

5) Run the full SQ66 HIL/e2e suite

```bash
SQ66_HIL=1 SQ66_HIL_RUN_FIRMWARE=1 .venv/bin/python -m pytest tests/test_hw_sq66_firmware -q
```

If firmware is already running and should not be started by pytest:

```bash
SQ66_HIL=1 .venv/bin/python -m pytest tests/test_hw_sq66_firmware -q
```

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

### `tests/test_hw_sq66_firmware/test_sq66_hil_mic_input_gain.py`

- `test_mic_input_settings_shape_sq66`
  - Verifies mic-input settings schema and expected channel-map lengths.
- `test_mic_input_gain_roundtrip_sq66`
  - Writes mic/ref gains and verifies values round-trip via readback.
- `test_mic_gain_changes_captured_level_sq66`
  - Verifies increasing mic gain raises captured RMS level.
  - May skip if captured signal is too small for reliable comparison.
- `test_ref_gain_changes_captured_level_sq66`
  - Verifies increasing reference gain raises captured RMS level.
  - May skip if reference-linked signal is not observable on this setup.

### `tests/test_hw_sq66_firmware/test_sq66_hil_mic_output_routing.py`

- `test_mic_output_get_settings_shape_sq66`
  - Verifies mic-output settings fields, types, and valid ranges.
- `test_mic_output_set_i2s_channel_map_roundtrip_sq66`
  - Verifies updating I2S output channel map round-trips correctly.
- `test_mic_output_set_pack_extra_roundtrip_sq66`
  - Verifies toggling pack-extra-upsample-channels round-trips correctly.
- `test_mic_output_set_upsample_channel_map_roundtrip_sq66`
  - Verifies updating upsample channel map round-trips correctly.
- `test_mic_output_partial_update_preserves_untouched_fields_sq66`
  - Verifies partial update changes only targeted fields.

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
