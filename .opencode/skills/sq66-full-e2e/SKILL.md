---
name: sq66-full-e2e
description: Deterministically build SQ66 dev-mode firmware and execute the full SQ66 HIL/e2e pytest suite.
compatibility: opencode
metadata:
  scope: sq66-full-e2e
  workflow: strict-sequence
---

## Purpose

Use this for requests like:
- "build the sq66 variant in dev mode and run a full end to end test"

This skill combines:
1) `sq66-devmode-run` build flow
2) `sq66-hil-e2e-tests` execution flow

## Required inputs

- Load `tools/env/xmos_env.sh` in the current shell before validating inputs;
  it sources repo `.env` and exports SQ66 HIL variables.
- `SQ66_RPI_HOST` must be set.
- `SQ66_HIL=1` must be set.

Recommended:

- `XMOS_ADAPTER_ID=<xtag-id>` when multiple adapters are connected.
- `SQ66_RPI_SAT1_CMD=<remote sat1 command>` when SDK is run from a non-default location (default: `sat1`).

For cached SDK execution on Pi, prefer:

`SQ66_RPI_SAT1_CMD='PYTHONPATH=$HOME/.cache/satellite1-rpi-e2e/src $HOME/.cache/venvs/satellite1-rpi-e2e/bin/python -m satellite1.cli.cli_sat1 --config $HOME/.cache/satellite1-rpi-e2e/satellite1.conf'`

Use single quotes so `$HOME` expands on the remote host.

If running the full `tests/test_hw_sq66_firmware` selection, prefer a wrapper
that supports both CLI and remote Python `-c` usage:

`SQ66_RPI_SAT1_CMD='/home/pi/.cache/satellite1-rpi-e2e/sat1_or_python.sh'`

## Canonical command sequence

0. Load XMOS env first so required variables are exported in this shell:

   `source tools/env/xmos_env.sh`

1. Ensure local Python env exists and is active for this shell:

   `tools/env/python_env.sh --setup --with-tests && source .venv/bin/activate`

2. Build SQ66 dev-mode firmware:

   `tools/e2e/run_sq66_dev.sh --build`

3. Run full SQ66 HIL/e2e suite:

   `source tools/env/xmos_env.sh && SQ66_HIL=1 SQ66_HIL_RUN_FIRMWARE=1 .venv/bin/python -m pytest tests/test_hw_sq66_firmware -q`

If firmware is already running and should not be restarted:

`source tools/env/xmos_env.sh && SQ66_HIL=1 .venv/bin/python -m pytest tests/test_hw_sq66_firmware -q`

Pi-side preflight (recommended):

`ssh "$SQ66_RPI_HOST" "${SQ66_RPI_SAT1_CMD:-sat1} --help"`

`ssh "$SQ66_RPI_HOST" "${SQ66_RPI_SAT1_CMD:-sat1} -c 'import satellite1; print(1)'"`

Environment setup reminders:

- `tools/env/python_env.sh --setup --with-tests`
- `source tools/env/xmos_env.sh`

`python_env.sh` keeps installs pinned to repo `.venv`. `xmos_env.sh` loads repo
`.env` and exports variables used by pytest and child processes.

## Execution rules

- Do not replace this sequence with ad hoc manual environment probing.
- Do not inspect external toolchain doc/version files (for example `XMOS_XTC_15.3.1/doc/version.txt`).
- Use repo wrappers/scripts only:
  - `tools/env/python_env.sh`
  - `tools/env/xmos_env.sh`
  - `tools/e2e/run_sq66_dev.sh`
  - `.venv/bin/python -m pytest ...`
- SDK deployment/install on target Pi is out of scope; provide `SQ66_RPI_SAT1_CMD` to point tests at the desired SDK location.
- If runner fails with `device is in use`, clear stale `xrun/xgdb/xgdbserver` processes before retrying.

## Output contract

Return:
- build result (`pass/fail` + target path)
- e2e result (counts of passed/failed/skipped)
- first failure root cause and next action (if any)
