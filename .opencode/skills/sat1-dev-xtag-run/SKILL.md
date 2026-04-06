---
name: sat1-dev-xtag-run
description: Build, run, and debug Satellite1 firmware over xTAG/JTAG using the repo helper script (no xscope).
compatibility: opencode
metadata:
  scope: sat1-bringup
  workflow: script-first
---

## Purpose

Use this skill for local Satellite1 bring-up when you need a known-good xTAG workflow for:
- adapter detection
- firmware build validation
- xrun launch
- xgdb launch

Satellite1 in this workflow does not provide xscope logs.

## Primary interface

Use:
- `tools/e2e/run_sat1_dev_xtag.sh`

## Default assumptions

- load `tools/env/xmos_env.sh` before validating SAT1 env vars in shell checks
- build directory: `build_sat1_dev_xtag`
- target: `satellite1_firmware_fixed_delay`
- XMOS environment wrapper: `tools/env/xmos_env.sh`
- `.venv` is activated automatically by the helper script if present
- adapter id may be auto-detected if not explicitly provided

## Commands

Adapter detect only:
- `tools/e2e/run_sat1_dev_xtag.sh --detect-only`

Build only:
- `tools/e2e/run_sat1_dev_xtag.sh --build`

Run firmware:
- `tools/e2e/run_sat1_dev_xtag.sh --run`

Note: when using `xrun` directly, launch from the build directory
(`build_sat1_dev_xtag`) so the correct `.xe` is loaded.

Run under debugger:
- `tools/e2e/run_sat1_dev_xtag.sh --debug`

Optional arguments:
- `--adapter-id <id>`
- `--build-dir <dir>`
- `--target <name>`
- `--skip-build`
- `--dry-run`

Env adapter defaults:
- `SAT1_XTAG_ID` (preferred)
- `XMOS_ADAPTER_ID` (backward-compatible fallback)

## Execution policy

- Prefer the helper script over ad hoc command reconstruction.
- If using xrun directly, add `--io` for Sat1 and keep it running in the
  background during SPI testing.
- Do not manually probe external XMOS toolchain files.
- Do not use destructive cleanup commands unless explicitly required.
- If multiple adapters are connected, pass `--adapter-id` explicitly.

## Failure handling

- no adapter found:
  - check xTAG connection and rerun detect-only
- multiple adapters found:
  - pass `--adapter-id`
- build failure:
  - report failure before run/debug
- run/debug failure with adapter busy:
  - terminate stale `xrun`/`xgdb`/`xgdbserver` processes and retry
- missing artifact:
  - rerun build and confirm `<build-dir>/<target>.xe` exists
