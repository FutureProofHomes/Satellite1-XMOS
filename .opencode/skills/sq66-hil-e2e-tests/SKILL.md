---
name: sq66-hil-e2e-tests
description: Run and triage SQ66 hardware-in-the-loop end-to-end pytest checks against XMOS firmware and Pi-side CLI integration.
compatibility: opencode
metadata:
  scope: sq66-hil
  workflow: hardware-test
---

## Purpose

Use this skill when validating SQ66 end-to-end behavior with real hardware.

This workflow covers:
- adapter detect-only checks
- optional firmware run orchestration via `tools/e2e/run_sq66_dev.sh`
- Pi-side CLI smoke checks (`<SQ66_RPI_SAT1_CMD> --board sq66 ...`)
- line-out-only capability enforcement checks

## Test suite

- `tests/test_hw_sq66_firmware/test_sq66_hil_smoke.py`

## Required environment

Set these before running HIL tests:

- `SQ66_HIL=1`
- `SQ66_RPI_HOST=<ssh-host>`

Optional:

- `SQ66_RPI_SAT1_CMD=<remote sat1 command>` (default: `sat1`)
- `XMOS_ADAPTER_ID=<xtag-id>` (recommended when multiple adapters are connected)
- `SQ66_HIL_RUN_FIRMWARE=1` (start firmware runner fixture automatically)
- `SQ66_HIL_REQUIRE_RUNNER=1` (require local runner fixture, otherwise skip)
- `SQ66_HIL_BOOT_WAIT_S=<seconds>` (boot settle time when auto-running firmware)

`SQ66_RPI_SAT1_CMD` allows running SDK tests from any install location on the Pi,
for example:

`PYTHONPATH=$HOME/.cache/satellite1-rpi-e2e/src $HOME/.cache/venvs/satellite1-rpi-e2e/bin/python -m satellite1.cli.cli_sat1 --config $HOME/.cache/satellite1-rpi-e2e/satellite1.conf`

When exporting from local shell, wrap the command in single quotes so `$HOME`
expands on the remote Pi shell (not locally), for example:

`SQ66_RPI_SAT1_CMD='PYTHONPATH=$HOME/.cache/satellite1-rpi-e2e/src $HOME/.cache/venvs/satellite1-rpi-e2e/bin/python -m satellite1.cli.cli_sat1 --config $HOME/.cache/satellite1-rpi-e2e/satellite1.conf'`

If the HIL selection includes tests that run remote Python `-c` snippets, ensure
`SQ66_RPI_SAT1_CMD` supports both patterns:
- CLI mode: `<cmd> --board sq66 ...`
- Python mode: `<cmd> -c '<python>'`

Recommended wrapper command:

`SQ66_RPI_SAT1_CMD='/home/pi/.cache/satellite1-rpi-e2e/sat1_or_python.sh'`

## Commands

Primary:

- `.venv/bin/python -m pytest tests/test_hw_sq66_firmware -q`

Marker scoped:

- `.venv/bin/python -m pytest -m "hil and sq66" tests/test_hw_sq66_firmware -q`

Single test examples:

- `.venv/bin/python -m pytest tests/test_hw_sq66_firmware/test_sq66_hil_smoke.py::test_sq66_detect_only_reports_adapter -q`
- `.venv/bin/python -m pytest tests/test_hw_sq66_firmware/test_sq66_hil_smoke.py::test_sq66_cli_enforces_lineout_only -q`

## Recommended execution order

1. Confirm adapter visibility with detect-only test.
2. Run firmware (`SQ66_HIL_RUN_FIRMWARE=1`) or ensure firmware is already running.
3. Preflight Pi-side CLI command:
   - `ssh "$SQ66_RPI_HOST" "${SQ66_RPI_SAT1_CMD:-sat1} --help"`
   - `ssh "$SQ66_RPI_HOST" "${SQ66_RPI_SAT1_CMD:-sat1} -c 'import satellite1; print(1)'"`
4. Run full SQ66 HIL smoke suite.

## Expected behavior

- If `SQ66_HIL` is not enabled, tests skip by design.
- If `SQ66_RPI_HOST` is missing, Pi-side tests skip.
- On SQ66, speaker DAC path must be rejected with explicit unsupported message.
- If Pi-side CLI import/setup is broken, tests fail in command execution; fixing SDK deploy is a precondition outside this skill.

## Failure triage

- Adapter detection failure:
  - verify xTAG connection and retry detect-only test
  - provide `XMOS_ADAPTER_ID` explicitly
- SSH/host failures:
  - verify `SQ66_RPI_HOST` connectivity and that `SQ66_RPI_SAT1_CMD` works on target
- `invalid choice` / argument parser errors in Python-snippet tests:
  - your command likely points to `sat1` only and does not support `-c`
  - switch to a wrapper command that dispatches `-c` to Python interpreter
- CLI expectation mismatch:
  - verify Satellite1-RPi branch/commit deployed on Pi matches local SDK contract
  - if CLI fails with `pydantic ... extra_forbidden`, ensure `--config` points to
    the SDK-matching config file and `SQ66_RPI_SAT1_CMD` uses remote `$HOME`
- Runner exited early:
  - run `tools/e2e/run_sq66_dev.sh --run` manually and inspect xscope output

## Notes

- Keep this skill focused on HIL/e2e execution and triage.
- Keep deterministic build/run/debug workflow details in `sq66-devmode-run`.
- Do not manually probe XMOS toolchain docs/version files; use repo wrappers and commands only.
- SDK deploy/install method is intentionally out of scope; this skill consumes an already working Pi-side command.
