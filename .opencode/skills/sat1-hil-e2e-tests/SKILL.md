---
name: sat1-hil-e2e-tests
description: Run and triage Satellite1 hardware-in-the-loop tests against Pi-side sat1 CLI integration.
compatibility: opencode
metadata:
  scope: sat1-hil
  workflow: hardware-test
---

## Purpose

Use this skill when validating Satellite1 behavior with real hardware.

This workflow covers:
- Pi-side CLI smoke checks (`sat1 xmos ...` / `sat1 dac ...`)
- mic input gain and output routing tests in `tests/test_hw_sat1_firmware`
- optional flash-first flow via Pi-side CLI when xTAG is unavailable

## Required environment

Load XMOS env in the current shell before setting/running Sat1 HIL variables:

- `source tools/env/xmos_env.sh`

Set:

- `SAT1_HIL=1`
- `SAT1_RPI_HOST=<ssh-host>`

Optional:

- `SAT1_RPI_CLI_CMD=<remote sat1 command>` (default: `sat1`)
- `SAT1_RPI_PY_CMD=<remote python command>` (default: `/opt/satellite1/venv/bin/python`)

## Commands

Primary:

- `source tools/env/xmos_env.sh && SAT1_HIL=1 .venv/bin/python -m pytest tests/test_hw_sat1_firmware -q`

Marker scoped:

- `source tools/env/xmos_env.sh && SAT1_HIL=1 .venv/bin/python -m pytest -m "hil and sat1" tests/test_hw_sat1_firmware -q`

Smoke only:

- `source tools/env/xmos_env.sh && SAT1_HIL=1 .venv/bin/python -m pytest tests/test_hw_sat1_firmware/test_sat1_hil_smoke.py -q`

## Recommended execution order

1. Preflight local env and Pi CLI:
   - `source tools/env/xmos_env.sh`
   - `ssh "$SAT1_RPI_HOST" "${SAT1_RPI_CLI_CMD:-sat1} --help"`
   - `ssh "$SAT1_RPI_HOST" "${SAT1_RPI_PY_CMD:-/opt/satellite1/venv/bin/python} -c 'import satellite1; print(1)'"`
2. If firmware state is unknown, run flash-first workflow:
   - `SAT1_RPI_HOST=<ssh-host> tools/e2e/run_sat1_flash_via_rpi.sh --all`
3. Run Sat1 smoke tests.
4. Run full Sat1 HIL suite.

## Notes

- Satellite1 HIL tests do not depend on xscope logs.
- `tools/env/xmos_env.sh` is required for loading repo `.env` values like
  `SAT1_RPI_HOST` into the shell running pytest.
- Full Sat1 HIL uses two remote command paths:
  - CLI path via `SAT1_RPI_CLI_CMD` for `sat1 ...`
  - Python path via `SAT1_RPI_PY_CMD` for `python -c '...'` snippets
