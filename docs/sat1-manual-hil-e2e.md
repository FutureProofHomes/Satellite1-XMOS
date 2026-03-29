# Satellite1 Manual HIL/E2E Test Runbook

This document describes how to run the Satellite1 hardware-in-the-loop tests in
`tests/test_hw_sat1_firmware`.

## What this covers

- Run the Satellite1 HIL pytest selection without xscope dependencies
- Use the Pi-side `sat1` command with default board selection

## Prerequisites

- Satellite1 hardware connected and reachable
- A reachable Pi host with Satellite1 SDK command available
- SSH access to the Pi host without interactive prompts
- Repo cloned with submodules and local `.venv` available (or creatable)

## Environment variables

Required:

- `SAT1_RPI_HOST=<ssh-host>`

Common/optional:

- `SAT1_RPI_SAT1_CMD=<remote sat1 command>` (defaults to `sat1`)
- `SAT1_RPI_PY_CMD=<remote python command>` (defaults to `/opt/satellite1/venv/bin/python`)
- `SAT1_HIL=1` (enables Satellite1 HIL tests)
- `SAT1_HIL_SSH_CONNECT_TIMEOUT_S=<seconds>`
- `SAT1_HIL_SSH_TIMEOUT_S=<seconds>`
- `SAT1_HIL_REMOTE_SDK_TIMEOUT_S=<seconds>`

## Command sequence

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
ssh "$SAT1_RPI_HOST" "${SAT1_RPI_SAT1_CMD:-sat1} --help"
ssh "$SAT1_RPI_HOST" "${SAT1_RPI_PY_CMD:-/opt/satellite1/venv/bin/python} -c 'import satellite1; print(1)'"
```

4) Run Satellite1 HIL suite

```bash
SAT1_HIL=1 .venv/bin/python -m pytest -m "hil and sat1" tests/test_hw_sat1_firmware -q
```

## Current test inventory

- `tests/test_hw_sat1_firmware/test_sat1_hil_smoke.py`
  - CLI smoke checks for firmware/status read and DAC setup + volume flow.
- `tests/test_hw_sat1_firmware/test_sat1_hil_mic_input_gain.py`
  - Mic/ref gain round-trip and captured-level checks.
- `tests/test_hw_sat1_firmware/test_sat1_hil_mic_output_routing.py`
  - Mic output settings shape and partial/round-trip update checks.

## Notes on xscope

Satellite1 runs here do not rely on xscope logs or firmware print parsing. The
DoA playback/xscope-log validation remains in the SQ66-only suite.

## Optional flash-first flow (no xTAG)

If Satellite1 is not connected to xTAG and needs firmware provisioning from the
Pi host, use:

```bash
source tools/env/xmos_env.sh
SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --all
```

See `docs/sat1-flash-via-rpi.md` for full details.
